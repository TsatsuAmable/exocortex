#!/usr/bin/env python3
"""Policy-bounded PR shepherd: discover, classify, remediate hooks, and merge."""
from __future__ import annotations
import argparse, json, subprocess
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
            action='enqueue-remediation'
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
