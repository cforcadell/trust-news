import asyncio
import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "isolated_benchmark", ROOT / "tests/llm-benchmark/generate_assertions_isolated.py",
)
benchmark = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(benchmark)


def catalogue():
    return {"data": [{"id": row["model"], "supported_parameters": ["response_format", "reasoning"],
                      "pricing": {"prompt": "0.000001", "completion": "0.000002"}}
                     for row in benchmark.CONFIGURATIONS]}


def test_fixed_matrix_contains_exactly_the_five_requested_experiments():
    assert [(row["id"], row["model"], row["reasoning_effort"]) for row in benchmark.configurations()] == [
        ("B0", "openai/gpt-5-nano", None), ("B1", "openai/gpt-5-nano", "minimal"),
        ("B2", "openai/gpt-4.1-nano", None), ("B3", "mistralai/mistral-small-3.2-24b-instruct", None),
        ("B4", "google/gemini-3.1-flash-lite", None),
    ]


def test_request_adds_reasoning_only_for_the_reasoning_experiment_and_keeps_strict_schema():
    schema = {"title": "AssertionBatch", "properties": {"assertions": {"type": "array", "default": []}}}
    base = benchmark.request_payload("prompt", schema, benchmark.configurations()[0])
    reasoning = benchmark.request_payload("prompt", schema, benchmark.configurations()[1])

    assert "reasoning" not in base
    assert reasoning["reasoning"] == {"effort": "minimal"}
    assert reasoning["response_format"]["json_schema"]["strict"] is True
    assert reasoning["response_format"]["json_schema"]["schema"]["required"] == ["assertions"]
    assert reasoning["provider"] == {"require_parameters": True}


def test_usage_preserves_missing_fields_as_none_and_retains_provider_cost():
    usage = benchmark.parse_usage({"usage": {"prompt_tokens": 11, "completion_tokens": 7, "cost": 0.0012,
                                                "completion_tokens_details": {"reasoning_tokens": 4}}})
    assert usage["prompt_tokens"] == 11
    assert usage["completion_tokens"] == 7
    assert usage["reasoning_tokens"] == 4
    assert usage["cached_tokens"] is None
    assert usage["total_tokens"] is None
    assert usage["cost_usd"] == 0.0012


def test_plan_counts_cases_models_and_repetitions_and_uses_public_prices():
    cases = [{"id": "one", "news": "uno"}, {"id": "two", "news": "dos"}]
    plan = benchmark.plan(cases, catalogue(), 5, 20, lambda text: f"prompt {text}")
    assert plan["executions"] == 50
    assert plan["preflight_provider_calls"] == 5
    assert plan["minimum_provider_calls"] == 55
    assert plan["estimated_total_cost_usd"] > 0
    assert all(row["compatibility_error"] is None for row in plan["models"])


def test_plan_can_exclude_any_matrix_configuration_without_changing_the_matrix():
    cases = [{"id": "one", "news": "uno"}]
    selected = benchmark.configurations({"B4"})
    plan = benchmark.plan(cases, catalogue(), 2, 20, lambda text: f"prompt {text}", selected)

    assert [row["id"] for row in plan["models"]] == ["B0", "B1", "B2", "B3"]
    assert plan["executions"] == 8
    assert plan["preflight_provider_calls"] == 4
    assert plan["minimum_provider_calls"] == 12
    assert [row["id"] for row in benchmark.configurations()] == ["B0", "B1", "B2", "B3", "B4"]


class FakeBatch:
    @classmethod
    def model_validate(cls, value):
        if value.get("invalid"):
            raise ValueError("schema invalid")
        return cls()

    def model_dump(self, **_):
        return {"assertions": [{"text": "A", "categoryId": 9}]}


