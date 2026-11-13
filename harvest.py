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
4. 完整保存地址索引 fs/ls；快照时按持久化轮转队列补查全部历史地址（含曾退出的地址）。
5. 候选与快照仅按单仓位 abs(positionValue)>5000 及当前监控币名单筛选；主/xyz 均查询。

诚实边界：HL 无"按余额枚举账户"端点，索引只能覆盖"采集开始后活跃过的地址"，
所以"全网"永远是"已发现地址的全网"。
"""
import json
import os
import time
import http.client
import urllib.request
import asyncio
import threading
import math

from position_scan import SELECTION, POSITION_MIN, prepare, plan, finish, progress
from concurrent.futures import ThreadPoolExecutor


API = 'https://api.hyperliquid.xyz/info'
WS_URL = 'wss://api.hyperliquid.xyz/ws'
CAPTURE_SECONDS = int(os.environ.get('HARVEST_SECONDS', '300'))
SEGMENT_SECONDS = int(os.environ.get('HARVEST_SEGMENT', '60'))  # 单段时长，段间重连
MAX_SEG_FAILS = 5                                              # 连续段失败上限，超过则带着已有地址收工
VOL_MIN = 5_000_000         # 币种日成交门槛（美元名义；主片区与xyz片区同标准$5M，2026-09-28用户拍板，原$10M）
SNAP_CONCURRENCY = 6       # 快照模式并发：每 worker 一条长连接 + pacing，合计约 22 请求/秒（实测安全区）
SNAP_PACE = float(os.environ.get('HARVEST_SNAP_PACE', '0.35'))  # 每地址间隔秒数
SCAN_SECONDS = 1200  # Stop scheduling after 20 min; preserve work for the next scheduled run.
SNAP_LIMIT = int(os.environ.get('HARVEST_SNAPSHOT_LIMIT', '0'))  # 冒烟测试用：>0 只拉前 N 个地址
TODAY = time.strftime('%Y-%m-%d', time.gmtime())
DATA_DIR = os.environ.get('PRIVATE_DATA_DIR')


def require_private_data_dir():
    global DATA_DIR
    if not DATA_DIR:
        raise RuntimeError('Set PRIVATE_DATA_DIR to a private data directory; public checkout data is forbidden')
    DATA_DIR = os.path.abspath(DATA_DIR)
    if DATA_DIR == os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data'):
        raise RuntimeError('Use a separate private data directory')
    os.makedirs(DATA_DIR, exist_ok=True)


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


def _read_state(name, default):
    path = os.path.join(DATA_DIR, name + '.json')
    if not os.path.exists(path):
        return default
    try:
        with open(path) as f:
            return json.load(f)
    except (ValueError, OSError):
        if name != 'position_recheck':
            raise
        backup = os.path.join(DATA_DIR, 'position_recheck.backup.json')
        try:
            with open(backup) as f:
                return json.load(f)
        except (ValueError, OSError):
            print('[recheck] checkpoint damaged; replaying full index', flush=True)
            return default


def _write_state(name, data):
    if name == 'position_recheck':
        previous = _read_state(name, None)
        if previous is not None:
            with open(os.path.join(DATA_DIR, 'position_recheck.backup.json'), 'w') as f:
                json.dump(previous, f, separators=(',', ':'), allow_nan=False)
    with open(os.path.join(DATA_DIR, name + '.json'), 'w') as f:
        json.dump(data, f, separators=(',', ':'), allow_nan=False)


def main():
    t_start = time.time()
    coins = load_coins()
    harvested, hstats = asyncio.run(harvest(coins))
    original = _read_state('addresses', {'addresses': {}})
    addresses = original['addresses']
    new_count = 0
    for a in harvested:
        if a not in addresses:
            addresses[a] = {'fs': TODAY, 'ls': TODAY}
            new_count += 1
        elif isinstance(addresses[a], dict):
            addresses[a]['ls'] = TODAY
        else:
            addresses[a] = {'fs': addresses[a], 'ls': TODAY}
    original.update(updated=TODAY, count=len(addresses), addresses=addresses)
    _write_state('addresses', original)
    # No account-value admission or random candidate sampling. Snapshot scans the
    # entire candidate pool and a bounded, durable portion of the complete index.
    accounts = _read_state('accounts', {'accounts': {}})['accounts']
    queue = prepare(_read_state('position_recheck', None), addresses, accounts)
    _write_state('position_recheck', queue)
    print('[harvest] ' + json.dumps({'new_addresses': new_count, 'captured': len(harvested),
          'coins': len(coins), 'run_seconds': round(time.time() - t_start),
          **hstats, **progress(queue)}, ensure_ascii=False), flush=True)


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


def _load_monitored_coins():
    """A readable monitored list is required: never publish unmonitored positions."""
    with open(os.path.join(DATA_DIR, 'coins.json')) as f:
        raw = json.load(f)
    if raw.get('caliber') != 'avg_7d' or raw.get('threshold') != VOL_MIN:
        raise ValueError('Invalid monitored coin rules')
    return {c['n'] for c in raw['coins']}


def fetch_positions(addr, post, allowed):
    # Read BOTH sides before interpreting equity; negative equity is a fact.
    st = post({'type': 'clearinghouseState', 'user': addr})
    sx = post({'type': 'clearinghouseState', 'user': addr, 'dex': 'xyz'})
    for side in (st, sx):
        if not isinstance(side, dict) or not isinstance(side.get('marginSummary'), dict) or not isinstance(side.get('assetPositions'), list):
            raise ValueError('Incomplete clearinghouseState')
    eq = float(st['marginSummary']['accountValue'])
    if not math.isfinite(eq):
        raise ValueError('Invalid accountValue')
    positions = _positions_of(st) + _positions_of(sx)
    kept = [p for p in positions if p[0] in allowed and math.isfinite(p[5]) and p[5] > POSITION_MIN]
    return {'a': addr, 'e': round(eq, 2), 'p': kept}, len(positions)


class PositionClient:
    """One persistent connection per worker, existing six-worker pacing and retries."""
    def __init__(self):
        self.deadline = time.monotonic() + SCAN_SECONDS
        self.local = threading.local()
        self.connections = []
        self.lock = threading.Lock()

    def _connection(self):
        c = getattr(self.local, 'conn', None)
        if c is None:
            c = http.client.HTTPSConnection('api.hyperliquid.xyz', 443, timeout=20)
            self.local.conn = c
            with self.lock:
                self.connections.append(c)
        return c

    def post(self, payload):
        c = self._connection()
        c.request('POST', '/info', json.dumps(payload),
                  {'Content-Type': 'application/json', 'User-Agent': 'Mozilla/5.0'})
        r = c.getresponse()
        raw = r.read()
        if r.status != 200:
            raise IOError('HTTP ' + str(r.status))
        return json.loads(raw)

    def query(self, addr, allowed):
        for attempt in range(3):
            if time.monotonic() >= self.deadline:
                return None, 0
            try:
                return fetch_positions(addr, self.post, allowed)
            except Exception:
                self._connection().close()
                self.local.conn = None
                if attempt < 2:
                    time.sleep(attempt + 1)
            finally:
                time.sleep(SNAP_PACE)
        return None, 0

    def close(self):
        for c in self.connections:
            c.close()


def snapshot_mode(query=None):
    """Candidates first, then <=2000 historical tasks including <=100 retries."""
    allowed = _load_monitored_coins()
    addresses = _read_state('addresses', {'addresses': {}})['addresses']
    original = _read_state('accounts', {'accounts': {}})
    accounts = original['accounts']
    queue = prepare(_read_state('position_recheck', None), addresses, accounts)
    batch, start, end = plan(queue)
    # SNAP_LIMIT never advances unseen work: it is a diagnostic-only bounded scan.
    candidates = list(accounts)
    candidate_offset = queue.get('candidate_cursor', 0) % max(1, len(candidates))
    rotated = candidates[candidate_offset:] + candidates[:candidate_offset]
    pool = list(dict.fromkeys(rotated + batch))
    if SNAP_LIMIT:
        pool = pool[:SNAP_LIMIT]
    t0 = time.time()
    client = PositionClient() if query is None else None
    run_query = query or client.query
    out, results = [], {}
    stats = {'ok': 0, 'empty': 0, 'failed': 0, 'pos_total': 0, 'pos_kept': 0}
    print('[snapshot] ' + json.dumps({'candidates': len(accounts), 'scheduled': len(pool),
          'concurrency': SNAP_CONCURRENCY, **progress(queue)}, ensure_ascii=False), flush=True)
    try:
        deadline = time.monotonic() + SCAN_SECONDS
        with ThreadPoolExecutor(max_workers=SNAP_CONCURRENCY) as ex:
            # Drain candidate work before submitting any historical-only work.
            boundary = min(len(rotated), len(pool))
            chunks = (pool[offset:min(offset + 60, stop)]
                      for first, stop in ((0, boundary), (boundary, len(pool)))
                      for offset in range(first, stop, 60))
            for chunk in chunks:
                if time.monotonic() >= deadline:
                    break
                for a, (rec, total) in zip(chunk, ex.map(lambda a: run_query(a, allowed), chunk)):
                    results[a] = rec
                    stats['pos_total'] += total
                    if rec is None:
                        stats['failed'] += 1  # Keep existing candidate; do not equate failure to empty.
                    elif rec['p']:
                        accounts[a] = {'v': rec['e'], 't': TODAY}
                        out.append(rec)
                        stats['ok'] += 1
                        stats['pos_kept'] += len(rec['p'])
                    else:
                        accounts.pop(a, None)  # Index/queue retain the address for future discovery.
                        stats['empty'] += 1
                    if len(results) % 200 == 0:
                        print(f'[snapshot] {len(results)}/{len(pool)}', flush=True)
    finally:
        if client:
            client.close()
    stats['unqueried'] = len(pool) - len(results)
    # Candidate facts first, cursor last. An interruption replays the batch.
    original.pop('pool_min', None)
    original.update(updated=TODAY, count=len(accounts), selection=SELECTION, accounts=accounts)
    _write_state('accounts', original)
    # A diagnostic limit must not skip the unqueried part of the forward batch.
    actual_end = start
    while actual_end < end and queue['order'][actual_end] in results:
        actual_end += 1
    finish(queue, start, actual_end, results)
    # Rotate the starting point if a degraded API exhausts the time budget.
    checked = 0
    for a in rotated:
        if a not in results:
            break
        checked += 1
    queue['candidate_cursor'] = (candidate_offset + checked) % max(1, len(candidates))
    elapsed = time.time() - t0
    queue['last_run'] = {'queried': len(results), 'failed': stats['failed'],
                         'seconds': round(elapsed, 3), 'completed_at_unix': int(time.time())}
    snap = {'ts': time.strftime('%Y-%m-%dT%H:%M:%S+08:00', time.gmtime(time.time() + 8 * 3600)),
            'generated_at_unix': int(time.time()), 'pool_scanned': len(results),
            'selection': SELECTION, 'stats': stats, 'accounts': out}
    _write_state('snapshot', snap)
    _write_state('position_recheck', queue)
    print('[snapshot] ' + json.dumps({**stats, **progress(queue), 'queried': len(results),
          'seconds': round(elapsed, 3)}, ensure_ascii=False), flush=True)
    return snap


if __name__ == '__main__':
    import sys
    require_private_data_dir()
    if '--snapshot' in sys.argv:
        snapshot_mode()
    else:
        main()
