#!/usr/bin/env python3
import json
from datetime import datetime, timezone


def _predicate(value):
    return "_".join(str(value or "").strip().lower().split())


class ExocortexContext:
    """Focused read model over canonical GOMS state for low-attention clients."""

    def __init__(self, store):
        self.store = store

    @staticmethod
    def _assertion(row):
        item = dict(row)
        metadata = item.pop("metadata", None)
        source_entity_id = item.pop("source_entity_id", None)
        source_ref = item.pop("source_ref", None)
        raw = item.get("predicate")
        item["raw_predicate"] = raw
        item["predicate"] = _predicate(raw)
        object_id = item.pop("object_id", None)
        object_type = item.pop("object_type", None)
        object_title = item.pop("object_title", None)
        object_summary = item.pop("object_summary", None)
        item["object"] = None if object_id is None else {
            "id": object_id, "type": object_type, "title": object_title,
            "summary": object_summary,
        }
        item["validity"] = {
            "valid_from": item.pop("valid_from", None),
            "valid_to": item.pop("valid_to", None),
        }
        try:
            parsed_metadata = json.loads(metadata or "{}")
        except (TypeError, json.JSONDecodeError):
            parsed_metadata = {}
        item["provenance"] = {
            "source_entity_id": source_entity_id,
            "source_ref": source_ref,
            "metadata": parsed_metadata,
        }
        return item

    def brief(self, person_title="User", project=None, limit=12):
        limit = max(1, min(int(limit), 100))
        cutoff = datetime.now(timezone.utc).isoformat()
        with self.store.connect() as con:
            person = con.execute(
                "SELECT id,type,title,summary,project,status FROM entities "
                "WHERE type='person' AND title=? LIMIT 1", (person_title,)
            ).fetchone()
            if not person:
                return {
                    "person": None, "goals": [], "constraints": [],
                    "preferences": [], "active_branches": [],
                    "unresolved_intents": [],
                }
            project_clause = (
                " AND (s.project=? OR o.project=? OR "
                "(s.id=? AND o.id IS NULL))" if project else ""
            )
            params = [person["id"], cutoff]
            if project:
                params += [project, project, person["id"]]
            params.append(limit * 4)
            rows = con.execute(f"""
                SELECT a.id,a.subject_id,a.predicate,a.literal_value,a.confidence,
                       a.epistemic_status,a.valid_from,a.valid_to,
                       a.source_entity_id,a.source_ref,a.metadata,
                       s.type subject_type,s.title subject_title,
                       o.id object_id,o.type object_type,o.title object_title,
                       o.summary object_summary
                FROM semantic_assertions a
                JOIN entities s ON s.id=a.subject_id
                LEFT JOIN entities o ON o.id=a.object_id
                WHERE (a.subject_id=? OR a.subject_id IN (
                    SELECT object_id FROM semantic_assertions
                    WHERE subject_id=? AND object_id IS NOT NULL
                ))
                  AND (a.valid_to IS NULL OR a.valid_to>?)
                  {project_clause}
                ORDER BY a.confidence DESC,a.updated_at DESC
                LIMIT ?
            """, [person["id"], *params]).fetchall()
            assertions = [self._assertion(r) for r in rows]
            goals = [x for x in assertions if x["subject_id"] == person["id"]
                     and x["predicate"] in {"has_objective", "has_goal"}][:limit]
            goal_ids = {x["object"]["id"] for x in goals if x.get("object")}
            constraints = [x for x in assertions
                           if x["subject_id"] in goal_ids
                           and x["predicate"] in {"constrained_by", "has_constraint"}][:limit]
            preferences = [x for x in assertions if x["subject_id"] == person["id"]
                           and x["predicate"] in {"prefers", "preference"}][:limit]
            branch_sql = "SELECT * FROM branches WHERE status IN ('ACTIVE','BLOCKED','DELEGATED')"
            branch_args = []
            if project:
                branch_sql += " AND project=?"; branch_args.append(project)
            branch_sql += " ORDER BY updated_at DESC LIMIT ?"; branch_args.append(limit)
            branches = [dict(r) for r in con.execute(branch_sql, branch_args).fetchall()]
            for branch in branches:
                branch["unresolved"] = json.loads(branch.get("unresolved") or "[]")
            intents = [dict(r) for r in con.execute(
                "SELECT id,kind,title,summary,status,priority,risk_tier,execution_policy,"
                "decision_required,recommended_action,updated_at FROM control_intents "
                "WHERE status NOT IN ('RESOLVED','REJECTED','CANCELLED') "
                "ORDER BY updated_at DESC LIMIT ?", (limit,)
            ).fetchall()]
        return {
            "person": dict(person), "goals": goals, "constraints": constraints,
            "preferences": preferences, "active_branches": branches,
            "unresolved_intents": intents,
        }
