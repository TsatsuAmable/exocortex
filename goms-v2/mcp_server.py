#!/usr/bin/env python3
from typing import Any
from pathlib import Path
from datetime import datetime, timezone
import json
import urllib.request

from mcp.server.mcpserver import MCPServer
from goms_store import GomsStore, ENTITY_TYPES, BRANCH_STATUSES
from control_intents import ControlIntentService, INTENT_STATUSES
from manfred_control import ManfredControl
from neo4j_projection import status as graph_projection_status, rebuild as graph_projection_rebuild, neighbors as graph_neighbors_query, vector_search as graph_vector_search

store = GomsStore()
server = MCPServer(
    name="goms",
    title="GOMS Research Exocortex",
    version="0.1.0",
    description="Provenance-first memory, branch state, and research coordination for Aineko.",
    instructions=(
        "Use GOMS for durable project memory, claims/evidence, checkpoints, failures, "
        "capabilities and handoffs. Prefer concise, meaningful records over chat transcripts."
    ),
)

def ok(**kwargs):
    return {"ok": True, **kwargs}


def _intent_service() -> ControlIntentService:
    return ControlIntentService(store.root)


def _manfred_control() -> ManfredControl:
    return ManfredControl(store.db)


@server.tool(structured_output=True, description="Store a durable typed memory entity with provenance metadata.")
def remember(entity_type: str, title: str, summary: str = "", project: str | None = None,
             status: str | None = None, confidence: float | None = None,
             source: str | None = None, tags: list[str] | None = None,
             metadata: dict[str, Any] | None = None, actor: str = "mcp") -> dict[str, Any]:
    if entity_type not in ENTITY_TYPES:
        raise ValueError(f"entity_type must be one of {sorted(ENTITY_TYPES)}")
    eid = store.add_entity(entity_type, title, summary, project, status, confidence,
                           source, tags, metadata, actor=actor)
    return ok(id=eid, type=entity_type)

@server.tool(structured_output=True, description="Recall durable memories by full-text query, optionally scoped to a project or type.")
def recall(query: str, project: str | None = None, entity_type: str | None = None,
           limit: int = 20) -> dict[str, Any]:
    limit = max(1, min(limit, 100))
    return ok(results=store.search(query, limit=limit, project=project, entity_type=entity_type))

@server.tool(structured_output=True, description="Fetch one memory entity and all direct graph relations.")
def get_memory(entity_id: str) -> dict[str, Any]:
    return ok(memory=store.get_entity(entity_id))

@server.tool(structured_output=True, description="Create or update a semantic relation between two durable memories.")
def link_memories(src: str, relation: str, dst: str,
                  evidence: str | None = None, actor: str = "mcp") -> dict[str, Any]:
    return ok(link=store.link(src, relation, dst, evidence=evidence, actor=actor))

@server.tool(structured_output=True, description="Create a tracked work branch for a project, investigation, or delegated task.")
def create_branch(title: str, project: str | None = None, objective: str = "",
                  status: str = "ACTIVE", next_action: str = "", blocker: str = "",
                  parent: str | None = None, worker: str | None = None,
                  unresolved: list[str] | None = None, actor: str = "mcp") -> dict[str, Any]:
    status = status.upper()
    if status not in BRANCH_STATUSES:
        raise ValueError(f"status must be one of {sorted(BRANCH_STATUSES)}")
    bid = store.create_branch(title=title, project=project, status=status,
                              objective=objective, next_action=next_action, blocker=blocker,
                              parent=parent, worker=worker, unresolved=unresolved, actor=actor)
    return ok(branch_id=bid)

