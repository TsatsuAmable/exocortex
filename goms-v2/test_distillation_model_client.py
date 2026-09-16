#!/usr/bin/env python3
import io
import json
import unittest

import distillation_model_client as client


class Response(io.BytesIO):
    def __enter__(self): return self
    def __exit__(self,*args): self.close(); return False


class DistillationModelClientTests(unittest.TestCase):
    def test_cloud_first_chain_and_qwen_last(self):
        self.assertEqual(client.DEFAULT_MODEL_CHAIN[0],'deepseek-v4-flash:cloud')
        self.assertEqual(client.DEFAULT_MODEL_CHAIN[1],'gpt-oss:120b-cloud')
        self.assertEqual(client.DEFAULT_MODEL_CHAIN[-1],'qwen3.5:4b')

    def test_generate_structured_falls_back_after_invalid_json(self):
        calls=[]
        def opener(req,timeout):
            payload=json.loads(req.data.decode()); calls.append(payload['model'])
            raw='not json' if len(calls)==1 else '{"items":[]}'
            return Response(json.dumps({'response':raw}).encode())
        result=client.generate_structured('prompt',models=('bad','good'),opener=opener)
        self.assertEqual(calls,['bad','good'])
        self.assertEqual(result['model'],'good')
        self.assertEqual(result['parsed'],{'items':[]})

    def test_generate_structured_disables_thinking_and_strips_fence(self):
        seen={}
        def opener(req,timeout):
            seen.update(json.loads(req.data.decode()))
            return Response(json.dumps({'response':'```json\n{"items":[]}\n```'}).encode())
        result=client.generate_structured('prompt',models=('m',),opener=opener)
        self.assertIs(seen['think'],False)
        self.assertEqual(result['parsed'],{'items':[]})


if __name__=='__main__': unittest.main(verbosity=2)
