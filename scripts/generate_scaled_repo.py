"""Generator for realistic multi-module software repository fixture (scaled_repo)."""

import os
import subprocess
from pathlib import Path

BASE_DIR = Path("/lifecore-swe/fixtures/scaled_repo")
BASE_DIR.mkdir(parents=True, exist_ok=True)

# 1. pyproject.toml
(BASE_DIR / "pyproject.toml").write_text("""[build-system]
requires = ["setuptools>=61.0"]
build-backend = "setuptools.build_meta"

[project]
name = "hydra-mesh"
version = "0.2.0"
description = "Scalable telemetry event pipeline and distributed mesh processing"
requires-python = ">=3.12"
dependencies = []

[tool.pytest.ini_options]
pythonpath = ["."]
testpaths = ["tests"]
""", encoding="utf-8")

# Package subdirectories
subpackages = ["core", "ingest", "pipeline", "storage", "connectors", "utils", "tests"]
for sp in subpackages:
    (BASE_DIR / "hydra_mesh" / sp if sp != "tests" else BASE_DIR / "tests").mkdir(parents=True, exist_ok=True)

# Create __init__.py for root
(BASE_DIR / "hydra_mesh" / "__init__.py").write_text('"""HydraMesh distributed telemetry framework."""\n__version__ = "0.2.0"\n', encoding="utf-8")

# Helper to create python files
def make_file(rel_path, content):
    p = BASE_DIR / rel_path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content.strip() + "\n", encoding="utf-8")

# ==================== CORE (10 files) ====================
make_file("hydra_mesh/core/__init__.py", '"""Core abstractions."""\nfrom .base import MeshEntity\nfrom .config import MeshConfig\n')
make_file("hydra_mesh/core/base.py", """
from dataclasses import dataclass, field
from typing import Dict, Any

@dataclass
class MeshEntity:
    entity_id: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    def validate(self) -> bool:
        return bool(self.entity_id)
""")
make_file("hydra_mesh/core/config.py", """
from dataclasses import dataclass

@dataclass
class MeshConfig:
    buffer_capacity: int = 100
    rate_limit: int = 10
    burst_allowance: int = 5
    strip_sensitive_headers: bool = True
""")
make_file("hydra_mesh/core/context.py", """
from typing import Optional

class MeshContext:
    def __init__(self, trace_id: str, tenant_id: Optional[str] = None):
        self.trace_id = trace_id
        self.tenant_id = tenant_id or "default"
""")
make_file("hydra_mesh/core/dispatcher.py", """
from typing import Callable, Dict, List

class EventDispatcher:
    def __init__(self):
        self.handlers: Dict[str, List[Callable]] = {}
    def register(self, event_type: str, handler: Callable):
        self.handlers.setdefault(event_type, []).append(handler)
    def dispatch(self, event_type: str, payload: dict):
        for h in self.handlers.get(event_type, []):
            h(payload)
""")
make_file("hydra_mesh/core/exceptions.py", """
class MeshError(Exception): pass
class SchemaError(MeshError): pass
class BufferOverflowError(MeshError): pass
class RateLimitExceeded(MeshError): pass
class ConnectionError(MeshError): pass
""")
make_file("hydra_mesh/core/interfaces.py", """
from abc import ABC, abstractmethod

class ReceiverInterface(ABC):
    @abstractmethod
    def receive(self, data: bytes) -> dict: pass

class SinkInterface(ABC):
    @abstractmethod
    def send(self, payload: dict) -> bool: pass
""")
make_file("hydra_mesh/core/logger.py", """
class MeshLogger:
    def __init__(self, name: str): self.name = name
    def info(self, msg: str): pass
    def warning(self, msg: str): pass
    def error(self, msg: str): pass
""")
make_file("hydra_mesh/core/protocols.py", """
from typing import Protocol

class Serializable(Protocol):
    def serialize(self) -> str: ...
""")
make_file("hydra_mesh/core/registry.py", """
from typing import Any, Dict

class ComponentRegistry:
    def __init__(self): self._reg: Dict[str, Any] = {}
    def register(self, name: str, comp: Any): self._reg[name] = comp
    def get(self, name: str) -> Any: return self._reg.get(name)
""")
make_file("hydra_mesh/core/serializer.py", """
import json

class JsonSerializer:
    @staticmethod
    def dumps(obj: dict) -> str: return json.dumps(obj)
    @staticmethod
    def loads(s: str) -> dict: return json.loads(s)
""")

