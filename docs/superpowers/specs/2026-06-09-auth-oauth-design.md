# ForgeLab Shared Auth (OAuth 2.0) — Design

**Date:** 2026-06-09
**Status:** Approved
**Spec bump:** none (no IR/spec model change; new optional `forgelab.auth` package + `[auth]` extra)

## Goal

Add a shared, domain-agnostic OAuth 2.0 module — `forgelab/auth/` — that
protects FastAPI applications through a single dependency. It is built **first**
as the foundation for a later MCP server (sub-project 2), and is proven
immediately by wiring it into the **existing REST API** (`forgelab/api/app.py`).

This is sub-project 1 of two. Sub-project 2 (the MCP server, `forgelab/mcp/`)
is a separate spec → plan → implementation cycle that consumes this module.

## Scope

In scope:

- A pluggable token-verification layer (built-in dev issuer **and** external
  IdP/JWKS verification).
- Both OAuth grant types: **client credentials** (machine-to-machine, for
  headless agents) and **authorization code + PKCE (S256)** (interactive
  delegation, e.g. a human authorizing a remote MCP connection).
- A minimal, in-memory **dev authorization server** so the repository runs
  standalone in CI and demos with **no external IdP**.
- A FastAPI dependency that enforces scopes, and the wiring of that dependency
  into the existing REST API.
- Three capability-aligned scopes reused later by the MCP server.

Out of scope (this spec):

- The MCP server and any MCP tools (sub-project 2).
- User accounts, password login, refresh-token rotation, consent UI,
  persistent client storage. The dev authorization server is for
  development/CI/demo only; production uses an external IdP via the JWKS
  verifier.
- Any change to the ForgeLab IR, spec models, or `SPEC_VERSION`.

## Boundary & dependencies

`forgelab/auth/` is **domain-agnostic** — it imports **nothing** from
`forgelab.core`, `forgelab.spec`, `forgelab.formats`, `forgelab.importers`,
`forgelab.exporters`, or `forgelab.sdk`. It depends only on `pydantic`,
`PyJWT`, and `cryptography`, plus `fastapi` in one isolated integration
submodule. Because it has zero ForgeLab dependencies, both `forgelab/api/` and
the future `forgelab/mcp/` HTTP transport reuse it identically.

New optional extra:

```
[project.optional-dependencies]
auth = ["pyjwt>=2.8", "cryptography>=42"]
```

`core` and `formats` remain dependency-free, consistent with the existing
`[agent]`, `[api]`, and (future) `[mcp]` extras. JWT libraries are imported only
inside the verifier implementations, so importing the package with auth
**disabled** does not require the extra.

## Components

### `config.py` — `AuthSettings`

A `pydantic` settings model loaded from `FORGELAB_AUTH_*` environment variables:

| Field | Default | Meaning |
|---|---|---|
| `enabled` | `False` | Master switch. When false, all endpoints are open. |
| `mode` | `"dev"` | `"dev"` (built-in HS256 issuer) or `"jwks"` (external RS256 IdP). |
| `issuer` | `"forgelab-dev"` | Expected/issued `iss` claim. |
| `audience` | `"forgelab"` | Expected/issued `aud` claim. |
| `dev_secret` | generated per process | HS256 signing secret for dev mode. |
| `jwks_url` | `None` | JWKS endpoint for `jwks` mode. |
| `access_token_ttl` | `3600` | Dev token lifetime, seconds. |

**`enabled=False` is the default**, so existing API tests and local usage are
unchanged until auth is explicitly switched on.

### `models.py`

- `Principal(sub: str, client_id: str, scopes: frozenset[str], claims: dict)` —
  the authenticated caller.
- `AuthError` hierarchy: `InvalidToken`, `ExpiredToken`, `InsufficientScope`.
  Each carries the OAuth error code (`invalid_token`, `insufficient_scope`) used
  in the `WWW-Authenticate` header.

### `verifier.py`

- `TokenVerifier` ABC: `verify(token: str) -> Principal`.
- `DevVerifier` — validates HS256 tokens issued by the dev authorization
  server (shared `dev_secret`); checks `iss`/`aud`/`exp`/signature.
- `JwksVerifier` — fetches and **caches** the JWKS from `jwks_url`, validates
  RS256 signature plus `iss`/`aud`/`exp`. The JWKS fetch is an injectable
  callable so it can be stubbed in tests (no network).
- `build_verifier(settings) -> TokenVerifier` — factory selecting the impl from
  `settings.mode`.

### `dev_server.py` — built-in authorization server (dev mode only)

In-memory only; exists so the repo is self-contained:

