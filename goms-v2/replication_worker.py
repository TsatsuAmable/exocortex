#!/usr/bin/env python3
from contextlib import closing
import argparse
import hashlib
import json
import re
import sqlite3
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

MAX_ATTEMPTS = 3
AUTH_PATTERNS = (
    "tailscale ssh requires an additional check",
    "login.tailscale.com/a/",
)
AUTH_URL = re.compile(r"https://login\.tailscale\.com/a/\S+", re.I)


def utcnow():
    return datetime.now(timezone.utc)


def classify_failure(text):
    lowered = str(text or "").lower()
    if any(pattern in lowered for pattern in AUTH_PATTERNS):
        return "human_authorization_required"
    if "manifest hash mismatch" in lowered:
        return "integrity_failure"
    return "transient"


def redact_auth_output(text):
    cleaned = AUTH_URL.sub("[authentication URL redacted]", str(text or ""))
    return cleaned[-2000:]


def retry_allowed(job, *, now=None):
    current = now or utcnow()
    status = job.get("status") or "pending"
    if status in {"human_authorization_required", "integrity_failure", "retry_exhausted", "replicated"}:
        return False
    next_retry = job.get("next_retry_at")
    if next_retry:
        try:
            when = datetime.fromisoformat(str(next_retry).replace("Z", "+00:00"))
            if when.tzinfo is None:
                when = when.replace(tzinfo=timezone.utc)
            if current < when:
                return False
        except ValueError:
            pass
    return True


def mark_job_failure(path, failure_class, detail, *, now=None):
    current = now or utcnow()
    path = Path(path)
    job = json.loads(path.read_text())
    job["failure_class"] = failure_class
    job["last_failure_at"] = current.isoformat()
    job["last_error"] = redact_auth_output(detail)
    if failure_class == "human_authorization_required":
        job["status"] = "human_authorization_required"
        job.pop("next_retry_at", None)
    elif failure_class == "integrity_failure":
        job["status"] = "integrity_failure"
        job.pop("next_retry_at", None)
    else:
        attempts = int(job.get("attempt_count") or 0) + 1
        job["attempt_count"] = attempts
        if attempts >= MAX_ATTEMPTS:
            job["status"] = "retry_exhausted"
            job.pop("next_retry_at", None)
        else:
            job["status"] = "retryable"
            delay = min(3600, 60 * (2 ** (attempts - 1)))
            job["next_retry_at"] = (current + timedelta(seconds=delay)).isoformat()
    path.write_text(json.dumps(job, indent=2, sort_keys=True))
    return job


