#!/usr/bin/env python3
from contextlib import closing
import http.client
import json
import sqlite3
import tempfile
import threading
import time
import unittest
from pathlib import Path

import distillation_queue_server as queue_server
import distillation_worker_pool as worker_pool


SCHEMA = """
create table entities(id text primary key, tags text not null, metadata text not null default '{}');
create table distillation_artifacts(id text primary key, source_entity_id text not null, source_ref text, metadata text not null default '{}');
create table distillation_segments(id text primary key, artifact_id text not null, ordinal integer not null, content_sha256 text not null, content text not null, status text not null default 'pending', attempts integer not null default 0, last_error text, metadata text not null default '{}', created_at text not null, updated_at text not null, priority integer not null default 0, lease_owner text, lease_until text, last_model text);
"""


def seed_segment(c, sid, role='user', privacy=None, priority=0, tags=None):
    eid=f'e_{sid}'
    aid=f'a_{sid}'
    c.execute('insert into entities(id,tags,metadata) values(?,?,?)', (eid, json.dumps(tags or ['chatgpt','message',role]), '{}'))
    c.execute('insert into distillation_artifacts(id,source_entity_id,source_ref,metadata) values(?,?,?,?)', (aid,eid,f'chatgpt://{sid}','{}'))
    meta={} if privacy is None else {'privacy': privacy}
    c.execute("insert into distillation_segments(id,artifact_id,ordinal,content_sha256,content,status,metadata,created_at,updated_at,priority) values(?,?,?,?,?,'pending',?,?,?,?)", (sid,aid,0,f'h_{sid}',f'text {sid}',json.dumps(meta),'2026-09-16T00:00:00+00:00','2026-09-16T00:00:00+00:00',priority))


class QueueLeaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.db=Path(self.tmp.name)/'q.sqlite3'
        with closing(sqlite3.connect(self.db)) as c:
            c.executescript(SCHEMA)
            seed_segment(c,'private-user','user',None,3)
            seed_segment(c,'public-user','user','non_sensitive',2)
            seed_segment(c,'public-assistant','assistant','non_sensitive',9)
            seed_segment(c,'other-user','user',None,10,tags=['other-source','message','user'])
            c.commit()

    def tearDown(self):
        self.tmp.cleanup()

    def test_local_claim_only_takes_user_role_and_can_take_unclassified(self):
        rows=queue_server.claim('local',10,db_path=self.db,privacy_scope='private')
        self.assertEqual([r['id'] for r in rows], ['private-user','public-user'])

    def test_remote_claim_requires_explicit_non_sensitive_mark(self):
        rows=queue_server.claim('remote',10,db_path=self.db,privacy_scope='non_sensitive')
        self.assertEqual([r['id'] for r in rows], ['public-user'])

    def test_active_lease_is_not_double_claimed(self):
        first=queue_server.claim('w1',1,db_path=self.db,privacy_scope='private')
        second=queue_server.claim('w2',1,db_path=self.db,privacy_scope='private')
        self.assertEqual(len(first),1)
        self.assertNotEqual(first[0]['id'], second[0]['id'])

    def test_empty_valid_salvage_is_done_not_repair(self):
        self.assertEqual(queue_server.segment_status_for_recovered(-1),'done')
        self.assertEqual(queue_server.segment_status_for_recovered(2),'done')
        self.assertEqual(queue_server.segment_status_for_recovered(0),'repair')

    def test_claim_waits_through_short_writer_contention(self):
        locker=sqlite3.connect(self.db,check_same_thread=False)
        locker.execute('BEGIN IMMEDIATE')
        releaser=threading.Thread(target=lambda: (time.sleep(0.05),locker.commit()))
        releaser.start()
        try:
            rows=queue_server.claim('waiter',1,db_path=self.db,privacy_scope='private',db_busy_timeout_ms=1000)
        finally:
            releaser.join(); locker.close()
        self.assertEqual(len(rows),1)



