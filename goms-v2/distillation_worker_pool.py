#!/usr/bin/env python3
import argparse
import http.client
import json
import os
import socket
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from threading import Lock, Thread

PROMPT = '''Extract only durable semantic state from the evidence below.
Return JSON only: {"items":[...]}.
Each item: kind, subject, predicate, object, literal, confidence, evidence_ids.
Allowed kind: objective, decision, task, scarcity, capability, constraint,
preference, outcome, adjacent_possible, proposal, principle, question.
Ignore acknowledgements, transient chatter, rhetoric and one-off requests unless project-relevant.
Do not invent completion or facts. Use exactly the supplied evidence ID.
Confidence <= 0.90 for this cheap extraction tier.
'''

@dataclass(frozen=True)
class ProviderSpec:
    name: str
    adapter: str
    model: str
    remote: bool

@dataclass(frozen=True)
class LaneSpec:
    name: str
    mode: str
    providers: tuple[ProviderSpec, ...]

class ProviderBroker:
    def __init__(self, providers):
        self.providers = tuple(providers)
        self._index = 0
        self._lock = Lock()

    def choose(self, privacy='private'):
        eligible = [p for p in self.providers if privacy == 'non_sensitive' or not p.remote]
        if not eligible:
            return None
        with self._lock:
            provider = eligible[self._index % len(eligible)]
            self._index += 1
        return provider

    def next_any(self):
        if not self.providers:
            return None
        with self._lock:
            provider = self.providers[self._index % len(self.providers)]
            self._index += 1
        return provider

class BurnInBudget:
    def __init__(self, limit):
        self.remaining = max(0, int(limit))
        self._lock = Lock()

    def take(self):
        with self._lock:
            if self.remaining <= 0:
                return False
            self.remaining -= 1
            return True

    def refund(self):
        with self._lock:
            self.remaining += 1


def privacy_scope_for(provider):
    return 'non_sensitive' if provider.remote else 'private'


def build_prompt(segment):
    return (PROMPT + '\nEVIDENCE_ID: ' + str(segment['source_entity_id']) +
            '\nSOURCE: ' + str(segment.get('source_ref') or '') +
            '\nTEXT:\n' + str(segment.get('content') or ''))


def ollama_adapter(model, prompt):
    payload = json.dumps({
        'model': model,
        'prompt': prompt,
        'stream': False,
        'format': 'json',
        'options': {'temperature': 0, 'num_ctx': 8192, 'num_predict': 1400},
    }).encode()
    req = urllib.request.Request('http://127.0.0.1:11434/api/generate', data=payload,
                                 headers={'Content-Type':'application/json'})
    started = time.perf_counter()
    with urllib.request.urlopen(req, timeout=180) as response:
        data = json.load(response)
    return (data.get('response') or data.get('thinking') or ''), {
        'elapsed_s': time.perf_counter() - started,
        'prompt_eval_count': data.get('prompt_eval_count'),
        'eval_count': data.get('eval_count'),
    }


def opencode_adapter(model, prompt):
    started = time.perf_counter()
    proc = subprocess.run(
        ['opencode','run','--pure','-m',model,'--agent','plan',prompt],
        capture_output=True, text=True, timeout=180, check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout or f'opencode exit {proc.returncode}')[-1000:])
    return proc.stdout.strip(), {'elapsed_s': time.perf_counter() - started}


def invoke_provider(provider, prompt, *, adapters=None):
    adapters = adapters or {'ollama': ollama_adapter, 'opencode': opencode_adapter}
    if provider.adapter not in adapters:
        raise ValueError(f'unknown provider adapter: {provider.adapter}')
    return adapters[provider.adapter](provider.model, prompt)


