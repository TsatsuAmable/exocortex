#!/usr/bin/env python3
"""Lightweight deployed Exocortex survivability heartbeat.

This is not a substitute for clean-room reconstruction. It proves that the
deployed runtime still contains its declared components and that canonical
state roots are reachable, then emits a machine-readable report for Aineko.
"""
import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path


def now():
    return datetime.now(timezone.utc).isoformat()


def sha256(path):
    h=hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda:f.read(1024*1024),b""):
            h.update(chunk)
    return h.hexdigest()


def audit(release, goms_home=None):
    release=Path(release).expanduser().resolve()
    failures=[]
    warnings=[]
    manifest_path=release/"manifest.json"
    if not manifest_path.is_file():
        return {"ok":False,"checked_at":now(),"release":str(release),
                "failures":["release_manifest_missing"],"warnings":[]}
    manifest=json.loads(manifest_path.read_text())
    components={}
    for name,component in manifest.get("components",{}).items():
        install=release/component["install"]
        entry=install/component["entrypoint"]
        present=entry.is_file()
        components[name]={"entrypoint":str(entry),"present":present}
        if present:
            components[name]["sha256"]=sha256(entry)
        else:
            failures.append("component_entrypoint_missing:"+name)
    goms_root=Path(goms_home or os.environ.get("GOMS_HOME","")).expanduser()
    state={}
    if str(goms_root) not in ("","."):
        db=goms_root/"goms.sqlite3"
        ledger=goms_root/"events.jsonl"
        state={"root":str(goms_root),"db_present":db.is_file(),
               "ledger_present":ledger.is_file()}
        if not db.is_file():
            failures.append("canonical_goms_db_missing")
        if not ledger.is_file():
            warnings.append("canonical_goms_ledger_missing")
    else:
        warnings.append("goms_home_not_declared")
    return {"ok":not failures,"checked_at":now(),"release":str(release),
            "components":components,"state":state,
            "failures":failures,"warnings":warnings}


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--release",required=True)
    p.add_argument("--goms-home")
    p.add_argument("--report")
    a=p.parse_args()
    result=audit(a.release,a.goms_home)
    if a.report:
        out=Path(a.report).expanduser()
        out.parent.mkdir(parents=True,exist_ok=True)
        out.write_text(json.dumps(result,indent=2)+"\n")
    print(json.dumps(result,indent=2))
    return 0 if result["ok"] else 1

if __name__=="__main__":
    raise SystemExit(main())
