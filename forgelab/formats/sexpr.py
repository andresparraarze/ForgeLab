"""A minimal, zero-dependency S-expression parser and writer.

Atoms parse as: quoted tokens -> plain ``str``; bare tokens -> ``Symbol`` (a
``str`` subclass); numeric tokens -> ``int``/``float``. Lists are Python lists.
The ``Symbol`` distinction lets the writer re-emit bare symbols without quotes
while quoting genuine strings.
"""

from __future__ import annotations

SExpr = "list | str | Symbol | int | float"


class Symbol(str):
    """A bare (unquoted) S-expression atom."""

    __slots__ = ()


class SExprError(ValueError):
    """Raised when S-expression text cannot be parsed."""


def _tokenize(text: str) -> list[str]:
    tokens: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        c = text[i]
        if c in " \t\r\n":
            i += 1
        elif c in "()":
            tokens.append(c)
            i += 1
        elif c == '"':
            j = i + 1
            buf: list[str] = []
            while j < n:
                if text[j] == "\\" and j + 1 < n:
                    buf.append(text[j + 1])
                    j += 2
                elif text[j] == '"':
                    break
                else:
                    buf.append(text[j])
                    j += 1
            if j >= n:
                raise SExprError("unterminated string literal")
            tokens.append('"' + "".join(buf) + '"')
            i = j + 1
        else:
            j = i
            while j < n and text[j] not in ' \t\r\n()"':
                j += 1
            tokens.append(text[i:j])
            i = j
    return tokens


def _atom(token: str) -> str | Symbol | int | float:
    if token.startswith('"') and token.endswith('"'):
        return token[1:-1]
    try:
        return int(token)
    except ValueError:
        pass
    try:
        return float(token)
    except ValueError:
        pass
    return Symbol(token)


def parse(text: str) -> list:
    """Parse S-expression ``text`` whose top level is a single list."""
    tokens = _tokenize(text)
    if not tokens or tokens[0] != "(":
        raise SExprError("top-level S-expression must be a list")
    pos = 0

    def parse_list() -> list:
        nonlocal pos
        assert tokens[pos] == "("
        pos += 1
        out: list = []
        while pos < len(tokens):
            tok = tokens[pos]
            if tok == "(":
                out.append(parse_list())
            elif tok == ")":
                pos += 1
                return out
            else:
                out.append(_atom(tok))
                pos += 1
        raise SExprError("unbalanced parentheses")

    result = parse_list()
    if pos != len(tokens):
        raise SExprError("trailing tokens after top-level list")
    return result


def _dump_atom(value: object) -> str:
    if isinstance(value, Symbol):
        return str(value)
    if isinstance(value, bool):  # guard: bool is an int subclass
        return "true" if value else "false"
    if isinstance(value, int | float):
        return repr(value) if isinstance(value, float) else str(value)
    if isinstance(value, str):
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    raise SExprError(f"cannot serialize atom of type {type(value).__name__}")


def dumps(tree: object, *, indent: int = 0, _level: int = 0) -> str:
    """Serialize an S-expression tree back to text.

    With ``indent == 0`` (default) the output is compact on one line per list.
    """
    if not isinstance(tree, list):
        return _dump_atom(tree)
    inner = " ".join(dumps(item, indent=indent) for item in tree)
    return f"({inner})"