@server.tool(structured_output=True, description="Append a checkpoint and update the current state of a branch.")
def checkpoint(branch_id: str, status: str, summary: str,
               next_action: str = "", blocker: str = "",
               unresolved: list[str] | None = None, source: str | None = None,
               actor: str = "mcp") -> dict[str, Any]:
    status = status.upper()
    if status not in BRANCH_STATUSES:
        raise ValueError(f"status must be one of {sorted(BRANCH_STATUSES)}")
    cid = store.checkpoint(branch_id, status, summary, unresolved=unresolved,
                           next_action=next_action, blocker=blocker, source=source, actor=actor)
    return ok(checkpoint_id=cid)

@server.tool(structured_output=True, description="List active, blocked, delegated, parked, or concluded branches.")
def branches(status: str | None = None, project: str | None = None) -> dict[str, Any]:
    return ok(branches=store.list_branches(status=status, project=project))

@server.tool(structured_output=True, description="Return a compact project-state packet: branches plus query-matched durable memories.")
def project_state(project: str | None = None, query: str | None = None,
                  limit: int = 12) -> dict[str, Any]:
    return ok(state=store.project_state(project=project, query=query, limit=max(1, min(limit, 50))))

@server.tool(structured_output=True, description="Record a research claim as a first-class memory entity.")
def record_claim(title: str, claim: str, project: str | None = None,
                 confidence: float | None = None, source: str | None = None,
                 tags: list[str] | None = None, actor: str = "mcp") -> dict[str, Any]:
    eid = store.add_entity("claim", title, claim, project, "ACTIVE", confidence,
                           source, tags, {"epistemic_role": "claim"}, actor=actor)
    return ok(claim_id=eid)

@server.tool(structured_output=True, description="Record evidence and optionally connect it to a claim as supporting or contradicting.")
def record_evidence(title: str, summary: str, project: str | None = None,
                    source: str | None = None, claim_id: str | None = None,
                    stance: str = "neutral", confidence: float | None = None,
                    tags: list[str] | None = None, actor: str = "mcp") -> dict[str, Any]:
    stance = stance.lower()
    if stance not in {"supports", "contradicts", "neutral"}:
        raise ValueError("stance must be supports, contradicts, or neutral")
    eid = store.add_entity("evidence", title, summary, project, "ACTIVE", confidence,
                           source, tags, {"epistemic_role": "evidence", "stance": stance}, actor=actor)
    relation = None
    if claim_id and stance != "neutral":
        relation = store.link(eid, stance, claim_id, evidence=source, actor=actor)
    return ok(evidence_id=eid, relation=relation)

@server.tool(structured_output=True, description="Record a failure and optionally extract a linked reusable lesson.")
def record_failure(title: str, summary: str, project: str | None = None,
                   lesson: str | None = None, source: str | None = None,
                   tags: list[str] | None = None, actor: str = "mcp") -> dict[str, Any]:
    failure_id = store.add_entity("failure", title, summary, project, "OBSERVED", None,
                                  source, tags, {"epistemic_role": "failure"}, actor=actor)
    lesson_id = None
    if lesson:
        lesson_id = store.add_entity("lesson", f"Lesson: {title}", lesson, project,
                                     "ACTIVE", None, source, tags,
                                     {"derived_from_failure": failure_id}, actor=actor)
        store.link(failure_id, "yields_lesson", lesson_id, actor=actor)
    return ok(failure_id=failure_id, lesson_id=lesson_id)

@server.tool(structured_output=True, description="Inspect aggregate GOMS entity, relation, and branch counts.")
def stats() -> dict[str, Any]:
    return ok(stats=store.stats())

@server.tool(structured_output=True, description="Inspect recent provenance events from the append-only ledger.")
def recent_events(limit: int = 30) -> dict[str, Any]:
    return ok(events=store.recent_events(limit=max(1, min(limit, 200))))

@server.tool(structured_output=True, description="Check whether the local Neo4j graph projection is reachable and current enough to query.")
def graph_status() -> dict[str, Any]:
    return ok(graph=graph_projection_status())

