#!/usr/bin/env python3
"""Repeatable local DEMO benchmark for serial and bounded stock workers.

This measures deterministic local DEMO execution only. It does not measure an
LLM, production data, investment performance, or cache layers other than the
completed-job idempotency behavior exercised through the HTTP API.
"""
from __future__ import annotations

import argparse
import asyncio
import csv
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import sqlite3
import statistics
import subprocess
import sys
import tempfile
import time
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from fastapi.testclient import TestClient  # noqa: E402

from finagent import agents  # noqa: E402
from finagent.api import create_app  # noqa: E402
from finagent.contracts import VersionBundle, stable_hash  # noqa: E402
from finagent.storage import Store  # noqa: E402
from finagent.worker import Worker  # noqa: E402


SCENARIOS = ("cold_start", "completed_job_cache_reuse", "worker_recovery")
STRATEGIES = (("serial", 1), ("bounded_parallel_3", 3))
REQUEST_BODY: dict[str, Any] = {
    "period": "2025-H2",
    "mode": "DEMO",
    "research_mode": "multi_persona",
    "max_candidates": 10,
    "safety_margin": 0.2,
    "max_per_sector": 4,
    "idempotency_key": "phase2-demo-e2e-benchmark-v1",
}
REQUEST_INPUT_HASH = stable_hash(REQUEST_BODY)
SEMANTIC_INPUT_HASH = stable_hash({k: v for k, v in REQUEST_BODY.items() if k != "idempotency_key"})


def utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def package_version(distribution: str) -> str | None:
    try:
        return importlib.metadata.version(distribution)
    except importlib.metadata.PackageNotFoundError:
        return None


def repository_identity() -> dict[str, Any]:
    def git(*args: str) -> str | None:
        try:
            return subprocess.check_output(
                ["git", *args], cwd=ROOT, text=True, stderr=subprocess.DEVNULL
            ).strip()
        except (OSError, subprocess.CalledProcessError):
            return None

    return {
        "commit": git("rev-parse", "HEAD"),
        "worktree_dirty": git("status", "--porcelain") not in (None, ""),
    }


def source_content_hashes() -> dict[str, Any]:
    """Fingerprint source code even when the worktree has uncommitted edits."""
    files: dict[str, str] = {}
    for dirname in ("backend", "scripts"):
        for path in sorted((ROOT / dirname).rglob("*")):
            if not path.is_file() or "__pycache__" in path.parts or path.suffix not in {".py", ".sh"}:
                continue
            relpath = path.relative_to(ROOT).as_posix()
            files[relpath] = hashlib.sha256(path.read_bytes()).hexdigest()
    return {"files": files, "tree_sha256": stable_hash(files)}


def observability_environment() -> dict[str, Any]:
    remote_enabled = os.getenv("FINAGENT_LANGFUSE_ENABLED", "").lower() == "true"
    credentials_present = bool(os.getenv("LANGFUSE_PUBLIC_KEY")) and bool(os.getenv("LANGFUSE_SECRET_KEY"))
    remote_active = remote_enabled and credentials_present
    base_url = os.getenv("LANGFUSE_BASE_URL", "https://cloud.langfuse.com")
    return {
        "otel_worker_instrumentation": "enabled",
        "local_jsonl_exporter": "enabled",
        "local_trace_path_mode": "CUSTOM" if os.getenv("FINAGENT_TRACE_PATH") else "DEFAULT",
        "langfuse_remote_enabled_flag": remote_enabled,
        "langfuse_credentials_present": credentials_present,
        "langfuse_remote_exporter_configured": remote_active,
        "langfuse_endpoint_hash": stable_hash(base_url.rstrip("/")) if remote_active else None,
    }


