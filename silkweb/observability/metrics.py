from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any

from ..config import SilkwebConfig, get_config

_LOCK = threading.Lock()
_STARTED = False


class _Noop:
    def labels(self, **_kwargs: Any):
        return self

    def inc(self, _n: float = 1.0) -> None:
        return

    def observe(self, _v: float) -> None:
        return


@dataclass(frozen=True, slots=True)
class Metrics:
    requests_total: Any
    request_duration_seconds: Any
    llm_calls_total: Any
    llm_duration_seconds: Any
    cache_hits_total: Any
    blocks_total: Any


_NOOP_METRICS = Metrics(
    requests_total=_Noop(),
    request_duration_seconds=_Noop(),
    llm_calls_total=_Noop(),
    llm_duration_seconds=_Noop(),
    cache_hits_total=_Noop(),
    blocks_total=_Noop(),
)

_METRICS: Metrics | None = None


def _build_metrics() -> Metrics:
    try:
        from prometheus_client import Counter, Histogram  # type: ignore
    except Exception:
        return _NOOP_METRICS

    return Metrics(
        requests_total=Counter(
            "silkweb_requests_total",
            "Total number of fetch requests.",
            labelnames=("tier", "status", "domain"),
        ),
        request_duration_seconds=Histogram(
            "silkweb_request_duration_seconds",
            "Fetch duration in seconds.",
            labelnames=("tier", "domain"),
        ),
        llm_calls_total=Counter(
            "silkweb_llm_calls_total",
            "Total number of LLM calls.",
            labelnames=("model", "task"),
        ),
        llm_duration_seconds=Histogram(
            "silkweb_llm_duration_seconds",
            "LLM call duration in seconds.",
            labelnames=("model", "task"),
        ),
        cache_hits_total=Counter(
            "silkweb_cache_hits_total",
            "Cache hits by layer.",
            labelnames=("layer",),
        ),
        blocks_total=Counter(
            "silkweb_blocks_total",
            "Detected blocks/challenges.",
            labelnames=("domain", "challenge_type"),
        ),
    )


def get_metrics() -> Metrics:
    global _METRICS
    if _METRICS is None:
        _METRICS = _build_metrics()
    return _METRICS


def ensure_metrics_server(cfg: SilkwebConfig | None = None) -> None:
    """
    Start Prometheus HTTP server if config.metrics_port is set.
    Safe to call many times.
    """
    global _STARTED
    cfg = cfg or get_config()
    port = cfg.metrics_port
    if not port:
        return

    with _LOCK:
        if _STARTED:
            return
        try:
            from prometheus_client import start_http_server  # type: ignore
        except Exception:
            return
        start_http_server(int(port))
        _STARTED = True


class Timer:
    def __init__(self) -> None:
        self._start = time.perf_counter()

    def seconds(self) -> float:
        return max(0.0, time.perf_counter() - self._start)
