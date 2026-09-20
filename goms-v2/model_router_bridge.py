#!/usr/bin/env python3
import os
from functools import lru_cache
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path


class RouterUnavailable(RuntimeError):
    pass


def resolve_router_path():
    explicit = str(os.environ.get("AINEKO_MODEL_ROUTER_PATH") or "").strip()
    if explicit:
        return Path(explicit).expanduser()
    here = Path(__file__).resolve()
    candidates = (
        here.parents[1] / "compute" / "model-routing" / "router.py",
        here.parents[1] / "model-routing" / "router.py",
        Path.home() / "Library" / "Application Support" / "Aineko" / "compute" / "model-routing" / "router.py",
        Path.home() / ".local" / "share" / "exocortex" / "current" / "model-routing" / "router.py",
        Path.home() / "Documents" / "aineko-infrastructure" / "compute" / "model-routing" / "router.py",
    )
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


@lru_cache(maxsize=1)
def _router_module():
    router_path = resolve_router_path()
    if not router_path.exists():
        raise RouterUnavailable(f"shared model router not found: {router_path}")
    spec = spec_from_file_location("aineko_shared_model_router", router_path)
    if spec is None or spec.loader is None:
        raise RouterUnavailable(f"cannot load shared model router: {router_path}")
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def rank_models(prompt, *, family="general", privacy="non_sensitive",
                mode="direct", context=0, threshold=0.65, limit=12):
    task = {
        "prompt": str(prompt),
        "family": str(family),
        "privacy": str(privacy),
        "mode": str(mode),
        "context": int(context or 0),
    }
    rows = _router_module().rank_candidates(task, threshold)
    return rows[:max(1, min(int(limit or 12), 50))]
