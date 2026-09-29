"""One publish/poll implementation for the historical runner and evaluation."""

from .artifacts import EvaluationError


def publish_and_wait(client, dataset, wait_for_order, *, timeout_seconds=600, poll_seconds=2,
                     on_publish=None, progress=None):
    published = client.post("/orders/publishNew", {"text": dataset["news"], "validation_mode": "LIGHT"})
    order_id = str(published.get("order_id") or "")
    if not order_id:
        raise EvaluationError("publishNew did not return order_id")
    if on_publish:
        on_publish(order_id)
    return wait_for_order(client, order_id, timeout_seconds, poll_seconds, progress=progress)


def legacy_client(base_url, verify_tls, timeout):
    """Reuse authentication, API contracts and polling without copying the runner."""
    import importlib.util
    import sys
    from evaluation import ROOT
    name = "evaluation_legacy_benchmark"
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, ROOT / "tests/llm-benchmark/llm-benchmark.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    module = sys.modules[name]
    origin = base_url.rstrip("/").removesuffix("/backend")
    client = module.ApiClient(base_url, module.TokenProvider(origin, verify_tls), verify_tls, timeout)
    return client, module.wait_for_order
