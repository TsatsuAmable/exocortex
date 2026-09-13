#!/usr/bin/env python3
import fcntl, subprocess, sys
from pathlib import Path

ROOT=Path.home()/"Library/Application Support/Aineko/GOMS"
LOCK=ROOT/"semantic_maintenance.lock"
PY=Path.home()/"Library/Application Support/Aineko/venv/bin/python"

with LOCK.open("w") as f:
    try:
        fcntl.flock(f.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:
        print("semantic maintenance already running")
        raise SystemExit(0)
    steps=[
      ["/usr/bin/python3",str(ROOT/"ontology_evolution.py")],
      ["/usr/bin/python3",str(ROOT/"embed_semantics.py")],
      [str(PY),"-c",
       "from neo4j_projection import rebuild,status; print(rebuild(batch_size=1000)); print(status())"]
    ]
    for cmd in steps:
        cp=subprocess.run(cmd,cwd=ROOT,text=True,capture_output=True)
        if cp.stdout: print(cp.stdout,end="")
        if cp.returncode:
            if cp.stderr: print(cp.stderr,file=sys.stderr,end="")
            raise SystemExit(cp.returncode)
