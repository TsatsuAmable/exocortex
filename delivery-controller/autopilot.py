#!/usr/bin/env python3
"""Policy-bounded PR shepherd: discover, classify, remediate hooks, and merge."""
from __future__ import annotations
import argparse, json, os, shutil, subprocess, tempfile
from dataclasses import dataclass
from pathlib import Path

ROOT=Path(__file__).resolve().parent
POLICY_ROOT=ROOT/'policies'
FAIL={'FAILURE','CANCELLED','TIMED_OUT','ACTION_REQUIRED','STALE'}
PENDING={'PENDING','QUEUED','IN_PROGRESS','EXPECTED','WAITING','REQUESTED'}
INFRA_HINTS=('billing','spending limit','runner','actions are disabled','minutes quota')

class AutopilotError(RuntimeError): pass

def run(args, timeout=120, check=True):
    cp=subprocess.run(args,text=True,capture_output=True,timeout=timeout)
    if check and cp.returncode: raise AutopilotError(cp.stderr.strip() or cp.stdout.strip())
    return cp

def policy(repo):
    p=POLICY_ROOT/f"{repo.replace('/','__')}.json"
    if not p.exists(): return None
    d=json.loads(p.read_text()); return d if d.get('repository')==repo else None

def open_prs(repo):
    cp=run(['gh','pr','list','-R',repo,'--state','open','--json','number,title,headRefName,headRefOid,baseRefName,url,statusCheckRollup,reviewDecision,mergeStateStatus'])
    return json.loads(cp.stdout)

def check_state(pr):
    failed=[]; pending=[]
    for c in pr.get('statusCheckRollup') or []:
        name=c.get('name') or c.get('context') or 'unnamed-check'
        state=(c.get('conclusion') or c.get('state') or c.get('status') or '').upper()
        (failed if state in FAIL else pending if state in PENDING or not state else []).append(name)
    return failed,pending

def classify(repo,pr):
    failed,pending=check_state(pr)
    if pending: return 'WAIT_CI',pending
    if failed:
        # Jobs with no executed steps are typically account/runner infrastructure failures.
        infra=True
        for c in pr.get('statusCheckRollup') or []:
            if (c.get('conclusion') or '').upper() in FAIL and c.get('detailsUrl'):
                jid=str(c['detailsUrl']).rstrip('/').split('/')[-1]
                cp=run(['gh','api',f'repos/{repo}/actions/jobs/{jid}'],check=False)
                if cp.returncode==0:
                    j=json.loads(cp.stdout)
                    if j.get('steps'): infra=False
        return ('INFRA_FAILURE' if infra else 'CODE_FAILURE'),failed
    if (pr.get('reviewDecision') or '').upper()=='CHANGES_REQUESTED': return 'REVIEW_REQUIRED',[]
    if (pr.get('mergeStateStatus') or '').upper() in {'DIRTY','BEHIND'}: return 'RECONCILE',[]
    return 'MERGE_READY',[]

def _attempt_key(repo,pr): return f"{repo}#{pr['number']}:{pr['headRefOid']}"

def _load_attempts(root):
    f=root/'repair-attempts.json'
    try: return json.loads(f.read_text())
    except Exception: return {}

def _save_attempts(root,st): (root/'repair-attempts.json').write_text(json.dumps(st))

def escalate(repo,pr,reason):
    run(['gh','label','create','autopilot-escalated','-R',repo,'--force'],check=False)
    run(['gh','pr','edit',str(pr['number']),'-R',repo,'--add-label','autopilot-escalated'],check=False)
    run(['gh','pr','comment',str(pr['number']),'-R',repo,'--body',f"autopilot escalation ({reason}): bounded retries exhausted or policy block; human review required"],check=False)

JUNK=('__pycache__/','.DS_Store','*.pyc')

