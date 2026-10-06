#!/usr/bin/env python3
# HL 清算地图 (hl-liqmap) — https://xyz1367487.github.io/hl-liqmap/
# Copyright (C) 2026 xyz1367487.
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published
# by the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.
"""hl-liqmap 地址收割器（Phase 2）

每6小时运行一次（北京 09:40/15:40/21:40/03:40，UTC 40 1,7,13,19）：
1. 拉取近 7 日日均成交额 > $5M 的币种列表（avg_7d 口径，与 HL-UPERP-MONITOR 一致；主 dex + xyz 双 dex；结果写 data/coins.json 供页面读取）；
2. 分段订阅 WS 成交流（默认 5×60s，段间重连、断线自动续采，连续失败5次才放弃），
   收割 users 字段里的地址——xyz-only 交易者因此也能进索引；
3. 合并进 data/addresses.json（记录 fs=first_seen / ls=last_seen，兼容旧格式）；
4. 对【新地址】+【候选池中 $8k~$12k 缓冲带的老地址】+【$12k 以上账户随机抽 10% 轮转复查】逐个查 clearinghouseState：
   - 账户值 >= $8k 进候选池 data/accounts.json（主 dex 的 accountValue = 账户总值，
     含 xyz 子账户，实测口径，无需双拉）；
   - 掉出 $8k 的从候选池移除（仍在 addresses 索引中）；
5. 收割统计（查询数/成功/失败/失败率/分段情况/耗时）写进 data meta，页面可查。

诚实边界：HL 无"按余额枚举账户"端点，索引只能覆盖"采集开始后活跃过的地址"，
所以"全网"永远是"已发现地址的全网"。
"""
import json
import os
import time
import http.client
import urllib.request
import asyncio
import random
import threading
from concurrent.futures import ThreadPoolExecutor

import websockets

API = 'https://api.hyperliquid.xyz/info'
WS_URL = 'wss://api.hyperliquid.xyz/ws'
CAPTURE_SECONDS = int(os.environ.get('HARVEST_SECONDS', '300'))
SEGMENT_SECONDS = int(os.environ.get('HARVEST_SEGMENT', '60'))  # 单段时长，段间重连
MAX_SEG_FAILS = 5                                              # 连续段失败上限，超过则带着已有地址收工
VOL_MIN = 5_000_000         # 币种日成交门槛（美元名义；主片区与xyz片区同标准$5M，2026-09-28用户拍板，原$10M）
POOL_MIN = 8_000            # 候选池下限（相对 $10k 门槛留 20% 缓冲）
RECHECK_MAX = 12_000        # 缓冲带上限：此区间内的老地址每次复查
SNAP_MIN = 10_000           # 快照门槛：独立于候选池，避免每次快照白查 $8k~$10k 地址
ROTATION_DAYS = 3           # 老账户轮转复查间隔（天）：>$12k 的账户从不进缓冲带，靠此机制淘汰缩水账户
ROTATION_RATE = 0.10        # 每次从"超出缓冲带上限"的老账户里随机抽取比例
CONCURRENCY = 10
SNAP_CONCURRENCY = 6       # 快照模式并发：每 worker 一条长连接 + pacing，合计约 22 请求/秒（实测安全区）
SNAP_PACE = float(os.environ.get('HARVEST_SNAP_PACE', '0.35'))  # 每地址间隔秒数
SNAP_LIMIT = int(os.environ.get('HARVEST_SNAPSHOT_LIMIT', '0'))  # 冒烟测试用：>0 只拉前 N 个地址
TODAY = time.strftime('%Y-%m-%d', time.gmtime())
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')


def info(payload, retries=2):
    for i in range(retries + 1):
        try:
            req = urllib.request.Request(
                API,
                data=json.dumps(payload).encode(),
                headers={'Content-Type': 'application/json', 'User-Agent': 'Mozilla/5.0'},
            )
            with urllib.request.urlopen(req, timeout=15) as r:
                return json.load(r)
        except Exception:
            if i == retries:
                raise
            time.sleep(1.5)


