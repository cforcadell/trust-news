from common.utils.llm_json import parse_json_content


def test_parse_json_content_removes_markdown_and_trailing_commas():
    raw = """```json
    {
      "assertions": [
        {"text": "claim", "categoryId": 1,},
      ],
    }
    ```"""

    parsed = parse_json_content(raw)

    assert parsed == {"assertions": [{"text": "claim", "categoryId": 1}]}


def test_parse_json_content_extracts_balanced_json_from_text():
    raw = "Aqui tienes el JSON:\n{\"assertions\": [{\"text\": \"claim\", \"categoryId\": 1}]}\nFin."

    parsed = parse_json_content(raw)

    assert parsed == {"assertions": [{"text": "claim", "categoryId": 1}]}


def test_coerce_list_accepts_common_llm_wrappers():
    from common.utils.llm_json import coerce_list

    assert coerce_list({"aserciones": [{"text": "claim"}]}, list_key="assertions") == [{"text": "claim"}]
    assert coerce_list({"data": {"assertions": [{"text": "nested"}]}}, list_key="assertions") == [{"text": "nested"}]
    assert coerce_list({"output": [{"text": "single-list-field"}]}, list_key="assertions") == [{"text": "single-list-field"}]


def test_coerce_list_accepts_single_item_and_object_map():
    from common.utils.llm_json import coerce_list

    single = {"text": "claim", "categoryId": 1}
    mapped = {
        "claim_1": {"text": "first", "categoryId": 1},
        "claim_2": {"text": "second", "categoryId": 2},
    }

    assert coerce_list(single, list_key="assertions") == [single]
    assert coerce_list({"assertion": single}, list_key="assertions") == [single]
    assert coerce_list(mapped, list_key="assertions") == list(mapped.values())
