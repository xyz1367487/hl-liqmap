#!/usr/bin/env python3
"""hl-liqmap 地址收割器（Phase 2）

每日运行一次：
1. 拉取日成交 > $10M 的币种列表（与页面、信号监控列表同源）；
2. 订阅这些币种的 WS 成交流，采集 N 秒（默认 180s），收割 users 字段里的地址；
3. 合并进 data/addresses.json（记录 first_seen）；
4. 对【新地址】+【候选池中 $8k~$12k 缓冲带的老地址】逐个查 clearinghouseState：
   - 账户值 >= $8k 进候选池 data/accounts.json；
   - 掉出 $8k 的从候选池移除（仍在 addresses 索引中）；
5. 页面侧对候选池地址实时拉取，按【实时账户值 >= $10k】过滤渲染。

诚实边界：HL 无"按余额枚举账户"端点，索引只能覆盖"采集开始后活跃过的地址"，
所以"全网"永远是"已发现地址的全网"。
"""
import json
import os
import time
import urllib.request
import asyncio
from concurrent.futures import ThreadPoolExecutor

import websockets

API = 'https://api.hyperliquid.xyz/info'
WS_URL = 'wss://api.hyperliquid.xyz/ws'
CAPTURE_SECONDS = int(os.environ.get('HARVEST_SECONDS', '180'))
VOL_MIN = 10_000_000        # 币种日成交门槛（美元名义）
POOL_MIN = 8_000            # 候选池下限（相对 $10k 门槛留 20% 缓冲）
RECHECK_MAX = 12_000        # 缓冲带上限：此区间内的老地址每日复查
CONCURRENCY = 10
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


def load_coins():
    meta, ctxs = info({'type': 'metaAndAssetCtxs'})
    coins = []
    for i, u in enumerate(meta['universe']):
        try:
            if float(ctxs[i]['dayNtlVlm']) > VOL_MIN:
                coins.append(u['name'])
        except Exception:
            pass
    return coins


async def harvest(coins):
    addrs = set()
    t0 = time.time()
    async with websockets.connect(WS_URL) as ws:
        for c in coins:
            await ws.send(json.dumps({
                'method': 'subscribe',
                'subscription': {'type': 'trades', 'coin': c},
            }))
        print(f'[harvest] subscribed {len(coins)} coins, capturing {CAPTURE_SECONDS}s', flush=True)
        while time.time() - t0 < CAPTURE_SECONDS:
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
    print(f'[harvest] {len(addrs)} distinct addresses in {CAPTURE_SECONDS}s', flush=True)
    return addrs


def get_equity(addr):
    st = info({'type': 'clearinghouseState', 'user': addr})
    return float(st.get('marginSummary', {}).get('accountValue', 0))


def main():
    coins = load_coins()
    print(f'[coins] {len(coins)} coins with dayNtlVlm > ${VOL_MIN:,}', flush=True)
    harvested = asyncio.run(harvest(coins))

    addr_path = os.path.join(DATA_DIR, 'addresses.json')
    acc_path = os.path.join(DATA_DIR, 'accounts.json')
    addresses, accounts = {}, {}
    if os.path.exists(addr_path):
        with open(addr_path) as f:
            addresses = json.load(f).get('addresses', {})
    if os.path.exists(acc_path):
        with open(acc_path) as f:
            accounts = json.load(f).get('accounts', {})

    new_addrs = [a for a in harvested if a not in addresses]
    recheck = [a for a, rec in accounts.items() if POOL_MIN <= rec.get('v', 0) < RECHECK_MAX]
    todo = new_addrs + [a for a in recheck if a not in set(new_addrs)]
    print(f'[merge] {len(new_addrs)} new addresses; {len(recheck)} buffer-band rechecks', flush=True)
    print(f'[equity] checking {len(todo)} addresses, concurrency {CONCURRENCY}', flush=True)

    done = 0
    lock_free = {'n': 0}

    def work(a):
        try:
            v = get_equity(a)
        except Exception:
            v = None
        lock_free['n'] += 1
        if lock_free['n'] % 200 == 0:
            print(f'[equity] {lock_free["n"]}/{len(todo)}', flush=True)
        return a, v

    results = {}
    if todo:
        with ThreadPoolExecutor(max_workers=CONCURRENCY) as ex:
            for a, v in ex.map(work, todo):
                results[a] = v

    for a in new_addrs:
        addresses[a] = TODAY
    for a, v in results.items():
        if v is not None and v >= POOL_MIN:
            accounts[a] = {'v': round(v, 2), 't': TODAY}
        elif v is not None and a in accounts and v < POOL_MIN:
            del accounts[a]

    os.makedirs(DATA_DIR, exist_ok=True)
    with open(addr_path, 'w') as f:
        json.dump({'updated': TODAY, 'count': len(addresses), 'addresses': addresses}, f)
    with open(acc_path, 'w') as f:
        json.dump({'updated': TODAY, 'pool_min': POOL_MIN, 'count': len(accounts), 'accounts': accounts}, f)
    print(f'[done] addresses={len(addresses)} pool(>=${POOL_MIN})={len(accounts)}', flush=True)


if __name__ == '__main__':
    main()
