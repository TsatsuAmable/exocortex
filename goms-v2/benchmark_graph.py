#!/usr/bin/env python3
import argparse,time,json,statistics
from graph_backend import open_backend

QUERIES={
 "person_world":"""MATCH (p:GOMS:Memory {type:'person'})-[r:SEMANTIC_ASSERTION]->(o:GOMS)
 RETURN p.title AS person,r.predicate AS predicate,o.title AS object,r.confidence AS confidence""",
 "project_context":"""MATCH (p:GOMS:Memory {type:'project'})
 OPTIONAL MATCH (p)-[r:SEMANTIC_ASSERTION]->(o:GOMS)
 RETURN p.title AS project,collect({predicate:r.predicate,target:o.title}) AS context""",
 "two_hop_semantic":"""MATCH (p:GOMS:Memory {type:'person'})-[r1:SEMANTIC_ASSERTION]->(a:GOMS)
 OPTIONAL MATCH (a)-[r2:SEMANTIC_ASSERTION]->(b:GOMS)
 RETURN a.title AS first,r1.predicate AS relation,b.title AS second,r2.predicate AS second_relation""",
 "evidence_degree":"""MATCH (c:GOMS:Memory {type:'source'})<-[:GOMS_REL]-(e:GOMS:Memory {type:'evidence'})
 RETURN c.id AS conversation,count(e) AS messages ORDER BY messages DESC LIMIT 20"""
}
def main():
 ap=argparse.ArgumentParser(); ap.add_argument("--backend",default="neo4j")
 ap.add_argument("--iterations",type=int,default=30); a=ap.parse_args()
 b=open_backend(a.backend); out={}
 try:
  for name,q in QUERIES.items():
   times=[]; rows=0
   for _ in range(a.iterations):
    t=time.perf_counter(); r=b.query(q); times.append((time.perf_counter()-t)*1000); rows=len(r)
   s=sorted(times)
   out[name]={"rows":rows,"mean_ms":round(statistics.mean(times),3),
              "p50_ms":round(statistics.median(times),3),
              "p95_ms":round(s[max(0,int(len(s)*.95)-1)],3),
              "max_ms":round(max(times),3)}
 finally:b.close()
 print(json.dumps(out,indent=2))
if __name__=="__main__": main()
