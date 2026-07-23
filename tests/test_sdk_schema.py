import pytest

from forgelab.sdk.schema import DOMAIN_VOCAB, domain_schema


def _variants(schema):
    return schema["$defs"]["node"]["oneOf"]


def test_registry_covers_all_domains():
    assert set(DOMAIN_VOCAB) == {"hardware", "threed", "mechanical"}
    assert set(DOMAIN_VOCAB["hardware"]) == {"board", "net", "component", "track", "via"}
    assert set(DOMAIN_VOCAB["threed"]) == {"scene", "material", "mesh", "object"}
    assert set(DOMAIN_VOCAB["mechanical"]) == {
        "part",
        "body",
        "sketch",
        "pad",
        "pocket",
        "loft",
        "sweep",
        "fillet",
        "shell",
        "revolve",
        "boolean",
    }


def test_mechanical_schema_pins_domain_and_includes_pad():
    schema = domain_schema("mechanical")
    assert schema["properties"]["domain"] == {"const": "mechanical"}
    consts = {v["properties"]["type"]["const"] for v in _variants(schema)}
    assert consts == {
        "part",
        "body",
        "sketch",
        "pad",
        "pocket",
        "loft",
        "sweep",
        "fillet",
        "shell",
        "revolve",
        "boolean",
    }


def test_hardware_schema_pins_domain_const():
    schema = domain_schema("hardware")
    assert schema["properties"]["domain"] == {"const": "hardware"}


def test_schema_includes_every_node_type():
    schema = domain_schema("threed")
    consts = {v["properties"]["type"]["const"] for v in _variants(schema)}
    assert consts == {"scene", "material", "mesh", "object"}


def test_component_props_field_names_match_model():
    schema = domain_schema("hardware")
    component = next(
        v for v in _variants(schema) if v["properties"]["type"]["const"] == "component"
    )
    props = component["properties"]["props"]["properties"]
    assert "reference" in props
    assert "footprint" in props


def test_pad_at_field_description_mentions_offset():
    schema = domain_schema("hardware")
    # Pad is a sub-model of Component, hoisted into the document-level $defs.
    at_field = schema["$defs"]["Pad"]["properties"]["at"]
    desc = at_field["description"].lower()
    assert "offset" in desc or "position" in desc


def test_object_mesh_ref_description_says_use_id_not_name():
    schema = domain_schema("threed")
    obj = next(v for v in _variants(schema) if v["properties"]["type"]["const"] == "object")
    mesh_field = obj["properties"]["props"]["properties"]["mesh"]
    desc = mesh_field["description"].lower()
    assert "id" in desc and "name" in desc


def test_primitive_material_ref_description_says_use_id_not_name():
    schema = domain_schema("threed")
    # Primitive is a sub-model of Mesh, hoisted into the document-level $defs.
    material_field = schema["$defs"]["Primitive"]["properties"]["material"]
    desc = material_field["description"].lower()
    assert "id" in desc and "name" in desc


def test_unknown_domain_raises():
    with pytest.raises(KeyError):
        domain_schema("nope")


def _collect_refs(node):
    refs = []
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "$ref" and isinstance(value, str):
                refs.append(value)
            else:
                refs.extend(_collect_refs(value))
    elif isinstance(node, list):
        for item in node:
            refs.extend(_collect_refs(item))
    return refs


@pytest.mark.parametrize("domain", ["hardware", "threed", "mechanical"])
def test_all_internal_refs_resolve(domain):
    schema = domain_schema(domain)
    defs = schema["$defs"]
    refs = _collect_refs(schema)
    assert refs, "expected the schema to contain $ref pointers"
    for ref in refs:
        assert ref.startswith("#/$defs/"), ref
        name = ref[len("#/$defs/") :]
        assert name in defs, f"unresolved $ref {ref!r}; available: {sorted(defs)}"


def test_schema_pins_forgelab_version_to_installed_spec():
    from forgelab.spec import SPEC_VERSION

    schema = domain_schema("mechanical")
    assert schema["properties"]["forgelab_version"] == {"const": SPEC_VERSION}
