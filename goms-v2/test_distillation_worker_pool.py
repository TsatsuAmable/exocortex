#!/usr/bin/env python3
from contextlib import closing
import json
import sqlite3
import tempfile
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

    def test_default_pool_has_two_broker_lanes_and_one_qwen_lane(self):
        lanes=worker_pool.default_lane_specs()
        self.assertEqual(len(lanes),3)
        self.assertEqual(sum(x.mode=='broker' for x in lanes),2)
        qwen=[x for x in lanes if x.mode=='qwen']
        self.assertEqual(len(qwen),1)
        self.assertIn('qwen3.5:4b', qwen[0].providers[0].model)

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
