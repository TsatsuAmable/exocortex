#!/usr/bin/env python3
"""Second-pass evidence sufficiency review for low-confidence semantic candidates.

This stage never lowers the base promotion threshold. It can only override the
LOW_COMPOSITE_CONFIDENCE reason when independent qualified reviewers unanimously
judge the cited evidence sufficient. All other hard-review reasons remain binding.
"""
from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone, timedelta
import json
import os
import sqlite3
from pathlib import Path

from distillation_model_client import generate_structured, prompt_allows_remote
from distillation_review_policy import (
    LOW_COMPOSITE_CONFIDENCE,
    gate_fingerprint,
    requires_hard_review,
)
from model_router_bridge import rank_models

ROOT=Path.home()/"Library/Application Support/Aineko/GOMS"
DB=ROOT/"goms.sqlite3"

PROMPT="""You are an independent evidence-sufficiency reviewer for a long-lived personal knowledge graph.
The candidate has already passed extraction and first-pass validation but fell below the normal
confidence threshold. Judge ONLY whether the cited evidence directly and durably supports the
proposed canonical assertion.

Return strict JSON {"items":[...]} with one item per candidate:
candidate_id, verdict (ACCEPT|ABSTAIN|REJECT), confidence 0..1, rationale.

ACCEPT only when the evidence itself clearly supports the proposed assertion and its durability.
ABSTAIN when evidence is incomplete, ambiguous, context-dependent, or requires inference.
REJECT when the evidence contradicts or does not support the assertion.
Do not repair graph shape, invent facts, infer user intent, or reward plausibility."""


def now():
    return datetime.now(timezone.utc).isoformat()


def ensure_schema(connection):
    connection.executescript("""
      create table if not exists distillation_evidence_reviews(
        candidate_id text not null,
        gate_fingerprint text not null,
        reviewer_model text not null,
        verdict text not null,
        confidence real not null,
        rationale text not null,
        reviewed_at text not null,
        primary key(candidate_id,gate_fingerprint,reviewer_model)
      );
      create table if not exists distillation_evidence_review_decisions(
        candidate_id text not null,
        gate_fingerprint text not null,
        decision text not null,
        confidence real not null,
        reviewer_models text not null,
        rationale text not null,
        decided_at text not null,
        primary key(candidate_id,gate_fingerprint)
      );
      create table if not exists distillation_reviewer_route_health(
        family text not null,
        model text not null,
        consecutive_failures integer not null default 0,
        last_error text,
        cooldown_until text,
        last_success_at text,
        updated_at text not null,
        primary key(family,model)
      );
    """)


def _reasons(raw):
    try:
        value=json.loads(raw or "[]")
        return [str(x) for x in value] if isinstance(value,list) else []
    except Exception:
        return []


def select_pending(connection, limit=24):
    ensure_schema(connection)
    connection.row_factory=sqlite3.Row
    rows=connection.execute("""
      select p.*,g.decision,g.score,g.reasons,g.subject_resolution,g.object_resolution,
             g.contradiction_count,g.checked_at gate_checked_at,g.gate_fingerprint,
             d.confidence extractor_confidence,d.evidence_ids,
             v.confidence validator_confidence,v.verdict,v.validated_kind,v.durability,
             t.temporal_mode,t.observed_at temporal_observed_at,
             t.auto_eligible temporal_auto_eligible,t.reasons temporal_reasons
      from distillation_reconciliation_proposals p
      join distillation_promotion_gate g on g.candidate_id=p.candidate_id
      join distillation_candidates d on d.id=p.candidate_id
      join distillation_validations v on v.candidate_id=p.candidate_id
      join distillation_temporal_authority t on t.candidate_id=p.candidate_id
      join distillation_review_adjudications a
        on a.candidate_id=p.candidate_id and a.gate_fingerprint=g.gate_fingerprint
      left join distillation_evidence_review_decisions er
        on er.candidate_id=p.candidate_id and er.gate_fingerprint=g.gate_fingerprint
      where p.status='candidate'
        and g.decision='REVIEW'
        and g.gate_fingerprint is not null
        and a.action='HOLD'
        and a.reason=?
        and t.auto_eligible=1
        and g.contradiction_count=0
        and er.candidate_id is null
      order by g.checked_at,p.candidate_id
      limit ?
    """,(LOW_COMPOSITE_CONFIDENCE,max(1,int(limit)))).fetchall()
    out=[]
    for row in rows:
        reasons=[r for r in _reasons(row["reasons"]) if r != LOW_COMPOSITE_CONFIDENCE]
        # An evidence-confidence committee cannot waive identity/contradiction/shape/temporal reasons.
        if requires_hard_review(reasons):
            continue
        out.append(dict(row))
    return out


