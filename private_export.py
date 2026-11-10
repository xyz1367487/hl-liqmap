#!/usr/bin/env python3
"""Run only in the private repository after collecting a private snapshot."""
import json
import os
import time
from pathlib import Path

from aggregate import aggregate
from harvest import info, require_private_data_dir
import harvest


def main():
    require_private_data_dir()
    state = Path(harvest.DATA_DIR)
    snapshot = json.loads((state / 'snapshot.json').read_text())
    coins = json.loads((state / 'coins.json').read_text())
    marks = {}
    for dex in (None, 'xyz'):
        payload = {'type': 'metaAndAssetCtxs'}
        if dex:
            payload['dex'] = dex
        meta, ctxs = info(payload)
        marks.update({u['name']: float(c['markPx']) for u, c in zip(meta['universe'], ctxs)})
    output = aggregate(snapshot, marks, coins)
    generation = os.environ.get('GITHUB_RUN_ID', str(time.time_ns())) + '-' + os.environ.get('GITHUB_RUN_ATTEMPT', '1')
    folder = Path('exports') / generation
    folder.mkdir(parents=True, exist_ok=False)
    with (folder / 'aggregate.json').open('x') as f:
        json.dump(output, f, separators=(',', ':'), allow_nan=False)
    # The raw snapshot and marks remain private and are versioned for reproducibility.
    archive = Path('snapshots') / generation
    archive.mkdir(parents=True, exist_ok=False)
    for name, data in [('snapshot.json', snapshot), ('marks.json', marks)]:
        with (archive / name).open('x') as f:
            json.dump(data, f, separators=(',', ':'), allow_nan=False)
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'], 'a') as f:
            f.write(f'aggregate_path={folder}/aggregate.json\n')
    print('Private generation archived; aggregate validated')


if __name__ == '__main__':
    main()
