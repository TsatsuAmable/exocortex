#!/usr/bin/env python3
from contextlib import closing
import fcntl
import json
import os
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from distillation_review_reconciler import ensure_schema as ensure_review_schema, unadjudicated_review_count
from distillation_review_surface import review_surface_dirty
from distillation_rewrite_repair import actionable_rewrite_count
from distillation_evidence_review import pending_count as evidence_review_pending_count

ROOT = Path.home()/"Library/Application Support/Aineko/GOMS"
DB = ROOT/"goms.sqlite3"
LOCK = ROOT/"distillation_semantic_daemon.lock"
STAGE_ORDER = ('validate','reconcile','gate','adjudicate','evidence','shape','rewrite','promote','surface')
STAGE_KEYS = {
    'validate':'unvalidated','reconcile':'unreconciled','gate':'gate_missing',
    'adjudicate':'review_actionable','evidence':'evidence_review_actionable',
    'shape':'shape_missing','rewrite':'rewrite_actionable',
    'promote':'promotable','surface':'surface_dirty',
}
STAGE_CAPACITY = {
    'validate':100,
    'reconcile':120,
    'gate':1000,
    'adjudicate':100,
    'evidence':12,
    'shape':12,
    'rewrite':50,
    'promote':1000,
    'surface':1,
}
SCRIPTS = {
    'validate': 'distillation_validate_incremental.py','reconcile': 'distillation_reconcile.py',
    'gate': 'distillation_promotion_gate.py','adjudicate': 'distillation_review_reconciler.py',
    'evidence': 'distillation_evidence_review.py',
    'shape': 'distillation_graphshape_review.py','rewrite': 'distillation_rewrite_repair.py',
    'promote': 'distillation_promote.py','surface': 'distillation_review_surface.py',
}


def stage_counts(db_path=DB):
    with closing(sqlite3.connect(db_path)) as c:
        ensure_review_schema(c)
        q = {}
        q['unvalidated'] = c.execute("select count(*) from distillation_candidates d left join distillation_validations v on v.candidate_id=d.id where v.candidate_id is null").fetchone()[0]
        q['unreconciled'] = c.execute("select count(*) from distillation_candidates d join distillation_validations v on v.candidate_id=d.id left join distillation_reconciliation_proposals p on p.candidate_id=d.id where p.candidate_id is null and v.verdict in ('accept','reclassify') and v.durability in ('project','enduring') and d.confidence>=0.80 and v.confidence>=0.80").fetchone()[0]
        q['gate_missing'] = c.execute("select count(*) from distillation_reconciliation_proposals p left join distillation_promotion_gate g on g.candidate_id=p.candidate_id where p.status='candidate' and (g.candidate_id is null or g.gate_fingerprint is null)").fetchone()[0]
        q['review_actionable'] = unadjudicated_review_count(c)
        q['evidence_review_actionable'] = evidence_review_pending_count(c)
        q['shape_missing'] = c.execute("select count(*) from distillation_reconciliation_proposals p join distillation_promotion_gate g on g.candidate_id=p.candidate_id left join distillation_graphshape_reviews s on s.candidate_id=g.candidate_id and s.gate_fingerprint=g.gate_fingerprint where p.status='candidate' and g.decision='AUTO_READY' and g.gate_fingerprint is not null and s.candidate_id is null").fetchone()[0]
        q['rewrite_actionable'] = actionable_rewrite_count(c)
        q['promotable'] = c.execute("select count(*) from distillation_reconciliation_proposals p join distillation_promotion_gate g on g.candidate_id=p.candidate_id join distillation_graphshape_reviews s on s.candidate_id=p.candidate_id and s.gate_fingerprint=g.gate_fingerprint where p.status='candidate' and g.decision='AUTO_READY' and g.gate_fingerprint is not null and s.verdict='ACCEPT'").fetchone()[0]
        q['surface_dirty'] = 1 if review_surface_dirty(c) else 0
        return q


def choose_stage(counts, cursor=0, promotion_enabled=True, backlog_aware=False):
    start=int(cursor) % len(STAGE_ORDER)
    ordered=[STAGE_ORDER[(start+offset) % len(STAGE_ORDER)] for offset in range(len(STAGE_ORDER))]
    active=[
        stage for stage in ordered
        if not (stage=='promote' and not promotion_enabled)
        and int(counts.get(STAGE_KEYS[stage],0)) > 0
    ]
    if not active:
        return None
    if backlog_aware:
        overloaded=[
            stage for stage in active
            if int(counts.get(STAGE_KEYS[stage],0)) >= int(STAGE_CAPACITY[stage])
        ]
        if overloaded:
            order_index={stage:i for i,stage in enumerate(ordered)}
            return max(
                overloaded,
                key=lambda stage: (
                    float(counts.get(STAGE_KEYS[stage],0))/max(1,float(STAGE_CAPACITY[stage])),
                    -order_index[stage],
                ),
            )
    return active[0]


def run_stage(stage, root=ROOT):
    script = SCRIPTS[stage]
    cp = subprocess.run([sys.executable, str(Path(root)/script)], cwd=root, text=True, capture_output=True, timeout=300)
    return {'stage':stage,'returncode':cp.returncode,'stdout':cp.stdout[-4000:],'stderr':cp.stderr[-4000:]}


def run_forever(active_sleep=1.0, idle_sleep=15.0):
    with LOCK.open('w') as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX|fcntl.LOCK_NB)
        cursor=0
        promotion_enabled=os.getenv('GOMS_PROMOTION_ENABLED','1').strip().lower() not in ('0','false','no','off')
        while True:
            counts = stage_counts()
            scheduler=os.getenv('GOMS_SEMANTIC_SCHEDULER','pressure').strip().lower()
            stage = choose_stage(
                counts,cursor=cursor,promotion_enabled=promotion_enabled,
                backlog_aware=scheduler in ('pressure','backlog','adaptive'),
            )
            result = {'observed_at':datetime.now(timezone.utc).isoformat(),'counts':counts,'stage':stage}
            if stage:
                cursor=(STAGE_ORDER.index(stage)+1) % len(STAGE_ORDER)
                outcome = run_stage(stage); result['outcome'] = outcome
                print(json.dumps(result,sort_keys=True),flush=True)
                time.sleep(max(5.0,idle_sleep) if outcome['returncode'] else active_sleep)
            else:
                print(json.dumps(result,sort_keys=True),flush=True); time.sleep(idle_sleep)


def main(): run_forever()
if __name__=='__main__': main()