def _get_volume_metrics(coin_name):
    """近7日日均成交额（avg_7d，估算USD）——与 HL-UPERP-MONITOR._get_volume_metrics 同口径。

    日K线 v 是成交数量(base)，×收盘价≈当日成交额(USD)；去掉今天未完成的K线，
    取最近7根完整日K的均值。死币返回 0，API失败返回 None（调用方不得当0缓存，防误杀）。
    """
    now_ms = int(time.time() * 1000)
    try:
        candles = info({
            'type': 'candleSnapshot',
            'req': {'coin': coin_name, 'interval': '1d',
                    'startTime': now_ms - 10 * 86400 * 1000, 'endTime': now_ms},
        })
        if not candles or len(candles) < 2:
            return 0
        complete = [c for c in candles if c['t'] < (now_ms - 86400000)]
        if len(complete) < 2:
            return 0
        recent = complete[-7:]
        return sum(float(c['v']) * float(c['c']) for c in recent) / len(recent)
    except Exception:
        return None


def load_coins():
    """主 dex + xyz builder dex 双 dex，返回近7日日均成交额 > $5M 的币种全名列表。

    avg_7d 口径与 HL-UPERP-MONITOR 完全一致（2026-09-28 对齐）：日K线去掉今天未完成的，
    取最近7根完整日K的 v×c（base量×收盘价）均值。用 data/volume_cache.json 跨次缓存
    （同日直接命中，candleSnapshot 权重20/次、IP限60次/分，全量304币约7分钟，日级缓存后趋近零成本）。
    同时把名单写入 data/coins.json 供页面读取（页面不再自己算，避免每次打开拉304根K线）。
    """
    cache_path = os.path.join(DATA_DIR, 'volume_cache.json')
    cache = {}
    if os.path.exists(cache_path):
        try:
            with open(cache_path) as f:
                cache = json.load(f)
        except Exception:
            cache = {}
    today = time.strftime('%Y-%m-%d', time.gmtime())
    same_day = cache.get('date') == today
    pairs_cache = cache.get('pairs', {}) if same_day else {}

    coins = []
    coin_avg = {}
    api_calls = 0
    for dex in (None, 'xyz'):
        payload = {'type': 'metaAndAssetCtxs'}
        if dex:
            payload['dex'] = dex
        meta, ctxs = info(payload)
        for u in meta['universe']:
            name = u['name']
            if name in pairs_cache:
                avg7 = pairs_cache[name]
            else:
                avg7 = _get_volume_metrics(name)
                api_calls += 1
                if avg7 is not None:
                    pairs_cache[name] = avg7
                time.sleep(0.5)  # candleSnapshot 权重20/次，IP限60次/分——pacing 防 429 风暴（仅未命中缓存时）
            if avg7 is not None and avg7 > VOL_MIN:
                coins.append(name)
                coin_avg[name] = round(avg7)

    try:
        with open(cache_path, 'w') as f:
            json.dump({'date': today, 'pairs': pairs_cache}, f)
        with open(os.path.join(DATA_DIR, 'coins.json'), 'w') as f:
            json.dump({'updated': today, 'caliber': 'avg_7d', 'threshold': VOL_MIN,
                       'coins': [{'n': n, 'v': coin_avg[n]} for n in coins]}, f)
    except Exception:
        pass
    print(f'[coins] avg_7d>${VOL_MIN:,}: {len(coins)} 个（主+xyz双dex；本次 candle 查询 {api_calls} 次'
          f'{"，缓存命中" if same_day else "，全量重算"}）', flush=True)
    return coins


