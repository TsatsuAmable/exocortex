#!/usr/bin/env python3
import json
import re
import time
import urllib.request

OLLAMA_URL='http://127.0.0.1:11434/api/generate'
REMOTE_MODEL_CHAIN=('deepseek-v4-flash:cloud','gpt-oss:120b-cloud')
LOCAL_MODEL_CHAIN=('gsvaineko-core:v1','bonsai27b:q1','qwen3.5:4b')
DEFAULT_MODEL_CHAIN=REMOTE_MODEL_CHAIN+LOCAL_MODEL_CHAIN
_SECRET_PATTERNS=(
    re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH |PGP )?PRIVATE KEY-----',re.I),
    re.compile(r'\bAuthorization\s*:\s*Bearer\s+[A-Za-z0-9._~+/-]{16,}',re.I),
    re.compile(r'\b(?:api[_-]?key|access[_-]?token|secret|password)\s*[:=]\s*[\"\']?[A-Za-z0-9._~+/-]{16,}',re.I),
)


def normalize(raw):
    text=str(raw or '').strip()
    if text.startswith('```') and text.endswith('```'):
        lines=text.splitlines()
        if lines and lines[0].strip().lower() in ('```json','```'):
            lines=lines[1:]
        if lines and lines[-1].strip()=='```':
            lines=lines[:-1]
        text='\n'.join(lines).strip()
    return text


def prompt_allows_remote(prompt):
    text=str(prompt or '')
    return not any(p.search(text) for p in _SECRET_PATTERNS)


def generate_structured(prompt, *, models=None, opener=None, timeout=180):
    chain=tuple(models or (DEFAULT_MODEL_CHAIN if prompt_allows_remote(prompt) else LOCAL_MODEL_CHAIN))
    open_fn=opener or urllib.request.urlopen
    errors=[]
    for model in chain:
        payload=json.dumps({
            'model':model,'prompt':prompt,'stream':False,'format':'json','think':False,
            'options':{'temperature':0,'num_ctx':8192,'num_predict':1800},
        }).encode()
        req=urllib.request.Request(OLLAMA_URL,data=payload,headers={'Content-Type':'application/json'})
        started=time.perf_counter()
        try:
            with open_fn(req,timeout=timeout) as response:
                data=json.load(response)
            raw=normalize(data.get('response') or data.get('thinking') or '')
            parsed=json.loads(raw)
            if not isinstance(parsed,dict):
                raise ValueError('structured response root must be an object')
            return {'model':model,'response':raw,'parsed':parsed,'elapsed_s':time.perf_counter()-started}
        except Exception as exc:
            errors.append({'model':model,'error':f'{type(exc).__name__}: {exc}'[:500]})
    raise RuntimeError('all distillation models failed: '+json.dumps(errors,sort_keys=True))
