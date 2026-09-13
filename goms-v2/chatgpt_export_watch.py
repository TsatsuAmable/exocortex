#!/usr/bin/env python3
from __future__ import annotations
import hashlib, json, os, subprocess, sys, zipfile
from pathlib import Path

HOME=Path.home()
GOMS_HOME=Path(os.environ.get("GOMS_HOME", HOME/"Library/Application Support/Aineko/GOMS"))
DOWNLOADS=HOME/"AinekoImport"
STATE=GOMS_HOME/"chatgpt_export_watch.json"
IMPORTER=GOMS_HOME/"chatgpt_export_import.py"
STAGING=GOMS_HOME/"imports"/"chatgpt"

def sha256(path: Path) -> str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda:f.read(1024*1024),b""):
            h.update(chunk)
    return h.hexdigest()

def load_state():
    try: return json.loads(STATE.read_text())
    except Exception: return {"processed":{}}

def save_state(s):
    STATE.parent.mkdir(parents=True,exist_ok=True)
    tmp=STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(s,indent=2,sort_keys=True))
    os.replace(tmp,STATE)

def candidates():
    DOWNLOADS.mkdir(parents=True,exist_ok=True)
    for p in DOWNLOADS.iterdir():
        if not p.is_file(): continue
        n=p.name.lower()
        if n.endswith(".json") and ("conversation" in n or "chatgpt" in n):
            yield p
        elif n.endswith(".zip") and ("openai" in n or "chatgpt" in n or "export" in n):
            yield p

def materialize(path: Path, digest: str):
    if path.suffix.lower()==".json":
        return path
    STAGING.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(path) as z:
        names=[n for n in z.namelist()
               if Path(n).name=="conversations.json"
               or (Path(n).name.startswith("conversations-") and n.endswith(".json"))]
        if not names: return None
        out=STAGING/f"{digest[:16]}-conversations.json"
        with out.open("wb") as f:
            for i,name in enumerate(names):
                data=z.read(name)
                if i==0 and len(names)==1:
                    f.write(data)
                    continue
                # Multiple numbered files: concatenate list payloads safely.
                # Defer merge below when needed.
                pass
        if len(names)==1: return out
        merged=[]
        for name in names:
            obj=json.loads(z.read(name))
            if isinstance(obj,list): merged.extend(obj)
            elif isinstance(obj,dict): merged.append(obj)
        out.write_text(json.dumps(merged,ensure_ascii=False))
        return out

def main():
    state=load_state()
    changed=False
    for p in candidates():
        try: d=sha256(p)
        except OSError: continue
        if d in state["processed"]: continue
        src=materialize(p,d)
        if not src: continue
        env=dict(os.environ); env["GOMS_HOME"]=str(GOMS_HOME)
        cp=subprocess.run([sys.executable,str(IMPORTER),str(src)],
                          env=env,text=True,capture_output=True)
        state["processed"][d]={
            "file":str(p),"source":str(src),"returncode":cp.returncode,
            "stdout":cp.stdout[-4000:],"stderr":cp.stderr[-4000:]
        }
        changed=True
    if changed: save_state(state)

if __name__=="__main__":
    main()
