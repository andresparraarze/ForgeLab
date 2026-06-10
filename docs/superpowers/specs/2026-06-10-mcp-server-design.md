# ForgeLab MCP Server — Design

**Date:** 2026-06-10
**Status:** Approved
**Spec bump:** none (no IR/spec model change; new optional `forgelab.mcp` package + `[mcp]` extra)

## Goal

Expose ForgeLab's capabilities as **MCP tools** so MCP-speaking agents (Claude
Code, Hermes, OpenClaw) can validate, generate, import, and export ForgeLab IR
directly in their workflows. The server is a **thin layer** over the existing
core compiler, registry, and AI SDK. It runs over **two transports**: stdio
(local, unauthenticated) and **Streamable HTTP** (remote, OAuth-protected by the
shared `forgelab.auth` module using the three existing scopes).

This is sub-project 2 of two. Sub-project 1 (`forgelab.auth`) is merged; this
spec consumes it. It is its own spec → plan → implementation cycle.

## Scope

In scope:

- A `forgelab/mcp/` package built on the **official MCP Python SDK** (`FastMCP`),
  added under a new optional `[mcp]` extra.
- **All four tool groups**: validate + schema/prompts, import + export,
  generate (`ForgeAgent`), and list/discovery.
- **Both transports** from one tool definition set: stdio and Streamable HTTP.
- **OAuth on the HTTP transport** via an adapter that bridges the MCP SDK's
  `TokenVerifier` to `forgelab.auth`, plus **per-tool scope enforcement**
  reusing `forge:read` / `forge:export` / `forge:generate`.
- The **`generate` tool returns a clear, actionable error when the server-side
  `ANTHROPIC_API_KEY` is not configured** (or the `[agent]` extra is missing) —
  never an internal stack trace.
- A CLI entry point to run either transport.

Out of scope (this spec):

- Issuing tokens. The MCP server is an OAuth **resource server only** — it
  validates bearer tokens. Tokens come from the dev authorization server in the
  REST API (`forgelab.auth.dev_server`) or an external IdP. No client
  registration, consent UI, or token storage here.
- MCP **resources** and **prompts** primitives — v1 exposes **tools** only.
- New ForgeLab domains, transform passes, glTF/Gerber/etc. expansion.
- Any change to the ForgeLab IR, spec models, or `SPEC_VERSION`.

## Boundary & dependencies

`forgelab/mcp/` is a **frontend**, peer to `forgelab/api/`. It may depend on
`forgelab.core` (validate, `default_registry`, errors), `forgelab.spec`
(`ForgeDocument`), `forgelab.sdk` (`domain_schema`, `system_prompt`, `few_shot`,
`ForgeAgent`), and `forgelab.auth`. Like `api/`, it reaches importers/exporters
**only through the registry** — it never imports `forgelab.importers` or
`forgelab.exporters` directly. The MCP SDK (`import mcp`) is confined to
`forgelab/mcp/`.

New optional extra:

```toml
[project.optional-dependencies]
mcp = ["mcp>=1.12"]
```

`mcp` is also added to `[dev]` so the test suite can import it. `core` and
`formats` stay dependency-free.

**Naming gotcha:** the MCP SDK has its own `AuthSettings`
(`mcp.server.auth.settings.AuthSettings`) which collides with
`forgelab.auth.config.AuthSettings`. Import the SDK one aliased
(`from mcp.server.auth.settings import AuthSettings as McpAuthSettings`) to keep
the two unambiguous.

## Tools

Each tool is a thin wrapper. Failures that an agent should read and react to
(unknown format, unimplemented stub, missing API key, bad input) surface as a
**clear error message** (raised — the SDK returns it as an error result without
leaking a traceback). `validate_document` is the one exception: a `valid: false`
result is a *normal* return, not an error, mirroring the REST API.

### Group 1 — Validate + schema/prompts (`forge:read`)

| Tool | Signature | Behavior |
|---|---|---|
| `validate_document` | `(document: dict) -> dict` | `forgelab.core.validate`; returns `{"valid": true}` or `{"valid": false, "error": "..."}`. Never raises on invalid input. |
| `get_domain_schema` | `(domain: str) -> dict` | `forgelab.sdk.domain_schema(domain)`; unknown domain → clear error. |
| `get_prompt` | `(domain: str) -> dict` | `{"system": system_prompt(domain), "few_shot": few_shot(domain)}`. |

