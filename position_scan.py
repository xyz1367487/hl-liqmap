"""Private, persistent full-index rotation; never uses equity or last-seen as admission."""
import math

POSITION_MIN = 5000
SELECTION = {'unit': 'position_notional_usd', 'operator': 'gt', 'threshold': POSITION_MIN,
             'account_equity_min': None}
BATCH_SIZE = 400
RETRY_SIZE = 100


def prepare(state, addresses, accounts):
    """Append discoveries without reordering the unfinished pass or changing fs/ls."""
    if state is None:
        state = {'version': 1, 'order': [], 'cursor': 0, 'cycles': 0, 'retry': []}
    if state.get('version') != 1:
        raise ValueError('Unsupported recheck state')
    known = set(state['order'])
    # accounts may contain legacy candidates absent from the address index.
    for a in sorted(set(addresses) | set(accounts)):
        if a not in known:
            state['order'].append(a)
            known.add(a)
    if not 0 <= state['cursor'] <= len(state['order']):
        raise ValueError('Invalid recheck cursor')
    return state


def plan(state, batch_size=BATCH_SIZE, retry_size=RETRY_SIZE):
    if batch_size <= 0 or not 0 <= retry_size < batch_size:
        raise ValueError('Invalid bounded scan sizes')
    start = state['cursor']
    if start == len(state['order']) and state['order']:
        start = 0
    retries = state['retry'][:retry_size]
    end = min(len(state['order']), start + batch_size - len(retries))
    forward = state['order'][start:end]
    return list(dict.fromkeys(retries + forward)), start, end


def finish(state, start, end, results):
    """Only advance after results and candidate state have been saved. Failed work stays queued.

    No checkpoint on a killed run means replay, never skipping unfinished work.
    Retry failures rotate to the tail so one broken address cannot starve others.
    """
    retry = [a for a in state['retry'] if a not in results]
    retry.extend(a for a, rec in results.items() if rec is None)
    state['retry'] = list(dict.fromkeys(retry))
    state['cursor'] = end
    if end == len(state['order']) and end > start:
        state['cycles'] += 1
    return state


def progress(state, batch_size=BATCH_SIZE):
    remaining = len(state['order']) - state['cursor']
    return {'indexed': len(state['order']), 'cursor': state['cursor'], 'cycles': state['cycles'],
            'retry_pending': len(state['retry']), 'batch_size': batch_size,
            'remaining_in_pass': remaining,
            'estimated_runs': math.ceil(remaining / (batch_size - RETRY_SIZE)),
            'cadence_minutes': 30}
