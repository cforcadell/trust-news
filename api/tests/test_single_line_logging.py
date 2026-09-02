import json
import io
import logging
import sys

from common.utils.logging_utils import (
    SingleLineJsonFormatter,
    configure_single_line_json_logging,
    exception_message,
    log_event,
)


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


def test_configuration_applies_json_formatter_to_root_and_uvicorn_handlers():
    root_logger = logging.getLogger()
    uvicorn_logger = logging.getLogger("uvicorn.access")
    original_root_handlers = root_logger.handlers[:]
    original_root_level = root_logger.level
    original_uvicorn_handlers = uvicorn_logger.handlers[:]
    original_uvicorn_level = uvicorn_logger.level
    original_uvicorn_propagate = uvicorn_logger.propagate
    root_stream = io.StringIO()
    uvicorn_stream = io.StringIO()

    try:
        root_logger.handlers = [logging.StreamHandler(root_stream)]
        uvicorn_logger.handlers = [logging.StreamHandler(uvicorn_stream)]
        uvicorn_logger.setLevel(logging.INFO)
        uvicorn_logger.propagate = False

        configure_single_line_json_logging(logging.INFO)
        logging.getLogger("application").info("mensaje\nmultilínea")
        uvicorn_logger.info(
            '%s - "%s %s HTTP/%s" %d',
            "127.0.0.1:1234",
            "GET",
            "/health",
            "1.1",
            200,
        )

        application_line = root_stream.getvalue().strip()
        access_line = uvicorn_stream.getvalue().strip()
        assert "\n" not in application_line
        assert "\n" not in access_line
        assert json.loads(application_line)["message"] == "mensaje\nmultilínea"
        assert json.loads(access_line)["logger"] == "uvicorn.access"
        assert json.loads(access_line)["message"].endswith('"GET /health HTTP/1.1" 200')
    finally:
        root_logger.handlers = original_root_handlers
        root_logger.setLevel(original_root_level)
        uvicorn_logger.handlers = original_uvicorn_handlers
        uvicorn_logger.setLevel(original_uvicorn_level)
        uvicorn_logger.propagate = original_uvicorn_propagate


def test_log_event_does_not_flatten_multiline_fields():
    stream = io.StringIO()
    logger = logging.getLogger("structured-test")
    handler = logging.StreamHandler(stream)
    handler.setFormatter(SingleLineJsonFormatter())
    original_handlers = logger.handlers[:]
    original_level = logger.level
    original_propagate = logger.propagate

    try:
        logger.handlers = [handler]
        logger.setLevel(logging.INFO)
        logger.propagate = False
        log_event(
            logger,
            logging.INFO,
            "llm_response_received",
            provider="openrouter",
            model="example/model",
            attempt=1,
            status=200,
            duration_ms=12.5,
            response_chars=42,
            diagnostic="línea 1\nlínea 2",
        )

        rendered = stream.getvalue().strip()
        assert "\n" not in rendered
        payload = json.loads(rendered)
        assert payload["event"] == "llm_response_received"
        assert payload["diagnostic"] == "línea 1\nlínea 2"
    finally:
        logger.handlers = original_handlers
        logger.setLevel(original_level)
        logger.propagate = original_propagate