def pending_count(connection):
    return len(select_pending(connection,limit=100000))


def _evidence_payload(connection, row):
    try:
        ids=json.loads(row.get("evidence_ids") or "[]")
    except Exception:
        ids=[]
    evidence=[]
    for eid in ids:
        found=connection.execute(
            "select id,title,summary,created_at from entities where id=?",(eid,)
        ).fetchone()
        if found:
            evidence.append({
                "id":found["id"],
                "title":found["title"],
                "text":str(found["summary"] or "")[:2400],
                "created_at":found["created_at"],
            })
    return evidence


def _candidate_payload(connection, row):
    return {
        "candidate_id":row["candidate_id"],
        "canonical_kind":row["canonical_kind"],
        "assertion":{
            "subject":{"mode":row["subject_mode"],"id":row["subject_id"],
                       "type":row["subject_type"],"title":row["subject_title"]},
            "predicate":row["predicate"],
            "object":{"mode":row["object_mode"],"id":row["object_id"],
                      "type":row["object_type"],"title":row["object_title"],
                      "literal":row["literal"]},
        },
        "durability":row["durability"],
        "extractor_confidence":row["extractor_confidence"],
        "validator_confidence":row["validator_confidence"],
        "proposal_confidence":row["confidence"],
        "evidence":_evidence_payload(connection,row),
    }


REVIEW_FAMILY="goms-evidence-review"