def repair(repo,pr,p):
    if not p.get("auto_repair",False): return "repair policy disabled"
    source=Path(p.get("source_path","")).expanduser()
    if not source.is_dir(): return "repair source unavailable"
    codex=shutil.which("codex")
    if not codex: return "repair worker unavailable"
    root=Path(os.environ.get("AINEKO_REPAIR_ROOT",Path.home()/"Library/Application Support/Aineko/repair-worktrees"))
    root.mkdir(parents=True,exist_ok=True)
    wt=root/f"{repo.replace('/','__')}-pr-{pr['number']}"
    if wt.exists(): subprocess.run(["git","-C",str(source),"worktree","remove","--force",str(wt)],capture_output=True)
    run(["git","-C",str(source),"fetch","origin",pr["headRefName"]],timeout=180)
    run(["git","-C",str(source),"worktree","add","--detach",str(wt),pr["headRefOid"]],timeout=180)
    prompt=f"""Repair PR #{pr['number']} in {repo}. Diagnose the current CI/review failure, make the smallest safe code fix in this worktree, and run relevant local tests. Do not change blocked governance/security paths, do not push, merge, or alter GitHub settings. Leave verified edits in the worktree. If the failure is infrastructure-only or requires architecture/intent/security judgment, make no edits and explain why."""
    attempts=_load_attempts(root); key=_attempt_key(repo,pr)
    if attempts.get(key,0)>=int(p.get('max_repair_attempts',3)):
        escalate(repo,pr,'exhausted_retries')
        return "repair escalated: bounded retries exhausted"
    attempts[key]=attempts.get(key,0)+1; _save_attempts(root,attempts)
    try:
        cp=subprocess.run([codex,"exec","-s","workspace-write","-a","never","-C",str(wt),prompt],text=True,capture_output=True,timeout=int(p.get("repair_timeout_seconds",1200)))
    except subprocess.TimeoutExpired:
        return "repair worker timeout"
    if cp.returncode: return "repair worker failed"
    changed=[l for l in subprocess.run(["git","diff","--name-only"],cwd=wt,text=True,capture_output=True).stdout.splitlines() if l.strip() and not any(l.endswith(j.split('/')[-1]) if '/' not in j else l.startswith(j.split('/')[0]+'/') and l.endswith(j) for j in JUNK)]
    blocked=[x.rstrip('/') for x in p.get('blocked_paths',[])]
    if any(path==b or path.startswith(b+'/') for path in changed for b in blocked): return "repair blocked by path policy"
    if not changed: return "repair produced no code change"
    for command in p.get('local_verification',[]):
        vc=subprocess.run(command,shell=True,cwd=wt,text=True,capture_output=True,timeout=int(p.get('repair_timeout_seconds',1200)))
        if vc.returncode: return "repair verification failed"
    current=json.loads(run(['gh','pr','view',str(pr['number']),'-R',repo,'--json','headRefOid']).stdout)
    if current['headRefOid']!=pr['headRefOid']: return "repair abandoned: PR head moved"
    subprocess.run(['git','add','--',*changed],cwd=wt,check=True)
    subprocess.run(['git','commit','-m',f"fix: autonomously remediate PR #{pr['number']}"],cwd=wt,check=True)
    subprocess.run(['git','push','origin',f"HEAD:refs/heads/{pr['headRefName']}"],cwd=wt,check=True,timeout=180)
    attempts=_load_attempts(root); attempts.pop(_attempt_key(repo,pr),None); _save_attempts(root,attempts)
    return "repair pushed; awaiting GitHub event"

def merge(repo,pr,p):
    if not p.get('auto_merge',False): return 'merge policy disabled'
    if (pr.get('baseRefName') or '') not in p.get('allowed_base_branches',['main']): return 'base branch not allowed'
    cp=run(['gh','pr','merge',str(pr['number']),'-R',repo,'--merge'],timeout=180,check=False)
    if cp.returncode: raise AutopilotError(cp.stderr.strip() or cp.stdout.strip())
    return 'merged'

def tick(repo,dry_run=False):
    p=policy(repo)
    if not p: return [{'repo':repo,'state':'UNMANAGED','detail':'no autopilot policy'}]
    out=[]
    for pr in open_prs(repo):
        state,detail=classify(repo,pr)
        action='observe'
        if state=='MERGE_READY' and p.get('auto_merge') and not dry_run:
            action=merge(repo,pr,p)
        elif state in {'CODE_FAILURE','RECONCILE','REVIEW_REQUIRED'}:
            action=repair(repo,pr,p) if not dry_run else 'enqueue-remediation'
        elif state=='INFRA_FAILURE': action='suppress-human-interrupt; verify locally before policy merge'
        out.append({'repo':repo,'pr':pr['number'],'title':pr['title'],'state':state,'detail':detail,'action':action,'url':pr['url']})
    return out

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--repo',action='append'); ap.add_argument('--dry-run',action='store_true'); a=ap.parse_args()
    repos=a.repo or [json.loads(p.read_text())['repository'] for p in POLICY_ROOT.glob('*.json') if json.loads(p.read_text()).get('autopilot_enabled')]
    result=[]
    for repo in repos: result += tick(repo,a.dry_run)
    print(json.dumps(result,indent=2))
if __name__=='__main__': main()
