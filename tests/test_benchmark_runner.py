"""Integrity checks for the local DEMO benchmark's inputs and raw artifacts."""
import csv
import json

import pytest

from scripts.benchmark_e2e import (
    REQUEST_BODY,
    REQUEST_INPUT_HASH,
    SEMANTIC_INPUT_HASH,
    add_failure,
    append_observation,
    new_document,
    persist_document,
    build_metadata,
    _base_observation,
)
from finagent.contracts import stable_hash


def _document():
    metadata = build_metadata()
    metadata["input_hash"] = REQUEST_INPUT_HASH
    metadata["semantic_input_hash"] = SEMANTIC_INPUT_HASH
    return new_document(metadata)


def test_benchmark_input_hash_is_stable_for_all_worker_strategies():
    serial = _base_observation("cold_start", "serial", 1, 1)
    bounded = _base_observation("cold_start", "bounded_parallel_3", 3, 1)
    assert serial["input_hash"] == bounded["input_hash"] == REQUEST_INPUT_HASH
    assert serial["semantic_input_hash"] == bounded["semantic_input_hash"] == SEMANTIC_INPUT_HASH
    assert serial["model_version"] == bounded["model_version"] == "deterministic-demo-v1"
    assert REQUEST_INPUT_HASH == _document()["metadata"]["input_hash"]
    assert SEMANTIC_INPUT_HASH == _document()["metadata"]["semantic_input_hash"]


def test_rejects_observation_with_different_input_or_model():
    document = _document()
    row = {
        "scenario": "cold_start",
        "strategy": "serial",
        "input_hash": "different-input",
        "semantic_input_hash": SEMANTIC_INPUT_HASH,
        "model_version": "deterministic-demo-v1",
    }
    with pytest.raises(ValueError, match="OBSERVATION_INPUT_HASH_MISMATCH"):
        append_observation(document, row)

    row["input_hash"] = REQUEST_INPUT_HASH
    row["model_version"] = "different-model"
    with pytest.raises(ValueError, match="OBSERVATION_MODEL_VERSION_MISMATCH"):
        append_observation(document, row)


def test_persists_observation_and_failure_to_json_and_csv(tmp_path):
    document = _document()
    append_observation(document, {
        "scenario": "cold_start",
        "strategy": "serial",
        "worker_concurrency": 1,
        "repetition": 1,
        "input_hash": REQUEST_INPUT_HASH,
        "semantic_input_hash": SEMANTIC_INPUT_HASH,
        "model_version": "deterministic-demo-v1",
        "wall_time_ms": 12.5,
        "llm_latency_ms": 999,
        "llm_tokens": 10,
        "status": "COMPLETED",
    })
    add_failure(document, {
        "scenario": "worker_recovery",
        "strategy": "bounded_parallel_3",
        "repetition": 2,
        "input_hash": REQUEST_INPUT_HASH,
        "error_type": "RuntimeError",
        "error": "RECOVERY_INJECTION_TIMEOUT",
    })
    document["metadata"]["status"] = "PARTIAL"
    json_path = tmp_path / "raw.json"
    csv_path = tmp_path / "raw.csv"
    persist_document(document, json_path, csv_path)

    saved = json.loads(json_path.read_text())
    assert saved["metadata"]["status"] == "PARTIAL"
    assert saved["failures"][0]["error"] == "RECOVERY_INJECTION_TIMEOUT"
    assert saved["observations"][0]["llm_latency_ms"] is None
    assert saved["observations"][0]["llm_tokens"] is None
    with csv_path.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == 1
    assert rows[0]["input_hash"] == REQUEST_INPUT_HASH
    assert rows[0]["wall_time_ms"] == "12.5"


def test_request_has_fixed_multi_persona_demo_identity():
    assert REQUEST_BODY["mode"] == "DEMO"
    assert REQUEST_BODY["research_mode"] == "multi_persona"
    assert REQUEST_BODY["idempotency_key"]
    assert REQUEST_BODY["max_candidates"] == 10


def test_environment_identity_contains_otlp_versions_and_source_hashes():
    metadata = build_metadata()
    assert metadata["dependencies"]["opentelemetry-sdk"]
    assert metadata["dependencies"]["opentelemetry-exporter-otlp-proto-http"]
    assert "backend/finagent/worker.py" in metadata["source_content_hashes"]
    assert "scripts/benchmark_e2e.py" in metadata["source_content_hashes"]
    assert metadata["observability"]["otel_worker_instrumentation"] == "enabled"
    assert "LANGFUSE_SECRET_KEY" not in json.dumps(metadata)
    assert metadata["execution_environment_hash"] == stable_hash({
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
    })
