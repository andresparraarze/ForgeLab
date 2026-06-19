import copy

import pytest

from forgelab.patch import PatchError, apply_patch, diff, parse_pointer, resolve


# --------------------------------------------------------------------------- #
# RFC 6901 JSON Pointer
# --------------------------------------------------------------------------- #
def test_pointer_root_is_whole_document():
    doc = {"a": 1}
    assert resolve(doc, "") == doc


def test_pointer_resolves_nested_path():
    doc = {"nodes": [{"props": {"value": "330R"}}]}
    assert resolve(doc, "/nodes/0/props/value") == "330R"


def test_pointer_unescapes_tilde_and_slash():
    doc = {"a/b": 1, "m~n": 2}
    assert resolve(doc, "/a~1b") == 1
    assert resolve(doc, "/m~0n") == 2


def test_pointer_parse_tokens():
    assert parse_pointer("/nodes/0/props") == ["nodes", "0", "props"]
    assert parse_pointer("") == []


def test_pointer_missing_member_raises():
    with pytest.raises(PatchError):
        resolve({"a": 1}, "/b")


def test_pointer_bad_array_index_raises():
    with pytest.raises(PatchError, match="array index"):
        resolve({"l": [1, 2]}, "/l/01")


# --------------------------------------------------------------------------- #
# RFC 6902 — the six operations
# --------------------------------------------------------------------------- #
def test_add_object_member():
    out = apply_patch({"a": {}}, [{"op": "add", "path": "/a/b", "value": 1}])
    assert out == {"a": {"b": 1}}


def test_add_array_insert_and_append():
    inserted = apply_patch({"l": [1, 3]}, [{"op": "add", "path": "/l/1", "value": 2}])
    assert inserted == {"l": [1, 2, 3]}
    appended = apply_patch({"l": [1]}, [{"op": "add", "path": "/l/-", "value": 2}])
    assert appended == {"l": [1, 2]}


def test_remove_member_and_element():
    assert apply_patch({"a": 1, "b": 2}, [{"op": "remove", "path": "/b"}]) == {"a": 1}
    assert apply_patch({"l": [1, 2, 3]}, [{"op": "remove", "path": "/l/1"}]) == {"l": [1, 3]}


def test_replace_value():
    assert apply_patch({"a": 1}, [{"op": "replace", "path": "/a", "value": 2}]) == {"a": 2}


def test_move_value():
    out = apply_patch({"a": 1, "b": {}}, [{"op": "move", "from": "/a", "path": "/b/x"}])
    assert out == {"b": {"x": 1}}


def test_copy_value():
    out = apply_patch({"a": 1, "b": {}}, [{"op": "copy", "from": "/a", "path": "/b/x"}])
    assert out == {"a": 1, "b": {"x": 1}}


def test_test_op_passes_and_fails():
    # Passing test leaves the document unchanged.
    assert apply_patch({"a": 1}, [{"op": "test", "path": "/a", "value": 1}]) == {"a": 1}
    with pytest.raises(PatchError, match="test failed"):
        apply_patch({"a": 1}, [{"op": "test", "path": "/a", "value": 2}])


def test_move_into_own_child_is_rejected():
    with pytest.raises(PatchError, match="child"):
        apply_patch({"a": {"b": 1}}, [{"op": "move", "from": "/a", "path": "/a/b/c"}])


def test_apply_does_not_mutate_the_input():
    doc = {"nodes": [{"props": {"value": "330R"}}]}
    snapshot = copy.deepcopy(doc)
    apply_patch(doc, [{"op": "replace", "path": "/nodes/0/props/value", "value": "10k"}])
    assert doc == snapshot  # original is untouched; apply works on a copy


def test_failed_op_aborts_whole_patch():
    # The remove of /missing fails, so the earlier add must not be observable.
    doc = {"a": 1}
    with pytest.raises(PatchError):
        apply_patch(doc, [{"op": "add", "path": "/b", "value": 2}, {"op": "remove", "path": "/x"}])
    assert doc == {"a": 1}


def test_unknown_op_raises():
    with pytest.raises(PatchError, match="unknown op"):
        apply_patch({}, [{"op": "frobnicate", "path": "/a"}])


def test_missing_member_raises():
    with pytest.raises(PatchError, match="value"):
        apply_patch({"a": 1}, [{"op": "replace", "path": "/a"}])


# --------------------------------------------------------------------------- #
# diff round-trips: apply_patch(a, diff(a, b)) == b
# --------------------------------------------------------------------------- #
_ROUNDTRIP_CASES = [
    ({"a": 1}, {"a": 2}),  # scalar change
    ({"a": 1}, {"a": 1, "b": 2}),  # add key
    ({"a": 1, "b": 2}, {"a": 1}),  # remove key
    ({"a": {"x": 1}}, {"a": {"x": 2, "y": 3}}),  # nested
    ({"l": [1, 2, 3]}, {"l": [1, 9, 3]}),  # list element change
    ({"l": [1, 2]}, {"l": [1, 2, 3, 4]}),  # list grow
    ({"l": [1, 2, 3, 4]}, {"l": [1, 2]}),  # list shrink
    ({"a": 1}, {"a": [1, 2]}),  # type change
    ({"a/b": 1}, {"a/b": 2}),  # escaped key
    (
        {"nodes": [{"id": "r1", "props": {"value": "330R"}}]},
        {"nodes": [{"id": "r1", "props": {"value": "10k"}}, {"id": "r2"}]},
    ),  # realistic
]


@pytest.mark.parametrize("source,target", _ROUNDTRIP_CASES)
def test_diff_then_apply_equals_target(source, target):
    patch = diff(source, target)
    assert apply_patch(source, patch) == target


def test_diff_of_equal_documents_is_empty():
    assert diff({"a": 1}, {"a": 1}) == []
