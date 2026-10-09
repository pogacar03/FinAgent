"""Manual, allowlisted OpenTelemetry tracing with independent fail-open sinks.

No automatic HTTP/LLM instrumentation: prompts, documents and credentials never
enter a span. ContextVars preserve correlation across asyncio tasks/to_thread.
"""
from __future__ import annotations

import base64
from contextlib import contextmanager
from contextvars import ContextVar
import json
import math
import os
from pathlib import Path
import re
import threading
from typing import Any, Mapping

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (BatchSpanProcessor, SimpleSpanProcessor,
                                           SpanExporter, SpanExportResult)
from opentelemetry.trace import Status, StatusCode

STAGES = ('Task Planning', 'Tool Calling', 'State Management',
          'Evidence Verification', 'Result Expression')
_ALIASES = dict(zip(('Plan', 'Tools', 'State', 'Evidence', 'Output'), STAGES))
_ALIASES.update({'Planning': STAGES[0], 'Tool Execution': STAGES[1],
                 'Result Synthesis': STAGES[4]})
IDS = frozenset({'batch_id', 'run_id', 'ticker', 'snapshot_id', 'checkpoint_id'})
_STRINGS = IDS | frozenset({'status', 'error_code', 'exception_type', 'mode', 'research_mode',
    'model_version', 'graph_version', 'prompt_version', 'snapshot_hash', 'thread_id', 'channel',
    'period', 'recovery_result', 'backtest_status', 'sa_status', 'signal_id', 'tool', 'persona',
    'usage_source'})
_BOOLS = frozenset({'cache_hit', 'resumed', 'eligible', 'frozen', 'llm_called'})
_NUMBERS = frozenset({'attempt', 'attempts', 'retry_count', 'latency_ms', 'llm_latency_ms',
    'prompt_tokens', 'completion_tokens', 'total_tokens', 'persona_count', 'review_rounds',
    'budget_wait_ms', 'concurrency_limit', 'min_interval_seconds', 'count', 'picks', 'cost_usd'})
_METRICS = ('prompt_tokens', 'completion_tokens', 'total_tokens', 'llm_latency_ms', 'cost_usd')
_IDENTIFIER = re.compile(r'[A-Za-z0-9_.:\-]{1,256}\Z')
_SECRET = re.compile(r'(?i)(?:sk-|pk-lf-|bearer|api.?key|authorization|password|secret)')
_correlation: ContextVar[dict[str, Any]] = ContextVar('finagent_trace_correlation', default={})
_instance: Observability | None = None
_lock = threading.RLock()


def safe_attributes(metadata: Mapping[str, Any]) -> dict[str, Any]:
    """Accept typed controlled metadata only, never nested or free-form content."""
    result = {}
    for key, value in metadata.items():
        if key in _STRINGS and isinstance(value, str) and _IDENTIFIER.fullmatch(value) and not _SECRET.search(value):
            result[key] = value
        elif key in _BOOLS and isinstance(value, bool):
            result[key] = value
        elif key in _NUMBERS and isinstance(value, (int, float)) and not isinstance(value, bool):
            if value >= 0 and value <= 1e15 and math.isfinite(value) and (not key.endswith('tokens') or isinstance(value, int)):
                result[key] = value
    return result


def canonical_stage(stage: str) -> str:
    return stage if stage in STAGES else _ALIASES.get(stage, 'State Management')