class ProviderBrokerTests(unittest.TestCase):
    def test_private_work_never_selects_remote_provider(self):
        broker=worker_pool.ProviderBroker([
            worker_pool.ProviderSpec('remote','opencode','opencode/nemotron-3.5-lightning-free',True),
            worker_pool.ProviderSpec('local','ollama','gsvaineko-core:v1',False),
        ])
        chosen=broker.choose(privacy='private')
        self.assertEqual(chosen.name,'local')

    def test_non_sensitive_work_round_robins_across_eligible_providers(self):
        broker=worker_pool.ProviderBroker([
            worker_pool.ProviderSpec('a','opencode','opencode/nemotron-3.5-lightning-free',True),
            worker_pool.ProviderSpec('b','ollama','glm-5.3-flash:cloud',True),
        ])
        self.assertEqual([broker.choose('non_sensitive').name for _ in range(4)], ['a','b','a','b'])

    def test_default_pool_has_three_cloud_first_lanes_and_no_dedicated_qwen_lane(self):
        lanes=worker_pool.default_lane_specs()
        self.assertEqual(len(lanes),3)
        self.assertTrue(all(x.mode=='cloud-first' for x in lanes))
        self.assertTrue(all(x.providers[-1].model=='qwen3.5:4b' for x in lanes))


    def test_default_provider_chain_is_ollama_cloud_first_and_qwen_last(self):
        lanes=worker_pool.default_lane_specs()
        self.assertEqual(len(lanes),3)
        for lane in lanes:
            self.assertEqual(lane.providers[0].model,'glm-5.3:cloud')
            self.assertTrue(lane.providers[0].remote)
            self.assertEqual(lane.providers[-1].model,'qwen3.5:4b')
            self.assertFalse(lane.providers[-1].remote)

    def test_normal_chatgpt_segment_allows_remote_provider(self):
        self.assertTrue(worker_pool.segment_allows_remote({'content':'ordinary project discussion','privacy':None}))

    def test_explicit_local_only_segment_blocks_remote_provider(self):
        self.assertFalse(worker_pool.segment_allows_remote({'content':'ordinary text','privacy':'local_only'}))

    def test_secret_bearing_segment_blocks_remote_provider(self):
        self.assertFalse(worker_pool.segment_allows_remote({'content':'Authorization: Bearer abcdefghijklmnopqrstuvwxyz123456','privacy':None}))

    def test_burn_in_budget_never_allocates_more_than_limit(self):
        budget=worker_pool.BurnInBudget(3)
        self.assertEqual([budget.take() for _ in range(5)], [True,True,True,False,False])


class QueueEndpointDiscoveryTests(unittest.TestCase):
    def test_explicit_queue_url_wins(self):
        self.assertEqual(
            worker_pool.default_queue_url(
                env={"GOMS_QUEUE_URL":"http://queue.example:9999"},
                tailscale_ip=lambda: "100.64.0.1",
            ),
            "http://queue.example:9999",
        )

    def test_tailscale_ip_is_used_when_no_override(self):
        self.assertEqual(
            worker_pool.default_queue_url(env={}, tailscale_ip=lambda: "100.109.209.29"),
            "http://100.109.209.29:8767",
        )

    def test_loopback_is_safe_fallback_when_tailscale_unavailable(self):
        self.assertEqual(
            worker_pool.default_queue_url(env={}, tailscale_ip=lambda: None),
            "http://127.0.0.1:8767",
        )

class QueueTransportTests(unittest.TestCase):
    def test_http_client_retries_transient_disconnect(self):
        calls=[]
        class Response:
            def __enter__(self): return self
            def __exit__(self,*args): return False
            def read(self,*args): return b'{"segments":[]}'
        def opener(req,timeout):
            calls.append(req.full_url)
            if len(calls)==1:
                raise http.client.RemoteDisconnected('temporary disconnect')
            return Response()
        client=worker_pool.QueueHTTPClient('http://queue',opener=opener,sleep=lambda _:None,retries=2)
        self.assertEqual(client.claim('w',1,'private'),[])
        self.assertEqual(len(calls),2)