def build_metadata() -> dict[str, Any]:
    versions = VersionBundle().model_dump(mode="json")
    source_hashes = source_content_hashes()
    metadata = {
        "benchmark_name": "finagent-local-demo-worker-e2e",
        "benchmark_version": "1",
        "started_at_utc": utc_iso(),
        "status": "RUNNING",
        "data_class": "DEMO_SYNTHETIC",
        "research_mode": "multi_persona",
        "model_version": "deterministic-demo-v1",
        "model_kind": "deterministic DEMO generator; no LLM calls",
        "versions": versions,
        "request_body": REQUEST_BODY,
        "input_hash": REQUEST_INPUT_HASH,
        "semantic_input_hash": SEMANTIC_INPUT_HASH,
        "python": sys.version,
        "python_implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "cpu_count": os.cpu_count(),
        "sqlite_library_version": sqlite3.sqlite_version,
        "dependencies": {
            name: package_version(name)
            for name in (
                "finagent",
                "fastapi",
                "pydantic",
                "sqlalchemy",
                "langgraph",
                "langgraph-checkpoint-sqlite",
                "httpx",
                "opentelemetry-api",
                "opentelemetry-sdk",
                "opentelemetry-exporter-otlp-proto-http",
                "opentelemetry-exporter-otlp-proto-common",
                "opentelemetry-exporter-otlp-common",
                "opentelemetry-exporter-http-transport",
                "opentelemetry-proto",
            )
        },
        "repository": repository_identity(),
        "source_content_hashes": source_hashes["files"],
        "source_tree_sha256": source_hashes["tree_sha256"],
        "observability": observability_environment(),
        "strategies": [
            {"name": name, "worker_concurrency": concurrency}
            for name, concurrency in STRATEGIES
        ],
        "scenario_definitions": {
            "cold_start": "fresh SQLiteStore and native SQLite checkpoint; API submit then actual Worker run_once",
            "completed_job_cache_reuse": "actual completed RUN submitted again with same idempotency key; measures API replay only",
            "worker_recovery": "interrupt after a ticker result is persisted; wait for lease expiry; restart Worker on the same DB/checkpoint",
        },
        "llm_metrics_status": "UNAVAILABLE_DEMO_NO_LLM_CALLS",
        "real_llm_benchmark": "UNVERIFIED",
    }
    metadata["execution_environment_hash"] = stable_hash(
        {
            key: metadata[key]
            for key in (
                "python",
                "platform",
                "machine",
                "sqlite_library_version",
                "dependencies",
                "repository",
                "source_content_hashes",
                "source_tree_sha256",
                "observability",
            )
        }
    )
    return metadata


def new_document(metadata: dict[str, Any]) -> dict[str, Any]:
    return {"metadata": metadata, "observations": [], "failures": [], "summary": {}}


def append_observation(document: dict[str, Any], observation: dict[str, Any]) -> None:
    expected = document["metadata"]["input_hash"]
    if observation.get("input_hash") != expected:
        raise ValueError("OBSERVATION_INPUT_HASH_MISMATCH")
    if observation.get("semantic_input_hash") != document["metadata"]["semantic_input_hash"]:
        raise ValueError("OBSERVATION_SEMANTIC_INPUT_HASH_MISMATCH")
    if observation.get("model_version") != document["metadata"]["model_version"]:
        raise ValueError("OBSERVATION_MODEL_VERSION_MISMATCH")
    observation["llm_latency_ms"] = None
    observation["llm_tokens"] = None
    observation["llm_metrics_status"] = "UNAVAILABLE_DEMO_NO_LLM_CALLS"
    document["observations"].append(observation)


def add_failure(document: dict[str, Any], failure: dict[str, Any]) -> None:
    document["failures"].append(failure)


def _csv_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def persist_document(document: dict[str, Any], json_path: Path, csv_path: Path) -> None:
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_tmp = json_path.with_suffix(json_path.suffix + ".tmp")
    csv_tmp = csv_path.with_suffix(csv_path.suffix + ".tmp")
    json_tmp.write_text(json.dumps(document, indent=2, ensure_ascii=False, sort_keys=True) + "\n")
    fields = sorted({key for row in document["observations"] for key in row})
    with csv_tmp.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows({key: _csv_value(value) for key, value in row.items()} for row in document["observations"])
    json_tmp.replace(json_path)
    csv_tmp.replace(csv_path)


def snapshot_identity(store: Store, run_id: str) -> tuple[dict[str, str], str]:
    universe = store.artifact(run_id + ":universe")
    if not universe:
        return {}, stable_hash({})
    by_ticker: dict[str, str] = {}
    for member in universe.get("members", []):
        ticker = member["ticker"]
        item = store.artifact(run_id + ":input:" + ticker)
        if item:
            evidence = item.get("evidence", {})
            by_ticker[ticker] = evidence.get("content_hash", "MISSING")
    by_ticker = dict(sorted(by_ticker.items()))
    return by_ticker, stable_hash(by_ticker)