# ==================== INGEST (8 files) ====================
make_file("hydra_mesh/ingest/__init__.py", '"""Ingestion package."""\nfrom .rate_limiter import SlidingWindowLimiter\n')
make_file("hydra_mesh/ingest/rate_limiter.py", """
import time
from typing import Dict, List
from ..core.exceptions import RateLimitExceeded

class SlidingWindowLimiter:
    \"\"\"Limits requests based on window seconds, threshold, and burst capacity.\"\"\"
    def __init__(self, max_requests: int = 10, burst_allowance: int = 5, window_seconds: float = 60.0):
        self.max_requests = max_requests
        self.burst_allowance = burst_allowance
        self.window_seconds = window_seconds
        self.history: Dict[str, List[float]] = {}

    def allow_request(self, client_id: str, timestamp: float) -> bool:
        \"\"\"Evaluate whether client is permitted to make a request.\"\"\"
        window_start = timestamp - self.window_seconds
        timestamps = self.history.setdefault(client_id, [])
        # Prune expired
        self.history[client_id] = [t for t in timestamps if t >= window_start]
        current_count = len(self.history[client_id])
        
        # BUG FOR TASK-201:
        # Strict equality drops request when count reaches max_requests, even if burst_allowance allows extra!
        # Should check: current_count < (self.max_requests + self.burst_allowance)
        limit = self.max_requests  # Erroneously ignores burst_allowance!
        if current_count < limit:
            self.history[client_id].append(timestamp)
            return True
        return False
""")
make_file("hydra_mesh/ingest/batcher.py", """
from typing import List

class EventBatcher:
    def __init__(self, max_batch_size: int = 50):
        self.max_batch_size = max_batch_size
        self.current_batch: List[dict] = []
    def add(self, event: dict) -> bool:
        if len(self.current_batch) >= self.max_batch_size:
            return False
        self.current_batch.append(event)
        return True
    def flush(self) -> List[dict]:
        b = list(self.current_batch)
        self.current_batch.clear()
        return b
""")
make_file("hydra_mesh/ingest/decoders.py", """
import json

class FrameDecoder:
    def decode(self, payload: bytes) -> dict:
        return json.loads(payload.decode("utf-8"))
""")
make_file("hydra_mesh/ingest/filters.py", """
class IngestFilter:
    def filter_blacklisted(self, client_ip: str, blacklist: set) -> bool:
        return client_ip not in blacklist
""")
make_file("hydra_mesh/ingest/receivers.py", """
from .decoders import FrameDecoder

class NetworkReceiver:
    def __init__(self):
        self.decoder = FrameDecoder()
    def handle_incoming(self, raw: bytes) -> dict:
        return self.decoder.decode(raw)
""")
make_file("hydra_mesh/ingest/sanitizers.py", """
class InputSanitizer:
    @staticmethod
    def clean_text(text: str) -> str:
        return text.strip().replace("\\x00", "")
""")
make_file("hydra_mesh/ingest/validator.py", """
class PayloadValidator:
    @staticmethod
    def validate_schema(payload: dict, required_keys: set) -> bool:
        return required_keys.issubset(payload.keys())
""")