class WorkerRuntimeTests(unittest.TestCase):
    def test_remote_provider_claims_only_non_sensitive_scope(self):
        remote=worker_pool.ProviderSpec('r','opencode','model',True)
        local=worker_pool.ProviderSpec('l','ollama','model',False)
        self.assertEqual(worker_pool.privacy_scope_for(remote),'non_sensitive')
        self.assertEqual(worker_pool.privacy_scope_for(local),'private')

    def test_prompt_binds_exact_evidence_id_and_source(self):
        seg={'source_entity_id':'evidence-123','source_ref':'chatgpt://conversation/x','content':'Keep durable state.'}
        prompt=worker_pool.build_prompt(seg)
        self.assertIn('EVIDENCE_ID: evidence-123',prompt)
        self.assertIn('SOURCE: chatgpt://conversation/x',prompt)
        self.assertIn('Keep durable state.',prompt)

    def test_invoke_provider_dispatches_by_adapter(self):
        seen=[]
        provider=worker_pool.ProviderSpec('x','fake','m',False)
        raw,meta=worker_pool.invoke_provider(provider,'p',adapters={'fake':lambda model,prompt: (seen.append((model,prompt)) or ('{}',{'ok':1}))})
        self.assertEqual(raw,'{}')
        self.assertEqual(meta['ok'],1)
        self.assertEqual(seen,[('m','p')])

    def test_lane_survives_transient_claim_failure_without_spending_budget(self):
        class FlakyQueue:
            def __init__(self): self.calls=0; self.submitted=[]
            def claim(self,worker,count,privacy_scope):
                self.calls+=1
                if self.calls==1: raise OSError('temporary queue failure')
                return [{'id':'s1','source_entity_id':'e1','source_ref':'src','content':'c','privacy':None}]
            def submit(self,worker,segment_id,extractor,raw):
                self.submitted.append(segment_id); return {'ok':True,'segment_status':'done'}
            def release(self,worker,segment_id,error): return {'ok':True}
        lane=worker_pool.LaneSpec('one','broker',(worker_pool.ProviderSpec('p','fake','m',False),))
        stats=worker_pool.run_pool(1,lanes=(lane,),queue=FlakyQueue(),adapters={'fake':lambda m,p: ('{"items":[]}',{})})['one']
        self.assertEqual(stats['attempted'],1)
        self.assertEqual(stats['done'],1)
        self.assertEqual(stats['queue_errors'],1)


    def test_provider_chain_falls_back_to_qwen_only_after_earlier_failures(self):
        calls=[]
        class OneQueue:
            def __init__(self): self.claims=0; self.submitted=[]; self.released=[]
            def claim(self,worker,count,privacy_scope):
                self.claims+=1
                if self.claims>1: return []
                return [{'id':'s1','source_entity_id':'e1','source_ref':'src','content':'ordinary text','privacy':None}]
            def submit(self,worker,segment_id,extractor,raw):
                self.submitted.append(extractor); return {'ok':True,'segment_status':'done'}
            def release(self,worker,segment_id,error): self.released.append(error); return {'ok':True}
        lane=worker_pool.LaneSpec('one','cloud-first',(
            worker_pool.ProviderSpec('cloud','fake','glm-5.3:cloud',True),
            worker_pool.ProviderSpec('local','fake','gsvaineko-core:v1',False),
            worker_pool.ProviderSpec('qwen','fake','qwen3.5:4b',False),
        ))
        def adapter(model,prompt):
            calls.append(model)
            if model!='qwen3.5:4b': raise RuntimeError('provider unavailable')
            return ('{"items":[]}',{})
        q=OneQueue()
        stats=worker_pool.run_pool(1,lanes=(lane,),queue=q,adapters={'fake':adapter})['one']
        self.assertEqual(calls,['glm-5.3:cloud','gsvaineko-core:v1','qwen3.5:4b'])
        self.assertEqual(stats['done'],1)
        self.assertEqual(q.submitted,['fake:qwen3.5:4b'])
        self.assertEqual(q.released,[])

    def test_local_only_segment_skips_cloud_and_uses_local_before_qwen(self):
        calls=[]
        class OneQueue:
            def __init__(self): self.claims=0
            def claim(self,worker,count,privacy_scope):
                self.claims+=1
                return [] if self.claims>1 else [{'id':'s1','source_entity_id':'e1','source_ref':'src','content':'ordinary','privacy':'local_only'}]
            def submit(self,*args): return {'ok':True,'segment_status':'done'}
            def release(self,*args): return {'ok':True}
        lane=worker_pool.LaneSpec('one','cloud-first',(
            worker_pool.ProviderSpec('cloud','fake','glm-5.3:cloud',True),
            worker_pool.ProviderSpec('local','fake','gsvaineko-core:v1',False),
            worker_pool.ProviderSpec('qwen','fake','qwen3.5:4b',False),
        ))
        stats=worker_pool.run_pool(1,lanes=(lane,),queue=OneQueue(),adapters={'fake':lambda m,p:(calls.append(m) or ('{"items":[]}',{}))})['one']
        self.assertEqual(calls,['gsvaineko-core:v1'])
        self.assertEqual(stats['done'],1)

    def test_pool_processes_exact_budget_with_stateless_lanes(self):
        class FakeQueue:
            def __init__(self):
                self.lock=__import__('threading').Lock(); self.next=0; self.submitted=[]; self.released=[]
            def claim(self,worker,count,privacy_scope):
                with self.lock:
                    self.next+=1; n=self.next
                return [{'id':f's{n}','source_entity_id':f'e{n}','source_ref':f'src{n}','content':f'c{n}','privacy':None}]
            def submit(self,worker,segment_id,extractor,raw):
                with self.lock: self.submitted.append((worker,segment_id,extractor,raw))
                return {'ok':True,'segment_status':'done','recovered':1}
            def release(self,worker,segment_id,error):
                with self.lock: self.released.append((worker,segment_id,error))
                return {'ok':True}
        q=FakeQueue()
        lanes=worker_pool.default_lane_specs()
        stats=worker_pool.run_pool(7,lanes=lanes,queue=q,adapters={
            'ollama':lambda model,prompt: ('{"items":[]}',{}),
            'opencode':lambda model,prompt: ('{"items":[]}',{}),
        })
        self.assertEqual(sum(x['attempted'] for x in stats.values()),7)
        self.assertEqual(len(q.submitted),7)
        self.assertEqual(len(q.released),0)