### Group 2 — List / discovery (`forge:read`)

| Tool | Signature | Behavior |
|---|---|---|
| `list_domains` | `() -> list[str]` | Keys of `DOMAIN_VOCAB` (hardware, threed, mechanical). |
| `list_formats` | `() -> dict` | Registry contents: each format tool (kicad, gltf, freecad, …) with `import`/`export` availability flags. Named `formats` to avoid confusion with MCP "tools". |

`Registry` currently exposes only `register_*` / `get_*` (which raise on miss).
`list_formats` needs to enumerate registered tools, so this work adds a small
read-only accessor to `forgelab.core.Registry` (e.g. `tool_names() -> dict[str,
dict[str, bool]]` mapping tool → `{"import": bool, "export": bool}`). This is the
only change outside `forgelab/mcp/`, and it is additive (no behavior change).

### Group 3 — Import + export (`forge:export`)

| Tool | Signature | Behavior |
|---|---|---|
| `export_document` | `(document: dict, tool: str) -> dict` | validate → `registry.get_exporter(tool)().from_ir(doc)` → bytes encoded as `{"tool", "encoding", "content"}`. `UnknownToolError` → clear error; `NotImplementedError` (stub) → "format not implemented" error. |
| `import_file` | `(tool: str, content: str, encoding: str = "utf-8") -> dict` | decode content → `registry.get_importer(tool)().to_ir(bytes)` → `document.model_dump()`. Unknown tool / parse failure → clear error. |

**Content encoding helper.** Exporter output is `bytes`. The helper tries UTF-8
decode and returns `{"encoding": "utf-8", "content": <text>}`; on failure
(binary, e.g. the FCStd zip) returns `{"encoding": "base64", "content":
<base64>}`. `import_file` accepts the same `encoding` discriminator. This single
shape works for text (KiCad S-expr, glTF JSON) and binary (FCStd) uniformly.

### Group 4 — Generate (`forge:generate`)

| Tool | Signature | Behavior |
|---|---|---|
| `generate_document` | `(prompt: str, domain: str, model: str = "claude-opus-4-8") -> dict` | NL → validated `ForgeDocument` via `ForgeAgent`. Returns `document.model_dump()`. |

**`ANTHROPIC_API_KEY` graceful error (required).** Before constructing the
agent, the tool checks `os.environ.get("ANTHROPIC_API_KEY")`. If unset/empty it
raises a clear, actionable error — e.g. *"generation unavailable:
ANTHROPIC_API_KEY is not set on the server"* — and never constructs the Anthropic
client. If the `[agent]` extra is not installed, `ForgeAgent`'s `ImportError` is
caught and re-surfaced as *"generation unavailable: install the agent extra
(`pip install forgelab[agent]`)"*. `LLMOutputError` and unknown-domain errors
become clear messages too. A **testing seam** (`_make_agent(model)` indirection)
lets tests inject a fake agent without network or a real key.

## Transports & server assembly

A single `create_server(auth_settings: forgelab.auth.AuthSettings | None) ->
FastMCP` registers all tools, then:

- **stdio** (local): `create_server(None)` — no token verifier; tools run
  unauthenticated (trusted local process).
- **Streamable HTTP** (remote): `create_server(settings)` where
  `settings.enabled` is true → `FastMCP(..., token_verifier=ForgeLabTokenVerifier(settings),
  auth=McpAuthSettings(issuer_url=..., resource_server_url=..., required_scopes=[]),
  stateless_http=True, json_response=True)`. `required_scopes=[]` means a valid
  token is required to connect, with the **specific** scope enforced per tool.

`forgelab/mcp/__main__.py` provides the CLI:
`python -m forgelab.mcp --transport {stdio|streamable-http} [--host --port]`
(default stdio). A `forgelab-mcp` console script is also added. HTTP mode reads
auth config from the same `FORGELAB_AUTH_*` env the REST API uses (so one
deployment shares issuer/audience/secret/JWKS), plus two MCP-specific URLs for
RFC 9728 Protected Resource Metadata:

- `FORGELAB_MCP_ISSUER_URL` — the OAuth AS clients should authenticate against
  (dev: the REST API's dev server, e.g. `http://localhost:8000`; prod: the IdP).
- `FORGELAB_MCP_RESOURCE_URL` — this MCP server's own public URL (default
  `http://localhost:8001`).

