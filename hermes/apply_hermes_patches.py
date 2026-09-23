#!/usr/bin/env python3
"""Apply Exocortex-owned compatibility patches to the pinned Hermes checkout."""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATCH = Path(__file__).resolve().parent / "patches/context-safe-main-fallback.patch"
EXPECTED_BASE = "f6ddd89692dff1f900983a16208f39a1485a14eb"


def run_git(repo: Path, *args: str, check: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=check,
    )


def patch_state(repo: Path) -> str:
    reverse = run_git(repo, "apply", "--reverse", "--check", str(PATCH))
    if reverse.returncode == 0:
        return "applied"
    forward = run_git(repo, "apply", "--check", str(PATCH))
    if forward.returncode == 0:
        return "applicable"
    return "incompatible"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--hermes-home",
        type=Path,
        default=Path.home() / ".hermes" / "hermes-agent",
        help="Hermes Agent git checkout",
    )
    ap.add_argument(
        "--verify",
        action="store_true",
        help="Do not mutate; require the Exocortex patch to already be present",
    )
    args = ap.parse_args()
    repo = args.hermes_home.expanduser().resolve()

    if not PATCH.is_file():
        print(f"FAIL: Hermes patch missing: {PATCH}", file=sys.stderr)
        return 2
    if run_git(repo, "rev-parse", "--is-inside-work-tree").returncode != 0:
        print(f"FAIL: not a Hermes git checkout: {repo}", file=sys.stderr)
        return 2

    state = patch_state(repo)
    if state == "applied":
        print("hermes-patch: context-safe-main-fallback already applied")
        return 0
    if args.verify:
        print("FAIL: Hermes context-safe fallback patch is not applied", file=sys.stderr)
        return 1

    head = run_git(repo, "rev-parse", "HEAD", check=True).stdout.strip()
    if head != EXPECTED_BASE:
        print(
            "FAIL: Hermes checkout is not at the qualified Exocortex base commit "
            f"{EXPECTED_BASE}; got {head}. Requalify before applying this patch.",
            file=sys.stderr,
        )
        return 1
    if state != "applicable":
        print(
            "FAIL: Hermes patch does not apply cleanly to the pinned checkout. "
            "Do not force it; inspect upstream drift.",
            file=sys.stderr,
        )
        return 1

    applied = run_git(repo, "apply", str(PATCH))
    if applied.returncode != 0:
        print(applied.stderr.strip(), file=sys.stderr)
        return applied.returncode or 1
    if patch_state(repo) != "applied":
        print("FAIL: Hermes patch application could not be verified", file=sys.stderr)
        return 1

    print("hermes-patch: context-safe-main-fallback applied and verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
