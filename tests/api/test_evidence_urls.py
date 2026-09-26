import pytest

from common.utils.evidence import is_http_url, sanitize_evidence_item


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("https://example.test/article", True),
        ("http://example.test/article", True),
        ("javascript:alert(1)", False),
        ("data:text/html,<script>alert(1)</script>", False),
        ("not a URL", False),
        ("https://[invalid", False),
        ("https://user@", False),
        ("https://exa mple.com", False),
        ("https://example.test:invalid", False),
        ("https://example.test:99999", False),
        ("https:///example.test", False),
        ("https://exa\\nmple.test", False),
        ("https://example.test\\\\evil", False),
        ("https://%20.test", False),
        ("//example.test", False),
        ("file:///tmp/test", False),
        ("https://[::1]:8443/article", True),
        (" HTTPS://example.test/article?q=1&x=2 ", True),
        (None, False),
        (123, False),
    ],
)
def test_evidence_url_accepts_only_http_s(value, expected):
    assert is_http_url(value) is expected


def test_sanitize_evidence_item_removes_unsafe_url_but_keeps_evidence():
    item = sanitize_evidence_item(
        {"url": "javascript:alert(1)", "title": "Fuente no navegable"}
    )

    assert item == {"title": "Fuente no navegable", "url_text": "javascript:alert(1)"}


@pytest.mark.parametrize("field", ["sources", "evidence_used"])
@pytest.mark.parametrize("key", ["url", "source_url"])
@pytest.mark.parametrize("url", ["https://[invalid", "https://user@", "https://exa mple.com", "javascript:alert(1)"])
def test_response_model_preserves_invalid_evidence_as_text(field, key, url):
    from common.models.async_models import ValidatorAPIResponse

    evidence = {key: url, "title": "Fuente", "quote": "Fragmento"}
    model = ValidatorAPIResponse(resultado="TRUE", descripcion="Resultado", **{field: [evidence]})
    result = model.model_dump()[field][0]
    assert key not in result
    assert result[f"{key}_text"] == url
    assert result["quote"] == "Fragmento"
    assert evidence[key] == url


def test_response_model_preserves_valid_link():
    from common.models.async_models import ValidatorAPIResponse

    evidence = {"url": "https://example.test/article", "title": "Fuente"}
    model = ValidatorAPIResponse(resultado="TRUE", descripcion="Resultado", sources=[evidence])
    assert model.model_dump()["sources"] == [evidence]