async def harvest(coins):
    """分段订阅 + 断线重连；返回 (地址set, 采集统计dict)"""
    import websockets  # 延迟导入：snapshot 模式不需要 websockets，workflow 无需安装
    addrs = set()
    t0 = time.time()
    seg = 0
    fails = 0
    while time.time() - t0 < CAPTURE_SECONDS:
        seg += 1
        dur = min(SEGMENT_SECONDS, CAPTURE_SECONDS - (time.time() - t0))
        try:
            async with websockets.connect(WS_URL) as ws:
                for c in coins:
                    await ws.send(json.dumps({
                        'method': 'subscribe',
                        'subscription': {'type': 'trades', 'coin': c},
                    }))
                seg_t0 = time.time()
                while time.time() - seg_t0 < dur:
                    try:
                        msg = await asyncio.wait_for(ws.recv(), timeout=20)
                    except asyncio.TimeoutError:
                        continue
                    try:
                        d = json.loads(msg)
                    except Exception:
                        continue
                    if d.get('channel') == 'trades':
                        for tr in d.get('data', []):
                            for u in tr.get('users', []):
                                addrs.add(u.lower())
            fails = 0
            print(f'[harvest] 段{seg}完成 {dur:.0f}s，累计 {len(addrs)} 地址', flush=True)
        except Exception as e:
            fails += 1
            print(f'[harvest] 段{seg}断线({e})，连续第{fails}次失败，5s后重连', flush=True)
            if fails >= MAX_SEG_FAILS:
                print(f'[harvest] 连续失败{fails}次，放弃剩余采集，带着已有 {len(addrs)} 地址收工', flush=True)
                break
            await asyncio.sleep(5)
    stats = {'segments': seg, 'segment_fails': fails}
    print(f'[harvest] 共 {len(addrs)} 个不同地址（预算 {CAPTURE_SECONDS}s / {seg} 段）', flush=True)
    return addrs, stats


def get_equity(addr):
    st = info({'type': 'clearinghouseState', 'user': addr})
    return float(st.get('marginSummary', {}).get('accountValue', 0))


def main():
    t_start = time.time()
    coins = load_coins()
    print(f'[coins] {len(coins)} coins（avg_7d 名单，主+xyz双dex）', flush=True)
    harvested, hstats = asyncio.run(harvest(coins))

    addr_path = os.path.join(DATA_DIR, 'addresses.json')
    acc_path = os.path.join(DATA_DIR, 'accounts.json')
    addresses, accounts = {}, {}
    if os.path.exists(addr_path):
        with open(addr_path) as f:
            raw = json.load(f).get('addresses', {})
        # 向前兼容：旧格式 {addr: date_str}，新格式 {addr: {fs, ls}}
        for a, v in raw.items():
            addresses[a] = v if isinstance(v, dict) else {'fs': v, 'ls': v}
    if os.path.exists(acc_path):
        with open(acc_path) as f:
            accounts = json.load(f).get('accounts', {})

    new_addrs = [a for a in harvested if a not in addresses]

    # 缓冲带复查：$8k~$12k 之间的账户每次都查
    recheck = [a for a, rec in accounts.items() if POOL_MIN <= rec.get('v', 0) < RECHECK_MAX]

    # 轮转复查：$12k 以上的账户随机抽 10%（防止长期不查、候选池积累缩水账户）
    cutoff = time.strftime('%Y-%m-%d', time.gmtime(time.time() - ROTATION_DAYS * 86400))
    rotation_pool = [a for a, rec in accounts.items()
                     if rec.get('v', 0) >= RECHECK_MAX and rec.get('t', '') <= cutoff]
    rotation_sample = random.sample(rotation_pool, max(0, int(len(rotation_pool) * ROTATION_RATE)))

    todo_set = set(new_addrs)
    todo = new_addrs[:]
    for a in recheck:
        if a not in todo_set:
            todo.append(a); todo_set.add(a)
    for a in rotation_sample:
        if a not in todo_set:
            todo.append(a); todo_set.add(a)

    print(f'[merge] {len(new_addrs)} new / {len(recheck)} buffer-band / '
          f'{len(rotation_sample)} rotation (eligible {len(rotation_pool)})', flush=True)
    print(f'[equity] checking {len(todo)} addresses, concurrency {CONCURRENCY}', flush=True)

    prog = {'n': 0}

    def work(a):
        try:
            v = get_equity(a)
        except Exception:
            v = None
        prog['n'] += 1
        if prog['n'] % 200 == 0:
            print(f'[equity] {prog["n"]}/{len(todo)}', flush=True)
        return a, v

    results = {}
    if todo:
        with ThreadPoolExecutor(max_workers=CONCURRENCY) as ex:
            for a, v in ex.map(work, todo):
                results[a] = v

    ok = sum(1 for v in results.values() if v is not None)
    failed = len(results) - ok
    for a in new_addrs:
        addresses[a] = {'fs': TODAY, 'ls': TODAY}
    for a in harvested:
        if a in addresses and isinstance(addresses[a], dict):
            addresses[a]['ls'] = TODAY
    for a, v in results.items():
        if v is not None and v >= POOL_MIN:
            accounts[a] = {'v': round(v, 2), 't': TODAY}
        elif v is not None and a in accounts and v < POOL_MIN:
            del accounts[a]

    run_seconds = round(time.time() - t_start)
    stats = {
        'queried': len(todo), 'ok': ok, 'failed': failed,
        'fail_rate': round(failed / len(todo), 4) if todo else 0,
        'new_addresses': len(new_addrs), 'rechecks': len(recheck),
        'captured': len(harvested), 'coins': len(coins),
        'run_seconds': run_seconds,
        'segments': hstats['segments'], 'segment_fails': hstats['segment_fails'],
    }
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(addr_path, 'w') as f:
        json.dump({'updated': TODAY, 'count': len(addresses), 'addresses': addresses}, f)
    with open(acc_path, 'w') as f:
        json.dump({'updated': TODAY, 'pool_min': POOL_MIN, 'count': len(accounts),
                   'stats': stats, 'accounts': accounts}, f)
    print(f'[done] addresses={len(addresses)} pool={len(accounts)} | '
          f'查询 {len(todo)} 成功 {ok} 失败 {failed} ({stats["fail_rate"]*100:.1f}%) | '
          f'{seg_note(hstats)} | {run_seconds}s', flush=True)