- `DevClientStore` — in-memory registry: `client_id → (secret, allowed_scopes,
  redirect_uris)`. Seeded from config/env for tests and demos.
- `POST /oauth/token`:
  - `grant_type=client_credentials` → validate client_id/secret, intersect
    requested scopes with allowed, issue HS256 access token.
  - `grant_type=authorization_code` → validate code + **PKCE** `code_verifier`
    against the stored `S256` challenge, issue token. Codes are single-use,
    short-TTL, in-memory.
- `GET /oauth/authorize` — auth-code flow entry; **auto-approves** in dev (no
  consent UI), stores the PKCE challenge, redirects with `code` + `state`.
- `GET /.well-known/oauth-authorization-server` — RFC 8414 metadata document
  (issuer, token/authorization endpoints, supported grant types, `S256` PKCE)
  so OAuth/MCP clients can discover the server.

`TokenResponse(access_token, token_type="Bearer", expires_in, scope)` is the
token endpoint response shape.

### `fastapi.py` — integration (the only submodule importing `fastapi`)

- `require_auth(*scopes: str)` — a dependency **factory**. Returns a dependency
  that: extracts the `Authorization: Bearer <token>` header; if
  `settings.enabled` is false, returns an anonymous `Principal` (open access);
  otherwise runs the configured verifier and enforces that every required scope
  is present; returns `Principal` or raises the mapped HTTP error.
- `mount_dev_auth(app, settings)` — mounts the dev authorization-server router
  and the well-known metadata route; called only when `mode="dev"`.

## Scopes

Capability-aligned and **reused verbatim by the MCP server** in sub-project 2:

| Scope | Grants |
|---|---|
| `forge:read` | health, spec, domain schema, system prompts, validate, list/discovery |
| `forge:export` | import (native → IR) and export (IR → native) |
| `forge:generate` | natural-language generation via `ForgeAgent` |

## REST API wiring

Applied to `forgelab/api/app.py`:

| Endpoint | Protection |
|---|---|
| `GET /health` | **public** |
| `GET /spec` | **public** |
| `GET /.well-known/oauth-authorization-server` | **public** (dev mode) |
| `POST /validate` | `require_auth("forge:read")` |
| `POST /export/{tool}` | `require_auth("forge:export")` |

With `enabled=False` (default) all of these are open, so current behavior and
tests are preserved until auth is turned on.

## Error handling

`AuthError` subclasses map centrally to responses:

- Missing / malformed / invalid-signature / wrong-issuer/audience token → `401`
  with `WWW-Authenticate: Bearer error="invalid_token"`.
- Expired token → `401` with `error="invalid_token"` (description notes
  expiry).
- Authenticated but missing a required scope → `403` with
  `WWW-Authenticate: Bearer error="insufficient_scope", scope="<needed>"`.

## Testing (offline, no real IdP)

- **Dev grant flows** via FastAPI `TestClient`: `client_credentials` and
  `authorization_code`+PKCE(S256) both issue usable tokens; a protected
  endpoint returns `200` with a valid token.
- **Negative paths**: missing token, malformed token, expired token, tampered
  signature → `401`; valid token lacking the scope → `403`.
- **`JwksVerifier`**: generate an RSA keypair in-test, build a local JWKS, sign
  a token, inject the JWKS via the stubbed fetch callable → valid token passes;
  tampered/expired/wrong-`aud` fails. Fully offline.
- **PKCE**: a mismatched `code_verifier` is rejected; a correct one succeeds.
- **Discovery**: `/.well-known/oauth-authorization-server` returns the expected
  metadata fields.
- **`enabled=False`**: protected endpoints stay open; the existing API test
  suite remains green unchanged.

## Carried forward to the MCP spec (sub-project 2)

These are recorded here so they are not lost; they are **implemented in
sub-project 2**, not here:

- The MCP server exposes four tool groups — validate + schema/prompts,
  import + export, generate (`ForgeAgent`), and list/discovery — over **both**
  stdio (local, unauthenticated) and Streamable HTTP (remote, protected by this
  `auth` module using the three scopes above).
- **`generate` must fail gracefully when the server-side `ANTHROPIC_API_KEY` is
  not configured**: the tool returns a clear, actionable error (e.g. "generation
  is unavailable: ANTHROPIC_API_KEY is not set on the server") rather than
  surfacing an internal exception or stack trace. (User requirement, attached to
  the `forge:generate` capability.)
- The official `mcp` Python SDK (FastMCP) is used under a `[mcp]` extra; core
  and `formats` stay dependency-free.

## Out-of-scope / future

- Refresh tokens, token revocation endpoint, dynamic client registration.
- Persistent (non-in-memory) client storage for the dev server.
- Rate limiting / per-client quotas.
