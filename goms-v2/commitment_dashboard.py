#!/usr/bin/env python3
from __future__ import annotations
import argparse, html, json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from commitment_gate import CommitmentGate

def render_dashboard(data):
    lanes = [
        ("human_attention", "Human attention", "Only decisions where evidence has earned scarce judgment."),
        ("autonomous_queue", "Autonomous", "Evidence-qualified work inside delegated authority."),
        ("machine_explore", "Machine explore", "Cheap research, falsification, deduplication and evidence gathering."),
        ("committed", "Committed", "Work deliberately accepted into the active frontier."),
        ("parked_or_closed", "Parked / closed", "Rejected, parked or completed candidates retained for provenance."),
    ]
    def card(c):
        score=f'{c.get("score",0):.3f}'
        badges=f'<span>score {score}</span><span>{html.escape(c.get("risk_class",""))} risk</span>'
        if c.get("human_judgment_required"):
            badges += '<span>human judgment</span>'
        return (
            '<article>'
            f'<h3>{html.escape(c["title"])}</h3>'
            f'<p>{html.escape(c.get("summary") or c.get("rationale") or "")}</p>'
            f'<div class="badges">{badges}</div>'
            f'<small>{html.escape(c.get("project") or "unscoped")} &middot; {html.escape(c.get("status",""))}</small>'
            '</article>'
        )
    sections=[]
    for key,title,desc in lanes:
        items=data["lanes"].get(key,[])
        sections.append(
            f'<section><header><h2>{title} <b>{len(items)}</b></h2><p>{desc}</p></header>'
            f'<div class="cards">{"".join(card(x) for x in items) or "<div class=\"empty\">Empty</div>"}</div></section>'
        )
    m=data["metrics"]
    yield_value=m["capacity_yield_per_human_minute"]
    yield_text="not measured" if yield_value is None else f"{yield_value:.3f}/min"
    return f'''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Aineko Commitment Gate</title><style>
:root{{font-family:Inter,ui-sans-serif,system-ui;background:#0d1117;color:#e6edf3}}
body{{margin:0;padding:28px;max-width:1500px;margin:auto}} h1{{margin-bottom:4px}} .sub{{color:#8b949e;margin-top:0}}
.metrics{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin:24px 0}}
.metric,article,.empty{{background:#161b22;border:1px solid #30363d;border-radius:12px;padding:14px}}
.metric strong{{display:block;font-size:1.5rem}} main{{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:14px;align-items:start}}
section{{background:#0b0f14;border:1px solid #21262d;border-radius:14px;padding:12px}} section header h2{{margin:2px 0}} section header p{{color:#8b949e;min-height:2.5em}}
.cards{{display:grid;gap:9px}} article h3{{font-size:1rem;margin:0 0 8px}} article p{{font-size:.88rem;color:#b1bac4}} small{{color:#8b949e}}
.badges{{display:flex;gap:5px;flex-wrap:wrap;margin:9px 0}} .badges span{{font-size:.72rem;border:1px solid #30363d;border-radius:999px;padding:3px 7px;color:#c9d1d9}}
.empty{{color:#6e7681}} b{{font-size:.8rem;color:#8b949e}}
</style></head><body><h1>Commitment Gate</h1>
<p class="sub">Discovery does not create commitment. Evidence earns attention.</p>
<div class="metrics">
<div class="metric"><strong>{m["candidates"]}</strong>candidates</div>
<div class="metric"><strong>{m["autonomous_queue"]}</strong>autonomous</div>
<div class="metric"><strong>{m["human_attention_queue"]}</strong>need you</div>
<div class="metric"><strong>{m["valuable_durable_outcomes"]}</strong>valuable outcomes</div>
<div class="metric"><strong>{yield_text}</strong>capacity yield</div>
</div><main>{''.join(sections)}</main></body></html>'''

class Handler(BaseHTTPRequestHandler):
    gate=CommitmentGate()
    def do_GET(self):
        data=self.gate.dashboard()
        if self.path == "/api/dashboard":
            body=json.dumps(data,indent=2).encode(); typ="application/json"
        elif self.path == "/":
            body=render_dashboard(data).encode(); typ="text/html; charset=utf-8"
        else:
            self.send_error(404); return
        self.send_response(200); self.send_header("Content-Type",typ)
        self.send_header("Content-Length",str(len(body))); self.end_headers(); self.wfile.write(body)
    def log_message(self, fmt, *args):
        pass

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--host",default="127.0.0.1")
    p.add_argument("--port",type=int,default=8765)
    a=p.parse_args()
    print(f"Commitment Gate dashboard: http://{a.host}:{a.port}", flush=True)
    ThreadingHTTPServer((a.host,a.port),Handler).serve_forever()

if __name__=="__main__":
    main()
