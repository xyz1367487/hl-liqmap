#!/usr/bin/env python3
"""Private snapshot -> allowlisted public distance buckets (standard library only)."""
import argparse
import json
import math
import re
from pathlib import Path

EDGES = [0, .0025, .005, .01, .015, .02, .03, .05, .075, .10, .15, .20, .30, .50, math.inf]
LABELS = ['0-0.25%', '0.25-0.5%', '0.5-1%', '1-1.5%', '1.5-2%', '2-3%', '3-5%', '5-7.5%', '7.5-10%', '10-15%', '15-20%', '20-30%', '30-50%', '50%+']
ADDRESS = re.compile(r'0x[a-fA-F0-9]{40}')
COIN = re.compile(r'^[A-Za-z0-9@:_./-]{1,64}$')


def number(v, positive=False):
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v < 0 or (positive and v == 0):
        raise ValueError('Invalid aggregate number')
    return v


def aggregate(snapshot, marks, coins):
    """Same side, distance, half-open bands, notional sum and extrema as original JS.

    Publish every nonempty original bucket without collecting contributor identities.
    Invalid/unlocatable liquidation prices follow the original map's exclusion rule.
    """
    result = {}
    for coin in coins['coins']:
        name = coin['n']
        mark = float(marks[name])
        number(mark, positive=True)
        result[name] = {'reference_mark': mark, 'buckets': []}
    groups = {}
    for account in snapshot['accounts']:
        if account['e'] < 10000:
            continue
        for position in account['p']:
            name, side, _, _, px, notional, *_ = position
            if name not in result or side not in ('L', 'S') or px is None or px <= 0:
                continue
            number(px, positive=True)
            number(notional)
            distance = abs(px - result[name]['reference_mark']) / result[name]['reference_mark']
            band = next(i for i in range(14) if EDGES[i] <= distance < EDGES[i + 1])
            key = name, side, band
            group = groups.setdefault(key, {'notional': 0, 'positions': 0, 'px_low': px, 'px_high': px})
            group['notional'] += notional
            group['positions'] += 1
            group['px_low'] = min(group['px_low'], px)
            group['px_high'] = max(group['px_high'], px)
    for (name, side, band), group in sorted(groups.items()):
        result[name]['buckets'].append({'side': side, 'band': band,
            **{k: group[k] for k in ('notional', 'positions', 'px_low', 'px_high')}})
    output = {'schema_version': 1, 'generated_at_unix': snapshot['generated_at_unix'],
              'privacy': {'scope': 'aggregate_only', 'buckets': 'all_nonempty'},
              'coin_list': {'updated': coins['updated'], 'caliber': 'avg_7d', 'threshold': 5000000,
                            'coins': [{'n': c['n'], 'v': c['v']} for c in coins['coins']]},
              'markets': result}
    validate_public(output)
    return output


def keys(obj, expected):
    if not isinstance(obj, dict) or set(obj) != set(expected.split()):
        raise ValueError('Unexpected aggregate schema keys')


def validate_public(data):
    """Fail closed: no opaque metadata, account rows, arbitrary keys or strings."""
    keys(data, 'schema_version generated_at_unix privacy coin_list markets')
    if data['schema_version'] != 1:
        raise ValueError('Unsupported schema')
    number(data['generated_at_unix'], positive=True)
    if data['privacy'] != {'scope': 'aggregate_only', 'buckets': 'all_nonempty'}:
        raise ValueError('Unexpected privacy policy')
    coins = data['coin_list']
    keys(coins, 'updated caliber threshold coins')
    if not isinstance(coins['updated'], str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', coins['updated']):
        raise ValueError('Invalid coin date')
    if coins['caliber'] != 'avg_7d' or coins['threshold'] != 5000000:
        raise ValueError('Unexpected coin rules')
    names = []
    for c in coins['coins']:
        keys(c, 'n v')
        if not isinstance(c['n'], str) or not COIN.fullmatch(c['n']) or ADDRESS.search(c['n']):
            raise ValueError('Invalid public symbol')
        number(c['v'])
        names.append(c['n'])
    if len(names) != len(set(names)) or set(data['markets']) != set(names):
        raise ValueError('Market list mismatch')
    for market in data['markets'].values():
        keys(market, 'reference_mark buckets')
        number(market['reference_mark'], positive=True)
        seen = set()
        for b in market['buckets']:
            keys(b, 'side band notional positions px_low px_high')
            if b['side'] not in ('L', 'S') or type(b['band']) is not int or not 0 <= b['band'] < 14:
                raise ValueError('Invalid bucket')
            key = b['side'], b['band']
            if key in seen:
                raise ValueError('Duplicate bucket')
            seen.add(key)
            if type(b['positions']) is not int or b['positions'] <= 0:
                raise ValueError('Empty bucket')
            number(b['notional'])
            number(b['px_low'], positive=True)
            number(b['px_high'], positive=True)
            if b['px_low'] > b['px_high']:
                raise ValueError('Invalid price range')
    if ADDRESS.search(json.dumps(data, allow_nan=False)):
        raise ValueError('Address in public output')
    return data


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--snapshot', type=Path)
    p.add_argument('--coins', type=Path)
    p.add_argument('--marks', type=Path)
    p.add_argument('--output', type=Path)
    p.add_argument('--validate', type=Path)
    args = p.parse_args()
    if args.validate:
        validate_public(json.loads(args.validate.read_text()))
        print('Aggregate schema valid; no addresses or account records')
        return
    if not all((args.snapshot, args.coins, args.marks, args.output)):
        p.error('snapshot, coins, marks and output are required')
    output = aggregate(json.loads(args.snapshot.read_text()), json.loads(args.marks.read_text()), json.loads(args.coins.read_text()))
    # A new immutable generation prevents accidental replacement of a previous file.
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x') as f:
        json.dump(output, f, separators=(',', ':'), allow_nan=False)
    print(f'Exported {sum(len(m["buckets"]) for m in output["markets"].values())} public buckets')


if __name__ == '__main__':
    main()