def checkpoint_ids_by_ticker(store: Store, run_id: str) -> dict[str, list[str]]:
    checkpoints: dict[str, set[str]] = {}
    for event in store.events(run_id):
        metadata = event["metadata"]
        ticker = metadata.get("ticker")
        checkpoint_id = metadata.get("checkpoint_id")
        if ticker and checkpoint_id:
            checkpoints.setdefault(ticker, set()).add(checkpoint_id)
    return {ticker: sorted(ids) for ticker, ids in sorted(checkpoints.items())}


def _store_paths(root: Path) -> tuple[Store, Path]:
    store = Store("sqlite:///" + str(root / "app.db"))
    checkpoint = root / "checkpoints.db"
    return store, checkpoint


def _submit(client: TestClient) -> dict[str, Any]:
    response = client.post("/api/runs", json=REQUEST_BODY)
    if response.status_code != 202:
        raise RuntimeError(f"API_SUBMIT_FAILED_{response.status_code}")
    return response.json()


def _assert_completed(client: TestClient, run_id: str) -> dict[str, Any]:
    run = client.get("/api/runs/" + run_id).json()
    if run.get("status") != "COMPLETED":
        raise RuntimeError("DEMO_WORKER_DID_NOT_COMPLETE")
    if run.get("payload", {}).get("research_mode") != "multi_persona":
        raise RuntimeError("UNEXPECTED_RESEARCH_MODE")
    return run


def _base_observation(scenario: str, strategy: str, concurrency: int, repetition: int) -> dict[str, Any]:
    return {
        "scenario": scenario,
        "strategy": strategy,
        "worker_concurrency": concurrency,
        "research_mode": "multi_persona",
        "repetition": repetition,
        "input_hash": REQUEST_INPUT_HASH,
        "semantic_input_hash": SEMANTIC_INPUT_HASH,
        "model_version": "deterministic-demo-v1",
        "wall_time_ms": None,
        "status": "FAILED",
    }


async def cold_start_trial(strategy: str, concurrency: int, repetition: int) -> dict[str, Any]:
    record = _base_observation("cold_start", strategy, concurrency, repetition)
    started = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="finagent-benchmark-cold-") as temp:
        root = Path(temp)
        store, checkpoint = _store_paths(root)
        app = create_app(store)
        with TestClient(app) as client:
            submission = _submit(client)
            record["run_id"] = submission["run_id"]
            record["submitted_status"] = submission["status"]
            work_started = time.perf_counter()
            worker = Worker(store, checkpoint_url=str(checkpoint), concurrency=concurrency)
            await worker.run_once()
            record["worker_wall_time_ms"] = round((time.perf_counter() - work_started) * 1000, 3)
            _assert_completed(client, submission["run_id"])
            hashes, hashes_digest = snapshot_identity(store, submission["run_id"])
            record["source_snapshot_hashes_by_ticker"] = hashes
            record["source_snapshot_hashes_digest"] = hashes_digest
            record["checkpoint_ids_by_ticker"] = checkpoint_ids_by_ticker(store, submission["run_id"])
            record["persisted_research_count"] = len(store.research(submission["run_id"]))
            record["worker_attempts"] = store.get(submission["run_id"])["attempts"]
            record["status"] = "COMPLETED"
    record["wall_time_ms"] = round((time.perf_counter() - started) * 1000, 3)
    record["timing_scope"] = "fresh store/checkpoint initialization + HTTP API submission + actual Worker execution + status verification"
    return record