@server.tool(structured_output=True, description="Rebuild the Neo4j projection from canonical SQLite GOMS state. Canonical data is not modified.")
def graph_rebuild() -> dict[str, Any]:
    counts = graph_projection_rebuild(store)
    return ok(rebuilt=counts, graph=graph_projection_status())

@server.tool(structured_output=True, description="Return one-hop graph neighbours for a memory, branch, or checkpoint without exposing arbitrary Cypher.")
def graph_neighbors(node_id: str, limit: int = 50) -> dict[str, Any]:
    return ok(node_id=node_id, neighbors=graph_neighbors_query(node_id, limit))


@server.tool(structured_output=True, description="Return the compact current semantic world model around a person. History is opt-in.")
def semantic_world(person_title: str = "User", limit: int = 100, include_history: bool = False) -> dict[str, Any]:
    limit=max(1,min(limit,500))
    cutoff=datetime.now(timezone.utc).isoformat()
    with store.connect() as con:
        person=con.execute("SELECT id,title,summary FROM entities WHERE type='person' AND title=? LIMIT 1",(person_title,)).fetchone()
        if not person:
            return ok(person=None, assertions=[])
        history_clause="" if include_history else " AND (a.valid_to IS NULL OR a.valid_to > ?)"
        args=(person["id"],limit) if include_history else (person["id"],cutoff,limit)
        rows=con.execute(f"""
          SELECT a.id,a.predicate,a.confidence,a.epistemic_status,a.literal_value,
                 a.valid_from,a.valid_to,a.supersedes,a.source_ref,
                 o.id object_id,o.type object_type,o.title object_title,o.summary object_summary
          FROM semantic_assertions a
          LEFT JOIN entities o ON o.id=a.object_id
          WHERE a.subject_id=?{history_clause}
          ORDER BY a.confidence DESC,a.predicate,o.title
          LIMIT ?
        """,args).fetchall()
        return ok(person=dict(person), assertions=[dict(r) for r in rows], include_history=include_history)

@server.tool(structured_output=True, description="List ontology evolution proposals without promoting them to facts.")
def ontology_proposals(status: str = "candidate", limit: int = 50) -> dict[str, Any]:
    limit=max(1,min(limit,200))
    with store.connect() as con:
        rows=con.execute("""
          SELECT id,proposal_type,canonical_name,description,evidence_count,confidence,
                 status,rationale,metadata,created_at,updated_at
          FROM ontology_proposals WHERE status=?
          ORDER BY confidence DESC,evidence_count DESC LIMIT ?
        """,(status,limit)).fetchall()
    out=[]
    for r in rows:
        x=dict(r)
        try:x["metadata"]=json.loads(x.get("metadata") or "{}")
        except Exception:pass
        out.append(x)
    return ok(proposals=out)

@server.tool(structured_output=True, description="Return active semantic assertions for one canonical entity; set include_history for expired observations and superseded state.")
def semantic_assertions(entity_id: str, limit: int = 100, include_history: bool = False) -> dict[str, Any]:
    limit=max(1,min(limit,500))
    cutoff=datetime.now(timezone.utc).isoformat()
    with store.connect() as con:
        history_clause="" if include_history else " AND (a.valid_to IS NULL OR a.valid_to > ?)"
        args=(entity_id,entity_id,limit) if include_history else (entity_id,entity_id,cutoff,limit)
        rows=con.execute(f"""
          SELECT a.*,o.type object_type,o.title object_title
          FROM semantic_assertions a LEFT JOIN entities o ON o.id=a.object_id
          WHERE (a.subject_id=? OR a.object_id=?){history_clause}
          ORDER BY a.confidence DESC,a.updated_at DESC LIMIT ?
        """,args).fetchall()
    return ok(entity_id=entity_id, assertions=[dict(r) for r in rows], include_history=include_history)


