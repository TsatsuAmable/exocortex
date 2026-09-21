#!/usr/bin/env python3
"""Policy-bounded PR shepherd: discover, classify, remediate hooks, and merge."""
from __future__ import annotations
import argparse, hashlib, json, os, subprocess, sys
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

def _intent_service():
    source=Path(os.environ.get('EXOCORTEX_CURRENT', str(Path.home()/'.local/share/exocortex/current')))/'goms-v2'
    if not (source/'control_intents.py').exists():
        source=ROOT.parent/'goms-v2'
    if not (source/'control_intents.py').exists():
        raise AutopilotError('control-intent runtime unavailable')
    if str(source) not in sys.path:
        sys.path.insert(0,str(source))
    from control_intents import ControlIntentService
    goms_root=Path(os.environ.get('GOMS_HOME', str(Path.home()/'Library/Application Support/Aineko/GOMS')))
    return ControlIntentService(goms_root)

def enqueue_remediation(repo,pr,state,detail,p):
    authority_ref=str(p.get('standing_authority_ref') or '').strip()
    if not p.get('repair_auto_dispatch') or not authority_ref:
        return 'remediation-disabled'
    head=str(pr.get('headRefOid') or '')
    identity=f"{repo}:{pr['number']}:{head}:{state}"
    key='pr-remediation:'+hashlib.sha256(identity.encode()).hexdigest()[:32]
    target=f"{repo}#PR{pr['number']}"
    summary=(
        f"Exocortex delivery autopilot detected {state} on {target} at exact head {head}. "
        f"Observed blockers: {', '.join(detail) if detail else 'none listed'}. "
        "Repair the existing PR end-to-end under repository policy. Preserve governance and tests; "
        "do not weaken checks or manufacture evidence. Push only to the existing PR branch, verify "
        "the real outcome, and drive it back to the merge gate. If a genuinely human, physical, "
        "security, legal, or authority-only boundary remains, return UNKNOWN with precise evidence."
    )
    service=_intent_service()
    authority=service.get(authority_ref)
    submission=((authority.get('provenance') or {}).get('submission') or {})
    resolved_by=str(submission.get('resolved_by') or '')
    if not submission.get('human_attested') or not resolved_by.startswith('human:'):
        raise AutopilotError(f'standing authority {authority_ref} lacks human attestation')
    if str(authority.get('status') or '') not in {'APPROVED','EXECUTING','VERIFYING','RESOLVED'}:
        raise AutopilotError(f'standing authority {authority_ref} is not active/resolved')
    result=service.submit_intent(
        title=f"Repair {target}: {state}", summary=summary, kind='aineko_task',
        source='system', source_ref=str(pr.get('url') or target), project=repo,
        priority='P1', risk_tier='normal', execution_policy='AUTO_AFTER_APPROVAL',
        recommended_action={'type':'aineko_task','target_id':target,'instructions':summary},
        verification_policy={'exact_head':head,'same_pr':True,'require_real_outcome':True},
        provenance={'standing_authority_ref':authority_ref,'detected_state':state},
        decision_required=False, idempotency_key=key, actor='system:delivery-autopilot',
        human_attested=True,
        resolved_by=resolved_by,
    )
    return f"intent:{result['intent_id']}"

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
            action='enqueue-remediation' if dry_run else enqueue_remediation(repo,pr,state,detail,p)
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
