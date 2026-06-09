from forgelab.spec.version import SPEC_VERSION, is_compatible


def test_spec_version_is_semver_string():
    assert isinstance(SPEC_VERSION, str)
    parts = SPEC_VERSION.split(".")
    assert len(parts) == 3
    assert all(p.isdigit() for p in parts)


def test_same_major_is_compatible():
    major = SPEC_VERSION.split(".")[0]
    assert is_compatible(f"{major}.0.0") is True


def test_different_major_is_incompatible():
    assert is_compatible("999.0.0") is False


def test_malformed_version_is_incompatible():
    assert is_compatible("not-a-version") is False
