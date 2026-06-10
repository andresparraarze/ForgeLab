import pytest

from forgelab.auth.models import (
    AuthError,
    ExpiredToken,
    InsufficientScope,
    InvalidToken,
    Principal,
)


def test_principal_holds_scopes():
    p = Principal(sub="u1", client_id="c1", scopes=frozenset({"forge:read"}), claims={"x": 1})
    assert "forge:read" in p.scopes
    assert p.client_id == "c1"


def test_invalid_and_expired_are_401_invalid_token():
    for exc in (InvalidToken("nope"), ExpiredToken("old")):
        assert exc.status_code == 401
        assert exc.error_code == "invalid_token"
        assert "Bearer" in exc.www_authenticate()


def test_insufficient_scope_is_403_with_scope():
    exc = InsufficientScope(["forge:export"])
    assert exc.status_code == 403
    assert exc.error_code == "insufficient_scope"
    assert 'scope="forge:export"' in exc.www_authenticate()


def test_hierarchy():
    assert issubclass(InvalidToken, AuthError)
    assert issubclass(InsufficientScope, AuthError)
    with pytest.raises(AuthError):
        raise ExpiredToken("x")
