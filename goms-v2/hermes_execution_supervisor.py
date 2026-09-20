#!/usr/bin/env python3
from dataclasses import dataclass
from hermes_route_selector import select_route

@dataclass
class Attempt:
    route: str
    ok: bool
    result: object = None
    error: str = ""

class HermesExecutionSupervisor:
    """Deterministic retry/failover loop. Executors are injected route adapters."""
    def __init__(self, capability_provider, executors, audit=None):
        self.capability_provider=capability_provider
        self.executors=executors
        self.audit=audit or (lambda *a, **k: None)

    def execute(self, task, *, task_kind="machine", verifier=None, max_attempts=4):
        attempted=[]; attempts=[]
        for _ in range(max_attempts):
            capabilities=self.capability_provider()
            choice=select_route(capabilities, task_kind, attempted)
            route=choice["route"]
            if not route:
                return {"ok":False,"decision":"ESCALATE","reason":choice["reason"],
                        "attempted_routes":attempted,"attempts":[a.__dict__ for a in attempts]}
            executor=self.executors.get(route)
            if executor is None:
                attempted.append(route)
                attempts.append(Attempt(route,False,error="no executor adapter"))
                self.audit("route_attempt",route,"unavailable",{"reason":"no executor adapter"})
                continue
            try:
                result=executor(task)
                ok=bool(result.get("ok",True)) if isinstance(result,dict) else True
                if ok and verifier is not None:
                    ok=bool(verifier(result))
                attempts.append(Attempt(route,ok,result=result,
                                        error="" if ok else "execution or verification failed"))
                self.audit("route_attempt",route,"ok" if ok else "failed",{})
                if ok:
                    return {"ok":True,"decision":"ACT" if len(attempts)==1 else "RECOVER",
                            "route":route,"result":result,"attempted_routes":attempted,
                            "attempts":[a.__dict__ for a in attempts]}
            except Exception as exc:
                attempts.append(Attempt(route,False,error=f"{type(exc).__name__}: {exc}"))
                self.audit("route_attempt",route,"failed",{"error_type":type(exc).__name__})
            attempted.append(route)
        return {"ok":False,"decision":"ESCALATE","reason":"execution routes exhausted",
                "attempted_routes":attempted,"attempts":[a.__dict__ for a in attempts]}
