"""The artifact is an evaluation envelope, not a duplicate production contract."""

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any
from uuid import uuid4


class ExecutionMode(str, Enum):
    FULL_PIPELINE = "FULL_PIPELINE"
    GOLD_DOMAINS = "GOLD_DOMAINS"
    GOLD_EVIDENCE = "GOLD_EVIDENCE"
    VALIDATOR_REPLAY = "VALIDATOR_REPLAY"


class CacheMode(str, Enum):
    COLD = "COLD"
    WARM = "WARM"
    FROZEN = "FROZEN"


@dataclass
class CaseResult:
    case_id: str
    execution_mode: str
    assertion: dict
    expected: dict
    run_id: str = field(default_factory=lambda: str(uuid4()))
    schema_version: str = "evaluation-result-v1"
    dataset_id: str | None = None
    dataset_hash: str | None = None
    order_id: str | None = None
    assertion_id: str | None = None
    validator: dict = field(default_factory=dict)
    extraction: dict = field(default_factory=lambda: {"status": "NOT_EVALUATED"})
    router: dict = field(default_factory=lambda: {"status": "NOT_EVALUATED"})
    retrieval: dict = field(default_factory=lambda: {"status": "NOT_EVALUATED"})
    validator_input: dict = field(default_factory=dict)
    validator_output: dict = field(default_factory=dict)
    grounding: dict = field(default_factory=dict)
    consensus: dict = field(default_factory=lambda: {"status": "NOT_EVALUATED"})
    cache_state: dict = field(default_factory=lambda: {
        "mode": "WARM", "router_cache_hit": None, "evidence_cache_hit": None,
        "route_recomputed": None, "evidence_recomputed": None,
    })
    timings: dict = field(default_factory=dict)
    errors: list[dict] = field(default_factory=list)
    metrics: dict = field(default_factory=dict)
    root_cause: dict = field(default_factory=dict)
    provenance: dict = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