class FakeTarget:
    AssertionBatch = FakeBatch
    get_assertions_schema = staticmethod(lambda: {"title": "AssertionBatch", "properties": {"assertions": {"type": "array"}}})
    build_assertions_prompt = staticmethod(lambda text: f"original {text}")
    build_assertions_repair_prompt = staticmethod(lambda invalid, error: f"repair {invalid} {error}")
    parse_assertions_content = staticmethod(lambda value: [type("A", (), {"model_dump": lambda self, **_: value["assertions"][0]})()])


def response(content, cost):
    return {"id": "generation-id", "choices": [{"message": {"content": content}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3, "cost": cost}}


def test_invalid_json_triggers_one_repair_and_counts_both_costed_calls():
    replies = iter([response('{"invalid": true}', 0.01), response('{"assertions": []}', 0.02)])

    async def fake_post(*_):
        return next(replies)

    result = asyncio.run(benchmark.structured_generation(
        FakeTarget, benchmark.configurations()[0], "noticia", post=fake_post, url="url", key="secret", timeout=1, attempts=1,
    ))
    assert result["status"] == "COMPLETED"
    assert result["repair_used"] is True
    assert result["provider_call_count"] == 2
    assert result["cost_real_usd"] == 0.03


def test_transport_timeouts_are_counted_for_every_bounded_attempt():
    async def timeout(*_):
        raise TimeoutError("timeout")

    result = asyncio.run(benchmark.structured_generation(
        FakeTarget, benchmark.configurations()[0], "noticia", post=timeout, url="url", key="secret", timeout=1, attempts=3,
    ))
    assert result["status"] == "FAILED"
    assert result["provider_call_count"] == 3
    assert all(call["status"] == "FAILED" for call in result["provider_calls"])


def test_hard_cap_counts_every_http_attempt_including_failures():
    async def response_once(*_):
        return response('{"assertions": []}', 0.01)

    cap = benchmark.CappedPoster(2, response_once)
    asyncio.run(cap("url", "key", {}, 1))
    asyncio.run(cap("url", "key", {}, 1))
    try:
        asyncio.run(cap("url", "key", {}, 1))
    except benchmark.BenchmarkError as exc:
        assert "MAX_PROVIDER_CALLS_REACHED" in str(exc)
    else:
        raise AssertionError("Expected hard provider-call cap")
    assert cap.calls == 2


def test_hard_cap_can_resume_from_previously_recorded_calls():
    cap = benchmark.CappedPoster(30, initial_calls=29)
    assert cap.calls == 29


def test_parser_supports_resumable_execution_boundaries():
    args = benchmark.parser().parse_args([
        "run", "--max-new-executions", "2", "--max-new-preflights", "1", "--preflight-only", "--exclude-configuration", "B4",
        "--catalog-cache", "/tmp/openrouter-catalog.json",
    ])
    assert args.max_new_executions == 2
    assert args.max_new_preflights == 1
    assert args.preflight_only is True
    assert args.exclude_configuration == ["B4"]
    assert args.catalog_cache == Path("/tmp/openrouter-catalog.json")


def test_aggregate_keeps_unknown_usage_and_cost_as_null():
    rows = [{"configuration_id": "B0", "status": "COMPLETED", "duration_seconds": 1.0, "repair_used": False,
             "provider_calls": [{"usage": {}}], "cost_real_usd": None, "quality": {"extraction": {"f1": 1.0}}}]
    aggregate = benchmark.aggregate(rows)["B0"]
    assert aggregate["tokens"]["prompt_tokens"] is None
    assert aggregate["cost_real_usd"] is None
    assert aggregate["duration_seconds"]["p50"] == 1.0


def test_aggregate_includes_billable_provider_calls_from_failed_rows():
    rows = [{"configuration_id": "B0", "status": "FAILED", "duration_seconds": 1.0, "repair_used": True,
             "provider_calls": [{"usage": {"cost_usd": 0.012}}], "cost_real_usd": None}]
    aggregate = benchmark.aggregate(rows)["B0"]
    assert aggregate["cost_real_usd"] == 0.012
