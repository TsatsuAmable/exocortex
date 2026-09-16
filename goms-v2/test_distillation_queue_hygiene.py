#!/usr/bin/env python3
from contextlib import closing
import json
import sqlite3
import unittest

import distillation_queue_hygiene as hygiene


class QueueHygieneTests(unittest.TestCase):
    def test_marks_non_user_ineligible_and_missing_artifact_orphaned(self):
        with closing(sqlite3.connect(':memory:')) as c:
            c.executescript('''
              create table entities(id text primary key,tags text not null);
              create table distillation_artifacts(id text primary key,source_entity_id text not null);
              create table distillation_segments(id text primary key,artifact_id text not null,status text,last_error text,updated_at text);
            ''')
            c.execute("insert into entities values('u',?)",(json.dumps(['chatgpt','message','user']),))
            c.execute("insert into entities values('a',?)",(json.dumps(['chatgpt','message','assistant']),))
            c.execute("insert into distillation_artifacts values('au','u')")
            c.execute("insert into distillation_artifacts values('aa','a')")
            c.execute("insert into distillation_segments values('user','au','pending',null,'t')")
            c.execute("insert into distillation_segments values('assistant','aa','pending',null,'t')")
            c.execute("insert into distillation_segments values('orphan','missing','pending',null,'t')")
            c.commit()
            result=hygiene.apply_hygiene(c)
            states=dict(c.execute('select id,status from distillation_segments'))
            events=c.execute('select segment_id,new_status,reason from distillation_queue_hygiene_events order by segment_id').fetchall()
        self.assertEqual(result,{'ineligible':1,'orphaned':1})
        self.assertEqual(states['user'],'pending')
        self.assertEqual(states['assistant'],'ineligible')
        self.assertEqual(states['orphan'],'orphaned')
        self.assertEqual(events,[('assistant','ineligible','not_chatgpt_user_message'),('orphan','orphaned','missing_distillation_artifact')])

    def test_hygiene_is_idempotent(self):
        with closing(sqlite3.connect(':memory:')) as c:
            c.executescript('''create table entities(id text primary key,tags text not null);create table distillation_artifacts(id text primary key,source_entity_id text not null);create table distillation_segments(id text primary key,artifact_id text not null,status text,last_error text,updated_at text);''')
            c.execute("insert into distillation_segments values('orphan','missing','pending',null,'t')")
            c.commit()
            first=hygiene.apply_hygiene(c); second=hygiene.apply_hygiene(c)
            n=c.execute('select count(*) from distillation_queue_hygiene_events').fetchone()[0]
        self.assertEqual(first,{'ineligible':0,'orphaned':1})
        self.assertEqual(second,{'ineligible':0,'orphaned':0})
        self.assertEqual(n,1)


if __name__=='__main__': unittest.main(verbosity=2)
