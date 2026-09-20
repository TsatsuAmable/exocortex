#!/usr/bin/env python3
import argparse
import json
import math
import statistics
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
FLEET = ROOT / "fleet.json"
TASKS = ROOT / "tasks.jsonl"
RESULTS = ROOT / "results.jsonl"
EMBED_CACHE = ROOT / "embeddings.json"
OLLAMA_EMBED = "http://127.0.0.1:11434/api/embed"
EMBED_MODEL = "nomic-embed-text:latest"
RESOURCE_RANK = {"light": 0, "remote": 1, "medium": 2, "heavy": 3}


def load_jsonl(path):
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def lifecycle_state(candidate, now=None):
    if candidate.get("enabled", True) is False:
        return "disabled", 99
    qualification = str(candidate.get("qualification") or "qualified").lower()
    if qualification == "unqualified":
        return "unqualified", 90
    retire_at = str(candidate.get("retire_at") or "").strip()
    if not retire_at:
        return "active", 0
    try:
        retire_dt = datetime.fromisoformat(retire_at.replace("Z", "+00:00"))
        now = now or datetime.now(timezone.utc)
        days = (retire_dt - now).total_seconds() / 86400.0
    except ValueError:
        return "unknown_lifecycle", 5
    if days <= 0:
        return "retired", 99
    if days <= 14:
        return "draining", 10
    if days <= 30:
        return "retiring", 3
    return "active", 0


def eligible(task, candidate):
    state, penalty = lifecycle_state(candidate)
    if penalty >= 90:
        return False
    if task.get("privacy") == "private" and candidate.get("privacy") != "private":
        return False
    if task.get("mode") == "agent" and not candidate.get("tool_use"):
        return False
    required_context = int(task.get("context", 0) or 0)
    if required_context and candidate.get("context", 0) < required_context:
        return False
    return True


def cosine(a, b):
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    return dot / (na * nb) if na and nb else 0.0

def embed(text):
    cache = json.loads(EMBED_CACHE.read_text()) if EMBED_CACHE.exists() else {}
    if text in cache:
        return cache[text]
    payload = json.dumps({"model": EMBED_MODEL, "input": text}).encode()
    req = urllib.request.Request(OLLAMA_EMBED, payload, {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as response:
        data = json.load(response)
    vector = data["embeddings"][0]
    cache[text] = vector
    EMBED_CACHE.write_text(json.dumps(cache))
    return vector


def estimate(candidate, task, task_by_id, results, k=5):
    rows = [r for r in results if r.get("candidate_id") == candidate["id"] and not r.get("error")]
    if not rows:
        return {"p_success": 0.5, "evidence": 0, "family_evidence": 0, "latency_s": None, "basis": "prior"}

    family_rows = []
    for row in rows:
        hist_task = task_by_id.get(row.get("task_id"))
        if hist_task and hist_task.get("family") == task.get("family"):
            family_rows.append(row)
    pool = family_rows if family_rows else rows
    basis = "family_knn" if family_rows else "cross_family_knn"

    qv = embed(task["prompt"])
    scored = []
    for row in pool:
        hist_task = task_by_id.get(row.get("task_id"))
        if not hist_task:
            continue
        sim = max(cosine(qv, embed(hist_task["prompt"])), 0.0)
        scored.append((sim, row))
    scored.sort(key=lambda pair: pair[0], reverse=True)
    neighbours = scored[:k]
    if not neighbours:
        return {"p_success": 0.5, "evidence": 0, "family_evidence": 0, "latency_s": None, "basis": "prior"}

    prior_weight, prior_p = 1.0, 0.5
    weighted_success = prior_weight * prior_p
    total_weight = prior_weight
    latencies = []
    for similarity, row in neighbours:
        weight = max(similarity, 0.05)
        weighted_success += weight * (1.0 if row.get("passed") else 0.0)
        total_weight += weight
        if row.get("elapsed_s") is not None:
            latencies.append(float(row["elapsed_s"]))
    return {
        "p_success": weighted_success / total_weight,
        "evidence": len(neighbours),
        "family_evidence": len(family_rows),
        "latency_s": statistics.median(latencies) if latencies else None,
        "basis": basis,
    }

def rank_candidates(task, threshold=0.65):
    fleet = json.loads(FLEET.read_text())["candidates"]
    tasks = load_jsonl(TASKS)
    results = load_jsonl(RESULTS)
    task_by_id = {t["id"]: t for t in tasks}
    ranked = []
    for candidate in fleet:
        if not eligible(task, candidate):
            continue
        est = estimate(candidate, task, task_by_id, results)
        latency = est["latency_s"] if est["latency_s"] is not None else 9999.0
        task_family = str(task.get("family") or "general")
        if task_family == "general":
            enough_evidence = est["evidence"] >= 3
        else:
            enough_evidence = est["family_evidence"] >= int(task.get("min_family_evidence", 2) or 2)
        known_good = enough_evidence and est["p_success"] >= threshold
        state, lifecycle_penalty = lifecycle_state(candidate)
        qualification = str(candidate.get("qualification") or "qualified").lower()
        qualification_penalty = {"qualified": 0, "provisional": 1}.get(qualification, 5)
        ranked.append({
            "candidate": candidate["id"],
            "provider": candidate["provider"],
            "adapter": candidate.get("adapter"),
            "model": candidate["model"],
            "network": bool(candidate.get("network", True)),
            "privacy": candidate.get("privacy", "non_sensitive"),
            "qualification": qualification,
            "lifecycle_state": state,
            "known_good": known_good,
            **est,
            "marginal_cost_usd": candidate.get("marginal_cost_usd", 0),
            "billing_class": candidate.get("billing_class", "unknown"),
            "cold_start_rank": int(candidate.get("cold_start_rank", 50)),
            "resource_class": candidate.get("resource_class", "heavy"),
            "_sort": (
                lifecycle_penalty,
                qualification_penalty,
                0 if known_good else 1,
                int(candidate.get("cold_start_rank", 50)),
                candidate.get("marginal_cost_usd", 0),
                latency,
                RESOURCE_RANK.get(candidate.get("resource_class"), 9),
                -est["p_success"],
            ),
        })
    ranked.sort(key=lambda x: x["_sort"])
    for row in ranked:
        row.pop("_sort", None)
    return ranked


def main():
    ap = argparse.ArgumentParser(description="Evidence-driven Aineko model router")
    ap.add_argument("--prompt", required=True)
    ap.add_argument("--family", default="general")
    ap.add_argument("--privacy", choices=["non_sensitive", "private"], default="non_sensitive")
    ap.add_argument("--mode", choices=["direct", "agent"], default="direct")
    ap.add_argument("--context", type=int, default=0)
    ap.add_argument("--threshold", type=float, default=0.65)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    task = vars(args)
    ranked = rank_candidates(task, args.threshold)
    if args.json:
        print(json.dumps(ranked, indent=2))
        return
    if not ranked:
        raise SystemExit("No eligible candidates")
    best = ranked[0]
    print(f"route={best['candidate']} p_success={best['p_success']:.3f} evidence={best['evidence']} basis={best['basis']}")
    for row in ranked:
        latency = "?" if row["latency_s"] is None else f"{row['latency_s']:.3f}s"
        print(f"  {row['candidate']}: p={row['p_success']:.3f} n={row['evidence']} latency={latency} known_good={row['known_good']}")


if __name__ == "__main__":
    main()