# ==================== PIPELINE (8 files) ====================
make_file("hydra_mesh/pipeline/__init__.py", '"""Pipeline package."""\nfrom .transformer import EventTransformer\n')
make_file("hydra_mesh/pipeline/dead_letter.py", """
from typing import List, Dict, Any

class DeadLetterQueue:
    \"\"\"Stores failed events for inspection and replay.\"\"\"
    def __init__(self):
        self.failed_events: List[Dict[str, Any]] = []

    def route(self, event: dict, reason: str):
        self.failed_events.append({"event": event, "reason": reason})

    def count(self) -> int:
        return len(self.failed_events)
""")
make_file("hydra_mesh/pipeline/transformer.py", """
from typing import Dict, Any, Optional
from ..core.exceptions import SchemaError
from .dead_letter import DeadLetterQueue

class EventTransformer:
    \"\"\"Applies schema validation and enrichment to incoming events.\"\"\"
    def __init__(self, dlq: Optional[DeadLetterQueue] = None):
        self.dead_letter = dlq or DeadLetterQueue()

    def transform_event(self, event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        \"\"\"Transform event. If schema is missing required 'event_id', route to dead letter queue.\"\"\"
        if "event_id" not in event:
            # BUG FOR TASK-203:
            # Directly raises SchemaError instead of routing to self.dead_letter.route()!
            raise SchemaError("Missing required event_id")
        
        event["transformed"] = True
        return event
""")
make_file("hydra_mesh/pipeline/aggregators.py", """
from typing import List

class MetricsAggregator:
    def sum_metric(self, events: List[dict], metric_key: str) -> float:
        return sum(e.get(metric_key, 0.0) for e in events)
""")
make_file("hydra_mesh/pipeline/coordinator.py", """
from .transformer import EventTransformer

class PipelineCoordinator:
    def __init__(self):
        self.transformer = EventTransformer()
    def run_pipeline(self, events: list) -> list:
        return [self.transformer.transform_event(e) for e in events]
""")
make_file("hydra_mesh/pipeline/deduplicator.py", """
class EventDeduplicator:
    def __init__(self): self.seen = set()
    def is_duplicate(self, event_id: str) -> bool:
        if event_id in self.seen: return True
        self.seen.add(event_id)
        return False
""")
make_file("hydra_mesh/pipeline/enricher.py", """
class EventEnricher:
    def enrich(self, event: dict, tenant_name: str) -> dict:
        event["tenant"] = tenant_name
        return event
""")
make_file("hydra_mesh/pipeline/router.py", """
class EventRouter:
    def route_key(self, event: dict) -> str:
        return event.get("category", "default")
""")
make_file("hydra_mesh/pipeline/windowing.py", """
class TimeWindow:
    def __init__(self, start: float, end: float):
        self.start = start
        self.end = end
    def contains(self, t: float) -> bool:
        return self.start <= t <= self.end
""")

# ==================== STORAGE (8 files) ====================
make_file("hydra_mesh/storage/__init__.py", '"""Storage package."""\nfrom .buffer import RingBuffer\n')
make_file("hydra_mesh/storage/buffer.py", """
from typing import Any, List
from ..core.exceptions import BufferOverflowError

class RingBuffer:
    \"\"\"In-memory bounded buffer for event queuing.\"\"\"
    def __init__(self, capacity: int = 10):
        self.capacity = capacity
        self.items: List[Any] = []

    def push(self, item: Any) -> bool:
        \"\"\"Append item to buffer. Raises BufferOverflowError if capacity is exceeded.\"\"\"
        # BUG FOR TASK-204:
        # Off-by-one check: uses '>' instead of '>=' allowing buffer to grow beyond capacity!
        if len(self.items) > self.capacity:
            raise BufferOverflowError("Buffer capacity exceeded")
        self.items.append(item)
        return True

    def size(self) -> int:
        return len(self.items)
""")
make_file("hydra_mesh/storage/cache.py", """
class KeyValueCache:
    def __init__(self): self.data = {}
    def get(self, k): return self.data.get(k)
    def set(self, k, v): self.data[k] = v
""")
make_file("hydra_mesh/storage/eviction.py", """
class LRUEviction:
    def should_evict(self, current_size: int, limit: int) -> bool:
        return current_size >= limit
""")
make_file("hydra_mesh/storage/indexer.py", """
class EventIndexer:
    def __init__(self): self.index = {}
    def index_event(self, eid: str, doc: dict): self.index[eid] = doc
""")
make_file("hydra_mesh/storage/memory_store.py", """
class MemoryStore:
    def __init__(self): self.records = []
    def save(self, rec: dict): self.records.append(rec)
""")
make_file("hydra_mesh/storage/query_engine.py", """
class SimpleQueryEngine:
    def match(self, record: dict, key: str, val: any) -> bool:
        return record.get(key) == val
""")
make_file("hydra_mesh/storage/retention.py", """
class RetentionPolicy:
    def is_expired(self, created_at: float, max_age: float, now: float) -> bool:
        return (now - created_at) > max_age
""")
make_file("hydra_mesh/storage/wal.py", """
class WriteAheadLog:
    def __init__(self): self.log = []
    def append(self, entry: str): self.log.append(entry)
""")