class JSONLExporter(SpanExporter):
    """SDK ReadableSpans serialized locally; write failures never escape."""
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.failures = 0
        self.exported = 0
        self._lock = threading.Lock()

    def export(self, spans):
        try:
            rows = []
            for span in spans:
                attrs = dict(span.attributes or {})
                rows.append({'name': span.name, 'trace_id': f'{span.context.trace_id:032x}',
                    'span_id': f'{span.context.span_id:016x}',
                    'parent_span_id': f'{span.parent.span_id:016x}' if span.parent else None,
                    'start_time_unix_ns': span.start_time, 'end_time_unix_ns': span.end_time,
                    'duration_ms': (span.end_time - span.start_time) / 1_000_000,
                    'status': span.status.status_code.name, 'attributes': attrs,
                    'llm_metrics': {key: attrs.get(key) for key in _METRICS}})
            with self._lock:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                # Private files: local traces contain controlled identifiers only.
                descriptor = os.open(self.path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
                with os.fdopen(descriptor, 'a', encoding='utf-8') as stream:
                    for row in rows:
                        stream.write(json.dumps(row, sort_keys=True) + '\n')
                self.exported += len(rows)
            return SpanExportResult.SUCCESS
        except Exception:
            self.failures += 1
            return SpanExportResult.FAILURE

    def shutdown(self):
        pass


class QuietOTLPExporter(SpanExporter):
    """Suppress provider errors/logs potentially carrying URLs or credentials.

    The official OTLP exporter may log transport errors. Its requests session is
    adapted to return a sanitized terminal failure on transport/provider failure,
    avoiding raw retry/error logs. Local spans are independently durable.
    """
    def __init__(self, endpoint: str, public: str, secret: str):
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        import requests

        class QuietSession(requests.Session):
            def post(self, *args, **kwargs):
                try:
                    response = super().post(*args, **kwargs)
                    if response.ok:
                        return response
                except Exception:
                    pass
                # Synthetic internal terminal failure, never a success response:
                # the SDK reports FAILURE without printing raw provider details.
                response = requests.Response()
                response.status_code = 400
                response.reason = 'FINAGENT_OBSERVABILITY_UNAVAILABLE'
                response._content = b''
                self.failed = True
                return response

        self.session = QuietSession()
        self.session.failed = False
        auth = base64.b64encode(f'{public}:{secret}'.encode()).decode()
        self.delegate = OTLPSpanExporter(endpoint=endpoint, timeout=2,
            headers={'Authorization': 'Basic ' + auth, 'x-langfuse-ingestion-version': '4'},
            session=self.session)
        self.failures = 0

    def export(self, spans):
        try:
            self.session.failed = False
            result = self.delegate.export(spans)
            if self.session.failed or result != SpanExportResult.SUCCESS:
                self.failures += 1
                return SpanExportResult.FAILURE
            return result
        except Exception:
            self.failures += 1
            return SpanExportResult.FAILURE

    def shutdown(self):
        try:
            self.delegate.shutdown()
        except Exception:
            pass


class Observability:
    def __init__(self, path: str | Path | None = None, *, remote_exporter: SpanExporter | None = None):
        # Resource.create() imports OTEL_RESOURCE_ATTRIBUTES; avoid arbitrary env
        # metadata bypassing the same privacy boundary as span attributes.
        self.provider = TracerProvider(resource=Resource({'service.name': 'finagent-worker'}))
        self.local = JSONLExporter(path or os.getenv('FINAGENT_TRACE_PATH', 'artifacts/traces/worker.jsonl'))
        self.provider.add_span_processor(SimpleSpanProcessor(self.local))
        self.remote = remote_exporter
        self.remote_status = 'DISABLED'
        if self.remote is None and os.getenv('FINAGENT_LANGFUSE_ENABLED', '').lower() == 'true':
            public, secret = os.getenv('LANGFUSE_PUBLIC_KEY'), os.getenv('LANGFUSE_SECRET_KEY')
            if public and secret:
                try:
                    base = os.getenv('LANGFUSE_BASE_URL', 'https://cloud.langfuse.com').rstrip('/')
                    self.remote = QuietOTLPExporter(base + '/api/public/otel/v1/traces', public, secret)
                except Exception:
                    self.remote_status = 'UNAVAILABLE'
            else:
                self.remote_status = 'UNAVAILABLE'
        if self.remote is not None:
            self.provider.add_span_processor(BatchSpanProcessor(self.remote, max_queue_size=256,
                max_export_batch_size=32, schedule_delay_millis=1000, export_timeout_millis=3000))
            self.remote_status = 'CONFIGURED_UNVERIFIED'
        self.tracer = self.provider.get_tracer('finagent.manual', 'phase2-v1')

    @contextmanager
    def trace_scope(self, stage: str, **attributes):
        inherited = _correlation.get()
        safe = safe_attributes({**inherited, **attributes})
        stage = canonical_stage(stage)
        otel_attrs = {**safe, 'finagent.stage': stage, 'langfuse.trace.name': 'FinAgent E2E'}
        for key in IDS:
            if key in safe:
                otel_attrs['langfuse.trace.metadata.' + key] = safe[key]
        if safe.get('run_id'):
            otel_attrs['langfuse.session.id'] = safe['run_id']
        if 'prompt_tokens' in safe:
            otel_attrs['gen_ai.usage.input_tokens'] = safe['prompt_tokens']
        if 'completion_tokens' in safe:
            otel_attrs['gen_ai.usage.output_tokens'] = safe['completion_tokens']
        if safe.get('llm_called') is True or safe.get('usage_source') == 'PROVIDER':
            otel_attrs['langfuse.observation.type'] = 'generation'
            if safe.get('model_version'):
                otel_attrs['gen_ai.request.model'] = safe['model_version']
        if 'cost_usd' in safe:
            otel_attrs['gen_ai.usage.cost'] = safe['cost_usd']
        # Separate setup failures from the business body: never catch the latter
        # as an exporter error or accidentally execute the business body twice.
        try:
            manager = self.tracer.start_as_current_span(stage, attributes=otel_attrs,
                record_exception=False, set_status_on_exception=False)
            span = manager.__enter__()
        except Exception:
            yield current_correlation()
            return
        token = None
        try:
            context = span.get_span_context()
            ids = {key: safe[key] for key in IDS if key in safe}
            ids.update(trace_id=f'{context.trace_id:032x}', span_id=f'{context.span_id:016x}')
            token = _correlation.set(ids)
        except Exception:
            ids = current_correlation()
        try:
            yield dict(ids)
        except BaseException:
            # No exception message/body/stacktrace is recorded.
            try:
                span.set_status(Status(StatusCode.ERROR))
            except Exception:
                pass
            raise
        finally:
            if token is not None:
                _correlation.reset(token)
            try:
                manager.__exit__(None, None, None)
            except Exception:
                pass

    def record_event(self, stage: str, metadata: Mapping[str, Any]) -> dict[str, Any]:
        with self.trace_scope(stage, **safe_attributes(metadata)) as ids:
            return ids

    def flush(self, timeout_millis=3000):
        try:
            return self.provider.force_flush(timeout_millis)
        except Exception:
            return False

    def shutdown(self):
        try:
            self.provider.shutdown()
        except Exception:
            pass


def get_observability() -> Observability:
    global _instance
    with _lock:
        if _instance is None:
            _instance = Observability()
        return _instance


@contextmanager
def trace_scope(stage: str, **attributes):
    try:
        obs = get_observability()
    except Exception:
        yield current_correlation()
        return
    with obs.trace_scope(stage, **attributes) as ids:
        yield ids


def record_event(stage: str, metadata: Mapping[str, Any]) -> dict[str, Any]:
    try:
        return get_observability().record_event(stage, metadata)
    except Exception:
        return current_correlation()


def current_correlation() -> dict[str, Any]:
    return dict(_correlation.get())


def flush(timeout_millis=3000) -> bool:
    try:
        return get_observability().flush(timeout_millis)
    except Exception:
        return False


def shutdown() -> None:
    if _instance is not None:
        _instance.shutdown()
