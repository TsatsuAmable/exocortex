#!/usr/bin/env python3
import argparse, hashlib, json, os
from pathlib import Path
from goms_store import GomsStore

GOMS_HOME = Path(os.environ.get(
    "GOMS_HOME",
    str(Path.home() / "Library/Application Support/Aineko/GOMS")
)).expanduser()
RAW_ROOT = GOMS_HOME / "raw" / "chatgpt"

def stable_id(prefix, value):
    h=hashlib.sha256(value.encode("utf-8")).hexdigest()[:24]
    return f"{prefix}_{h}"

def iter_conversations(data):
    if isinstance(data, list):
        yield from data
    elif isinstance(data, dict):
        if "mapping" in data and ("id" in data or "conversation_id" in data):
            yield data
        else:
            for v in data.values():
                if isinstance(v, list):
                    for x in v:
                        if isinstance(x, dict) and "mapping" in x:
                            yield x

def message_text(message):
    content=(message or {}).get("content") or {}
    parts=content.get("parts")
    if isinstance(parts,list):
        out=[]
        for part in parts:
            if isinstance(part,str):
                out.append(part)
            elif isinstance(part,dict):
                out.append(json.dumps(part,ensure_ascii=False,sort_keys=True))
        return "\n".join(out).strip()
    text=content.get("text")
    return str(text).strip() if text is not None else ""

def iter_messages(conversation):
    mapping=conversation.get("mapping") or {}
    for node_id,node in mapping.items():
        if not isinstance(node,dict):
            continue
        msg=node.get("message")
        if not isinstance(msg,dict):
            continue
        mid=str(msg.get("id") or node_id)
        author=(msg.get("author") or {}).get("role") or "unknown"
        text=message_text(msg)
        if not text:
            continue
        yield {
            "id": mid,
            "role": str(author),
            "text": text,
            "create_time": msg.get("create_time"),
            "update_time": msg.get("update_time"),
            "parent": node.get("parent"),
            "children": node.get("children") or [],
            "status": msg.get("status"),
            "recipient": msg.get("recipient"),
        }

def add_once(store, **kwargs):
    try:
        return store.add_entity(**kwargs), True
    except Exception as e:
        if "UNIQUE constraint failed" in str(e):
            return kwargs["entity_id"], False
        raise

def ingest_file(path: Path, dry_run=False):
    data=json.loads(path.read_text())
    store=GomsStore()
    RAW_ROOT.mkdir(parents=True, exist_ok=True)
    stats={"conversations_seen":0,"conversations_added":0,"messages_seen":0,"messages_added":0}
    for c in iter_conversations(data):
        cid=str(c.get("id") or c.get("conversation_id") or "")
        if not cid:
            continue
        stats["conversations_seen"] += 1
        title=str(c.get("title") or "Untitled ChatGPT conversation")
        raw_path=RAW_ROOT / f"{cid}.json"
        if not dry_run:
            raw_path.write_text(json.dumps(c, ensure_ascii=False, indent=2))
        ceid=stable_id("chatgpt_conversation", cid)
        cmeta={
            "chatgpt_conversation_id": cid,
            "create_time": c.get("create_time"),
            "update_time": c.get("update_time"),
            "raw_path": str(raw_path),
            "source_file": str(path),
        }
        if dry_run:
            print(json.dumps({"conversation":cid,"title":title}))
        else:
            _,added=add_once(
                store,
                entity_type="source",
                title=title,
                summary="Raw ChatGPT conversation archive",
                source=f"chatgpt://conversation/{cid}",
                tags=["chatgpt","conversation","raw-archive"],
                metadata=cmeta,
                entity_id=ceid,
                actor="chatgpt-export-importer",
            )
            stats["conversations_added"] += int(added)

        for m in iter_messages(c):
            stats["messages_seen"] += 1
            meid=stable_id("chatgpt_message", m["id"])
            preview=m["text"][:240].replace("\n"," ")
            title_m=f"{m['role']}: {preview}" if preview else m["role"]
            meta={
                "chatgpt_message_id":m["id"],
                "chatgpt_conversation_id":cid,
                "role":m["role"],
                "create_time":m["create_time"],
                "update_time":m["update_time"],
                "parent":m["parent"],
                "children":m["children"],
                "status":m["status"],
                "recipient":m["recipient"],
                "full_text":m["text"],
            }
            if dry_run:
                continue
            _,added=add_once(
                store,
                entity_type="evidence",
                title=title_m[:500],
                summary=m["text"],
                source=f"chatgpt://conversation/{cid}/message/{m['id']}",
                tags=["chatgpt","message",m["role"]],
                metadata=meta,
                entity_id=meid,
                actor="chatgpt-export-importer",
            )
            if added:
                stats["messages_added"] += 1
                try:
                    store.link(meid,"contained_in",ceid,
                               evidence=f"chatgpt://conversation/{cid}",
                               actor="chatgpt-export-importer")
                except KeyError:
                    pass
    stats["dry_run"]=dry_run
    print(json.dumps(stats,indent=2))

if __name__=="__main__":
    ap=argparse.ArgumentParser()
    ap.add_argument("path", type=Path)
    ap.add_argument("--dry-run", action="store_true")
    args=ap.parse_args()
    ingest_file(args.path, args.dry_run)