class QueueReleaseTests(unittest.TestCase):
    def test_release_returns_owned_lease_to_pending(self):
        with tempfile.TemporaryDirectory() as td:
            db=Path(td)/'q.sqlite3'
            with closing(sqlite3.connect(db)) as c:
                c.executescript(SCHEMA); seed_segment(c,'s','user',None,1); c.commit()
            row=queue_server.claim('w',1,db_path=db)[0]
            self.assertEqual(row['id'],'s')
            self.assertTrue(queue_server.release('w','s','provider timeout',db_path=db))
            with closing(sqlite3.connect(db)) as c:
                status,owner,error=c.execute("select status,lease_owner,last_error from distillation_segments where id='s'").fetchone()
            self.assertEqual((status,owner,error),('pending',None,'provider timeout'))


class StreamingSchemaTests(unittest.TestCase):
    def test_schema_recreates_live_streaming_queue_contract(self):
        c=sqlite3.connect(':memory:')
        c.executescript(Path('schema.sql').read_text())
        tables={r[0] for r in c.execute("select name from sqlite_master where type='table'")}
        for name in ('distillation_artifacts','distillation_segments','distillation_claim_work','distillation_salvage_events','distillation_metrics'):
            self.assertIn(name,tables)
        segment_cols={r[1] for r in c.execute('pragma table_info(distillation_segments)')}
        self.assertTrue({'priority','lease_owner','lease_until','last_model'}.issubset(segment_cols))
        work_cols={r[1] for r in c.execute('pragma table_info(distillation_claim_work)')}
        self.assertTrue({'parent_work_id','route_stage','model_cost'}.issubset(work_cols))


if __name__=='__main__':
    unittest.main(verbosity=2)
