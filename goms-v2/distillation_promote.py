#!/usr/bin/env python3
from contextlib import closing
import hashlib, json, sqlite3
from datetime import datetime, timezone
from pathlib import Path

from distillation_temporal_authority import TemporalProfile, assertion_fields, authority_profile, reconcile_lineages
from distillation_review_policy import assess_existing_values, entity_is_rebindable, gate_fingerprint
from distillation_review_reconciler import ensure_schema as ensure_review_schema

ROOT=Path.home()/"Library/Application Support/Aineko/GOMS"
DB=ROOT/"goms.sqlite3"

def now(): return datetime.now(timezone.utc).isoformat()
def eid(kind,title):
    return kind+"_"+hashlib.sha256(title.encode()).hexdigest()[:20]
def aid(subject,predicate,obj,literal,source):
    raw="|".join(str(x or "") for x in [subject,predicate,obj,literal,source])
    return "assert_"+hashlib.sha256(raw.encode()).hexdigest()[:24]

with closing(sqlite3.connect(DB)) as c, c:
    c.row_factory=sqlite3.Row
    ensure_review_schema(c)
    c.execute('BEGIN IMMEDIATE')
    rows=[dict(r) for r in c.execute("""select p.*,d.evidence_ids,
      d.confidence extractor_confidence,v.confidence validator_confidence,
      v.validator_model,v.verdict,v.validated_kind,v.durability,
      g.decision gate_decision,g.score promotion_score,g.reasons gate_reasons,
      g.subject_resolution,g.object_resolution,g.contradiction_count,g.gate_fingerprint,
      s.verdict shape_verdict,s.reviewer_model,s.rationale shape_rationale,
      t.temporal_mode,t.observed_at,t.auto_eligible,t.reasons temporal_reasons
      from distillation_reconciliation_proposals p
      join distillation_candidates d on d.id=p.candidate_id
      join distillation_validations v on v.candidate_id=p.candidate_id
      join distillation_promotion_gate g on g.candidate_id=p.candidate_id
      join distillation_graphshape_reviews s on s.candidate_id=p.candidate_id
      join distillation_temporal_authority t on t.candidate_id=p.candidate_id
      where p.status='candidate' and g.decision='AUTO_READY' and g.gate_fingerprint is not null and s.verdict='ACCEPT' and t.auto_eligible=1
      order by g.score desc""").fetchall()]

    promoted=[]; skipped=[]
    def invalidate(candidate_id, reason):
        c.execute("update distillation_promotion_gate set gate_fingerprint=null where candidate_id=?",(candidate_id,))
        c.execute("delete from distillation_graphshape_reviews where candidate_id=?",(candidate_id,))
        skipped.append({'candidate_id':candidate_id,'reason':reason})

    for p in rows:
        try: evidence=json.loads(p.get("evidence_ids") or "[]")
        except: evidence=[]
        try: temporal_reasons=tuple(json.loads(p.get("temporal_reasons") or "[]"))
        except Exception: temporal_reasons=()
        temporal=TemporalProfile(p["temporal_mode"],p["observed_at"],bool(p["auto_eligible"]),temporal_reasons)
        current_temporal=authority_profile(c,p.get('canonical_kind'),p.get('durability'),evidence)
        if (current_temporal.mode,current_temporal.observed_at,current_temporal.auto_eligible,tuple(current_temporal.reasons)) != (temporal.mode,temporal.observed_at,temporal.auto_eligible,tuple(temporal.reasons)):
            invalidate(p['candidate_id'],'TEMPORAL_AUTHORITY_STALE')
            continue
        fingerprint_row=dict(p)
        fingerprint_row.update({
          'decision':p['gate_decision'],'score':p['promotion_score'],'reasons':p['gate_reasons'],
          'temporal_mode':current_temporal.mode,'temporal_observed_at':current_temporal.observed_at,
          'temporal_auto_eligible':current_temporal.auto_eligible,'temporal_reasons':list(current_temporal.reasons),
        })
        if gate_fingerprint(fingerprint_row) != p['gate_fingerprint']:
            invalidate(p['candidate_id'],'GATE_INPUTS_STALE')
            continue
        lifecycle=assertion_fields(current_temporal)
        temporal=current_temporal
        provenance={
          "distillation_candidate_id":p["candidate_id"],
          "evidence_ids":evidence,
          "extractor_confidence":p["extractor_confidence"],
          "validator_confidence":p["validator_confidence"],
          "validator_model":p["validator_model"],
          "promotion_score":p["promotion_score"],
          "shape_reviewer_model":p["reviewer_model"],
          "shape_rationale":p["shape_rationale"],
          "temporal_mode":temporal.mode,
          "observed_at":temporal.observed_at,
          "temporal_authority_reasons":list(temporal.reasons)
        }
        ts=now()

        if p["subject_mode"]=="existing":
            entity=c.execute("select id,type,title,status from entities where id=?",(p["subject_id"],)).fetchone()
            entity=dict(entity) if entity else None
            if not entity or not entity_is_rebindable(entity):
                invalidate(p['candidate_id'],'SUBJECT_ENTITY_STALE')
                continue
            subject_id=p["subject_id"]
        else:
            subject_id=eid(p["subject_type"] or "idea",p["subject_title"])
            c.execute("""insert or ignore into entities
              (id,type,title,summary,status,tags,metadata,created_at,updated_at)
              values(?,?,?,?,?,'[]',?,?,?)""",
              (subject_id,p["subject_type"] or "idea",p["subject_title"],
               "Promoted from validated distillation.","active",
               json.dumps({"provenance":provenance},sort_keys=True),ts,ts))

        object_id=None; literal=p["literal"]
        if p["object_mode"]=="existing":
            entity=c.execute("select id,type,title,status from entities where id=?",(p["object_id"],)).fetchone()
            entity=dict(entity) if entity else None
            if not entity or not entity_is_rebindable(entity):
                invalidate(p['candidate_id'],'OBJECT_ENTITY_STALE')
                continue
            object_id=p["object_id"]
        elif p["object_mode"]=="new":
            object_id=eid(p["object_type"] or "idea",p["object_title"])
            c.execute("""insert or ignore into entities
              (id,type,title,summary,status,tags,metadata,created_at,updated_at)
              values(?,?,?,?,?,'[]',?,?,?)""",
              (object_id,p["object_type"] or "idea",p["object_title"],
               "Promoted from validated distillation.","active",
               json.dumps({"provenance":provenance},sort_keys=True),ts,ts))

        if temporal.mode in ('CURRENT_STATE','COMMITMENT'):
            active=[dict(r) for r in c.execute(
              """select object_id,literal_value,valid_from,epistemic_status,source_ref
                 from semantic_assertions where subject_id=? and predicate=? and valid_to is null""",
              (subject_id,p['predicate'])).fetchall()]
            conflict=assess_existing_values(active,p['predicate'],object_id,literal,temporal)
            if conflict.contradiction_count:
                invalidate(p['candidate_id'],conflict.reasons[0] if conflict.reasons else 'AUTHORITY_CONFLICT')
                continue

        source_ref="distillation://"+p["candidate_id"]
        confidence=min(float(p["extractor_confidence"] or 0),
                       float(p["validator_confidence"] or 0),
                       float(p["confidence"] or 0),
                       float(p["promotion_score"] or 0))
        assertion_id=aid(subject_id,p["predicate"],object_id,literal,source_ref)
        source_entity_id=evidence[0] if evidence else None
        c.execute("""insert or ignore into semantic_assertions(
          id,subject_id,predicate,object_id,literal_value,confidence,
          epistemic_status,valid_from,valid_to,source_entity_id,source_ref,supersedes,
          metadata,created_at,updated_at)
          values(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
          (assertion_id,subject_id,p["predicate"],object_id,literal,
           confidence,lifecycle["epistemic_status"],lifecycle["valid_from"],lifecycle["valid_to"],
           source_entity_id,source_ref,None,json.dumps(provenance,sort_keys=True),ts,ts))
        if temporal.mode in ("CURRENT_STATE","COMMITMENT"):
            reconcile_lineages(c,subject_id,p["predicate"])
        c.execute("""update distillation_reconciliation_proposals
                     set status='promoted' where candidate_id=?""",(p["candidate_id"],))
        promoted.append({
          "candidate_id":p["candidate_id"],"assertion_id":assertion_id,
          "subject":p["subject_title"],"predicate":p["predicate"],
          "object":p["object_title"] or literal,"confidence":confidence
        })
    c.commit()
    print(json.dumps({"promoted":len(promoted),"items":promoted,"skipped":skipped},indent=2))