@server.tool(structured_output=True, description="Semantic vector search across embedded GOMS concepts, projects, branches and ontology items.")
def semantic_search(query: str, limit: int = 12) -> dict[str, Any]:
    body=json.dumps({"model":"nomic-embed-text","input":query}).encode()
    req=urllib.request.Request("http://127.0.0.1:11434/api/embed",data=body,
                               headers={"Content-Type":"application/json"})
    with urllib.request.urlopen(req,timeout=30) as r:
        vec=json.load(r)["embeddings"][0]
    return ok(query=query, results=graph_vector_search(vec,max(1,min(limit,50))))


@server.tool(structured_output=True, description="Return current deterministic agalmic reconciliation state for tracked tasks.")
def agalmic_state(limit: int = 100) -> dict[str, Any]:
    limit=max(1,min(limit,500))
    with store.connect() as con:
        rows=con.execute("""
          SELECT a.task_id,b.title,b.project,b.status AS branch_status,
                 a.task_state,a.scarcity_type,a.confidence,a.rationale,
                 a.proposed_action,a.adjacent_possible,
                 s.title AS scarcity,c.title AS capability,a.observed_at
          FROM agalmic_reconciliations a
          LEFT JOIN branches b ON b.id=a.task_id
          LEFT JOIN entities s ON s.id=a.scarcity_entity_id
          LEFT JOIN entities c ON c.id=a.capability_entity_id
          ORDER BY CASE a.task_state WHEN 'BLOCKED' THEN 0 WHEN 'ACTIVE' THEN 1 ELSE 2 END,
                   b.updated_at DESC
          LIMIT ?
        """,(limit,)).fetchall()
    return ok(reconciliations=[dict(r) for r in rows])

@server.tool(structured_output=True, description="Return unresolved GOMS attention items generated by reconcilers and controllers.")
def attention_items(category: str | None = None, limit: int = 50) -> dict[str, Any]:
    limit=max(1,min(limit,200))
    with store.connect() as con:
        if category:
            rows=con.execute("""SELECT * FROM attention_items
                                WHERE status='open' AND category=?
                                ORDER BY CASE severity WHEN 'critical' THEN 0 WHEN 'warning' THEN 1 ELSE 2 END,
                                         updated_at DESC LIMIT ?""",(category,limit)).fetchall()
        else:
            rows=con.execute("""SELECT * FROM attention_items
                                WHERE status='open'
                                ORDER BY CASE severity WHEN 'critical' THEN 0 WHEN 'warning' THEN 1 ELSE 2 END,
                                         updated_at DESC LIMIT ?""",(limit,)).fetchall()
    out=[]
    for r in rows:
        x=dict(r)
        try:x["suggested_actions"]=json.loads(x.get("suggested_actions") or "[]")
        except Exception:pass
        out.append(x)
    return ok(items=out)


@server.tool(structured_output=True, description="Return one canonical GOMS control intent by ID.")
def control_intent(intent_id: str) -> dict[str, Any]:
    try:
        return ok(intent=_intent_service().get(intent_id))
    except KeyError:
        return {"ok": False, "error": "intent_not_found"}


@server.tool(structured_output=True, description="List canonical GOMS control intents, optionally filtered by lifecycle status.")
def control_intents(status: str | None = None, limit: int = 50) -> dict[str, Any]:
    limit=max(1,min(limit,200))
    svc=_intent_service()
    if status is None:
        return ok(intents=svc.list_open(limit))
    status=str(status).upper()
    if status not in INTENT_STATUSES:
        return {"ok":False,"error":"invalid_intent_status"}
    with store.connect() as con:
        ids=[r["id"] for r in con.execute(
            "SELECT id FROM control_intents WHERE status=? ORDER BY updated_at DESC LIMIT ?",
            (status,limit)).fetchall()]
    return ok(intents=[svc.get(intent_id) for intent_id in ids])


