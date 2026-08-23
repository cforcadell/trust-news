import json
import logging
import sys

from common.utils.logging_utils import SingleLineJsonFormatter, exception_message


def build_record(message, exc_info=None):
    return logging.LogRecord(
        name="generate-assertions-test",
        level=logging.ERROR if exc_info else logging.INFO,
        pathname=__file__,
        lineno=1,
        msg=message,
        args=(),
        exc_info=exc_info,
    )


def test_formatter_keeps_multiline_message_in_one_physical_line():
    rendered = SingleLineJsonFormatter().format(
        build_record("primera línea\nsegunda línea\r\ntercera línea")
    )

    assert "\n" not in rendered
    payload = json.loads(rendered)
    assert payload["message"] == "primera línea\nsegunda línea\r\ntercera línea"


def test_formatter_keeps_traceback_in_one_physical_line():
    try:
        raise TimeoutError("respuesta\nno recibida")
    except TimeoutError:
        exc_info = sys.exc_info()

    rendered = SingleLineJsonFormatter().format(
        build_record({"event": "llm_request_failed", "provider": "openrouter"}, exc_info)
    )

    assert "\n" not in rendered
    payload = json.loads(rendered)
    assert payload["event"] == "llm_request_failed"
    assert payload["provider"] == "openrouter"
    assert "TimeoutError" in payload["exception"]
    assert "respuesta\nno recibida" in payload["exception"]


def test_timeout_without_message_still_has_useful_error_name():
    assert exception_message(TimeoutError()) == "TimeoutError"


def test_formatter_preserves_validator_provider_model_context():
    record = build_record("validación terminada")
    record.provider_model = "OPENROUTER_openai/gpt-5-nano"

    payload = json.loads(SingleLineJsonFormatter().format(record))

    assert payload["provider_model"] == "OPENROUTER_openai/gpt-5-nano"


def test_formatter_merges_existing_structured_message():
    rendered = SingleLineJsonFormatter().format(
        build_record('{"event":"gateway_access","duration_ms":12.5}')
    )

    payload = json.loads(rendered)
    assert payload["event"] == "gateway_access"
    assert payload["duration_ms"] == 12.5
    assert "message" not in payload
