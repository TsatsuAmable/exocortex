#!/usr/bin/env python3
"""Persistent Nemosyne adversarial validation supervisor.

Runs cheap liveness checks every delivery-controller tick, deterministic/stochastic
simulator and Rust/Moneta campaigns on cadence or source change, records physical
Quest readiness when ADB is available, and promotes novel findings into durable
Delivery/GOMS work packets. It never edits Nemosyne or changes roadmap order.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

HOME = Path.home()
WORKSPACE = HOME / "Library/Application Support/Aineko/workspaces"
MAIN = Path(os.getenv("NEMOSYNE_MAIN", WORKSPACE / "nemosyne-supervised-main"))
XR = Path(os.getenv("NEMOSYNE_XR_WORKTREE", WORKSPACE / "nemosyne-supervised"))
EVIDENCE = Path(os.getenv("NEMOSYNE_CONTINUOUS_EVIDENCE", HOME / "Library/Application Support/Aineko/evidence/nemosyne/continuous"))
STATE = EVIDENCE / "state.json"
EVENTS = EVIDENCE / "events.ndjson"
LOCK = EVIDENCE / ".tick.lock"
DELIVERY = Path(__file__).with_name("delivery.py")
ADB = Path(os.getenv("ADB_BIN", HOME / "Library/Android/sdk/platform-tools/adb"))
SIM_INTERVAL = int(os.getenv("NEMOSYNE_SIM_INTERVAL", "900"))
MONETA_INTERVAL = int(os.getenv("NEMOSYNE_MONETA_INTERVAL", "900"))
SEMANTIC_INTERVAL = int(os.getenv("NEMOSYNE_SEMANTIC_INTERVAL", "900"))
HARDWARE_INTERVAL = int(os.getenv("NEMOSYNE_HARDWARE_INTERVAL", "300"))
PHYSICAL_INTERVAL = int(os.getenv("NEMOSYNE_PHYSICAL_INTERVAL", "300"))
QUEST_APP_PORT = int(os.getenv("NEMOSYNE_QUEST_APP_PORT", "5173"))
QUEST_PROBE = XR / "scripts/quest-physical-runtime-probe.mjs"
PHYSICAL_LATEST = EVIDENCE / "physical-latest.json"
PHYSICAL_HISTORY = EVIDENCE / "physical.ndjson"
QUEST_SERVER_LOG = EVIDENCE / "quest-server.log"


def now() -> int:
    return int(time.time())


def load_state() -> dict:
    try:
        return json.loads(STATE.read_text())
    except Exception:
        return {}


def save_state(state: dict) -> None:
    EVIDENCE.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = STATE.with_suffix('.tmp')
    tmp.write_text(json.dumps(state, indent=2, sort_keys=True) + '\n')
    os.chmod(tmp, 0o600)
    tmp.replace(STATE)


def emit(kind: str, **detail) -> None:
    EVIDENCE.mkdir(parents=True, exist_ok=True, mode=0o700)
    with EVENTS.open('a') as fh:
        fh.write(json.dumps({'at': now(), 'kind': kind, **detail}, sort_keys=True) + '\n')
    os.chmod(EVENTS, 0o600)


def clip_output(text: str, limit: int = 12000) -> str:
    if len(text) <= limit:
        return text
    head = 4000
    tail = limit - head
    return text[:head] + '\n...[truncated]...\n' + text[-tail:]


def run(args: list[str], cwd: Path, timeout: int = 180, env: dict | None = None) -> dict:
    """Run one bounded command and own its whole descendant process group."""
    started = time.time()
    process = None
    try:
        process = subprocess.Popen(
            args, cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env=env, start_new_session=True,
        )
        stdout, stderr = process.communicate(timeout=timeout)
        return {'ok': process.returncode == 0, 'code': process.returncode,
                'seconds': round(time.time() - started, 3),
                'stdout': clip_output(stdout), 'stderr': clip_output(stderr)}
    except subprocess.TimeoutExpired:
        if process is not None:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            stdout, stderr = process.communicate(timeout=5)
        else:
            stdout, stderr = '', ''
        return {'ok': False, 'code': None, 'seconds': round(time.time() - started, 3),
                'stdout': clip_output(stdout or ''),
                'stderr': clip_output((stderr or '') + f'\nTIMEOUT after {timeout}s; process group terminated')}
    except Exception as exc:
        if process is not None and process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        return {'ok': False, 'code': None, 'seconds': round(time.time() - started, 3),
                'stdout': '', 'stderr': str(exc)}


def git_sha(root: Path) -> str | None:
    out = run(['git', 'rev-parse', 'HEAD'], root, 20)
    value = out['stdout'].strip()
    return value if out['ok'] and len(value) == 40 else None


def due(state: dict, key: str, interval: int, sha: str | None) -> bool:
    lane = state.get(key, {})
    return lane.get('sha') != sha or now() - int(lane.get('at', 0)) >= interval


def record_lane(state: dict, key: str, sha: str | None, result: dict, extra: dict | None = None) -> None:
    state[key] = {'at': now(), 'sha': sha, 'ok': bool(result.get('ok')),
                  'code': result.get('code'), 'seconds': result.get('seconds'),
                  **(extra or {})}
    emit(key, sha=sha, ok=bool(result.get('ok')), code=result.get('code'),
         seconds=result.get('seconds'), **(extra or {}))


def adb_snapshot() -> dict:
    listing = run([str(ADB), 'devices', '-l'], MAIN, 5)
    devices = [line for line in listing['stdout'].splitlines()[1:] if len(line.split()) >= 2 and line.split()[1] == 'device']
    if not devices:
        return {'connected': False, 'devices': [], 'awake': False, 'browserPid': None}
    serial = devices[0].split()[0]
    wake = run([str(ADB), '-s', serial, 'shell', 'dumpsys', 'power'], MAIN, 5)
    browser = run([str(ADB), '-s', serial, 'shell', 'pidof', 'com.oculus.browser'], MAIN, 5)
    props = {}
    for field, prop in {
        'model': 'ro.product.model',
        'buildIncremental': 'ro.build.version.incremental',
        'buildFingerprint': 'ro.build.fingerprint',
        'securityPatch': 'ro.build.version.security_patch',
    }.items():
        value = run([str(ADB), '-s', serial, 'shell', 'getprop', prop], MAIN, 4)
        props[field] = value['stdout'].strip() if value['ok'] else None
    identity_ok = bool(props['model'] and props['buildIncremental'] and props['buildFingerprint'])
    return {'connected': True, 'devices': devices, 'serialHash': hashlib.sha256(serial.encode()).hexdigest()[:12],
            'awake': 'Wakefulness: Awake' in wake['stdout'] or 'mWakefulness=Awake' in wake['stdout'],
            'browserPid': browser['stdout'].strip() or None,
            'identityOk': identity_ok, 'identity': props if identity_ok else None}



def git_clean(root: Path) -> bool:
    result = run(['git', 'status', '--porcelain'], root, 20)
    return bool(result['ok']) and result['stdout'].strip() == ''


def listener_info(port: int = QUEST_APP_PORT) -> dict:
    found = run(['/usr/sbin/lsof', f'-tiTCP:{port}', '-sTCP:LISTEN'], XR, 20)
    pid_text = found['stdout'].strip().splitlines()[0] if found['ok'] and found['stdout'].strip() else ''
    if not pid_text.isdigit():
        return {'pid': None, 'cwd': None, 'command': None}
    pid = int(pid_text)
    cwd_result = run(['/usr/sbin/lsof', '-a', '-p', str(pid), '-d', 'cwd', '-Fn'], XR, 20)
    cwd = next((line[1:] for line in cwd_result['stdout'].splitlines() if line.startswith('n')), None)
    command_result = run(['ps', '-p', str(pid), '-o', 'command='], XR, 20)
    return {'pid': pid, 'cwd': cwd, 'command': command_result['stdout'].strip() or None}


def start_quest_server(state: dict, target_sha: str | None) -> dict:
    if not QUEST_PROBE.exists():
        return {'ok': False, 'reason': 'physical-probe-missing'}
    if not git_clean(XR):
        return {'ok': False, 'reason': 'worktree-dirty'}
    EVIDENCE.mkdir(parents=True, exist_ok=True, mode=0o700)
    env = os.environ.copy()
    env['PATH'] = f"/opt/homebrew/bin:{ADB.parent}:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
    with QUEST_SERVER_LOG.open('ab', buffering=0) as log:
        process = subprocess.Popen(
            ['npm', 'run', 'dev:quest:validate'], cwd=XR, stdout=log, stderr=subprocess.STDOUT,
            env=env, start_new_session=True,
        )
    state['questServer'] = {'launcherPid': process.pid, 'sha': target_sha, 'startedAt': now()}
    emit('quest_server_started', launcherPid=process.pid, sha=target_sha)
    time.sleep(1.5)
    return {'ok': True, 'launcherPid': process.pid}


def stop_owned_listener(listener: dict) -> bool:
    pid = listener.get('pid')
    cwd = listener.get('cwd')
    command = listener.get('command') or ''
    if not pid or cwd != str(XR) or 'vite' not in command:
        return False
    try:
        os.kill(int(pid), signal.SIGTERM)
        for _ in range(20):
            time.sleep(0.1)
            if listener_info().get('pid') != pid:
                break
        emit('quest_server_stopped', pid=pid, reason='exact-head-rotation')
        return True
    except Exception as exc:
        emit('quest_server_stop_error', pid=pid, error=str(exc))
        return False


def parse_probe(result: dict) -> dict | None:
    try:
        value = json.loads(result.get('stdout') or '')
        return value if isinstance(value, dict) else None
    except Exception:
        return None


def launch_quest_page() -> None:
    listing = run([str(ADB), 'devices'], XR, 10)
    serials = [line.split()[0] for line in listing['stdout'].splitlines()[1:]
               if len(line.split()) >= 2 and line.split()[1] == 'device']
    if len(serials) != 1:
        return
    run([
        str(ADB), '-s', serials[0], 'shell', 'am', 'start',
        '-a', 'android.intent.action.VIEW',
        '-c', 'com.oculus.intent.category.VR_HOME_LAUNCHER',
        '-d', f'http://localhost:{QUEST_APP_PORT}/',
        '-n', 'com.oculus.browser/.OculusLauncherActivity',
    ], XR, 20)
    time.sleep(2.0)


def quest_presence(serial: str, worn: bool) -> dict:
    action = 'com.oculus.vrpowermanager.prox_close' if worn else 'com.oculus.vrpowermanager.prox_far'
    return run([str(ADB), '-s', serial, 'shell', 'am', 'broadcast', '-a', action], XR, 8)


def refocus_quest_browser(serial: str) -> dict:
    return run([
        str(ADB), '-s', serial, 'shell', 'am', 'start',
        '-a', 'android.intent.action.MAIN',
        '-c', 'com.oculus.intent.category.VR_HOME_LAUNCHER',
        '-n', 'com.oculus.browser/.OculusLauncherActivity',
    ], XR, 15)


def recover_quest_browser(serial: str) -> None:
    """Bounded recovery for a wedged Browser/DevTools lifecycle during a presence lease."""
    run([str(ADB), '-s', serial, 'shell', 'am', 'force-stop', 'com.oculus.browser'], XR, 8)
    time.sleep(0.5)
    launch_quest_page()
    run([str(ADB), '-s', serial, 'forward', 'tcp:9222', 'localabstract:chrome_devtools_remote'], XR, 8)
    time.sleep(2.0)


def run_physical_probe(reload_page: bool = False, immersive_smoke: bool = False) -> tuple[dict, dict | None]:
    args = ['node', str(QUEST_PROBE)]
    if reload_page:
        args.append('--reload')
    if immersive_smoke:
        args.append('--immersive-smoke')
    # Node can block in getcwd() under launchd when started inside an active Git worktree.
    # The probe resolves repository paths from import.meta, so use a neutral runtime CWD.
    neutral_cwd = EVIDENCE if EVIDENCE.exists() else Path('/tmp')
    result = run(args, neutral_cwd, 30 if immersive_smoke else 12)
    return result, parse_probe(result)


def persist_physical(payload: dict) -> None:
    EVIDENCE.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = PHYSICAL_LATEST.with_suffix('.tmp')
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + '\n')
    os.chmod(tmp, 0o600)
    tmp.replace(PHYSICAL_LATEST)
    with PHYSICAL_HISTORY.open('a') as history:
        history.write(json.dumps(payload, sort_keys=True) + '\n')
    os.chmod(PHYSICAL_HISTORY, 0o600)


def physical_lane(state: dict, hardware: dict, target_sha: str | None) -> None:
    """Run one bounded unattended Quest trial and always restore proximity state."""
    devices = hardware.get('devices') or []
    if not hardware.get('connected') or len(devices) != 1:
        return
    serial = devices[0].split()[0]
    presence = quest_presence(serial, True)
    if not presence.get('ok'):
        state['physicalAvailability'] = {
            'at': now(), 'sha': target_sha, 'available': False, 'reason': 'presence-lease-failed',
        }
        emit('physical_skipped', **state['physicalAvailability'])
        return
    try:
        run([str(ADB), '-s', serial, 'shell', 'input', 'keyevent', 'KEYCODE_WAKEUP'], XR, 5)
        refocus_quest_browser(serial)
        time.sleep(1.0)
        _physical_lane_active(state, hardware, target_sha)
    finally:
        quest_presence(serial, False)
        emit('quest_presence_restored', serialHash=hardware.get('serialHash'))


def _physical_lane_active(state: dict, hardware: dict, target_sha: str | None) -> None:
    if not hardware.get('connected') or not QUEST_PROBE.exists():
        return
    listener = listener_info()
    if listener.get('pid') is None:
        start_quest_server(state, target_sha)
    elif listener.get('cwd') != str(XR):
        state['physical'] = {'at': now(), 'sha': target_sha, 'ok': False, 'reason': 'port-conflict', **listener}
        emit('physical_port_conflict', **listener)
        return

    result, payload = run_physical_probe(False)
    if payload is None:
        devices = hardware.get('devices') or []
        if len(devices) == 1:
            serial = devices[0].split()[0]
            recover_quest_browser(serial)
            result, payload = run_physical_probe(False)
    reasons = ((payload or {}).get('attribution') or {}).get('reasons') or []
    stale_server = 'served build does not match worktree HEAD' in reasons
    stale_page = any(reason.startswith('running Quest page ') for reason in reasons)
    no_page = 'Quest Browser has no Nemosyne localhost page' in reasons

    if stale_server and git_clean(XR):
        current = listener_info()
        if stop_owned_listener(current):
            start_quest_server(state, target_sha)
            result, payload = run_physical_probe(True)
    elif stale_page:
        result, payload = run_physical_probe(True)
    elif no_page:
        launch_quest_page()
        result, payload = run_physical_probe(False)

    state['physicalAvailability'] = {
        'at': now(), 'sha': target_sha, 'available': True, 'reason': 'bounded-quest-presence-lease',
    }

    runtime_before = (payload or {}).get('runtime') or {}
    attribution_before = (payload or {}).get('attribution') or {}
    if (
        result.get('ok')
        and attribution_before.get('ok')
        and runtime_before.get('vrButton') == 'ENTER VR'
        and runtime_before.get('immersiveVrSupported') is True
        and runtime_before.get('visibilityState') == 'visible'
        and runtime_before.get('hasFocus') is True
    ):
        smoke_result, smoke_payload = run_physical_probe(False, True)
        if smoke_payload is not None:
            result, payload = smoke_result, smoke_payload

    extra = {}
    if payload:
        persist_physical(payload)
        attribution = payload.get('attribution') or {}
        browser = payload.get('browser') or {}
        runtime = payload.get('runtime') or {}
        extra = {
            'attributionOk': bool(attribution.get('ok')),
            'buildId': attribution.get('buildId'),
            'loadedBuildId': attribution.get('loadedBuildId'),
            'sessionLabel': attribution.get('sessionLabel'),
            'pssKb': browser.get('pssKb'),
            'socC': browser.get('socC'),
            'gpuC': browser.get('gpuC'),
            'thermalStatus': browser.get('status'),
            'usedJsHeapBytes': runtime.get('usedJsHeapBytes'),
            'immersiveVrSupported': runtime.get('immersiveVrSupported'),
            'vrButton': runtime.get('vrButton'),
            'immersiveAttempted': bool((payload.get('immersive') or {}).get('attempted')),
            'immersiveEntered': (payload.get('immersive') or {}).get('entered'),
            'immersiveCleanedUp': (payload.get('immersive') or {}).get('cleanedUp'),
        }
    record_lane(state, 'physical', target_sha, result, extra)

    if payload and (payload.get('attribution') or {}).get('ok'):
        runtime = payload.get('runtime') or {}
        sha_note = target_sha or 'unknown-head'
        if runtime.get('immersiveVrSupported') is False:
            submit_packet('Investigate physical Quest WebXR availability regression',
                          f'Exact head {sha_note} reported immersive-vr unavailable on Quest; reproduce before changing product behavior.',
                          str(PHYSICAL_LATEST), state)
        immersive = payload.get('immersive') or {}
        if immersive.get('attempted') is True and immersive.get('entered') is not True:
            submit_packet('Investigate physical Quest immersive XR smoke failure',
                          f'Exact head {sha_note} failed to enter immersive WebXR under the bounded physical smoke; preserve and reproduce the hardware evidence.',
                          str(PHYSICAL_LATEST), state)
        if immersive.get('entered') is True and immersive.get('cleanedUp') is not True:
            submit_packet('Repair physical Quest immersive lifecycle recovery',
                          f'Exact head {sha_note} entered immersive WebXR but did not end the session and recover the Browser task cleanly.',
                          str(PHYSICAL_LATEST), state)

def submit_packet(title: str, objective: str, evidence_ref: str, state: dict) -> None:
    packet_id = hashlib.sha256(f'{title}\0{objective}\0{evidence_ref}'.encode()).hexdigest()[:16]
    seen = set(state.setdefault('submittedPackets', []))
    if packet_id in seen:
        return
    goal = f'Experiment-generated Nemosyne iteration: {title}. {objective} Evidence: {evidence_ref}'
    out = run([sys.executable, str(DELIVERY), 'submit', '--repo', 'TsatsuAmable/nemosyne',
               '--goal', goal, '--authority', 'observe', '--provider', 'local-dispatch'], DELIVERY.parent, 60)
    if out['ok']:
        state['submittedPackets'] = (list(seen) + [packet_id])[-100:]
        emit('work_packet_submitted', packetId=packet_id, title=title, evidence=evidence_ref)


def ingest_xr_packet(state: dict, campaign_root: Path) -> None:
    report = campaign_root / 'test-results/xr-adversarial/latest.json'
    if not report.exists():
        return
    try:
        data = json.loads(report.read_text())
        packet = data.get('nextIteration')
        if not packet:
            return
        submit_packet(packet.get('title', 'Adversarial follow-up'),
                      packet.get('objective', 'Investigate latest adversarial evidence.'),
                      str(report), state)
    except Exception as exc:
        emit('packet_ingest_error', error=str(exc), report=str(report))


def tick() -> dict:
    EVIDENCE.mkdir(parents=True, exist_ok=True, mode=0o700)
    with LOCK.open('w') as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {'status': 'already-running'}
        state = load_state()
        main_sha = git_sha(MAIN)
        xr_sha = git_sha(XR) if XR.exists() else None
        state['heartbeat'] = {'at': now(), 'mainSha': main_sha, 'xrSha': xr_sha}

        hardware = adb_snapshot()
        state['hardware'] = {'at': now(), **hardware}
        emit('hardware_heartbeat', **hardware)

        if due(state, 'physical', PHYSICAL_INTERVAL, xr_sha):
            if hardware.get('connected'):
                physical_lane(state, hardware, xr_sha)
            else:
                state['physicalAvailability'] = {
                    'at': now(), 'sha': xr_sha, 'available': False,
                    'reason': 'device-disconnected',
                }
                emit('physical_skipped', **state['physicalAvailability'])

        if due(state, 'moneta', MONETA_INTERVAL, main_sha):
            result = run(['npm', 'run', 'experiment:moneta-known-structure'], MAIN, 60)
            record_lane(state, 'moneta', main_sha, result)
            if not result['ok']:
                submit_packet('Repair continuous Moneta known-structure campaign',
                              'Restore the exact-generative Rust/WASM benchmark campaign without weakening its oracle.',
                              str(EVENTS), state)

        campaign_root = XR if (XR / 'scripts/run-xr-adversarial-campaign.mjs').exists() else MAIN
        campaign_sha = git_sha(campaign_root)
        simulator_ran = False
        if due(state, 'simulator', SIM_INTERVAL, campaign_sha):
            result = run(['npm', 'run', 'experiment:xr-adversarial'], campaign_root, 90)
            record_lane(state, 'simulator', campaign_sha, result)
            simulator_ran = True
            if not result['ok']:
                submit_packet('Repair continuous XR adversarial campaign',
                              'Diagnose the latest deterministic/stochastic simulator failure and preserve the failing seed as a regression.',
                              str(EVENTS), state)

        semantic_script = campaign_root / 'scripts/run-xr-moneta-semantic-campaign.mjs'
        semantic_ran = False
        if semantic_script.exists() and due(state, 'semantic', SEMANTIC_INTERVAL, campaign_sha):
            result = run(['npm', 'run', 'experiment:xr-moneta-semantic'], campaign_root, 60)
            record_lane(state, 'semantic', campaign_sha, result)
            semantic_ran = True
            if result['ok']:
                report = campaign_root / 'test-results/xr-adversarial/moneta-bound.json'
                if report.exists():
                    try:
                        data = json.loads(report.read_text())
                        packet = data.get('nextIteration')
                        if packet:
                            submit_packet(packet.get('title', 'Semantic adversarial follow-up'),
                                          packet.get('objective', 'Investigate latest semantic adversarial evidence.'),
                                          str(report), state)
                    except Exception as exc:
                        emit('packet_ingest_error', error=str(exc), report=str(report))
            else:
                submit_packet('Repair continuous semantic Moneta XR campaign',
                              'Restore the real-WASM data-to-Moneta-to-semantic-geometry-to-XR adversarial lane.',
                              str(EVENTS), state)

        if simulator_ran and not semantic_script.exists():
            ingest_xr_packet(state, campaign_root)

        save_state(state)
        return state


if __name__ == '__main__':
    try:
        result = tick()
        print(json.dumps(result, indent=2, sort_keys=True))
    except Exception as exc:
        emit('supervisor_error', error=str(exc))
        raise