@server.tool(structured_output=True, description="Record a human decision on a canonical control intent using the shared GOMS authority ledger.")
def decide_control_intent(intent_id: str, decision: str, idempotency_key: str,
                          actor: str = "chatgpt", human_attested: bool = False,
                          resolved_by: str | None = None) -> dict[str, Any]:
    decision=str(decision or "").upper()
    commands={"APPROVE":"approve_intent","REJECT":"reject_intent",
              "DEFER":"defer_intent","CONFIRM":"confirm_intent"}
    if decision not in commands:
        return {"ok":False,"error":"unsupported_decision"}
    actor=str(actor or "").strip()
    resolved=str(resolved_by or "").strip()
    if not actor:
        return {"ok":False,"error":"actor_required"}
    if decision in {"APPROVE","CONFIRM"} and (human_attested is not True or not resolved):
        return {"ok":False,"error":"human_attestation_required"}
    effective_actor=resolved or actor
    command={"idempotency_key":str(idempotency_key or "").strip(),
             "type":commands[decision],"target_id":intent_id,
             "payload":{"actor":actor,"human_attested":bool(human_attested),
                        "resolved_by":effective_actor}}
    return _manfred_control().execute_command(command)


@server.tool(structured_output=True, description="Link an origin or execution ChatGPT conversation to a canonical control intent.")
def link_control_intent_conversation(intent_id: str, role: str,
                                     conversation_id: str | None, url: str | None,
                                     actor: str = "chatgpt",
                                     locator_source: str = "unverified") -> dict[str, Any]:
    try:
        intent=_intent_service().link_conversation(
            intent_id,role,conversation_id,url,actor,locator_source)
        return ok(intent=intent)
    except KeyError:
        return {"ok":False,"error":"intent_not_found"}
    except ValueError as exc:
        error=str(exc)
        if error == "invalid_conversation_url":
            return {"ok":False,"error":error}
        return {"ok":False,"error":"invalid_conversation_link"}


@server.tool(structured_output=True, description="Return a compact system resilience summary across cognition, infrastructure and open priority faults.")
def system_resilience() -> dict[str, Any]:
    with store.connect() as con:
        items=[dict(r) for r in con.execute("""
          SELECT category,severity,title,summary,source,updated_at
          FROM attention_items
          WHERE status='open' AND category='p1'
          ORDER BY CASE severity WHEN 'critical' THEN 0 WHEN 'warning' THEN 1 ELSE 2 END, updated_at DESC
        """).fetchall()]
        resources=[dict(r) for r in con.execute("""
          SELECT kind,name,status,generation,observed_generation,controller,updated_at
          FROM resources ORDER BY kind,name
        """).fetchall()]
    critical=sum(1 for x in items if x.get("severity")=="critical")
    warnings=sum(1 for x in items if x.get("severity")=="warning")
    return ok(healthy=(critical==0),critical=critical,warnings=warnings,
              priority_items=items,resources=resources)


@server.tool(structured_output=True, description="Return the latest completed GOMS Guardian audit and its candidate proposals.")
def guardian_brief() -> dict[str, Any]:
    with store.connect() as con:
        run=con.execute("""
          SELECT * FROM guardian_runs
          WHERE status='SUCCESS'
          ORDER BY completed_at DESC LIMIT 1
        """).fetchone()
        if not run:
            return ok(run=None, proposals=[])
        x=dict(run)
        try:x["metadata"]=json.loads(x.get("metadata") or "{}")
        except Exception:pass
        rows=con.execute("""
          SELECT category,severity,title,rationale,evidence_refs,
                 proposed_change,confidence,status,created_at
          FROM guardian_proposals WHERE run_id=?
          ORDER BY CASE severity WHEN 'critical' THEN 0 WHEN 'warning' THEN 1 ELSE 2 END,
                   confidence DESC
        """,(run["id"],)).fetchall()
    props=[]
    for r in rows:
        y=dict(r)
        try:y["evidence_refs"]=json.loads(y.get("evidence_refs") or "[]")
        except Exception:pass
        props.append(y)
    return ok(run=x,proposals=props)

if __name__ == "__main__":
    server.run("stdio")
