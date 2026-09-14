#!/usr/bin/env python3
from contextlib import closing
import hashlib, json, sqlite3
from datetime import datetime, timezone
from pathlib import Path

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
    rows=[dict(r) for r in c.execute("""select p.*,d.evidence_ids,
      d.confidence extractor_confidence,v.confidence validator_confidence,
      v.validator_model,g.score promotion_score,s.verdict shape_verdict,
      s.reviewer_model,s.rationale shape_rationale
      from distillation_reconciliation_proposals p
      join distillation_candidates d on d.id=p.candidate_id
      join distillation_validations v on v.candidate_id=p.candidate_id
      join distillation_promotion_gate g on g.candidate_id=p.candidate_id
      join distillation_graphshape_reviews s on s.candidate_id=p.candidate_id
      where p.status='candidate' and g.decision='AUTO_READY' and s.verdict='ACCEPT'
      order by g.score desc""").fetchall()]

    promoted=[]
    for p in rows:
        try: evidence=json.loads(p.get("evidence_ids") or "[]")
        except: evidence=[]
        provenance={
          "distillation_candidate_id":p["candidate_id"],
          "evidence_ids":evidence,
          "extractor_confidence":p["extractor_confidence"],
          "validator_confidence":p["validator_confidence"],
          "validator_model":p["validator_model"],
          "promotion_score":p["promotion_score"],
          "shape_reviewer_model":p["reviewer_model"],
          "shape_rationale":p["shape_rationale"]
        }
        ts=now()

        if p["subject_mode"]=="existing":
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
            object_id=p["object_id"]
        elif p["object_mode"]=="new":
            object_id=eid(p["object_type"] or "idea",p["object_title"])
            c.execute("""insert or ignore into entities
              (id,type,title,summary,status,tags,metadata,created_at,updated_at)
              values(?,?,?,?,?,'[]',?,?,?)""",
              (object_id,p["object_type"] or "idea",p["object_title"],
               "Promoted from validated distillation.","active",
               json.dumps({"provenance":provenance},sort_keys=True),ts,ts))

        source_ref="distillation://"+p["candidate_id"]
        confidence=min(float(p["extractor_confidence"] or 0),
                       float(p["validator_confidence"] or 0),
                       float(p["confidence"] or 0),
                       float(p["promotion_score"] or 0))
        assertion_id=aid(subject_id,p["predicate"],object_id,literal,source_ref)
        c.execute("""insert or ignore into semantic_assertions(
          id,subject_id,predicate,object_id,literal_value,confidence,
          epistemic_status,source_ref,metadata,created_at,updated_at)
          values(?,?,?,?,?,?,?,?,?,?,?)""",
          (assertion_id,subject_id,p["predicate"],object_id,literal,
           confidence,"validated_extracted",source_ref,
           json.dumps(provenance,sort_keys=True),ts,ts))
        c.execute("""update distillation_reconciliation_proposals
                     set status='promoted' where candidate_id=?""",(p["candidate_id"],))
        promoted.append({
          "candidate_id":p["candidate_id"],"assertion_id":assertion_id,
          "subject":p["subject_title"],"predicate":p["predicate"],
          "object":p["object_title"] or literal,"confidence":confidence
        })
    c.commit()
    print(json.dumps({"promoted":len(promoted),"items":promoted},indent=2))
