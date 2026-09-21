#!/usr/bin/env python3
"""Install/update zero-LLM Hermes cron bindings for scheduled Aineko intents."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from pathlib import Path


def load_specs(exocortex: Path) -> list[dict]:
    root = exocortex / "config" / "scheduled-intents"
    specs = []
    for path in sorted(root.glob("*.json")):
        data = json.loads(path.read_text())
        if all(data.get(k) for k in ("cron_schedule", "cron_name", "cron_wrapper")):
            data["_path"] = str(path)
            specs.append(data)
    return specs


def profile_jobs_path(hermes_home: Path, profile: str) -> Path:
    return hermes_home / "profiles" / profile / "cron" / "jobs.json"


def existing_jobs(path: Path) -> list[dict]:
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text())
    except json.JSONDecodeError:
        return []
    return payload.get("jobs", []) if isinstance(payload, dict) else []


def install_wrapper(source: Path, hermes_home: Path, profile: str) -> None:
    for dest_root in (hermes_home / "scripts", hermes_home / "profiles" / profile / "scripts"):
        dest_root.mkdir(parents=True, exist_ok=True)
        dest = dest_root / source.name
        shutil.copy2(source, dest)
        dest.chmod(dest.stat().st_mode | 0o111)


def hermes_cmd(agent_home: Path, profile: str) -> list[str]:
    python = agent_home / "venv" / "bin" / "python"
    if not python.exists():
        raise FileNotFoundError(f"Hermes Python missing: {python}")
    return [str(python), "-m", "hermes_cli.main", "--profile", profile]


def run(args: list[str], *, dry_run: bool) -> None:
    if dry_run:
        print("DRY-RUN", " ".join(args))
        return
    subprocess.run(args, check=True)


def install(exocortex: Path, hermes_home: Path, agent_home: Path,
            profile: str, dry_run: bool = False) -> list[dict]:
    specs = load_specs(exocortex)
    if not specs:
        raise RuntimeError("no scheduled-intent cron specs found")
    jobs_path = profile_jobs_path(hermes_home, profile)
    current = existing_jobs(jobs_path)
    base = hermes_cmd(agent_home, profile)
    results = []

    for spec in specs:
        wrapper = exocortex / "scripts" / spec["cron_wrapper"]
        if not wrapper.is_file():
            raise FileNotFoundError(f"cron wrapper missing: {wrapper}")
        if not dry_run:
            install_wrapper(wrapper, hermes_home, profile)

        match = next((
            j for j in current
            if j.get("name") == spec["cron_name"] or j.get("script") == spec["cron_wrapper"]
        ), None)
        if match:
            cmd = base + [
                "cron", "edit", str(match["id"]),
                "--schedule", str(spec["cron_schedule"]),
                "--name", str(spec["cron_name"]),
                "--script", str(spec["cron_wrapper"]),
                "--no-agent", "--prompt", "",
            ]
            action = "updated"
            job_id = str(match["id"])
        else:
            cmd = base + [
                "cron", "create", str(spec["cron_schedule"]),
                "--name", str(spec["cron_name"]),
                "--script", str(spec["cron_wrapper"]),
                "--no-agent", "--deliver", "local",
            ]
            action = "created"
            job_id = None
        run(cmd, dry_run=dry_run)
        results.append({"action": action, "job_id": job_id, "name": spec["cron_name"]})
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exocortex", default="~/.local/share/exocortex/current")
    parser.add_argument("--hermes-home", default="~/.hermes")
    parser.add_argument("--agent-home", default="~/.hermes/hermes-agent")
    parser.add_argument("--profile", default="gsvaineko")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    results = install(
        Path(args.exocortex).expanduser().resolve(),
        Path(args.hermes_home).expanduser().resolve(),
        Path(args.agent_home).expanduser().resolve(),
        args.profile,
        dry_run=args.dry_run,
    )
    print(json.dumps(results, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
