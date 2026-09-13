#!/usr/bin/env python3
import argparse
import json
from goms_store import GomsStore, ENTITY_TYPES

store = GomsStore()

def cmd_init(_):
    store.init(); print(f"GOMS ready: {store.db}")

def cmd_add(args):
    eid = store.add_entity(args.type, args.title, args.summary or "", args.project,
                           args.status, args.confidence, args.source, args.tag,
                           entity_id=args.id, actor="cli")
    print(eid)

def cmd_link(args):
    out = store.link(args.src, args.rel, args.dst, args.evidence, actor="cli")
    print(json.dumps(out))

def cmd_search(args):
    print(json.dumps(store.search(args.query, args.limit, args.project, args.type), indent=2))

def cmd_show(args):
    print(json.dumps(store.get_entity(args.id), indent=2))

def cmd_stats(_):
    print(json.dumps(store.stats(), indent=2))

def build_parser():
    p = argparse.ArgumentParser(description="GOMS v2 research memory")
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("init").set_defaults(func=cmd_init)

    a = sub.add_parser("add")
    a.add_argument("--type", required=True, choices=sorted(ENTITY_TYPES))
    a.add_argument("--title", required=True)
    a.add_argument("--summary"); a.add_argument("--project"); a.add_argument("--status")
    a.add_argument("--confidence", type=float); a.add_argument("--source")
    a.add_argument("--tag", action="append"); a.add_argument("--id")
    a.set_defaults(func=cmd_add)

    l = sub.add_parser("link")
    l.add_argument("--src", required=True); l.add_argument("--rel", required=True)
    l.add_argument("--dst", required=True); l.add_argument("--evidence")
    l.set_defaults(func=cmd_link)

    s = sub.add_parser("search")
    s.add_argument("query"); s.add_argument("--limit", type=int, default=20)
    s.add_argument("--project"); s.add_argument("--type")
    s.set_defaults(func=cmd_search)

    sh = sub.add_parser("show"); sh.add_argument("id"); sh.set_defaults(func=cmd_show)
    sub.add_parser("stats").set_defaults(func=cmd_stats)
    return p

def main():
    args = build_parser().parse_args()
    args.func(args)

if __name__ == "__main__":
    main()
