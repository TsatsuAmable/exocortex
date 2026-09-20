#!/usr/bin/env python3
"""Governed GOMS <-> Obsidian knowledge-surface synchronization.

The vault is a projection/capture surface. GOMS remains canonical.
Sync order is intentionally inbound-first:
1. detect edits to the last generated projection;
2. persist any semantic delta as a provenance-bearing GOMS evidence candidate;
3. regenerate the canonical projection;
4. persist projection state outside the vault.

The existing git-backed vault sync supplies transport and history.
"""
from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from goms_store import GomsStore

PROJECTION_REL = Path("90 System/Projections/GOMS Exocortex.md")
STATE_REL = Path("knowledge-surfaces/obsidian.json")
SNAPSHOT_REL = Path("knowledge-surfaces/obsidian-last-projection.md")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def deterministic_evidence_id(rel_path: str, digest: str) -> str:
    raw = hashlib.sha256(f"{rel_path}\0{digest}".encode()).hexdigest()[:16]
    return f"evidence_obsidian_{raw}"


def git_head(vault: Path) -> str | None:
    head = vault / ".git/HEAD"
    if not head.exists():
        return None
    try:
        import subprocess
        return subprocess.run(
            ["git", "-C", str(vault), "rev-parse", "HEAD"],
            check=True, capture_output=True, text=True,
        ).stdout.strip()
    except Exception:
        return None


def load_state(root: Path) -> dict:
    path = root / STATE_REL
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_state(root: Path, state: dict) -> None:
    path = root / STATE_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def render_exocortex_projection(store: GomsStore) -> str:
    branches = store.list_branches(project="Exocortex")
    active = [b for b in branches if b["status"] in {"ACTIVE", "BLOCKED", "DELEGATED"}]
    lines = [
        "---",
        "id: goms-projection-exocortex",
        "type: generated-projection",
        "project: Exocortex",
        "source: goms://project/Exocortex",
        "canonical: false",
        "generated_by: exocortex-knowledge-surfaces",
        "---",
        "",
        "# Exocortex · GOMS projection",
        "",
        "> Generated view of canonical GOMS state. Edit freely if useful: edits are captured",
        "> as provenance-bearing candidates before this projection is refreshed.",
        "",
        "## Authority",
        "",
        "- GOMS: canonical machine-readable state and provenance",
        "- GitHub: executable/project truth",
        "- Obsidian: human-readable synthesis and candidate capture",
        "- Notion: structured coordination cockpit",
        "- Manfred: operational control surface",
        "",
        "## Active work",
        "",
        "| GOMS ID | Title | Status | Next action |",
        "|---|---|---|---|",
    ]
    for b in active:
        title = str(b["title"]).replace("|", "\\|").replace("\n", " ")
        nxt = str(b.get("next_action") or "").replace("|", "\\|").replace("\n", " ")
        lines.append(f"| {b['id']} | {title} | {b['status']} | {nxt} |")
    if not active:
        lines.append("| _none_ | | | |")

    lines += [
        "",
        "## Unresolved human-facing questions",
        "",
    ]
    unresolved = []
    for b in active:
        for item in b.get("unresolved") or []:
            unresolved.append((b["id"], str(item)))
    if unresolved:
        for bid, item in unresolved:
            lines.append(f"- [{bid}] {item}")
    else:
        lines.append("- None recorded.")

    lines += [
        "",
        "## Provenance",
        "",
        f"- projected_at: {utc_now()}",
        "- source: canonical GOMS branch state",
        "- reconciliation: 90 System/RECONCILIATION.md",
        "",
    ]
    return "\n".join(lines)


def _entity_exists(store: GomsStore, entity_id: str) -> bool:
    try:
        store.get_entity(entity_id)
        return True
    except KeyError:
        return False


def capture_inbound_edit(root: Path, vault: Path, store: GomsStore) -> dict:
    state = load_state(root)
    target = vault / PROJECTION_REL
    snapshot = root / SNAPSHOT_REL
    if not target.exists() or not snapshot.exists():
        return {"captured": False, "reason": "no_prior_projection"}

    current = target.read_text(encoding="utf-8")
    previous = snapshot.read_text(encoding="utf-8")
    current_sha = sha256_text(current)
    previous_sha = sha256_text(previous)
    if current_sha == previous_sha:
        return {"captured": False, "reason": "unchanged"}

    diff = "\n".join(difflib.unified_diff(
        previous.splitlines(), current.splitlines(),
        fromfile="last-goms-projection", tofile="current-vault-edit", lineterm=""
    ))
    evidence_id = deterministic_evidence_id(PROJECTION_REL.as_posix(), current_sha)
    source = f"obsidian://aineko-vault/{PROJECTION_REL.as_posix()}?sha256={current_sha}"
    if not _entity_exists(store, evidence_id):
        store.add_entity(
            "evidence",
            "Obsidian edit candidate: Exocortex projection",
            summary=diff[:16000] or "Projection content changed.",
            project="Exocortex",
            status="CANDIDATE",
            confidence=1.0,
            source=source,
            tags=["obsidian", "knowledge-surface", "human-edit", "reconciliation-candidate"],
            metadata={
                "surface": "obsidian",
                "vault_path": PROJECTION_REL.as_posix(),
                "content_sha256": current_sha,
                "previous_projection_sha256": previous_sha,
                "git_head": git_head(vault),
                "canonical": False,
                "requires_reconciliation": True,
            },
            entity_id=evidence_id,
            actor="knowledge-surface-sync",
        )
    state["last_inbound_candidate"] = {
        "entity_id": evidence_id,
        "captured_at": utc_now(),
        "content_sha256": current_sha,
        "source": source,
    }
    save_state(root, state)
    return {"captured": True, "entity_id": evidence_id, "content_sha256": current_sha}



