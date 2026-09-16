#!/usr/bin/env python3
from contextlib import closing
import json, re, sqlite3
from datetime import datetime, timezone
from pathlib import Path

from distillation_temporal_authority import authority_profile, record_temporal_authority, temporal_gate_override
from distillation_review_policy import assess_existing_values, review_reason_for_score

ROOT=Path.home()/"Library/Application Support/Aineko/GOMS"
DB=ROOT/"goms.sqlite3"

def now(): return datetime.now(timezone.utc).isoformat()
def norm(x):
    return re.sub(r"[^a-z0-9]+"," ",str(x or "").lower()).strip()

SUSPICIOUS={"anversal","mnemosyne","nemosign","user workflow","system deployment","tooling ecosystem","neo4j knowledge graph"}
GENERIC_TYPES={"idea","constraint","capability","artifact","tool","project","routine","scarcity"}

with closing(sqlite3.connect(DB)) as c, c:
    c.row_factory=sqlite3.Row
    c.executescript("""CREATE TABLE IF NOT EXISTS distillation_promotion_gate(
      candidate_id TEXT PRIMARY KEY, decision TEXT NOT NULL, score REAL NOT NULL,
      reasons TEXT NOT NULL DEFAULT '[]', subject_resolution TEXT,
      object_resolution TEXT, contradiction_count INTEGER NOT NULL DEFAULT 0,
      checked_at TEXT NOT NULL);""")
    entities=[dict(r) for r in c.execute(
      "select id,type,title,summary from entities where type not in ('evidence','source')").fetchall()]
    by_title={norm(e["title"]):e for e in entities if e.get("title")}
    proposals=[dict(r) for r in c.execute("""select p.*,d.evidence_ids,
      d.confidence extractor_confidence,v.confidence validator_confidence,
      v.durability,v.verdict,v.validated_kind
      from distillation_reconciliation_proposals p
      join distillation_candidates d on d.id=p.candidate_id
      join distillation_validations v on v.candidate_id=p.candidate_id
      where p.status='candidate'""").fetchall()]

    counts={"AUTO_READY":0,"REVIEW":0,"REJECT":0}
    details=[]
    for p in proposals:
        reasons=[]
        ec=float(p.get("extractor_confidence") or 0)
        vc=float(p.get("validator_confidence") or 0)
        cc=float(p.get("confidence") or 0)
        score=(ec+vc+cc)/3.0
        try: evidence=json.loads(p.get("evidence_ids") or "[]")
        except: evidence=[]
        temporal=authority_profile(c,p.get('canonical_kind'),p.get('durability'),evidence)
        record_temporal_authority(c,p['candidate_id'],temporal,now())
        reasons.extend(temporal.reasons)
        if not evidence:
            reasons.append("NO_PROVENANCE"); score-=0.5
        elif len(evidence)>=2:
            score+=0.03
        if p.get("durability") not in ("project","enduring"):
            reasons.append("LOW_DURABILITY"); score-=0.25
        if p.get("verdict") not in ("accept","reclassify"):
            reasons.append("VALIDATOR_REJECTED"); score-=0.5

        stitle=norm(p.get("subject_title"))
        otitle=norm(p.get("object_title"))
        sres=None; ores=None

        if p.get("subject_mode")=="existing":
            row=next((e for e in entities if e["id"]==p.get("subject_id")),None)
            if not row:
                reasons.append("BAD_SUBJECT_ID"); score-=0.4
            else:
                sres=row["id"]
        elif stitle in by_title:
            reasons.append("SUBJECT_DUPLICATE_EXISTING")
            sres=by_title[stitle]["id"]; score-=0.08
        elif stitle in SUSPICIOUS or not stitle or len(stitle)>90:
            reasons.append("SUBJECT_IDENTITY_UNRESOLVED"); score-=0.25

        if p.get("object_mode")=="existing":
            row=next((e for e in entities if e["id"]==p.get("object_id")),None)
            if not row:
                reasons.append("BAD_OBJECT_ID"); score-=0.4
            else:
                ores=row["id"]
        elif p.get("object_mode")=="new":
            if otitle in by_title:
                reasons.append("OBJECT_DUPLICATE_EXISTING")
                ores=by_title[otitle]["id"]; score-=0.08
            elif otitle in SUSPICIOUS or not otitle or len(otitle)>110:
                reasons.append("OBJECT_IDENTITY_UNRESOLVED"); score-=0.20

        contradiction_count=0
        subject_id=sres or p.get("subject_id")
        if subject_id:
            existing_assertions=[dict(r) for r in c.execute(
              """select predicate,object_id,literal_value,valid_from from semantic_assertions
                 where subject_id=? and predicate=? and valid_to is null
                   and epistemic_status='validated_extracted'""",
              (subject_id,p.get("predicate"))).fetchall()]
            proposed_obj=ores or p.get("object_id")
            proposed_lit=p.get("literal")
            conflict=assess_existing_values(existing_assertions,p.get("predicate"),
                                             proposed_obj,proposed_lit,temporal)
            contradiction_count=conflict.contradiction_count
            reasons.extend(conflict.reasons)

        if contradiction_count:
            score-=min(0.35,0.15*contradiction_count)
        if p.get("subject_mode")=="new" and p.get("subject_type") in GENERIC_TYPES and len(stitle.split())>9:
            reasons.append("SENTENCE_SHAPED_SUBJECT"); score-=0.15
        if p.get("object_mode")=="new" and p.get("object_type") in GENERIC_TYPES and len(otitle.split())>12:
            reasons.append("SENTENCE_SHAPED_OBJECT"); score-=0.15

        score=max(0.0,min(1.0,score))
        score_reason=review_reason_for_score(score)
        if score_reason:
            reasons.append(score_reason)
        hard_reject={"NO_PROVENANCE","VALIDATOR_REJECTED","BAD_SUBJECT_ID","BAD_OBJECT_ID"}
        hard_review={"SUBJECT_IDENTITY_UNRESOLVED","OBJECT_IDENTITY_UNRESOLVED",
                     "POTENTIAL_CONTRADICTION","STALE_STATE_UPDATE",
                     "SENTENCE_SHAPED_SUBJECT","SENTENCE_SHAPED_OBJECT"}
        temporal_override=temporal_gate_override(temporal)
        if any(x in hard_reject for x in reasons) or score<0.55:
            decision="REJECT"
        elif temporal_override:
            decision=temporal_override
        elif any(x in hard_review for x in reasons) or score<0.88:
            decision="REVIEW"
        else:
            decision="AUTO_READY"

        counts[decision]+=1
        c.execute("""insert or replace into distillation_promotion_gate
          (candidate_id,decision,score,reasons,subject_resolution,object_resolution,
           contradiction_count,checked_at) values(?,?,?,?,?,?,?,?)""",
          (p["candidate_id"],decision,score,json.dumps(reasons),
           sres,ores,contradiction_count,now()))
        details.append({"candidate_id":p["candidate_id"],"decision":decision,
          "score":round(score,3),"subject":p.get("subject_title"),
          "predicate":p.get("predicate"),"object":p.get("object_title") or p.get("literal"),
          "reasons":reasons,"temporal_mode":temporal.mode,"observed_at":temporal.observed_at})
    c.commit()
    print(json.dumps({"counts":counts,"items":details},indent=2))