def _tailscale_ipv4():
    try:
        proc = subprocess.run(
            ["tailscale", "ip", "-4"],
            capture_output=True, text=True, timeout=3, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    value = proc.stdout.strip() if proc.returncode == 0 else ""
    return value or None


def default_queue_url(*, env=None, tailscale_ip=None):
    env = os.environ if env is None else env
    explicit = str(env.get("GOMS_QUEUE_URL") or "").strip()
    if explicit:
        return explicit.rstrip("/")
    resolver = _tailscale_ipv4 if tailscale_ip is None else tailscale_ip
    host = resolver() or "127.0.0.1"
    port = str(env.get("GOMS_QUEUE_PORT") or "8767").strip()
    return f"http://{host}:{port}"


class QueueHTTPClient:
    def __init__(self, base_url=None, *, opener=None, sleep=None, retries=4, retry_delay=0.2):
        self.base_url = (base_url or default_queue_url()).rstrip('/')
        self._opener = opener or urllib.request.urlopen
        self._sleep = sleep or time.sleep
        self.retries = max(1, int(retries))
        self.retry_delay = max(0.0, float(retry_delay))

    def _post(self, path, body):
        req = urllib.request.Request(self.base_url + path, data=json.dumps(body).encode(),
                                     headers={'Content-Type':'application/json'})
        last_error = None
        for attempt in range(self.retries):
            try:
                with self._opener(req, timeout=30) as response:
                    return json.load(response)
            except urllib.error.HTTPError as exc:
                if exc.code not in (429, 502, 503, 504):
                    raise
                last_error = exc
            except (http.client.RemoteDisconnected, urllib.error.URLError,
                    ConnectionResetError, ConnectionRefusedError, TimeoutError) as exc:
                last_error = exc
            if attempt + 1 < self.retries:
                self._sleep(self.retry_delay * (attempt + 1))
        raise last_error

    def claim(self, worker, count, privacy_scope):
        return self._post('/claim', {'worker':worker,'count':count,'privacy_scope':privacy_scope}).get('segments', [])

    def submit(self, worker, segment_id, extractor, raw):
        return self._post('/submit', {'worker':worker,'segment_id':segment_id,'extractor':extractor,'raw':raw})

    def release(self, worker, segment_id, error):
        return self._post('/release', {'worker':worker,'segment_id':segment_id,'error':error})


def default_lane_specs():
    broker_a = (
        ProviderSpec('nemotron-opencode','opencode','opencode/nemotron-3.5-lightning-free',True),
        ProviderSpec('gsvaineko-local','ollama','gsvaineko-core:v1',False),
    )
    broker_b = (
        ProviderSpec('glm-ollama-cloud','ollama','glm-5.3-flash:cloud',True),
        ProviderSpec('bonsai-local','ollama','bonsai27b:q1',False),
    )
    qwen = (ProviderSpec('qwen-local','ollama','qwen3.5:4b',False),)
    return (
        LaneSpec('broker-a','broker',broker_a),
        LaneSpec('broker-b','broker',broker_b),
        LaneSpec('qwen-local','qwen',qwen),
    )


def _new_stats(lane):
    return {'lane':lane.name,'mode':lane.mode,'attempted':0,'done':0,'repair':0,
            'provider_errors':0,'queue_errors':0,'claim_empty':0,'elapsed_s':0.0,'providers':{}}


def _run_lane(lane, budget, queue, adapters, stats):
    worker = f'{socket.gethostname()}-{lane.name}'
    broker = ProviderBroker(lane.providers)
    empty_streak = 0
    while True:
        if not budget.take():
            return
        provider = broker.next_any()
        if provider is None:
            budget.refund(); return
        scope = privacy_scope_for(provider)
        try:
            rows = queue.claim(worker, 1, scope)
        except Exception:
            budget.refund()
            stats['queue_errors'] += 1
            empty_streak += 1
            if empty_streak >= max(3, len(lane.providers) * 2):
                return
            time.sleep(min(0.5, 0.05 * empty_streak))
            continue
        if not rows:
            budget.refund()
            stats['claim_empty'] += 1
            empty_streak += 1
            if empty_streak >= max(2, len(lane.providers) * 2):
                return
            continue
        empty_streak = 0
        segment = rows[0]
        stats['attempted'] += 1
        pstats = stats['providers'].setdefault(provider.name, {'attempted':0,'done':0,'repair':0,'errors':0,'elapsed_s':0.0})
        pstats['attempted'] += 1
        started = time.perf_counter()
        try:
            raw, meta = invoke_provider(provider, build_prompt(segment), adapters=adapters)
            result = queue.submit(worker, segment['id'], f'{provider.adapter}:{provider.model}', raw)
            elapsed = float(meta.get('elapsed_s') or (time.perf_counter() - started))
            stats['elapsed_s'] += elapsed; pstats['elapsed_s'] += elapsed
            status = result.get('segment_status')
            if status == 'done':
                stats['done'] += 1; pstats['done'] += 1
            else:
                stats['repair'] += 1; pstats['repair'] += 1
        except Exception as exc:
            stats['provider_errors'] += 1; pstats['errors'] += 1
            try:
                queue.release(worker, segment['id'], str(exc)[:1000])
            except Exception:
                pass


def run_pool(limit, *, lanes=None, queue=None, adapters=None):
    lanes = tuple(lanes or default_lane_specs())
    queue = queue or QueueHTTPClient()
    budget = BurnInBudget(limit)
    stats = {lane.name:_new_stats(lane) for lane in lanes}
    threads = [Thread(target=_run_lane, args=(lane,budget,queue,adapters,stats[lane.name]), daemon=True)
               for lane in lanes]
    for thread in threads: thread.start()
    for thread in threads: thread.join()
    return stats


def main():
    ap = argparse.ArgumentParser(description='GOMS stateless distillation worker pool')
    ap.add_argument('--limit', type=int, default=100)
    ap.add_argument('--queue-url', default=None)
    ap.add_argument('--output')
    args = ap.parse_args()
    started = time.perf_counter()
    stats = run_pool(args.limit, queue=QueueHTTPClient(args.queue_url))
    result = {'limit':args.limit,'wall_s':time.perf_counter()-started,'lanes':stats}
    text = json.dumps(result, indent=2, sort_keys=True)
    if args.output:
        Path(args.output).write_text(text + '\n')
    print(text)

if __name__ == '__main__':
    main()
