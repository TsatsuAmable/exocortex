#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, math, uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from goms_store import GomsStore

VALID_STATUSES = {
    "CANDIDATE", "EXPLORE", "AUTONOMOUS", "HUMAN_ATTENTION",
    "COMMITTED", "PARKED", "REJECTED", "COMPLETED",
}
RISK_CLASSES = {"low", "medium", "high"}

def now():
    return datetime.now(timezone.utc).isoformat()

def make_id(prefix):
    return f"{prefix}_{uuid.uuid4().hex[:12]}"

def bounded(name, value):
    value=float(value)
    if not 0 <= value <= 1:
        raise ValueError(f"{name} must be in [0,1]")
    return value

@dataclass(frozen=True)
class GatePolicy:
    autonomous_threshold: float = 0.12
    human_threshold: float = 0.12
    reject_threshold: float = 0.01
    attention_scale_minutes: float = 30.0
    opportunity_weight: float = 1.0
    evidence_floor: float = 0.35

class CommitmentGate:
    """Deterministic attention-allocation layer over canonical GOMS state."""
    def __init__(self, store=None, policy=None):
        self.store = store or GomsStore()
        self.policy = policy or GatePolicy()

    def score(self, *, meaningfulness, leverage, evidence, reversibility,
              human_attention_minutes=0, opportunity_cost=0):
        m=bounded("meaningfulness", meaningfulness)
        l=bounded("leverage", leverage)
        e=bounded("evidence", evidence)
        r=bounded("reversibility", reversibility)
        h=max(0.0, float(human_attention_minutes))
        c=bounded("opportunity_cost", opportunity_cost)
        denom = 1.0 + h/self.policy.attention_scale_minutes + self.policy.opportunity_weight*c
        return (m*l*e*r)/denom

    def route(self, score, evidence, human_judgment_required=False, risk_class="low"):
        if risk_class not in RISK_CLASSES:
            raise ValueError(f"risk_class must be one of {sorted(RISK_CLASSES)}")
        evidence=bounded("evidence", evidence)
        if score < self.policy.reject_threshold:
            return "REJECTED", "Expected capacity yield is below the exploration floor."
        if evidence < self.policy.evidence_floor:
            return "EXPLORE", "Evidence is insufficient for commitment; continue machine-side exploration."
        if human_judgment_required or risk_class == "high":
            if score >= self.policy.human_threshold:
                return "HUMAN_ATTENTION", "Evidence justifies scarce human judgment."
            return "EXPLORE", "Potentially consequential, but not yet strong enough to spend human attention."
        if score >= self.policy.autonomous_threshold and risk_class in {"low","medium"}:
            return "AUTONOMOUS", "Evidence-qualified and within delegated authority."
        return "EXPLORE", "Promising but below autonomous promotion threshold."

    def add(self, title, summary="", project=None, *, meaningfulness, leverage,
            evidence, reversibility, human_attention_minutes=0,
            opportunity_cost=0, human_judgment_required=False,
            risk_class="low", source_entity_id=None, actor="commitment-gate"):
        score=self.score(
            meaningfulness=meaningfulness, leverage=leverage, evidence=evidence,
            reversibility=reversibility, human_attention_minutes=human_attention_minutes,
            opportunity_cost=opportunity_cost)
        status, rationale=self.route(score, evidence, human_judgment_required, risk_class)
        cid, ts = make_id("candidate"), now()
        with self.store.connect() as con:
            con.execute("""INSERT INTO commitment_candidates(
              id,title,summary,project,status,meaningfulness,leverage,evidence,reversibility,
              human_attention_minutes,opportunity_cost,human_judgment_required,risk_class,
              score,rationale,source_entity_id,created_at,updated_at)
              VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
              (cid,title,summary,project,status,float(meaningfulness),float(leverage),
               float(evidence),float(reversibility),float(human_attention_minutes),
               float(opportunity_cost),int(bool(human_judgment_required)),risk_class,
               score,rationale,source_entity_id,ts,ts))
        self.store.append_event({
            "op":"commitment_candidate_add","actor":actor,"candidate_id":cid,
            "title":title,"project":project,"status":status,"score":score,
            "human_judgment_required":bool(human_judgment_required),"risk_class":risk_class,
        })
        return self.get(cid)

    def get(self, cid):
        with self.store.connect() as con:
            row=con.execute("SELECT * FROM commitment_candidates WHERE id=?", (cid,)).fetchone()
        if not row:
            raise KeyError(cid)
        out=dict(row)
        out["human_judgment_required"]=bool(out["human_judgment_required"])
        return out

    def list(self, status=None):
        sql="SELECT * FROM commitment_candidates"
        vals=[]
        if status:
            if status not in VALID_STATUSES: raise ValueError(status)
            sql += " WHERE status=?"; vals.append(status)
        sql += " ORDER BY score DESC, updated_at DESC"
        with self.store.connect() as con:
            rows=[dict(r) for r in con.execute(sql, vals)]
        for r in rows: r["human_judgment_required"]=bool(r["human_judgment_required"])
        return rows

    def set_status(self, cid, status, reason="", actor="commitment-gate"):
        status=status.upper()
        if status not in VALID_STATUSES: raise ValueError(status)
        ts=now()
        before=self.get(cid)
        with self.store.connect() as con:
            con.execute("UPDATE commitment_candidates SET status=?,rationale=?,updated_at=? WHERE id=?",
                        (status,reason or before["rationale"],ts,cid))
        self.store.append_event({"op":"commitment_status","actor":actor,"candidate_id":cid,
                                 "from":before["status"],"to":status,"reason":reason})
        return self.get(cid)

    def record_outcome(self, cid, valuable, durable_artefact=None,
                       human_attention_minutes=0, notes="", actor="commitment-gate"):
        self.get(cid)
        oid, ts=make_id("outcome"), now()
        with self.store.connect() as con:
            con.execute("""INSERT INTO commitment_outcomes(
              id,candidate_id,valuable,durable_artefact,human_attention_minutes,notes,created_at)
              VALUES(?,?,?,?,?,?,?)""",
              (oid,cid,int(bool(valuable)),durable_artefact,
               max(0,float(human_attention_minutes)),notes,ts))
        self.store.append_event({"op":"commitment_outcome","actor":actor,"candidate_id":cid,
                                 "outcome_id":oid,"valuable":bool(valuable),
                                 "durable_artefact":durable_artefact})
        if valuable and durable_artefact:
            self.set_status(cid, "COMPLETED", f"Produced durable artefact: {durable_artefact}", actor)
        return {"id":oid,"candidate_id":cid}

    def metrics(self):
        with self.store.connect() as con:
            total=con.execute("SELECT COUNT(*) n FROM commitment_candidates").fetchone()["n"]
            auto=con.execute("SELECT COUNT(*) n FROM commitment_candidates WHERE status='AUTONOMOUS'").fetchone()["n"]
            human=con.execute("SELECT COUNT(*) n FROM commitment_candidates WHERE status='HUMAN_ATTENTION'").fetchone()["n"]
            rejected=con.execute("SELECT COUNT(*) n FROM commitment_candidates WHERE status='REJECTED'").fetchone()["n"]
            outcomes=con.execute("""SELECT COALESCE(SUM(valuable),0) valuable,
                COALESCE(SUM(human_attention_minutes),0) minutes,
                COUNT(*) outcomes FROM commitment_outcomes""").fetchone()
        minutes=float(outcomes["minutes"])
        valuable=int(outcomes["valuable"])
        yield_per_minute=(valuable/minutes) if minutes > 0 else None
        return {"candidates":total,"autonomous_queue":auto,"human_attention_queue":human,
                "rejected":rejected,"outcomes":outcomes["outcomes"],
                "valuable_durable_outcomes":valuable,
                "human_attention_minutes":minutes,
                "capacity_yield_per_human_minute":yield_per_minute}

    def dashboard(self):
        rows=self.list()
        lanes={"machine_explore":[],"autonomous_queue":[],"human_attention":[],
               "committed":[],"parked_or_closed":[]}
        for r in rows:
            st=r["status"]
            if st=="EXPLORE": lane="machine_explore"
            elif st=="AUTONOMOUS": lane="autonomous_queue"
            elif st=="HUMAN_ATTENTION": lane="human_attention"
            elif st=="COMMITTED": lane="committed"
            else: lane="parked_or_closed"
            lanes[lane].append(r)
        return {"policy":self.policy.__dict__,"metrics":self.metrics(),"lanes":lanes}

def parser():
    p=argparse.ArgumentParser(description="Aineko Commitment Gate")
    sub=p.add_subparsers(dest="cmd", required=True)
    a=sub.add_parser("add")
    a.add_argument("--title",required=True); a.add_argument("--summary",default=""); a.add_argument("--project")
    for name in ("meaningfulness","leverage","evidence","reversibility"):
        a.add_argument(f"--{name.replace('_','-')}",type=float,required=True)
    a.add_argument("--human-attention-minutes",type=float,default=0)
    a.add_argument("--opportunity-cost",type=float,default=0)
    a.add_argument("--human-judgment-required",action="store_true")
    a.add_argument("--risk-class",choices=sorted(RISK_CLASSES),default="low")
    l=sub.add_parser("list"); l.add_argument("--status",choices=sorted(VALID_STATUSES))
    d=sub.add_parser("dashboard")
    s=sub.add_parser("status"); s.add_argument("id"); s.add_argument("new_status",choices=sorted(VALID_STATUSES)); s.add_argument("--reason",default="")
    o=sub.add_parser("outcome"); o.add_argument("id"); o.add_argument("--valuable",action="store_true"); o.add_argument("--artefact"); o.add_argument("--human-attention-minutes",type=float,default=0); o.add_argument("--notes",default="")
    return p

def main():
    args=parser().parse_args(); g=CommitmentGate()
    if args.cmd=="add":
        out=g.add(args.title,args.summary,args.project,
            meaningfulness=args.meaningfulness,leverage=args.leverage,evidence=args.evidence,
            reversibility=args.reversibility,human_attention_minutes=args.human_attention_minutes,
            opportunity_cost=args.opportunity_cost,human_judgment_required=args.human_judgment_required,
            risk_class=args.risk_class)
    elif args.cmd=="list": out=g.list(args.status)
    elif args.cmd=="dashboard": out=g.dashboard()
    elif args.cmd=="status": out=g.set_status(args.id,args.new_status,args.reason,actor="cli")
    elif args.cmd=="outcome": out=g.record_outcome(args.id,args.valuable,args.artefact,args.human_attention_minutes,args.notes,actor="cli")
    print(json.dumps(out,indent=2,sort_keys=True))

if __name__=="__main__":
    main()