# ==================== CONNECTORS (8 files) ====================
make_file("hydra_mesh/connectors/__init__.py", '"""Connectors package."""\nfrom .http_sink import HttpSink\n')
make_file("hydra_mesh/connectors/http_sink.py", """
from typing import Dict

class HttpSink:
    \"\"\"HTTP export connector with header sanitization.\"\"\"
    def __init__(self, endpoint: str = "http://localhost/events"):
        self.endpoint = endpoint

    def prepare_headers(self, headers: Dict[str, str], strip_sensitive: bool = True) -> Dict[str, str]:
        \"\"\"Sanitize headers by stripping sensitive credentials (e.g. authorization, token).\"\"\"
        if not strip_sensitive:
            return dict(headers)
        
        sanitized = {}
        # Sensitive header names to remove
        sensitive_names = {"authorization", "x-api-key", "token"}
        
        for k, v in headers.items():
            # BUG FOR TASK-202:
            # Case-sensitive check: k in sensitive_names fails when header is 'Authorization' or 'Token'!
            if k in sensitive_names:
                continue
            sanitized[k] = v
        return sanitized
""")
make_file("hydra_mesh/connectors/auth.py", """
class TokenAuth:
    def __init__(self, token: str): self.token = token
    def get_auth_header(self) -> dict: return {"Authorization": f"Bearer {self.token}"}
""")
make_file("hydra_mesh/connectors/file_sink.py", """
class FileSink:
    def write_line(self, path: str, line: str): pass
""")
make_file("hydra_mesh/connectors/metrics_exporter.py", """
class MetricsExporter:
    def export(self, metrics: dict): pass
""")
make_file("hydra_mesh/connectors/retry_policy.py", """
class ExponentialRetry:
    def get_delay(self, attempt: int) -> float: return 2.0 ** attempt
""")
make_file("hydra_mesh/connectors/stream_sink.py", """
class StreamSink:
    def stream(self, chunk: bytes): pass
""")
make_file("hydra_mesh/connectors/webhook.py", """
class WebhookSender:
    def send_hook(self, url: str, payload: dict): pass
""")

# ==================== UTILS (7 files) ====================
make_file("hydra_mesh/utils/__init__.py", '"""Utilities."""\n')
make_file("hydra_mesh/utils/async_tools.py", "def run_sync(coro): return None\n")
make_file("hydra_mesh/utils/compression.py", "def compress(b: bytes) -> bytes: return b\n")
make_file("hydra_mesh/utils/hashing.py", "import hashlib\ndef sha(s: str) -> str: return hashlib.sha256(s.encode()).hexdigest()\n")
make_file("hydra_mesh/utils/math_tools.py", "def clamp(v, mn, mx): return max(mn, min(mx, v))\n")
make_file("hydra_mesh/utils/strings.py", "def truncate(s, n): return s[:n]\n")
make_file("hydra_mesh/utils/time_utils.py", "import time\ndef now() -> float: return time.time()\n")