def shasum(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _run(cmd, timeout):
    return subprocess.run(cmd, text=True, capture_output=True, timeout=timeout)


def _fail(job_path, cp, *, now=None):
    detail = "\n".join(x for x in (getattr(cp, "stdout", ""), getattr(cp, "stderr", "")) if x)
    failure = classify_failure(detail)
    return mark_job_failure(job_path, failure, detail, now=now)


def process_job(job_path, done_dir, *, runner=_run, now=None):
    job_path = Path(job_path)
    job = json.loads(job_path.read_text())
    if job.get("target") != "fedora" or not retry_allowed(job, now=now):
        return {"status": "skipped", "job": job}
    evidence = Path(job["evidence_dir"])
    cid = job["conversation_id"]
    snap = job["snapshot_sha256"][:16]
    remote = f"~/aineko-replica/chatgpt/{cid}/{snap}"

    cp = runner(["/usr/local/bin/tailscale", "ssh", "yoda@fedora", f"mkdir -p {remote}"], 30)
    if cp.returncode:
        return {"status": "failed", "job": _fail(job_path, cp, now=now)}

    cp = runner([
        "/usr/bin/rsync", "-a", "--partial", "--checksum",
        "-e", "/usr/local/bin/tailscale ssh", str(evidence) + "/",
        f"yoda@fedora:{remote}/",
    ], 180)
    if cp.returncode:
        return {"status": "failed", "job": _fail(job_path, cp, now=now)}

    cp = runner([
        "/usr/local/bin/tailscale", "ssh", "yoda@fedora",
        f"sha256sum {remote}/manifest.json",
    ], 30)
    if cp.returncode:
        return {"status": "failed", "job": _fail(job_path, cp, now=now)}

    local_hash = shasum(evidence / "manifest.json")
    remote_hash = (cp.stdout or "").split()[0] if (cp.stdout or "").split() else ""
    if local_hash != remote_hash:
        job = mark_job_failure(job_path, "integrity_failure", "manifest hash mismatch", now=now)
        return {"status": "failed", "job": job}

    job["status"] = "replicated"
    job["manifest_sha256"] = local_hash
    job["remote_path"] = remote
    job["replicated_at"] = (now or utcnow()).isoformat()
    done_dir = Path(done_dir)
    done_dir.mkdir(parents=True, exist_ok=True)
    (done_dir / job_path.name).write_text(json.dumps(job, indent=2, sort_keys=True))
    job_path.unlink()
    return {"status": "replicated", "job": job}


def queue_summary(outbox):
    counts = {}
    for path in Path(outbox).glob("*.json"):
        try:
            status = json.loads(path.read_text()).get("status") or "pending"
        except Exception:
            status = "invalid"
        counts[status] = counts.get(status, 0) + 1
    return counts


def publish_queue_resource(db_path, counts, *, now=None):
    current = now or utcnow()
    pending = sum(counts.values())
    if counts.get("human_authorization_required"):
        failure = "human_authorization_required"
    elif counts.get("integrity_failure"):
        failure = "integrity_failure"
    elif counts.get("retry_exhausted"):
        failure = "retry_exhausted"
    elif pending:
        failure = "transient_backlog"
    else:
        failure = None
    observed = "healthy" if not pending else "degraded"
    name = "ChatGPT evidence replica"
    kind = "ReplicationQueue"
    rid = "res_" + hashlib.sha256((kind + "|" + name).encode()).hexdigest()[:20]
    spec = {"desired_state": "healthy", "repair": "drain_replication", "target": "fedora"}
    status = {"observed_state": observed, "pending_count": pending,
              "failure_class": failure, "counts": counts,
              "last_observed": current.isoformat()}

    with closing(sqlite3.connect(db_path)) as c, c:
        row = c.execute("select generation,spec from resources where id=?", (rid,)).fetchone()
        spec_json = json.dumps(spec, sort_keys=True)
        generation = 1 if not row else int(row[0]) + (1 if row[1] != spec_json else 0)
        ts = current.isoformat()
        c.execute("""insert into resources(id,kind,name,spec,status,generation,observed_generation,
          controller,authority,metadata,created_at,updated_at)
          values(?,?,?,?,?,?,?,'ReplicationWorker','system','{}',?,?)
          on conflict(id) do update set spec=excluded.spec,status=excluded.status,
          generation=excluded.generation,observed_generation=excluded.observed_generation,
          controller=excluded.controller,updated_at=excluded.updated_at""",
          (rid, kind, name, spec_json, json.dumps(status, sort_keys=True), generation, generation, ts, ts))
        c.execute("""insert into resource_conditions(resource_id,condition_type,status,reason,message,severity,observed_at)
          values(?,?,?,?,?,?,?) on conflict(resource_id,condition_type) do update set
          status=excluded.status,reason=excluded.reason,message=excluded.message,
          severity=excluded.severity,observed_at=excluded.observed_at""",
          (rid, "Healthy", "True" if not pending else "False",
           "QueueDrained" if not pending else failure or "Backlog",
           f"replication queue pending={pending}; counts={json.dumps(counts, sort_keys=True)}",
           "info" if not pending else ("critical" if failure in {"human_authorization_required", "integrity_failure"} else "warning"),
           ts))
        c.commit()
    return rid


def resume_human_authorized(outbox, *, now=None):
    current = now or utcnow()
    changed = 0
    for path in Path(outbox).glob("*.json"):
        try:
            job = json.loads(path.read_text())
        except Exception:
            continue
        if job.get("status") != "human_authorization_required":
            continue
        job["status"] = "pending"
        job["authorization_resumed_at"] = current.isoformat()
        job.pop("failure_class", None)
        job.pop("next_retry_at", None)
        path.write_text(json.dumps(job, indent=2, sort_keys=True))
        changed += 1
    return changed


def main():
    home = Path.home()
    parser = argparse.ArgumentParser()
    parser.add_argument("--outbox", type=Path,
                        default=home / "Library/Application Support/Aineko/GOMS/outbox/replication")
    parser.add_argument("--done", type=Path,
                        default=home / "Library/Application Support/Aineko/GOMS/replication/done")
    parser.add_argument("--db", type=Path,
                        default=home / "Library/Application Support/Aineko/GOMS/goms.sqlite3")
    parser.add_argument("--resume-human-authorized", action="store_true")
    args = parser.parse_args()

    if args.resume_human_authorized:
        changed = resume_human_authorized(args.outbox)
        print(json.dumps({"authorization_resumed": changed}))
        return

    outcomes = {"replicated": 0, "failed": 0, "skipped": 0}
    for job_path in sorted(args.outbox.glob("*.json")):
        try:
            result = process_job(job_path, args.done)
            outcomes[result["status"]] = outcomes.get(result["status"], 0) + 1
        except Exception as exc:
            mark_job_failure(job_path, "transient", str(exc))
            outcomes["failed"] += 1
    counts = queue_summary(args.outbox)
    rid = publish_queue_resource(args.db, counts)
    print(json.dumps({"outcomes": outcomes, "queue": counts, "resource_id": rid}, sort_keys=True))


if __name__ == "__main__":
    main()
