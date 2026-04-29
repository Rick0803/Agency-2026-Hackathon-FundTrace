# tools/preload.py
# Background warmup for demo-critical Fetch scans.

from __future__ import annotations

import threading
import time
from typing import Any

_LOCK = threading.Lock()
_STATE: dict[str, Any] = {
    "started": False,
    "done": False,
    "error": "",
    "started_at": None,
    "finished_at": None,
}


def _warm_fetch_defaults() -> None:
    from agent.orchestrator import (
        run_fed_entity_count,
        run_way2_scan,
        run_zombie_heuristics,
    )

    try:
        run_zombie_heuristics(
            gov_dependency_threshold=0.70,
            min_fed_total=0.0,
            revenue_cliff_threshold=0.50,
            ceased_cutoff_year=2022,
            filing_window_days=360,
            young_org_years=2,
        )
        run_fed_entity_count()
        run_way2_scan(
            min_fed_total=0.0,
            model_name="ECOD",
            peer_grouping="By entity type + funding band",
        )
        with _LOCK:
            _STATE["done"] = True
            _STATE["finished_at"] = time.time()
    except Exception as exc:
        with _LOCK:
            _STATE["error"] = str(exc)
            _STATE["finished_at"] = time.time()


def start_fetch_preload() -> None:
    """Start the Fetch scan warmup once per Python process."""
    with _LOCK:
        if _STATE["started"]:
            return
        _STATE["started"] = True
        _STATE["started_at"] = time.time()

    thread = threading.Thread(target=_warm_fetch_defaults, name="fetch-preload", daemon=True)
    thread.start()


def fetch_preload_status() -> dict[str, Any]:
    with _LOCK:
        return dict(_STATE)
