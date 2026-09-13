#!/usr/bin/env python3
import argparse
import json
from goms_store import GomsStore, BRANCH_STATUSES

store = GomsStore()

def create_branch(args):
    bid = store.create_branch(
        title=args.title, project=args.project, status=args.status,
        objective=args.objective or "", last_result=args.last_result or "",
        unresolved=args.unresolved, next_action=args.next_action or "",
        blocker=args.blocker or "", parent=args.parent, worker=args.worker,
        branch_id=args.id, actor="cli")
    print(bid)

def checkpoint(args):
    cid = store.checkpoint(
        args.branch, args.status, args.summary, unresolved=args.unresolved,
        next_action=args.next_action or "", blocker=args.blocker or "",
        source=args.source, actor="cli")
    print(cid)

def list_branches(args):
    print(json.dumps(store.list_branches(args.status, args.project), indent=2))

def build_parser():
    p = argparse.ArgumentParser(description="GOMS branch/checkpoint ledger")
    sub = p.add_subparsers(dest="command", required=True)

    b = sub.add_parser("branch")
    b.add_argument("--id"); b.add_argument("--title", required=True); b.add_argument("--project")
    b.add_argument("--status", default="ACTIVE", choices=sorted(BRANCH_STATUSES))
    b.add_argument("--objective"); b.add_argument("--last-result"); b.add_argument("--next-action")
    b.add_argument("--blocker"); b.add_argument("--parent"); b.add_argument("--worker")
    b.add_argument("--unresolved", action="append"); b.set_defaults(func=create_branch)

    c = sub.add_parser("checkpoint")
    c.add_argument("--branch", required=True); c.add_argument("--status", required=True,
                   choices=sorted(BRANCH_STATUSES))
    c.add_argument("--summary", required=True); c.add_argument("--next-action")
    c.add_argument("--blocker"); c.add_argument("--source")
    c.add_argument("--unresolved", action="append"); c.set_defaults(func=checkpoint)

    l = sub.add_parser("list")
    l.add_argument("--status", choices=sorted(BRANCH_STATUSES)); l.add_argument("--project")
    l.set_defaults(func=list_branches)
    return p

def main():
    args = build_parser().parse_args(); args.func(args)

if __name__ == "__main__":
    main()