async def cache_reuse_trial(strategy: str, concurrency: int, repetition: int) -> dict[str, Any]:
    record = _base_observation("completed_job_cache_reuse", strategy, concurrency, repetition)
    setup_started = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="finagent-benchmark-cache-") as temp:
        root = Path(temp)
        store, checkpoint = _store_paths(root)
        app = create_app(store)
        with TestClient(app) as client:
            original = _submit(client)
            worker = Worker(store, checkpoint_url=str(checkpoint), concurrency=concurrency)
            await worker.run_once()
            _assert_completed(client, original["run_id"])
            original_hashes, original_digest = snapshot_identity(store, original["run_id"])
            record["preparation_wall_time_ms"] = round((time.perf_counter() - setup_started) * 1000, 3)

            replay_started = time.perf_counter()
            replay = _submit(client)
            record["wall_time_ms"] = round((time.perf_counter() - replay_started) * 1000, 3)
            replay_run = _assert_completed(client, replay["run_id"])
            replay_hashes, replay_digest = snapshot_identity(store, replay["run_id"])
            record["original_completed_job_id"] = original["run_id"]
            record["replayed_job_id"] = replay["run_id"]
            record["same_completed_job_reused"] = original["run_id"] == replay["run_id"]
            record["replay_status"] = replay["status"]
            record["completed_result_present"] = bool(replay_run.get("result"))
            record["source_snapshot_hashes_by_ticker"] = original_hashes
            record["source_snapshot_hashes_digest"] = original_digest
            record["replayed_snapshot_hashes_digest"] = replay_digest
            record["checkpoint_ids_by_ticker"] = checkpoint_ids_by_ticker(store, original["run_id"])
            record["snapshot_identity_unchanged"] = original_digest == replay_digest and original_hashes == replay_hashes
            record["worker_attempts"] = store.get(original["run_id"])["attempts"]
            record["status"] = "COMPLETED" if record["same_completed_job_reused"] and record["snapshot_identity_unchanged"] else "FAILED"
    record["timing_scope"] = "second HTTP API submission returning the same already-COMPLETED idempotent job; excludes first execution setup"
    return record


async def worker_recovery_trial(strategy: str, concurrency: int, repetition: int) -> dict[str, Any]:
    record = _base_observation("worker_recovery", strategy, concurrency, repetition)
    scenario_started = time.perf_counter()
    original_research_stock = agents.research_stock
    first_ticker: str | None = None
    blocked_tickers: list[str] = []
    resumed_tickers: list[str] = []
    never_release = asyncio.Event()

    async def interrupted_research(input_, *args, **kwargs):
        nonlocal first_ticker
        if first_ticker is None:
            first_ticker = input_.ticker
            return await original_research_stock(input_, *args, **kwargs)
        blocked_tickers.append(input_.ticker)
        await never_release.wait()
        return await original_research_stock(input_, *args, **kwargs)

    async def resumed_research(input_, *args, **kwargs):
        resumed_tickers.append(input_.ticker)
        return await original_research_stock(input_, *args, **kwargs)

    agents.research_stock = interrupted_research
    try:
        with tempfile.TemporaryDirectory(prefix="finagent-benchmark-recovery-") as temp:
            root = Path(temp)
            store, checkpoint = _store_paths(root)
            app = create_app(store)
            with TestClient(app) as client:
                submission = _submit(client)
                run_id = submission["run_id"]
                record["run_id"] = run_id
                first_worker = Worker(store, checkpoint_url=str(checkpoint), concurrency=concurrency, lease_seconds=0.3)
                first_attempt_started = time.perf_counter()
                interrupted_task = asyncio.create_task(first_worker.run_once())
                deadline = time.monotonic() + 45
                while time.monotonic() < deadline:
                    if first_ticker and blocked_tickers and store.research(run_id, first_ticker):
                        break
                    if interrupted_task.done():
                        await interrupted_task
                        raise RuntimeError("WORKER_FINISHED_BEFORE_RECOVERY_INJECTION")
                    await asyncio.sleep(0.005)
                else:
                    interrupted_task.cancel()
                    await asyncio.gather(interrupted_task, return_exceptions=True)
                    raise RuntimeError("RECOVERY_INJECTION_TIMEOUT")

                retained = store.research(run_id)
                retained_tickers = sorted(result["ticker"] for result in retained)
                record["retained_tickers_before_restart"] = retained_tickers
                record["retained_count_before_restart"] = len(retained_tickers)
                record["interrupted_tickers_entered"] = sorted(set(blocked_tickers))
                record["checkpoint_ids_before_restart_by_ticker"] = checkpoint_ids_by_ticker(store, run_id)
                record["interrupt_worker_status"] = store.get(run_id)["status"]
                record["interrupted_attempt_wall_time_ms"] = round((time.perf_counter() - first_attempt_started) * 1000, 3)

                interrupted_task.cancel()
                await asyncio.gather(interrupted_task, return_exceptions=True)
                lease_row = store.get(run_id)
                if lease_row["status"] != "RUNNING" or not lease_row["lease_until"]:
                    raise RuntimeError("INTERRUPTED_WORKER_DID_NOT_LEAVE_ACTIVE_LEASE")
                lease_wait_started = time.perf_counter()
                remaining = max(0.0, lease_row["lease_until"] - time.time() + 0.02)
                await asyncio.sleep(remaining)
                record["lease_wait_ms"] = round((time.perf_counter() - lease_wait_started) * 1000, 3)
                record["lease_wait_seconds_requested"] = round(remaining, 4)

                agents.research_stock = resumed_research
                restart_store = Store(store.url)
                restarted_worker = Worker(restart_store, checkpoint_url=str(checkpoint), concurrency=concurrency)
                recovery_started = time.perf_counter()
                worked = await restarted_worker.run_once()
                record["restart_recovery_wall_time_ms"] = round((time.perf_counter() - recovery_started) * 1000, 3)
                if not worked:
                    raise RuntimeError("RESTARTED_WORKER_CLAIM_FAILED")
                _assert_completed(client, run_id)
                after = restart_store.research(run_id)
                after_tickers = sorted(result["ticker"] for result in after)
                hashes, hashes_digest = snapshot_identity(restart_store, run_id)
                record["recovery_redone_tickers"] = resumed_tickers
                record["retained_tickers_after_restart"] = after_tickers
                record["retained_count_after_restart"] = len(after_tickers)
                record["redone_count"] = len(resumed_tickers)
                record["worker_attempts"] = restart_store.get(run_id)["attempts"]
                record["source_snapshot_hashes_by_ticker"] = hashes
                record["source_snapshot_hashes_digest"] = hashes_digest
                record["checkpoint_ids_after_restart_by_ticker"] = checkpoint_ids_by_ticker(restart_store, run_id)
                record["recovery_integrity_verified"] = (
                    first_ticker in retained_tickers
                    and not set(retained_tickers).intersection(resumed_tickers)
                    and set(after_tickers) == set(retained_tickers).union(resumed_tickers)
                    and len(after_tickers) == 10
                    and restart_store.get(run_id)["attempts"] == 2
                )
                record["status"] = "COMPLETED" if record["recovery_integrity_verified"] else "FAILED"
    finally:
        agents.research_stock = original_research_stock
    record["wall_time_ms"] = round((time.perf_counter() - scenario_started) * 1000, 3)
    record["timing_scope"] = "fresh store + API submission + actual interrupted Worker, lease expiry wait, new Store/Worker and completed recovery"
    return record


