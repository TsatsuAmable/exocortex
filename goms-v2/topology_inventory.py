#!/usr/bin/env python3
from contextlib import closing
import hashlib,json,sqlite3
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path.home()/"Library/Application Support/Aineko/GOMS"
DB=ROOT/"goms.sqlite3"
def now(): return datetime.now(timezone.utc).isoformat()
def sid(kind,name): return kind+"_"+hashlib.sha256(name.encode()).hexdigest()[:20]
def upsert(c,kind,title,summary,status="observed",metadata=None):
    eid=sid(kind,title); ts=now()
    c.execute("""insert into entities(id,type,title,summary,status,tags,metadata,created_at,updated_at)
    values(?,?,?,?,?,'[]',?,?,?) on conflict(id) do update set
    summary=excluded.summary,status=excluded.status,metadata=excluded.metadata,updated_at=excluded.updated_at""",
    (eid,kind,title,summary,status,json.dumps(metadata or {},sort_keys=True),ts,ts))
    return eid
def rel(c,a,r,b):
    c.execute("insert or replace into relations(src,rel,dst,evidence,created_at) values(?,?,?,?,?)",
              (a,r,b,"runtime-observation",now()))
with closing(sqlite3.connect(DB)) as c, c:
    mac=upsert(c,"machine","MacBook Pro","Primary local cognitive/tooling host.")
    yoda=upsert(c,"machine","Yoda/Fedora","Linux worker and replica host.",metadata={"online":True})
    mill=upsert(c,"machine","Millhouse ADB bridge","Windows device/ADB bridge.",metadata={"online":True})
    ultron=upsert(c,"machine","Ultron","Android device on tailnet.",metadata={"online":True})
    tailscale=upsert(c,"service","Tailscale","Private network connecting authorised machines.")
    for m in [mac,yoda,mill,ultron]: rel(c,m,"connected_via",tailscale)
    ollama=upsert(c,"service","Ollama","Local model and embedding runtime.")
    neo=upsert(c,"service","Neo4j","Derived graph/vector projection engine.")
    broker=upsert(c,"service","Agalmic LLM broker","Local LLM routing/broker service.")
    hermes=upsert(c,"service","Hermes gateway","Agent/MCP gateway.")
    whatsapp=upsert(c,"bridge","Hermes WhatsApp bridge","WhatsApp-facing Hermes bridge.")
    extension=upsert(c,"bridge","Aineko ChatGPT Sync Monitor v0.8.2","Chrome capture extension.")
    native=upsert(c,"bridge","ChatGPT native host","Chrome native messaging receiver.")
    ingest=upsert(c,"routine","ChatGPT→GOMS live ingest","Incremental archive ingestion.",metadata={"cadence_seconds":60})
    repl=upsert(c,"routine","GOMS→Yoda replication","Hash-verified evidence replication.",metadata={"cadence_seconds":60})
    sem=upsert(c,"routine","GOMS semantic maintenance","Ontology, embeddings and graph refresh.",metadata={"cadence_seconds":900})
    vault=upsert(c,"routine","Aineko vault git sync","Observed vault synchronisation routine.")
    msync=upsert(c,"routine","GOMS↔Manfred sync","Observed Manfred/GOMS synchronisation.")
    mcontrol=upsert(c,"service","GOMS Manfred authority","Loopback-only authenticated authority endpoint.")
    mread=upsert(c,"service","GOMS Manfred read projection","Read-only brief exposed through authenticated tailnet transport.")
    goms=upsert(c,"data_store","Canonical GOMS","Canonical cognitive state and ledger.")
    raw=upsert(c,"data_store","ChatGPT raw evidence archive","Durable raw conversation evidence.")
    graph=upsert(c,"data_store","Neo4j GOMS projection","Rebuildable semantic/vector projection.")
    manfred=upsert(c,"interface","Manfred control plane","Human-facing control surface.",status="declared")
    committees=upsert(c,"committee","Adversarial review committees","Multi-model review and critique.",status="declared")
    for x in [ollama,neo,broker,hermes,whatsapp,extension,native,ingest,repl,sem,vault,msync,mcontrol,mread,goms,raw,graph]:
        rel(c,x,"runs_on",mac)
    rel(c,extension,"sends_to",native); rel(c,native,"writes_to",raw)
    rel(c,ingest,"reads_from",raw); rel(c,ingest,"writes_to",goms)
    rel(c,repl,"reads_from",raw); rel(c,repl,"replicates_to",yoda)
    rel(c,sem,"reads_from",goms); rel(c,sem,"projects_to",graph)
    rel(c,graph,"implemented_by",neo); rel(c,hermes,"exposes",goms)
    rel(c,broker,"routes_to",ollama); rel(c,whatsapp,"depends_on",hermes)
    rel(c,manfred,"reads_from",goms); rel(c,manfred,"controls",goms)
    rel(c,committees,"uses",broker); rel(c,committees,"produces",goms)
    c.commit()
print("topology materialised")