def _parse_time(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z","+00:00"))
    except ValueError:
        return None


def route_in_cooldown(connection, model, family=REVIEW_FAMILY, observed_at=None):
    ensure_schema(connection)
    row=connection.execute(
        "select cooldown_until from distillation_reviewer_route_health where family=? and model=?",
        (family,model),
    ).fetchone()
    if not row:
        return False
    until=_parse_time(row[0] if not hasattr(row,"keys") else row["cooldown_until"])
    current=observed_at or datetime.now(timezone.utc)
    return bool(until and until > current)


def record_route_failure(connection, model, error, family=REVIEW_FAMILY,
                         base_cooldown_seconds=3600, observed_at=None):
    ensure_schema(connection)
    current=observed_at or datetime.now(timezone.utc)
    row=connection.execute(
        "select consecutive_failures from distillation_reviewer_route_health where family=? and model=?",
        (family,model),
    ).fetchone()
    failures=(int(row[0]) if row else 0)+1
    cooldown=min(86400,int(base_cooldown_seconds)*(2 ** max(0,failures-1)))
    until=(current+timedelta(seconds=cooldown)).isoformat()
    connection.execute("""
      insert into distillation_reviewer_route_health(
        family,model,consecutive_failures,last_error,cooldown_until,last_success_at,updated_at)
      values(?,?,?,?,?,null,?)
      on conflict(family,model) do update set
        consecutive_failures=excluded.consecutive_failures,
        last_error=excluded.last_error,
        cooldown_until=excluded.cooldown_until,
        updated_at=excluded.updated_at
    """,(family,model,failures,str(error)[:500],until,current.isoformat()))
    connection.commit()
    return until


def record_route_success(connection, model, family=REVIEW_FAMILY, observed_at=None):
    ensure_schema(connection)
    current=observed_at or datetime.now(timezone.utc)
    connection.execute("""
      insert into distillation_reviewer_route_health(
        family,model,consecutive_failures,last_error,cooldown_until,last_success_at,updated_at)
      values(?,?,0,null,null,?,?)
      on conflict(family,model) do update set
        consecutive_failures=0,last_error=null,cooldown_until=null,
        last_success_at=excluded.last_success_at,updated_at=excluded.updated_at
    """,(family,model,current.isoformat(),current.isoformat()))
    connection.commit()


def select_reviewer_models(prompt, required=2, max_models=4, connection=None):
    rows=rank_models(
        prompt,
        family=REVIEW_FAMILY,
        privacy="non_sensitive" if prompt_allows_remote(prompt) else "private",
        mode="direct",context=8192,threshold=.65,limit=12,
    )
    qualified=[
        row for row in rows
        if row.get("adapter")=="ollama"
        and row.get("qualification")=="qualified"
        and row.get("lifecycle_state") in ("active","draining")
        and not (connection is not None and route_in_cooldown(connection,row.get("model")))
    ]
    if not prompt_allows_remote(prompt):
        qualified=[row for row in qualified if not row.get("network")]
    # Prefer independent remote qualified models; use a qualified local model only when needed.
    remote=[row for row in qualified if row.get("network")]
    local=[row for row in qualified if not row.get("network")]
    chosen=[]
    for row in remote+local:
        model=row.get("model")
        if model and model not in chosen:
            chosen.append(model)
        if len(chosen)>=max(required,int(max_models)):
            break
    return chosen


def _parse_response(raw):
    if isinstance(raw,dict):
        return raw
    text=str(raw or "").strip()
    a,b=text.find("{"),text.rfind("}")
    if a<0 or b<=a:
        raise ValueError("no JSON object")
    return json.loads(text[a:b+1])


def aggregate_reviews(reviews, required=2, confidence_threshold=.90):
    by_model={}
    for review in reviews:
        model=str(review.get("model") or "").strip()
        verdict=str(review.get("verdict") or "").upper()
        if model and verdict in {"ACCEPT","ABSTAIN","REJECT"}:
            by_model[model]=review
    items=list(by_model.values())
    if len(items) < required:
        return "ABSTAIN",0.0,"INSUFFICIENT_QUALIFIED_REVIEWERS"
    verdicts=[str(x["verdict"]).upper() for x in items]
    min_conf=min(float(x.get("confidence") or 0) for x in items)
    if any(v=="REJECT" for v in verdicts):
        return "REJECT",min_conf,"EVIDENCE_REVIEW_REJECT"
    if all(v=="ACCEPT" for v in verdicts) and min_conf >= confidence_threshold:
        return "ACCEPT",min_conf,"EVIDENCE_SUFFICIENCY_CONSENSUS"
    return "ABSTAIN",min_conf,"EVIDENCE_REVIEW_ABSTAIN"


def accepted_override(connection, candidate_id, base_gate_fingerprint, min_confidence=.90):
    ensure_schema(connection)
    row=connection.execute("""
      select decision,confidence from distillation_evidence_review_decisions
      where candidate_id=? and gate_fingerprint=?
    """,(candidate_id,base_gate_fingerprint)).fetchone()
    if not row:
        return False
    decision=row["decision"] if hasattr(row,"keys") else row[0]
    confidence=row["confidence"] if hasattr(row,"keys") else row[1]
    return str(decision)=="ACCEPT" and float(confidence or 0) >= float(min_confidence)


def _activate_gate(connection, row, decision):
    reasons=[r for r in _reasons(row["reasons"]) if r != LOW_COMPOSITE_CONFIDENCE]
    reasons.append("EVIDENCE_SUFFICIENCY_CONSENSUS")
    updated=dict(row)
    updated.update({
        "decision":"AUTO_READY",
        "reasons":json.dumps(reasons),
        "temporal_observed_at":row["temporal_observed_at"],
        "temporal_auto_eligible":row["temporal_auto_eligible"],
        "temporal_reasons":_reasons(row["temporal_reasons"]),
    })
    fingerprint=gate_fingerprint(updated)
    connection.execute("""
      update distillation_promotion_gate
      set decision='AUTO_READY',reasons=?,checked_at=?,gate_fingerprint=?
      where candidate_id=? and gate_fingerprint=?
    """,(
        json.dumps(reasons),now(),fingerprint,row["candidate_id"],row["gate_fingerprint"]
    ))
    # No graph-shape review should exist for a REVIEW gate, but enforce the invariant.
    connection.execute(
        "delete from distillation_graphshape_reviews where candidate_id=?",
        (row["candidate_id"],)
    )
    return fingerprint


def review_batch(connection, limit=24, required_reviewers=2, generator=generate_structured):
    ensure_schema(connection)
    connection.row_factory=sqlite3.Row
    rows=select_pending(connection,limit=limit)
    if not rows:
        return {"candidates":0,"activated":0,"decisions":{},"models":[]}

    payload=[_candidate_payload(connection,row) for row in rows]
    prompt=PROMPT+"\n\n"+json.dumps(payload,ensure_ascii=False)
    models=select_reviewer_models(prompt,required=required_reviewers,connection=connection)
    if len(models) < required_reviewers:
        return {
            "candidates":len(rows),"activated":0,
            "decisions":{"ABSTAIN":len(rows)},"models":models,
            "reason":"INSUFFICIENT_QUALIFIED_REVIEWERS",
        }

    reviews_by_candidate={row["candidate_id"]:[] for row in rows}
    model_errors={}
    for model in models:
        try:
            result=generator(prompt,models=(model,))
            parsed=_parse_response(result.get("parsed") or result.get("response"))
            actual_model=result.get("model",model)
        except Exception as exc:
            detail=f"{type(exc).__name__}: {exc}"[:500]
            model_errors[model]=detail
            record_route_failure(connection,model,detail)
            continue
        record_route_success(connection,actual_model)
        byid={x.get("candidate_id"):x for x in parsed.get("items",[])}
        for row in rows:
            item=byid.get(row["candidate_id"])
            if not item:
                continue
            verdict=str(item.get("verdict") or "ABSTAIN").upper()
            if verdict not in {"ACCEPT","ABSTAIN","REJECT"}:
                verdict="ABSTAIN"
            confidence=max(0.0,min(1.0,float(item.get("confidence") or 0)))
            rationale=str(item.get("rationale") or "")
            review={"model":actual_model,"verdict":verdict,
                    "confidence":confidence,"rationale":rationale}
            reviews_by_candidate[row["candidate_id"]].append(review)
            connection.execute("""
              insert or replace into distillation_evidence_reviews(
                candidate_id,gate_fingerprint,reviewer_model,verdict,
                confidence,rationale,reviewed_at)
              values(?,?,?,?,?,?,?)
            """,(row["candidate_id"],row["gate_fingerprint"],actual_model,
                 verdict,confidence,rationale,now()))
        connection.commit()
        if all(len({x["model"] for x in reviews_by_candidate[cid]}) >= required_reviewers
               for cid in reviews_by_candidate):
            break

    counts={"ACCEPT":0,"ABSTAIN":0,"REJECT":0,"PENDING":0}
    activated=0
    for row in rows:
        reviews=reviews_by_candidate[row["candidate_id"]]
        reviewers=sorted({x["model"] for x in reviews})
        if len(reviewers) < required_reviewers:
            counts["PENDING"]+=1
            continue
        decision,confidence,rationale=aggregate_reviews(
            reviews,
            required=required_reviewers,
        )
        counts[decision]+=1
        connection.execute("""
          insert or replace into distillation_evidence_review_decisions(
            candidate_id,gate_fingerprint,decision,confidence,
            reviewer_models,rationale,decided_at)
          values(?,?,?,?,?,?,?)
        """,(row["candidate_id"],row["gate_fingerprint"],decision,confidence,
             json.dumps(reviewers),rationale,now()))
        if decision=="ACCEPT":
            _activate_gate(connection,row,decision)
            activated+=1
    connection.commit()
    return {
        "candidates":len(rows),"activated":activated,
        "decisions":counts,"models":models,"model_errors":model_errors,
    }


def main():
    batch=max(1,min(int(os.getenv("GOMS_EVIDENCE_REVIEW_BATCH_SIZE","12")),96))
    with closing(sqlite3.connect(DB)) as c:
        print(json.dumps(review_batch(c,limit=batch),indent=2))


if __name__=="__main__":
    main()
