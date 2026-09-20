#!/bin/sh
set -eu

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
cd "$ROOT"

python3 scripts/reconstruction_check.py
python3 -m unittest -q test_exocortex_deploy.py
python3 compute/model-routing/test_router.py

if [ -x "$HOME/.hermes/hermes-agent/venv/bin/python" ]; then
  "$HOME/.hermes/hermes-agent/venv/bin/python" -m unittest -q hermes/test_install_profile.py
else
  echo "NOTE: Hermes Python unavailable; skipping profile installer regression" >&2
fi

if [ -x "goms-v2/.venv/bin/python" ]; then
  (
    cd goms-v2
    .venv/bin/python -m unittest -q \
      test_model_router_bridge.py \
      test_distillation_worker_pool.py \
      test_distillation_evidence_review.py \
      test_distillation_rewrite_repair.py \
      test_distillation_semantic_daemon.py \
      test_storage_governor.py \
      test_hermes_goms_config.py \
      test_hermes_authority.py \
      test_hermes_capability_graph.py \
      test_hermes_route_selector.py
  )
else
  echo "NOTE: goms-v2/.venv unavailable; run 'cd goms-v2 && uv sync' for full GOMS contract tests" >&2
fi

echo "verify-reconstruction: OK"
