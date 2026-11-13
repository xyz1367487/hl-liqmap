#!/usr/bin/env python3
"""Private snapshot -> allowlisted public distance buckets (standard library only)."""
import argparse
import json
import math
import re
from decimal import Decimal, localcontext
from pathlib import Path

from position_scan import SELECTION, POSITION_MIN

EDGES = [0, .0025, .005, .01, .015, .02, .03, .05, .075, .10, .15, .20, .30, .50, math.inf]
LABELS = ['0-0.25%', '0.25-0.5%', '0.5-1%', '1-1.5%', '1.5-2%', '2-3%', '3-5%', '5-7.5%', '7.5-10%', '10-15%', '15-20%', '20-30%', '30-50%', '50%+']
ADDRESS = re.compile(r'0x[a-fA-F0-9]{40}')
COIN = re.compile(r'^[A-Za-z0-9@:_./-]{1,64}$')

# Real leverage bands, upper bound inclusive: <=10x, 11-25x, 26-50x, >50x.
# Order is the published array order and the browser legend/stacking order.
LEV_LIMITS = (10, 25, 50)
LEV_COUNT = 4


def number(v, positive=False):
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v < 0 or (positive and v == 0):
        raise ValueError('Invalid aggregate number')
    return v


def lev_band(value):
    """Band index from the raw position leverage field only; -1 when it is unusable."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        return -1
    return 0 if value <= LEV_LIMITS[0] else 1 if value <= LEV_LIMITS[1] else 2 if value <= LEV_LIMITS[2] else 3


def aggregate_v1(snapshot, marks, coins):
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
        for position in account['p']:
            name, side, _, _, px, notional, *_ = position
            if name not in result or side not in ('L', 'S') or px is None or px <= 0:
                continue
            number(px, positive=True)
            number(notional)
            if notional <= POSITION_MIN:
                continue
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
              'markets': result,
              **selection_metadata(snapshot)}
    validate_public(output)
    return output


# 5 basis points of each generation's reference mark; sparse, unbounded price grid.
BUCKET_FRACTION = 0.0005


def grid_index(px, step):
    # Decimal JSON values decide exact half-open boundaries, not binary division drift.
    with localcontext() as context:
        context.prec = 100
        return int(Decimal(str(px)) // Decimal(str(step)))


def _bin(snapshot, marks, coins, with_leverage):
    """Bin raw positions directly, never subdivide legacy distance bands.

    Index i represents [i*step, (i+1)*step). The fixed zero origin allows
    exact integer coarsening in the browser. Only nonempty cells are published,
    including single-contributor cells; no account identifiers are collected.

    With ``with_leverage`` each cell also carries the notional split across the
    four real leverage bands. A cell is only split when every contributing
    position reports a usable leverage value: otherwise the split is omitted
    rather than guessed, and the cell is counted in the market's ``lev_unknown``.
    """
    result = {}
    for coin in coins['coins']:
        name = coin['n']
        mark = number(float(marks[name]), positive=True)
        result[name] = {'reference_mark': mark, 'bucket_step': mark * BUCKET_FRACTION, 'buckets': [],
                        'lev_unknown': {'buckets': 0, 'notional': 0}}
    groups = {}
    for account in snapshot['accounts']:
        for position in account['p']:
            name, side, _, _, px, notional, leverage, *_ = position
            if name not in result or side not in ('L', 'S') or px is None or px <= 0:
                continue
            number(px, positive=True)
            number(notional)
            if notional <= POSITION_MIN:
                continue
            index = grid_index(px, result[name]['bucket_step'])
            key = name, side, index
            g = groups.setdefault(key, {'notional': 0, 'positions': 0, 'px_low': px, 'px_high': px,
                                        'lev': [0.0] * LEV_COUNT, 'unsplittable': False})
            g['notional'] += notional
            g['positions'] += 1
            g['px_low'] = min(g['px_low'], px)
            g['px_high'] = max(g['px_high'], px)
            band = lev_band(leverage)
            if band < 0:
                g['unsplittable'] = True
            else:
                g['lev'][band] += notional
    for (name, side, index), group in sorted(groups.items()):
        if with_leverage:
            if group['unsplittable']:
                # Explicit degradation: report the amount, do not invent a band.
                result[name]['lev_unknown']['buckets'] += 1
                result[name]['lev_unknown']['notional'] += group['notional']
                group['lev'] = None
            else:
                group['lev'] = [number(v) for v in group['lev']]
        else:
            group.pop('lev')
        group.pop('unsplittable')
        result[name]['buckets'].append({'side': side, 'index': index, **group})
    return result


def aggregate_v2(snapshot, marks, coins):
    """Schema 2: fixed grid without the leverage dimension (kept for rollback)."""
    result = _bin(snapshot, marks, coins, with_leverage=False)
    for market in result.values():
        market.pop('lev_unknown')
    output = {'schema_version': 2, 'generated_at_unix': snapshot['generated_at_unix'],
              'privacy': {'scope': 'aggregate_only', 'buckets': 'all_nonempty'},
              'coin_list': {'updated': coins['updated'], 'caliber': 'avg_7d', 'threshold': 5000000,
                            'coins': [{'n': c['n'], 'v': c['v']} for c in coins['coins']]},
              'markets': result,
              **selection_metadata(snapshot)}
    return validate_public(output)


def aggregate(snapshot, marks, coins):
    """Schema 3: schema 2 plus a per-cell real-leverage split for stacked bars."""
    output = {'schema_version': 3, 'generated_at_unix': snapshot['generated_at_unix'],
              'privacy': {'scope': 'aggregate_only', 'buckets': 'all_nonempty'},
              'coin_list': {'updated': coins['updated'], 'caliber': 'avg_7d', 'threshold': 5000000,
                            'coins': [{'n': c['n'], 'v': c['v']} for c in coins['coins']]},
              'markets': _bin(snapshot, marks, coins, with_leverage=True),
              **selection_metadata(snapshot)}
    return validate_public(output)


def selection_metadata(snapshot):
    if 'selection' not in snapshot:
        return {}  # Legacy collection coverage must never be relabeled as the new policy.
    if snapshot['selection'] != SELECTION:
        raise ValueError('Unsupported snapshot selection')
    return {'selection': dict(SELECTION)}


def keys(obj, expected):
    if not isinstance(obj, dict) or set(obj) != set(expected.split()):
        raise ValueError('Unexpected aggregate schema keys')


def validate_public(data):
    """Fail closed: no opaque metadata, account rows, arbitrary keys or strings."""
    keys(data, 'schema_version generated_at_unix privacy coin_list markets' + (' selection' if 'selection' in data else ''))
    if 'selection' in data:
        keys(data['selection'], 'unit operator threshold account_equity_min')
        if data['selection'] != SELECTION or type(data['selection']['threshold']) is not int:
            raise ValueError('Unsupported aggregate selection')
    if type(data['schema_version']) is not int or data['schema_version'] not in (1, 2, 3):
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
    version = data['schema_version']
    for market in data['markets'].values():
        v2 = version >= 2
        keys(market, 'reference_mark bucket_step buckets lev_unknown' if version == 3
             else 'reference_mark bucket_step buckets' if v2 else 'reference_mark buckets')
        number(market['reference_mark'], positive=True)
        if v2:
            number(market['bucket_step'], positive=True)
            if market['bucket_step'] != market['reference_mark'] * BUCKET_FRACTION:
                raise ValueError('Unexpected grid step')
        if version == 3:
            unknown = market['lev_unknown']
            keys(unknown, 'buckets notional')
            if type(unknown['buckets']) is not int or unknown['buckets'] < 0:
                raise ValueError('Invalid unsplit bucket count')
            number(unknown['notional'])
        if not isinstance(market['buckets'], list):
            raise ValueError('Invalid bucket list')
        seen = set()
        unsplit_buckets, unsplit_notional = 0, 0
        for b in market['buckets']:
            field = 'index' if v2 else 'band'
            keys(b, f'side {field} notional positions px_low px_high lev' if version == 3
                 else f'side {field} notional positions px_low px_high')
            index = b[field]
            if b['side'] not in ('L', 'S') or type(index) is not int or index < 0 or (not v2 and index >= 14) or index > 9007199254740991:
                raise ValueError('Invalid bucket')
            key = b['side'], index
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
            if v2 and (grid_index(b['px_low'], market['bucket_step']) != index or
                       grid_index(b['px_high'], market['bucket_step']) != index):
                raise ValueError('Price outside fixed grid cell')
            if version == 3:
                if b['lev'] is None:
                    unsplit_buckets += 1
                    unsplit_notional += b['notional']
                    continue
                if not isinstance(b['lev'], list) or len(b['lev']) != LEV_COUNT:
                    raise ValueError('Invalid leverage split')
                for value in b['lev']:
                    number(value)
                # The split must reconstruct the cell total, never approximate it.
                if not math.isclose(sum(b['lev']), b['notional'], rel_tol=1e-12, abs_tol=1e-6):
                    raise ValueError('Leverage split does not sum to bucket notional')
        if version == 3:
            if market['lev_unknown']['buckets'] != unsplit_buckets:
                raise ValueError('Unsplit bucket count mismatch')
            if not math.isclose(market['lev_unknown']['notional'], unsplit_notional, rel_tol=1e-12, abs_tol=1e-6):
                raise ValueError('Unsplit bucket notional mismatch')
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
    p.add_argument('--schema', type=int, default=3, choices=(1, 2, 3),
                   help='output schema version; 2 and 1 are kept for rollback only')
    args = p.parse_args()
    if args.validate:
        validate_public(json.loads(args.validate.read_text()))
        print('Aggregate schema valid; no addresses or account records')
        return
    if not all((args.snapshot, args.coins, args.marks, args.output)):
        p.error('snapshot, coins, marks and output are required')
    build = {1: aggregate_v1, 2: aggregate_v2, 3: aggregate}[args.schema]
    output = build(json.loads(args.snapshot.read_text()), json.loads(args.marks.read_text()), json.loads(args.coins.read_text()))
    # A new immutable generation prevents accidental replacement of a previous file.
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x') as f:
        json.dump(output, f, separators=(',', ':'), allow_nan=False)
    print(f'Exported {sum(len(m["buckets"]) for m in output["markets"].values())} public buckets (schema {args.schema})')


if __name__ == '__main__':
    main()
