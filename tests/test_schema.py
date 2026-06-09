from forgelab.spec.schema import json_schema


def test_json_schema_describes_forge_document():
    schema = json_schema()
    assert schema["title"] == "ForgeDocument"
    assert "forgelab_version" in schema["properties"]
    assert "forgelab_version" in schema["required"]
