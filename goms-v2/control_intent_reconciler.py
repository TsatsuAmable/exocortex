#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

from control_intents import ControlIntentService


def reconcile_attention_intents(root: str | Path) -> dict:
    """Ensure each open attention item has exactly one canonical control intent."""
    svc = ControlIntentService(root)
    with svc.store.connect() as con:
        open_ids = [str(row["id"]) for row in con.execute(
            "SELECT id FROM attention_items WHERE status='open' ORDER BY created_at,id"
        ).fetchall()]
        existing_ids = {
            str(row["attention_id"]) for row in con.execute(
                "SELECT attention_id FROM attention_control_intents"
            ).fetchall()
        }

    created = 0
    existing = 0
    for attention_id in open_ids:
        svc.ensure_for_attention(attention_id)
        if attention_id in existing_ids:
            existing += 1
        else:
            created += 1

    with svc.store.connect() as con:
        closed = int(con.execute("""SELECT count(*)
            FROM attention_control_intents m
            JOIN attention_items a ON a.id=m.attention_id
            WHERE a.status!='open'""").fetchone()[0])

    return {"created": created, "existing": existing, "closed": closed}


if __name__ == "__main__":
    from goms_store import ROOT
    print(reconcile_attention_intents(ROOT))