def summarize(observations: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for row in observations:
        grouped.setdefault(row["scenario"], {}).setdefault(row["strategy"], []).append(row)
    summary: dict[str, Any] = {"by_scenario_and_strategy": {}, "serial_vs_bounded": {}}
    for scenario in SCENARIOS:
        summary["by_scenario_and_strategy"][scenario] = {}
        for strategy, _ in STRATEGIES:
            rows = [r for r in grouped.get(scenario, {}).get(strategy, []) if r.get("status") == "COMPLETED"]
            values = [r["wall_time_ms"] for r in rows if isinstance(r.get("wall_time_ms"), (int, float))]
            item: dict[str, Any] = {
                "completed_repetitions": len(rows),
                "wall_time_ms_median": round(statistics.median(values), 3) if values else None,
                "wall_time_ms_min": round(min(values), 3) if values else None,
                "wall_time_ms_max": round(max(values), 3) if values else None,
                "interpretation": "DEMO-only descriptive observation; not an LLM or investment-performance metric",
            }
            if scenario == "worker_recovery":
                recovery_times = [r["restart_recovery_wall_time_ms"] for r in rows if r.get("restart_recovery_wall_time_ms") is not None]
                lease_waits = [r["lease_wait_ms"] for r in rows if r.get("lease_wait_ms") is not None]
                item["restart_recovery_ms_median"] = round(statistics.median(recovery_times), 3) if recovery_times else None
                item["lease_wait_ms_median"] = round(statistics.median(lease_waits), 3) if lease_waits else None
                item["retained_count_before_restart"] = [r.get("retained_count_before_restart") for r in rows]
                item["redone_count"] = [r.get("redone_count") for r in rows]
            summary["by_scenario_and_strategy"][scenario][strategy] = item
        serial = summary["by_scenario_and_strategy"][scenario]["serial"]
        bounded = summary["by_scenario_and_strategy"][scenario]["bounded_parallel_3"]
        if serial["wall_time_ms_median"] is None or bounded["wall_time_ms_median"] is None:
            summary["serial_vs_bounded"][scenario] = {"comparison_status": "INCOMPLETE"}
        else:
            serial_ms = serial["wall_time_ms_median"]
            bounded_ms = bounded["wall_time_ms_median"]
            summary["serial_vs_bounded"][scenario] = {
                "comparison_status": "OBSERVED_DEMO_ONLY",
                "serial_median_ms": serial_ms,
                "bounded_parallel_3_median_ms": bounded_ms,
                "serial_minus_bounded_median_ms": round(serial_ms - bounded_ms, 3),
                "serial_median_divided_by_bounded_median": round(serial_ms / bounded_ms, 4) if bounded_ms else None,
            }
    return summary


async def run_benchmark(repeats: int, output_dir: Path) -> dict[str, Any]:
    if repeats < 3:
        raise ValueError("REPEATS_MUST_BE_AT_LEAST_3")
    metadata = build_metadata()
    document = new_document(metadata)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    json_path = output_dir / f"phase2_demo_benchmark_{stamp}.json"
    csv_path = output_dir / f"phase2_demo_benchmark_{stamp}.csv"
    document["artifact_paths"] = {"json": str(json_path), "csv": str(csv_path)}
    persist_document(document, json_path, csv_path)

    for scenario in SCENARIOS:
        for repetition in range(1, repeats + 1):
            # Alternate pair order by repetition to avoid always giving one strategy the same warm/cold host position.
            order = STRATEGIES if repetition % 2 else tuple(reversed(STRATEGIES))
            for strategy, concurrency in order:
                print(f"RUN {scenario} {strategy} repetition={repetition}/{repeats}", flush=True)
                try:
                    if scenario == "cold_start":
                        observation = await cold_start_trial(strategy, concurrency, repetition)
                    elif scenario == "completed_job_cache_reuse":
                        observation = await cache_reuse_trial(strategy, concurrency, repetition)
                    else:
                        observation = await worker_recovery_trial(strategy, concurrency, repetition)
                    append_observation(document, observation)
                    if observation["status"] != "COMPLETED":
                        add_failure(document, {
                            "scenario": scenario,
                            "strategy": strategy,
                            "repetition": repetition,
                            "code": "OBSERVATION_VALIDATION_FAILED",
                        })
                except Exception as exc:
                    add_failure(document, {
                        "scenario": scenario,
                        "strategy": strategy,
                        "repetition": repetition,
                        "input_hash": REQUEST_INPUT_HASH,
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                    })
                document["summary"] = summarize(document["observations"])
                persist_document(document, json_path, csv_path)

    required = repeats * len(SCENARIOS) * len(STRATEGIES)
    all_completed = len(document["observations"]) == required and all(r["status"] == "COMPLETED" for r in document["observations"])
    document["metadata"]["completed_at_utc"] = utc_iso()
    document["metadata"]["repetitions_per_scenario_strategy"] = repeats
    document["metadata"]["expected_observation_count"] = required
    document["metadata"]["status"] = "PASSED" if all_completed and not document["failures"] else "PARTIAL"
    document["summary"] = summarize(document["observations"])
    document["summary"]["raw_observation_count"] = len(document["observations"])
    document["summary"]["failure_count"] = len(document["failures"])
    document["summary"]["benchmark_claim_scope"] = "DEMO implementation throughput/replay/recovery only; real LLM performance UNVERIFIED"
    persist_document(document, json_path, csv_path)
    document["artifact_paths"] = {"json": str(json_path), "csv": str(csv_path)}
    print(json.dumps({
        "status": document["metadata"]["status"],
        "observation_count": len(document["observations"]),
        "failure_count": len(document["failures"]),
        "json": str(json_path),
        "csv": str(csv_path),
        "summary": document["summary"],
    }, ensure_ascii=False, indent=2), flush=True)
    return document


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeats", type=int, default=3, help="per scenario/strategy; minimum 3")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "docs" / "benchmark_results",
        help="directory for timestamped JSON and CSV raw observations",
    )
    args = parser.parse_args()
    if args.repeats < 3:
        parser.error("--repeats must be at least 3")
    document = asyncio.run(run_benchmark(args.repeats, args.output_dir))
    return 0 if document["metadata"]["status"] == "PASSED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