def _human_markdown_files(vault: Path):
    for path in vault.rglob("*.md"):
        try:
            rel = path.relative_to(vault)
        except ValueError:
            continue
        if rel == PROJECTION_REL:
            continue
        if any(part in {".git", ".obsidian", ".trash"} for part in rel.parts):
            continue
        if rel.parts and rel.parts[0] == "90 System" and "Projections" in rel.parts:
            continue
        if path.is_file():
            yield rel, path


def capture_human_notes(root: Path, vault: Path, store: GomsStore) -> dict:
    state = load_state(root)
    prior = dict(state.get("note_hashes") or {})
    first_scan = not prior
    cutoff = state.get("projected_at")
    try:
        cutoff_dt = datetime.fromisoformat(cutoff) if cutoff else None
    except Exception:
        cutoff_dt = None

    current = {}
    captured = []
    for rel, path in _human_markdown_files(vault):
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        digest = sha256_text(text)
        key = rel.as_posix()
        current[key] = digest
        previous = prior.get(key)
        changed = previous != digest

        if first_scan and cutoff_dt is not None:
            modified = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
            changed = modified >= cutoff_dt

        if not changed:
            continue

        evidence_id = deterministic_evidence_id(key, digest)
        source = f"obsidian://aineko-vault/{key}?sha256={digest}"
        if not _entity_exists(store, evidence_id):
            title = path.stem
            store.add_entity(
                "evidence",
                f"Obsidian note candidate: {title}",
                summary=text[:16000],
                project="Exocortex",
                status="CANDIDATE",
                confidence=1.0,
                source=source,
                tags=["obsidian", "knowledge-surface", "human-note", "reconciliation-candidate"],
                metadata={
                    "surface": "obsidian",
                    "vault_path": key,
                    "content_sha256": digest,
                    "git_head": git_head(vault),
                    "canonical": False,
                    "requires_reconciliation": True,
                },
                entity_id=evidence_id,
                actor="knowledge-surface-sync",
            )
        captured.append({"entity_id": evidence_id, "vault_path": key, "content_sha256": digest})

    state["note_hashes"] = current
    state["notes_scanned_at"] = utc_now()
    if captured:
        state["last_note_candidates"] = captured[-20:]
    save_state(root, state)
    return {
        "captured": len(captured),
        "candidates": captured,
        "scanned": len(current),
        "first_scan": first_scan,
    }

def project(root: Path, vault: Path, store: GomsStore) -> dict:
    target = vault / PROJECTION_REL
    target.parent.mkdir(parents=True, exist_ok=True)
    content = render_exocortex_projection(store)
    target.write_text(content + "\n", encoding="utf-8")

    snapshot = root / SNAPSHOT_REL
    snapshot.parent.mkdir(parents=True, exist_ok=True)
    snapshot.write_text(content + "\n", encoding="utf-8")

    state = load_state(root)
    state.update({
        "schema_version": 1,
        "surface": "obsidian",
        "projection_path": PROJECTION_REL.as_posix(),
        "projection_sha256": sha256_text(content + "\n"),
        "projected_at": utc_now(),
        "git_head_before_vault_sync": git_head(vault),
    })
    save_state(root, state)
    return {
        "path": str(target),
        "sha256": state["projection_sha256"],
        "branches": len(store.list_branches(project="Exocortex")),
    }


def sync(root: Path, vault: Path) -> dict:
    root = root.expanduser().resolve()
    vault = vault.expanduser().resolve()
    store = GomsStore(root)
    projection_edit = capture_inbound_edit(root, vault, store)
    notes = capture_human_notes(root, vault, store)
    outbound = project(root, vault, store)
    return {
        "ok": True,
        "inbound": {"projection_edit": projection_edit, "human_notes": notes},
        "outbound": outbound,
        "at": utc_now(),
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("command", choices=["obsidian-sync", "obsidian-project", "obsidian-ingest"])
    p.add_argument("--root", type=Path, default=Path(os.environ.get("GOMS_HOME", ".")))
    p.add_argument("--vault", type=Path, default=Path.home() / "Projects/aineko-vault")
    args = p.parse_args()
    store = GomsStore(args.root.expanduser().resolve())
    if args.command == "obsidian-sync":
        result = sync(args.root, args.vault)
    elif args.command == "obsidian-project":
        result = project(args.root.expanduser().resolve(), args.vault.expanduser().resolve(), store)
    else:
        result = capture_inbound_edit(args.root.expanduser().resolve(), args.vault.expanduser().resolve(), store)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
