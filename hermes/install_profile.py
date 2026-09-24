#!/usr/bin/env python3
"""Install or verify the curated GSV Aineko Exocortex profile."""
import argparse
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
MANIFEST = HERE / "profile_manifest.json"
SOUL = HERE / "SOUL.md"

PERSONALITY_OVERLAY = (
    "You are GSV Aineko operating primarily as the Exocortex executive. "
    "Interpret requests as intents to accomplish, not instructions to relay. "
    "Reconstruct context, inspect live capabilities, act or delegate within current authority, "
    "supervise, verify, persist durable state, and report compactly. Human attention is scarce: "
    "never hand mechanical work back when an authorised route exists. Keep interactive turns bounded. "
    "Status-only turns are observational: inspect, answer, and stop in a 1–3 round target. Batch independent "
    "reads, and state mutable facts as current only when observed in that turn; otherwise mark them last-known "
    "or omit them. Do not repair live state inline, except that a durable remediation intent may be submitted "
    "for bounded execution. "
    "Next-action-only turns select but do not execute. Proceed executes the previously selected action "
    "directly only when completion and verification fit three rounds; otherwise delegate durably. "
    "Route sustained execution through the approved-intent bounded worker instead of growing the "
    "human-facing session through long tool loops. Personality is subordinate to Exocortex function: "
    "calm, incisive, curious, strategically patient, lightly playful. "
    "Use GOMS for durable state, the shared model router for cognitive substrate, and the execution "
    "capability graph for machine authority. Escalate only genuine human decisions, hard authority "
    "gates, unavailable credentials or physical actions, or demonstrated capability gaps."
)

def load_manifest():
    return json.loads(MANIFEST.read_text(encoding="utf-8"))

def find_skill_source(explicit=None):
    candidates = []
    if explicit:
        candidates.append(Path(explicit).expanduser())
    home = Path.home()
    candidates += [
        home / ".hermes" / "skills",
        home / ".hermes" / "hermes-agent" / "skills",
    ]
    for candidate in candidates:
        if candidate.is_dir():
            return candidate.resolve()
    raise FileNotFoundError("No Hermes generic skill source found")

def desired_paths(manifest):
    return set(manifest["custom_skills"] + manifest["generic_skills"])

def current_skill_paths(profile_home):
    root = Path(profile_home) / "skills"
    if not root.exists():
        return set()
    return {str(p.parent.relative_to(root)) for p in root.rglob("SKILL.md")}

def check(profile_home, skill_source=None):
    manifest = load_manifest()
    profile = Path(profile_home).expanduser().resolve()
    skills = profile / "skills"
    errors = []
    if not (profile / "SOUL.md").exists():
        errors.append("SOUL.md missing")
    elif (profile / "SOUL.md").read_text(encoding="utf-8") != SOUL.read_text(encoding="utf-8"):
        errors.append("SOUL.md differs from Exocortex source")
    actual = current_skill_paths(profile)
    wanted = desired_paths(manifest)
    missing = sorted(wanted - actual)
    extra = sorted(actual - wanted)
    if missing:
        errors.append("missing skills: " + ", ".join(missing))
    if extra:
        errors.append("extra skills: " + ", ".join(extra))
    return errors

def update_personality_config(profile):
    config = profile / "config.yaml"
    if not config.exists():
        return
    try:
        from ruamel.yaml import YAML
        yaml = YAML()
        yaml.preserve_quotes = True
        data = yaml.load(config.read_text(encoding="utf-8")) or {}
        # Context capacity belongs to the selected model/provider contract.
        # A global profile pin can silently undercut a larger chosen model and
        # can also overstate a smaller fallback. Let Hermes resolve it per model.
        data.setdefault("model", {}).pop("context_length", None)
        agent = data.setdefault("agent", {})
        agent["max_turns"] = 60
        agent["interactive_control_contract"] = "exocortex"
        personalities = agent.setdefault("personalities", {})
        personalities["exocortex"] = PERSONALITY_OVERLAY
        data.setdefault("delegation", {})["max_iterations"] = 30
        data.setdefault("code_execution", {})["max_tool_calls"] = 20
        guard = data.setdefault("tool_loop_guardrails", {})
        guard["warnings_enabled"] = True
        guard["hard_stop_enabled"] = True
        guard["warn_after"] = {"exact_failure": 2, "same_tool_failure": 3, "idempotent_no_progress": 2}
        guard["hard_stop_after"] = {"exact_failure": 4, "same_tool_failure": 6, "idempotent_no_progress": 3}
        display = data.setdefault("display", {})
        display["personality"] = "exocortex"
        tmp = config.with_suffix(".yaml.tmp")
        with tmp.open("w", encoding="utf-8") as fh:
            yaml.dump(data, fh)
        tmp.replace(config)
    except Exception as exc:
        raise RuntimeError(f"could not update config personality: {exc}") from exc

def install(profile_home, skill_source=None, prune=True):
    manifest = load_manifest()
    profile = Path(profile_home).expanduser().resolve()
    skills = profile / "skills"
    generic_root = find_skill_source(skill_source)
    profile.mkdir(parents=True, exist_ok=True)
    skills.mkdir(parents=True, exist_ok=True)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = profile / "backups" / f"exocortex-profile-{stamp}"
    backup.mkdir(parents=True)
    for name in ("SOUL.md", "config.yaml"):
        src = profile / name
        if src.exists():
            shutil.copy2(src, backup / name)
    if skills.exists():
        shutil.copytree(skills, backup / "skills", dirs_exist_ok=True)

    for name in manifest["custom_skills"]:
        src = HERE / "skills" / name
        dst = skills / name
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(src, dst)

    for rel in manifest["generic_skills"]:
        src = generic_root / rel
        if not (src / "SKILL.md").exists():
            raise FileNotFoundError(f"generic skill source missing: {src}")
        dst = skills / rel
        if dst.exists():
            shutil.rmtree(dst)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(src, dst)

    if prune:
        wanted = desired_paths(manifest)
        for md in list(skills.rglob("SKILL.md")):
            rel = str(md.parent.relative_to(skills))
            if rel not in wanted:
                shutil.rmtree(md.parent)

    shutil.copy2(SOUL, profile / "SOUL.md")
    update_personality_config(profile)
    (profile / ".skills_prompt_snapshot.json").unlink(missing_ok=True)
    return backup

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile-home", default="~/.hermes/profiles/gsvaineko")
    ap.add_argument("--skill-source")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--no-prune", action="store_true")
    args = ap.parse_args()
    if args.check:
        errors = check(args.profile_home, args.skill_source)
        if errors:
            for error in errors:
                print(error)
            raise SystemExit(1)
        print("exocortex-profile-ok")
        return
    backup = install(args.profile_home, args.skill_source, prune=not args.no_prune)
    print(backup)

if __name__ == "__main__":
    main()
