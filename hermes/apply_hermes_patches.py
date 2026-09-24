#!/usr/bin/env python3
"""Apply Exocortex-owned compatibility patches to the pinned Hermes checkout."""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
EXPECTED_BASE = "f6ddd89692dff1f900983a16208f39a1485a14eb"
PATCHES = [
    ("context-safe-main-fallback", HERE / "patches/context-safe-main-fallback.patch"),
    ("exocortex-control-turn-hard-guard", HERE / "patches/exocortex-control-turn-hard-guard.patch"),
]


def run_git(repo: Path, *args: str, check: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=check,
    )


def patch_state(repo: Path, patch: Path) -> str:
    reverse = run_git(repo, "apply", "--reverse", "--check", str(patch))
    if reverse.returncode == 0:
        return "applied"
    forward = run_git(repo, "apply", "--check", str(patch))
    if forward.returncode == 0:
        return "applicable"
    return "incompatible"


def verify_repo(repo: Path) -> bool:
    if run_git(repo, "rev-parse", "--is-inside-work-tree").returncode != 0:
        print(f"FAIL: not a Hermes git checkout: {repo}", file=sys.stderr)
        return False
    head = run_git(repo, "rev-parse", "HEAD", check=True).stdout.strip()
    if head != EXPECTED_BASE:
        print(
            "FAIL: Hermes checkout is not at the qualified Exocortex base commit "
            f"{EXPECTED_BASE}; got {head}. Requalify before applying these patches.",
            file=sys.stderr,
        )
        return False
    return True


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
        help="Do not mutate; require every qualified Exocortex patch to already be present",
    )
    args = ap.parse_args()
    repo = args.hermes_home.expanduser().resolve()

    missing = [str(patch) for _, patch in PATCHES if not patch.is_file()]
    if missing:
        print("FAIL: Hermes patch missing: " + ", ".join(missing), file=sys.stderr)
        return 2
    if not verify_repo(repo):
        return 2

    applied_names: list[str] = []
    for name, patch in PATCHES:
        state = patch_state(repo, patch)
        if state == "applied":
            applied_names.append(name)
            continue
        if args.verify:
            print(f"FAIL: Hermes patch is not applied: {name}", file=sys.stderr)
            return 1
        if state != "applicable":
            print(
                f"FAIL: Hermes patch does not apply cleanly: {name}. "
                "Do not force it; inspect upstream or patch-order drift.",
                file=sys.stderr,
            )
            return 1

        applied = run_git(repo, "apply", str(patch))
        if applied.returncode != 0:
            print(applied.stderr.strip(), file=sys.stderr)
            return applied.returncode or 1
        if patch_state(repo, patch) != "applied":
            print(f"FAIL: Hermes patch application could not be verified: {name}", file=sys.stderr)
            return 1
        applied_names.append(name)
        print(f"hermes-patch: {name} applied and verified")

    if args.verify:
        print("hermes-patches: all qualified patches are applied")
    elif len(applied_names) == len(PATCHES):
        print("hermes-patches: qualified patch set ready")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