# ==================== TESTS (8 test files) ====================
make_file("tests/__init__.py", '"""Test suite for scaled_repo."""\n')

# 1. Baseline tests for rate limiter (TASK-201)
make_file("tests/test_rate_limiter.py", """
import pytest
from hydra_mesh.ingest.rate_limiter import SlidingWindowLimiter

def test_rate_limiter_standard():
    limiter = SlidingWindowLimiter(max_requests=5, burst_allowance=2, window_seconds=60.0)
    for i in range(5):
        assert limiter.allow_request("client1", timestamp=10.0 + i)

def test_rate_limiter_burst_allowance():
    # max_requests=5, burst_allowance=2 -> total 7 requests allowed!
    limiter = SlidingWindowLimiter(max_requests=5, burst_allowance=2, window_seconds=60.0)
    for i in range(5):
        assert limiter.allow_request("client1", timestamp=10.0 + i)
    
    # 6th and 7th requests should be allowed under burst capacity
    assert limiter.allow_request("client1", timestamp=20.0), "Burst request 6 was rejected!"
    assert limiter.allow_request("client1", timestamp=21.0), "Burst request 7 was rejected!"
    # 8th should exceed limit
    assert not limiter.allow_request("client1", timestamp=22.0)
""")

# 2. Baseline tests for http sink (TASK-202)
make_file("tests/test_http_sink.py", """
import pytest
from hydra_mesh.connectors.http_sink import HttpSink

def test_http_sink_header_sanitization():
    sink = HttpSink()
    headers = {
        "Content-Type": "application/json",
        "Authorization": "Bearer secret_token_123",
        "X-Api-Key": "key_xyz",
        "User-Agent": "HydraClient/1.0"
    }
    sanitized = sink.prepare_headers(headers, strip_sensitive=True)
    assert "Content-Type" in sanitized
    assert "User-Agent" in sanitized
    assert "Authorization" not in sanitized, "Sensitive 'Authorization' header was not stripped!"
    assert "X-Api-Key" not in sanitized, "Sensitive 'X-Api-Key' header was not stripped!"
""")

# 3. Baseline tests for dead letter queue (TASK-203)
make_file("tests/test_dead_letter.py", """
import pytest
from hydra_mesh.pipeline.transformer import EventTransformer
from hydra_mesh.pipeline.dead_letter import DeadLetterQueue

def test_transformer_valid():
    dlq = DeadLetterQueue()
    transformer = EventTransformer(dlq=dlq)
    res = transformer.transform_event({"event_id": "ev1", "val": 42})
    assert res is not None
    assert res["transformed"] is True
    assert dlq.count() == 0

def test_transformer_missing_schema_routes_to_dlq():
    dlq = DeadLetterQueue()
    transformer = EventTransformer(dlq=dlq)
    # Event missing event_id should not crash; it should be routed to DLQ!
    res = transformer.transform_event({"val": 99})
    assert res is None, "Malformed event should return None"
    assert dlq.count() == 1, "Malformed event was not routed to DeadLetterQueue!"
""")

# 4. Baseline tests for buffer eviction (TASK-204)
make_file("tests/test_buffer_eviction.py", """
import pytest
from hydra_mesh.storage.buffer import RingBuffer
from hydra_mesh.core.exceptions import BufferOverflowError

def test_buffer_push_and_capacity():
    buf = RingBuffer(capacity=3)
    buf.push("item1")
    buf.push("item2")
    buf.push("item3")
    assert buf.size() == 3
    
    # 4th item should raise BufferOverflowError
    with pytest.raises(BufferOverflowError):
        buf.push("item4")
""")

# 5. Core unit tests
make_file("tests/test_core.py", """
from hydra_mesh.core.config import MeshConfig
from hydra_mesh.core.base import MeshEntity

def test_mesh_entity():
    e = MeshEntity(entity_id="e1", metadata={"type": "test"})
    assert e.validate()
""")

print("Scaled repository created successfully at", BASE_DIR)