def seg_note(hstats):
    return f'采集{hstats["segments"]}段/断线{hstats["segment_fails"]}次'


def _f(v):
    """HL 对全仓深权益仓位的 liquidationPx 等字段会返回 null——按 0 处理（与页面口径一致：强平价无效则不上图）"""
    try:
        return float(v) if v is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


def _positions_of(st):
    """clearinghouseState → 紧凑仓位元组 [coin, side, szi, entryPx, liqPx, notional, lev, levType]"""
    out = []
    for p in st.get('assetPositions', []):
        pos = p['position']
        szi = _f(pos.get('szi'))
        lev = pos.get('leverage') if isinstance(pos.get('leverage'), dict) else {}
        out.append([pos['coin'],
                    'S' if szi < 0 else 'L',
                    abs(szi),
                    _f(pos.get('entryPx')),
                    _f(pos.get('liquidationPx')),
                    abs(_f(pos.get('positionValue'))),
                    lev.get('value'),
                    lev.get('type')])
    return out


def snapshot_mode():
    """方案B：对候选池全量双 dex 拉取，写 data/snapshot.json（页面打开秒渲染用）。

    - 账户值门槛用主 dex 的 accountValue（= 账户总值，含 xyz 子账户，实测口径）
    - 仓位 = 主 dex + xyz builder dex 合并
    - 只保留快照时刻 ≥$10k 的账户（页面按时间戳标注新鲜度；要实时值用页面"拉取实时"按钮）
    """
    acc_path = os.path.join(DATA_DIR, 'accounts.json')
    if not os.path.exists(acc_path):
        print('[snapshot] accounts.json 不存在，跳过（等首次收割）', flush=True)
        return
    with open(acc_path) as f:
        accounts = json.load(f).get('accounts', {})
    pool = [a for a, rec in accounts.items() if rec.get('v', 0) >= SNAP_MIN]  # 用 SNAP_MIN($10k)，避免白查 $8k~$10k 缓冲带
    if SNAP_LIMIT:
        pool = pool[:SNAP_LIMIT]
    print(f'[snapshot] 候选池 {len(pool)} 个地址，双dex全量拉取，并发 {SNAP_CONCURRENCY}', flush=True)

    prog = {'n': 0}
    cnt = {'ok': 0, 'below': 0, 'fail': 0}
    bad = {'sample': None}

    def _new_conn():
        return http.client.HTTPSConnection('api.hyperliquid.xyz', 443, timeout=20)

    def worker(chunk):
        """每 worker 一条长连接跑完自己的地址块——urllib 每请求新建连接会被 HL 掐（实测52%失败）"""
        box = {'conn': _new_conn()}
        res = []

        def post(payload):
            c = box['conn']
            c.request('POST', '/info', json.dumps(payload),
                      {'Content-Type': 'application/json', 'User-Agent': 'Mozilla/5.0'})
            r = c.getresponse()
            raw = r.read()
            if r.status != 200:
                raise IOError(f'HTTP {r.status}')
            return json.loads(raw)

        def reconnect():
            try:
                box['conn'].close()
            except Exception:
                pass
            box['conn'] = _new_conn()

        for a in chunk:
            rec = ('fail', None)
            for attempt in range(3):
                try:
                    st = post({'type': 'clearinghouseState', 'user': a})
                    if 'marginSummary' not in st:
                        if not bad['sample']:
                            bad['sample'] = str(st)[:200]
                        raise ValueError('响应缺 marginSummary（软失败）')
                    eq = float(st['marginSummary']['accountValue'])
                    if eq < 10000:
                        rec = ('below', None)
                        break
                    pos = _positions_of(st)
                    try:
                        sx = post({'type': 'clearinghouseState', 'user': a, 'dex': 'xyz'})
                        if 'assetPositions' in sx:
                            pos.extend(_positions_of(sx))
                    except Exception:
                        reconnect()  # xyz 拉挂不丢主 dex 数据，但要换条干净连接
                    rec = ('ok', {'a': a, 'e': round(eq, 2), 'p': pos})
                    break
                except Exception:
                    reconnect()
                    if attempt == 2:
                        rec = ('fail', None)
                    else:
                        time.sleep(1.0 * (attempt + 1))
            res.append(rec)
            prog['n'] += 1
            if prog['n'] % 200 == 0:
                print(f'[snapshot] {prog["n"]}/{len(pool)}', flush=True)
            time.sleep(SNAP_PACE)  # 全局 pacing：6 worker × 2请求 ÷ (请求时延+0.35s) ≈ 22 请求/秒
        try:
            box['conn'].close()
        except Exception:
            pass
        return res

    out = []
    t0 = time.time()
    if pool:
        chunks = [pool[i::SNAP_CONCURRENCY] for i in range(SNAP_CONCURRENCY)]
        with ThreadPoolExecutor(max_workers=SNAP_CONCURRENCY) as ex:
            for res in ex.map(worker, chunks):
                for tag, rec in res:
                    cnt[tag] += 1
                    if rec:
                        out.append(rec)

    snap = {
        'ts': time.strftime('%Y-%m-%dT%H:%M:%S+08:00', time.gmtime(time.time() + 8 * 3600)),
        'generated_at_unix': int(time.time()),
        'pool_scanned': len(pool),
        'pool_min': POOL_MIN,
        'stats': {'ok': cnt['ok'], 'below': cnt['below'], 'failed': cnt['fail']},
        'accounts': out,
    }
    snap_path = os.path.join(DATA_DIR, 'snapshot.json')
    with open(snap_path, 'w') as f:
        json.dump(snap, f, separators=(',', ':'))  # 紧凑格式省体积
    size = os.path.getsize(snap_path)
    print(f'[snapshot] 完成：≥$10k 账户 {len(out)} 个（ok {cnt["ok"]} / 低于门槛 {cnt["below"]} / '
          f'失败 {cnt["fail"]}）· 文件 {size // 1024}KB · 耗时 {round(time.time() - t0)}s', flush=True)
    if bad['sample']:
        print(f'[snapshot] 异常响应样本: {bad["sample"]}', flush=True)
    if cnt['fail'] > len(pool) * 0.05:
        print(f'[snapshot] ⚠️ 失败率 {cnt["fail"]/len(pool)*100:.0f}% 偏高，疑似被限流，下次考虑再降并发/加大 pacing', flush=True)


if __name__ == '__main__':
    import sys
    if '--snapshot' in sys.argv:
        snapshot_mode()
    else:
        main()
