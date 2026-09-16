#!/usr/bin/env python3
from contextlib import closing
import json,sqlite3,hashlib
from datetime import datetime,timezone,timedelta
from pathlib import Path

ROOT=Path.home()/"Library/Application Support/Aineko/GOMS"
DB=ROOT/"goms.sqlite3"
OUT=ROOT/"guardian"/"packets"
OUT.mkdir(parents=True,exist_ok=True)

def now(): return datetime.now(timezone.utc).isoformat()
def rows(c,q,args=()): return [dict(r) for r in c.execute(q,args).fetchall()]

with closing(sqlite3.connect(DB)) as c, c:
    c.row_factory=sqlite3.Row
    generated_at=now()
    packet={
      "generated_at":generated_at,
      "purpose":"Adversarial constitutional audit of GOMS against agalmic objectives. Propose only; do not mutate canonical state.",
      "system_resilience":{
        "open_priority_items":rows(c,"""select category,severity,title,summary,source,updated_at
                                      from attention_items where status='open' and category='p1'
                                      order by severity,updated_at desc"""),
        "resources":rows(c,"""select kind,name,status,generation,observed_generation,controller,updated_at
                             from resources order by kind,name""")
      },
      "attention":{
        "open_items":rows(c,"""select category,severity,title,summary,source,updated_at
                              from attention_items where status='open'
                              order by case severity when 'critical' then 0 when 'warning' then 1 else 2 end,
                                       updated_at desc limit 50"""),
        "open_count":c.execute("select count(*) from attention_items where status='open'").fetchone()[0]
      },
      "agalmic":{
        "state_counts":rows(c,"select task_state,count(*) count from agalmic_reconciliations group by task_state"),
        "blocked":rows(c,"""select a.task_id,b.title,b.project,a.scarcity_type,a.confidence,
                           a.rationale,a.proposed_action,a.adjacent_possible
                           from agalmic_reconciliations a left join branches b on b.id=a.task_id
                           where a.task_state='BLOCKED'"""),
        "active_program":rows(c,"""select id,title,status,objective,next_action,blocker,parent_branch
                                  from branches where project='GOMS'
                                  order by updated_at desc""")
      },
      "semantic":{
        "entity_counts":rows(c,"select type,count(*) count from entities group by type order by count desc"),
        "assertion_count":c.execute("select count(*) from semantic_assertions").fetchone()[0],
        "active_assertion_count":c.execute("select count(*) from semantic_assertions where valid_to is null or valid_to > ?",(generated_at,)).fetchone()[0],
        "historical_assertion_count":c.execute("select count(*) from semantic_assertions where valid_to is not null and valid_to <= ?",(generated_at,)).fetchone()[0],
        "quarantined_assertion_count":c.execute("select count(*) from semantic_assertions where epistemic_status in ('quarantined_nonfactual','authority_review')").fetchone()[0],
        "ontology_candidate_count":c.execute("select count(*) from ontology_proposals where status='candidate'").fetchone()[0],
        "top_ontology_candidates":rows(c,"""select proposal_type,canonical_name,evidence_count,confidence,rationale
                                           from ontology_proposals where status='candidate'
                                           order by confidence desc,evidence_count desc limit 30"""),
        "embedding_count":c.execute("select count(*) from semantic_embeddings").fetchone()[0]
      },
      "distillation":{
        "chat_evidence_count":c.execute("""select count(*) from entities
                                          where type='evidence'
                                          and source like 'chatgpt://conversation/%/message/%'""").fetchone()[0],
        "conversation_count":c.execute("""select count(*) from entities
                                         where type='source'
                                         and source like 'chatgpt://conversation/%'""").fetchone()[0],
        "semantic_assertion_count":c.execute("select count(*) from semantic_assertions").fetchone()[0],
        "active_semantic_assertion_count":c.execute("select count(*) from semantic_assertions where valid_to is null or valid_to > ?",(generated_at,)).fetchone()[0],
        "note":"Golden-set distillation metrics not yet implemented; treat as a programme gap."
      },
      "architecture":{
        "topology_nodes":rows(c,"""select type,title,status,summary from entities
                                  where type in ('machine','service','bridge','routine','data_store','interface','committee')
                                  order by type,title"""),
        "topology_relations":rows(c,"""select s.title src,r.rel,o.title dst
                                      from relations r
                                      join entities s on s.id=r.src join entities o on o.id=r.dst
                                      where s.type in ('machine','service','bridge','routine','data_store','interface','committee')
                                         or o.type in ('machine','service','bridge','routine','data_store','interface','committee')
                                      order by s.title,r.rel,o.title limit 200""")
      },
      "recent_change":{
        "recent_branches":rows(c,"""select id,title,project,status,last_result,next_action,blocker,updated_at
                                   from branches order by updated_at desc limit 30"""),
        "recent_assertions":rows(c,"""select a.id,s.title subject,a.predicate,o.title object,
                                     a.literal_value,a.confidence,a.epistemic_status,a.valid_from,a.valid_to,
                                     a.supersedes,a.source_ref,a.updated_at
                                     from semantic_assertions a
                                     left join entities s on s.id=a.subject_id
                                     left join entities o on o.id=a.object_id
                                     order by a.updated_at desc limit 50""")
      },
      "guardian_questions":[
        "Does the graph still represent the principal's current objectives and priorities?",
        "What important recent chat decisions or direction changes appear absent from semantic state?",
        "Which beliefs are stale, contradicted, duplicated, oversimplified, or unsupported?",
        "Is the ontology helping or impeding the agalmic loop?",
        "Are controllers reducing attention or producing administrative noise?",
        "Which tasks are failing to converge, and what scarcity/capability model best explains them?",
        "Which capabilities have been acquired but are not producing measurable scarcity displacement?",
        "What adjacent possibles are newly reachable but absent from GOMS?",
        "What architecture components are single points of failure or unobserved?",
        "Given current goals, would you build GOMS this way today? What should be changed, merged, removed, or simplified?"
      ]
    }

data=json.dumps(packet,ensure_ascii=False,sort_keys=True,indent=2)
sha=hashlib.sha256(data.encode()).hexdigest()
path=OUT/f"{datetime.now(timezone.utc):%Y-%m-%d}-{sha[:12]}.json"
path.write_text(data)
print(json.dumps({"path":str(path),"sha256":sha,"bytes":len(data.encode()),
                  "open_attention":packet["attention"]["open_count"],
                  "assertions":packet["semantic"]["assertion_count"],
                  "evidence":packet["distillation"]["chat_evidence_count"]},indent=2))
