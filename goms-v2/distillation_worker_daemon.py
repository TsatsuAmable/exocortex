#!/usr/bin/env python3
import argparse
import json
import time
from datetime import datetime, timezone

from distillation_worker_pool import run_pool


def now():
    return datetime.now(timezone.utc).isoformat()


def run_cycle(batch_size, *, run_pool_fn=run_pool):
    lanes = run_pool_fn(int(batch_size))
    attempted = sum(int(x.get('attempted', 0)) for x in lanes.values())
    done = sum(int(x.get('done', 0)) for x in lanes.values())
    repair = sum(int(x.get('repair', 0)) for x in lanes.values())
    provider_errors = sum(int(x.get('provider_errors', 0)) for x in lanes.values())
    queue_errors = sum(int(x.get('queue_errors', 0)) for x in lanes.values())
    return {
        'observed_at': now(),
        'attempted': attempted,
        'done': done,
        'repair': repair,
        'provider_errors': provider_errors,
        'queue_errors': queue_errors,
        'idle': attempted == 0,
        'lanes': lanes,
    }


def run_forever(batch_size=100, active_sleep=1.0, idle_sleep=15.0):
    while True:
        result = run_cycle(batch_size)
        print(json.dumps(result, sort_keys=True), flush=True)
        time.sleep(idle_sleep if result['idle'] else active_sleep)


def main():
    ap = argparse.ArgumentParser(description='Persistent GOMS distillation worker supervisor')
    ap.add_argument('--batch-size', type=int, default=100)
    ap.add_argument('--active-sleep', type=float, default=1.0)
    ap.add_argument('--idle-sleep', type=float, default=15.0)
    args = ap.parse_args()
    run_forever(args.batch_size, args.active_sleep, args.idle_sleep)


if __name__ == '__main__':
    main()
