#!/usr/bin/env python3
"""Deterministically re-enter exact-consensus graph-shape rewrites into the semantic pipeline."""
from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone
import json
import os
import sqlite3
from pathlib import Path

from distillation_review_reconciler import ensure_schema as ensure_review_schema

ROOT=Path.home()/"Library/Application Support/Aineko/GOMS"
DB=ROOT/"goms.sqlite3"


def now():
    return datetime.now(timezone.utc).isoformat()


def ensure_schema(connection):
    ensure_review_schema(connection)
    connection.executescript("""
      create table if not exists distillation_rewrite_repairs(
        candidate_id text not null,
        gate_fingerprint text not null,
        action text not null,
        reason text not null,
        before_state text not null,
        after_state text not null,
        repaired_at text not null,
        primary key(candidate_id,gate_fingerprint)
      );
    """)


def _committee_models(raw):
    text=str(raw or "")
    if text.startswith("committee:"):
        text=text.split(":",1)[1]
    return [x.strip() for x in text.split(",") if x.strip()]


def _rewrite_signature(row):
    return (
        str(row["subject_title"] or "").strip(),
        str(row["subject_type"] or "").strip(),
        str(row["predicate"] or "").strip(),
        str(row["object_title"] or "").strip(),
        str(row["object_type"] or "").strip(),
        None if row["literal"] is None else str(row["literal"]).strip(),
    )


def _proposal_state(row):
    keys=("candidate_id","canonical_kind","subject_mode","subject_id","subject_type","subject_title",
          "predicate","object_mode","object_id","object_type","object_title","literal",
          "confidence","rationale","status","created_at")
    return {k:row[k] for k in keys if k in row.keys()}


def _exact_consensus_rewrite(connection, row):
    models=_committee_models(row["reviewer_model"])
    if len(models) < 2 or not str(row["shape_rationale"] or "").startswith("CONSENSUS_REWRITE"):
        return None

    reviews=[]
    for model in models:
        review=connection.execute("""
          select * from distillation_graphshape_review_history
          where candidate_id=? and reviewer_model=? and verdict='REWRITE'
            and reviewed_at<=?
          order by reviewed_at desc limit 1
        """,(row["candidate_id"],model,row["shape_reviewed_at"])).fetchone()
        if review is None:
            return None
        reviews.append(review)

    signatures={_rewrite_signature(r) for r in reviews}
    if len(signatures) != 1:
        return None
    signature=next(iter(signatures))
    subject_title,subject_type,predicate,object_title,object_type,literal=signature
    if not subject_title or not subject_type or not predicate:
        return None

    # Existing IDs are authoritative. Rewriting their title/type without identity reconciliation
    # could silently attach a claim to the wrong canonical entity, so only rewrite proposed subjects.
    if row["subject_mode"] != "new":
        return None
    if row["object_mode"] == "existing":
        return None
    if not object_title and literal is None:
        return None
    return {
        "subject_title":subject_title,
        "subject_type":subject_type,
        "predicate":predicate,
        "object_title":object_title or None,
        "object_type":object_type or None,
        "literal":literal,
    }


def actionable_rewrite_count(connection):
    ensure_schema(connection)
    connection.row_factory=sqlite3.Row
    count=0
    for row in _candidate_rows(connection, limit=10000):
        if _exact_consensus_rewrite(connection,row):
            count+=1
    return count


def _candidate_rows(connection, limit):
    return connection.execute("""
      select p.*,g.gate_fingerprint,
             s.rationale shape_rationale,s.reviewer_model,s.reviewed_at shape_reviewed_at
      from distillation_reconciliation_proposals p
      join distillation_promotion_gate g on g.candidate_id=p.candidate_id
      join distillation_graphshape_reviews s
        on s.candidate_id=p.candidate_id and s.gate_fingerprint=g.gate_fingerprint
      left join distillation_rewrite_repairs rr
        on rr.candidate_id=p.candidate_id and rr.gate_fingerprint=g.gate_fingerprint
      where p.status='candidate'
        and g.decision='AUTO_READY'
        and s.verdict='REWRITE'
        and rr.candidate_id is null
      order by s.reviewed_at,p.candidate_id
      limit ?
    """,(max(1,int(limit)),)).fetchall()


def repair_batch(connection, limit=50, observed_at=None):
    ensure_schema(connection)
    connection.row_factory=sqlite3.Row
    ts=observed_at or now()
    repaired=[]
    skipped=[]
    for row in _candidate_rows(connection, max(1,int(limit))*4):
        if len(repaired) >= max(1,int(limit)):
            break
        rewrite=_exact_consensus_rewrite(connection,row)
        if not rewrite:
            continue
        before=_proposal_state(row)
        if rewrite["object_title"]:
            object_mode="new"
            object_title=rewrite["object_title"]
            object_type=rewrite["object_type"] or "idea"
            literal=None
        else:
            object_mode="literal"
            object_title=None
            object_type=None
            literal=rewrite["literal"]

        connection.execute("""
          update distillation_reconciliation_proposals
          set subject_id=null,subject_type=?,subject_title=?,
              predicate=?,
              object_mode=?,object_id=null,object_type=?,object_title=?,literal=?,
              rationale=?
          where candidate_id=? and status='candidate'
        """,(
          rewrite["subject_type"],rewrite["subject_title"],rewrite["predicate"],
          object_mode,object_type,object_title,literal,
          "Deterministic exact-consensus graph-shape rewrite; re-gate required.",
          row["candidate_id"],
        ))
        after_row=connection.execute(
            "select * from distillation_reconciliation_proposals where candidate_id=?",
            (row["candidate_id"],)
        ).fetchone()
        after=_proposal_state(after_row)
        connection.execute("""
          insert or replace into distillation_rewrite_repairs(
            candidate_id,gate_fingerprint,action,reason,before_state,after_state,repaired_at)
          values(?,?,?,?,?,?,?)
        """,(
          row["candidate_id"],row["gate_fingerprint"],"APPLY_EXACT_CONSENSUS_REWRITE",
          "CONSENSUS_REWRITE_IDENTICAL_SHAPE",
          json.dumps(before,sort_keys=True),json.dumps(after,sort_keys=True),ts,
        ))
        # The proposal-update trigger invalidates the old gate fingerprint and shape review.
        repaired.append(row["candidate_id"])
    connection.commit()
    return {"repaired":len(repaired),"candidate_ids":repaired,"skipped":len(skipped)}


def main():
    batch=max(1,min(int(os.getenv("GOMS_REWRITE_REPAIR_BATCH_SIZE","50")),500))
    with closing(sqlite3.connect(DB)) as c:
        print(json.dumps(repair_batch(c,limit=batch),indent=2))


if __name__=="__main__":
    main()
