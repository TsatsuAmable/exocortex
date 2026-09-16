#!/usr/bin/env python3
from contextlib import closing
import fcntl
import json
import sqlite3
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path.home()/"Library/Application Support/Aineko/GOMS"
DB = ROOT/"goms.sqlite3"
LOCK = ROOT/"distillation_semantic_daemon.lock"

STAGE_ORDER = ('validate','reconcile','gate','shape','promote')

SCRIPTS = {
    'validate': 'distillation_validate_incremental.py',
    'reconcile': 'distillation_reconcile.py',
    'gate': 'distillation_promotion_gate.py',
    'shape': 'distillation_graphshape_review.py',
    'promote': 'distillation_promote.py',
}


def stage_counts(db_path=DB):
    with closing(sqlite3.connect(db_path)) as c:
        q = {}
        q['unvalidated'] = c.execute("""select count(*) from distillation_candidates d left join distillation_validations v on v.candidate_id=d.id where v.candidate_id is null""").fetchone()[0]
        q['unreconciled'] = c.execute("""select count(*) from distillation_candidates d join distillation_validations v on v.candidate_id=d.id left join distillation_reconciliation_proposals p on p.candidate_id=d.id where p.candidate_id is null and v.verdict in ('accept','reclassify') and v.durability in ('project','enduring') and d.confidence>=0.80 and v.confidence>=0.80""").fetchone()[0]
        q['gate_missing'] = c.execute("""select count(*) from distillation_reconciliation_proposals p left join distillation_promotion_gate g on g.candidate_id=p.candidate_id where p.status='candidate' and g.candidate_id is null""").fetchone()[0]
        q['shape_missing'] = c.execute("""select count(*) from distillation_promotion_gate g left join distillation_graphshape_reviews s on s.candidate_id=g.candidate_id where g.decision='AUTO_READY' and s.candidate_id is null""").fetchone()[0]
        q['promotable'] = c.execute("""select count(*) from distillation_reconciliation_proposals p join distillation_promotion_gate g on g.candidate_id=p.candidate_id join distillation_graphshape_reviews s on s.candidate_id=p.candidate_id where p.status='candidate' and g.decision='AUTO_READY' and s.verdict='ACCEPT'""").fetchone()[0]
        return q


def choose_stage(counts, cursor=0):
    keys={'validate':'unvalidated','reconcile':'unreconciled','gate':'gate_missing','shape':'shape_missing','promote':'promotable'}
    start=int(cursor) % len(STAGE_ORDER)
    for offset in range(len(STAGE_ORDER)):
        stage=STAGE_ORDER[(start+offset) % len(STAGE_ORDER)]
        if int(counts.get(keys[stage],0)) > 0:
            return stage
    return None


def run_stage(stage, root=ROOT):
    script = SCRIPTS[stage]
    cp = subprocess.run(['/usr/bin/python3', str(Path(root)/script)], cwd=root, text=True, capture_output=True, timeout=300)
    return {'stage':stage,'returncode':cp.returncode,'stdout':cp.stdout[-4000:],'stderr':cp.stderr[-4000:]}


def run_forever(active_sleep=1.0, idle_sleep=15.0):
    with LOCK.open('w') as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX|fcntl.LOCK_NB)
        cursor=0
        while True:
            counts = stage_counts()
            stage = choose_stage(counts,cursor=cursor)
            result = {'observed_at':datetime.now(timezone.utc).isoformat(),'counts':counts,'stage':stage}
            if stage:
                cursor=(STAGE_ORDER.index(stage)+1) % len(STAGE_ORDER)
                outcome = run_stage(stage)
                result['outcome'] = outcome
                print(json.dumps(result,sort_keys=True),flush=True)
                time.sleep(max(5.0,idle_sleep) if outcome['returncode'] else active_sleep)
            else:
                print(json.dumps(result,sort_keys=True),flush=True)
                time.sleep(idle_sleep)


def main():
    run_forever()


if __name__=='__main__': main()
