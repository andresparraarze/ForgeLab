import json

import pytest

from forgelab.core import LLMOutputError
from forgelab.sdk import dump, new_document
from forgelab.sdk.validation import validate_llm_output
from forgelab.spec import Node


def _hardware_doc_json():
    doc = new_document(domain="hardware", name="x")
    doc.nodes.append(Node(id="net:1", type="net", props={"code": 1, "name": "GND"}))
    return dump(doc)


def test_strips_markdown_fence():
    fenced = "```json\n" + _hardware_doc_json() + "\n```"
    document = validate_llm_output(fenced)
    assert document.domain.value == "hardware"


def test_strips_surrounding_prose():
    noisy = "Sure! Here is your document:\n" + _hardware_doc_json() + "\nHope that helps."
    document = validate_llm_output(noisy)
    assert document.nodes[0].id == "net:1"


def test_accepts_dict_input():
    data = json.loads(_hardware_doc_json())
    document = validate_llm_output(data, domain="hardware")
    assert document.domain.value == "hardware"


def test_malformed_json_raises_llm_output_error():
    with pytest.raises(LLMOutputError, match="not valid JSON"):
        validate_llm_output("{ this is not json ")


def test_unknown_field_raises_with_message():
    data = json.loads(_hardware_doc_json())
    data["nodes"][0]["props"]["bogus_field"] = 99
    with pytest.raises(LLMOutputError, match="invalid props"):
        validate_llm_output(data)


def test_unknown_node_type_raises():
    data = json.loads(_hardware_doc_json())
    data["nodes"][0]["type"] = "wormhole"
    with pytest.raises(LLMOutputError, match="unknown node type"):
        validate_llm_output(data)


def test_wrong_domain_raises():
    with pytest.raises(LLMOutputError, match="Expected domain"):
        validate_llm_output(_hardware_doc_json(), domain="threed")


def test_incompatible_version_raises():
    data = json.loads(_hardware_doc_json())
    data["forgelab_version"] = "99.0.0"
    with pytest.raises(LLMOutputError):
        validate_llm_output(data)


def test_invalid_child_props_reports_breadcrumb():
    doc = new_document(domain="threed", name="s")
    parent = Node(
        id="root",
        type="object",
        props={
            "name": "root",
            "transform": {
                "translation": [0, 0, 0],
                "rotation": [0, 0, 0, 1],
                "scale": [1, 1, 1],
            },
            "mesh": "",
        },
        children=[
            Node(
                id="bad",
                type="object",
                props={"name": "bad", "transform": {"translation": [0, 0]}},
            )
        ],
    )
    doc.nodes.append(parent)
    with pytest.raises(LLMOutputError, match=r"child\[0\]"):
        validate_llm_output(dump(doc), domain="threed")