These URLs are **discovery metadata only**. Actual token validation (signature,
`iss`, `aud`, `exp`) is done by `forgelab.auth`'s verifier, which checks `iss`
against `FORGELAB_AUTH_ISSUER` — that value may be a non-URL string like
`forgelab-dev` and is independent of `FORGELAB_MCP_ISSUER_URL`.

## Auth bridge & scope enforcement

`forgelab/mcp/auth_bridge.py`:

- `ForgeLabTokenVerifier(TokenVerifier)` — `async verify_token(token) ->
  AccessToken | None`: calls `build_verifier(settings).verify(token)`; on success
  maps the `forgelab.auth.Principal` to the SDK's `AccessToken(token=token,
  client_id=principal.client_id, scopes=list(principal.scopes),
  subject=principal.sub, claims=principal.claims)`; on `AuthError` returns `None`
  (the SDK responds 401). The method is `async` per the SDK protocol but the
  underlying verification is fast/sync (JWKS keys are cached by the verifier).
- `require_scope(scope: str) -> None` — called at the top of each tool. Reads
  `get_access_token()`. **If `None`** (stdio / no auth active) → allowed (trusted
  local). **If present** and `scope not in token.scopes` → raise a clear
  "missing required scope: <scope>" error (the agent sees an error result).

This gives the right matrix: stdio = full local access; HTTP = a valid token is
required to connect, and each tool additionally requires its specific scope.

## File structure

- `forgelab/mcp/__init__.py` — light exports (`create_server`).
- `forgelab/mcp/content.py` — `encode_bytes`/`decode_content` helper (no SDK import).
- `forgelab/mcp/auth_bridge.py` — `ForgeLabTokenVerifier`, `require_scope`.
- `forgelab/mcp/tools.py` — the tool callables + a `register(mcp)` function.
- `forgelab/mcp/server.py` — `create_server(auth_settings)` assembling FastMCP + transport/auth config.
- `forgelab/mcp/__main__.py` — CLI entry (`main()` + `forgelab-mcp` script).
- `pyproject.toml` — `[mcp]` extra, `mcp` in `[dev]`, `[project.scripts]` entry.

## Testing (offline, no network, no real key)

- **Tool unit tests** call the callables directly: `validate_document`
  (valid + invalid), `get_domain_schema`/`get_prompt` (per domain + unknown),
  `list_domains`/`list_formats`, `export_document` + `import_file`
  **round-trip** (e.g. the box-with-hole doc → FCStd base64 → back to IR),
  unknown-tool and stub `NotImplementedError` paths.
- **Generate**: (a) with `ANTHROPIC_API_KEY` unset → the graceful error fires and
  no Anthropic client is constructed; (b) happy path via an injected fake agent
  (the `_make_agent` seam) returning a known document — no network, no key.
- **Auth bridge**: `ForgeLabTokenVerifier.verify_token` maps a real dev HS256
  token (issued via `forgelab.auth`) to an `AccessToken` with the right scopes;
  an invalid token → `None`. `require_scope`: `None` token → allowed; token
  missing the scope → raises; token with the scope → passes.
- **Server assembly**: `create_server(None)` registers the expected tool names
  (stdio); `create_server(enabled_settings)` attaches the token verifier. An
  end-to-end check uses the MCP SDK's in-memory client/session to list tools and
  invoke one round-trip. Auth-path coverage relies on the bridge unit tests plus
  the verified `forgelab.auth` suite (already merged), keeping these tests
  network-free.

## Risks & mitigations

- **SDK API drift** (`mcp>=1.12`): pin a floor; the auth/transport API used here
  (`FastMCP`, `TokenVerifier`, `AccessToken`, `get_access_token`,
  `run(transport=...)`) is confirmed against the current SDK docs. Confined to
  `forgelab/mcp/` so churn is localized.
- **Blocking calls in async server**: tool callables are sync; FastMCP runs sync
  tools off the event loop. The one network call (`ForgeAgent.design`) lives in a
  sync tool, so it won't block the loop.
- **Scope-on-connect vs per-tool**: baseline `required_scopes=[]` + per-tool
  `require_scope` deliberately separates "authenticated" from "authorized for
  this action," so a `forge:export`-only token can call export without needing
  `forge:read`.

## Out-of-scope / future

- MCP resources/prompts primitives; streaming progress for long generations.
- Dynamic client registration; the MCP server issuing its own tokens.
- Exposing transform passes / a compile pipeline tool once those land in core.
