"""HTTP adapter; no credentials are put in requests to internal search services."""

class HttpServices:
    def __init__(self, router_url="http://localhost:8075", evidence_url="http://localhost:8074", timeout=60):
        self.router_url = router_url.rstrip("/")
        self.evidence_url = evidence_url.rstrip("/")
        self.timeout = timeout

    def post(self, url, payload, run_id, cache_mode):
        import httpx
        response = httpx.post(url, json=payload, timeout=self.timeout,
                              headers={"X-Evaluation-Run-ID": run_id, "X-Evaluation-Cache": cache_mode})
        response.raise_for_status()
        return response.json()

    def route(self, assertion, run_id, cache_mode):
        return self.post(self.router_url + "/routes/resolve", {
            "topic_code": assertion["topic_code"], "evidence_kind": assertion["evidence_kind"],
            "jurisdiction": assertion["context"]["jurisdiction"],
            "language": assertion["context"]["language"],
        }, run_id, cache_mode)

    def retrieve(self, assertion, sources, origin, run_id, cache_mode):
        from common.models.evidence_models import EvidenceSearchRequestV2
        payload = EvidenceSearchRequestV2.model_validate({
            "schema_version": "evidence-search-request-v2", "assertion": assertion,
            "origin_document": origin,
            "search_policy": {"strategy": "LOCAL", "preferred_sources": sources, "max_results": 5},
        }).model_dump(mode="json")
        return self.post(self.evidence_url + "/search/evidence", payload, run_id, cache_mode)
