# Spec Delta

## Purpose

Provides a stateless MCP-over-HTTP endpoint for Odoo that authenticates each request with an existing Odoo API key and runs tool calls as that key's owner, so later capabilities can expose Odoo data without any custom identity or permission layer.

## ADDED Requirements

### Requirement: Endpoint and transport
The module SHALL expose exactly one MCP endpoint at `POST /mcp`. The endpoint SHALL accept a single JSON-RPC 2.0 request or notification per HTTP request (`Content-Type: application/json`) and SHALL answer requests with `Content-Type: application/json` (never SSE). Other HTTP methods on `/mcp` SHALL be rejected with `405`. The endpoint SHALL NOT create, require, or return an `Mcp-Session-Id`, and SHALL ignore one if sent. The endpoint SHALL NOT set a session cookie.

#### Scenario: Successful request returns JSON
- **WHEN** an authenticated client POSTs a valid `ping` request
- **THEN** the response status is `200`, the `Content-Type` is `application/json`, and the body is a JSON-RPC response with the same `id`

#### Scenario: GET and DELETE are rejected
- **WHEN** a client sends `GET /mcp` or `DELETE /mcp`
- **THEN** the response status is `405`

#### Scenario: No session state is created
- **WHEN** any request succeeds
- **THEN** the response contains no `Set-Cookie: session_id` and no `Mcp-Session-Id` header

#### Scenario: Batch or non-object bodies are rejected
- **WHEN** the body is a JSON array or any non-object JSON value
- **THEN** the response status is `400` with JSON-RPC error `-32600` and no operation is executed

#### Scenario: Unparseable body is rejected
- **WHEN** the body is not valid JSON
- **THEN** the response status is `400` with JSON-RPC error `-32700` and no operation is executed

#### Scenario: Wrong content type
- **WHEN** an authenticated request has a `Content-Type` other than `application/json`
- **THEN** the response status is `415` and no operation is executed

#### Scenario: Oversized body is rejected
- **WHEN** the request body exceeds 2 MiB
- **THEN** the response status is `413` and no operation is executed

### Requirement: Authentication with Odoo API keys
Every request to `/mcp` SHALL be authenticated with `Authorization: Bearer <key>` where `<key>` is a valid, unexpired Odoo API key of an active user, verified by Odoo's own `auth='bearer'` mechanism. The module SHALL NOT introduce any other credential type, token table, session, or login flow. A request that fails authentication SHALL be rejected with `401` and a `WWW-Authenticate: Bearer` header before any JSON-RPC processing, and SHALL execute no operation.

#### Scenario: Valid key authenticates as its owner
- **WHEN** a client sends a valid API key of user U in the Bearer header
- **THEN** the request is processed and any tool executes with `env.uid == U.id`

#### Scenario: Missing key
- **WHEN** no `Authorization` header is sent
- **THEN** the response is `401` with `WWW-Authenticate: Bearer`

#### Scenario: Invalid or malformed key
- **WHEN** the Bearer value is not a valid API key
- **THEN** the response is `401` and no tool is executed

#### Scenario: Expired or revoked key
- **WHEN** the key has passed its expiration date or has been removed
- **THEN** the response is `401`

#### Scenario: Key of an archived user
- **WHEN** the key belongs to a user whose `active` is false
- **THEN** the response is `401`

#### Scenario: Browser session cookie is not enough
- **WHEN** a request carries a valid Odoo `session_id` cookie but no Bearer header and no browser navigation headers
- **THEN** the response is `401` and no operation is executed

#### Scenario: Never public or superuser
- **WHEN** any tool executes
- **THEN** its environment user is the API key's owner, `env.su` is false, and the user is never the public user

### Requirement: Origin validation
When an `Origin` header is present, the endpoint SHALL accept the request only if the Origin's scheme and host match those of the request itself; otherwise it SHALL respond `403` and execute nothing. Requests without an `Origin` header (non-browser clients) SHALL be unaffected.

#### Scenario: No Origin header
- **WHEN** an authenticated client sends no `Origin` header
- **THEN** the request is processed normally

#### Scenario: Foreign Origin
- **WHEN** an authenticated request carries `Origin: https://evil.example` and the endpoint is served from another host
- **THEN** the response is `403`

#### Scenario: Same-origin
- **WHEN** the `Origin` header equals the request's own scheme and host
- **THEN** the request is processed normally

### Requirement: Modern protocol framing (2026-07-28)
The endpoint SHALL accept the protocol versions `2026-07-28` and `2025-11-25`. For a request declaring `MCP-Protocol-Version: 2026-07-28` the endpoint SHALL require: `params._meta["io.modelcontextprotocol/protocolVersion"]` equal to the header; an `Mcp-Method` header equal to the body `method`; and, for `tools/call`, an `Mcp-Name` header equal to `params.name` (after decoding the `=?base64?...?=` sentinel form). A violation SHALL yield HTTP `400` with JSON-RPC error `-32020` (HeaderMismatch). An unsupported version SHALL yield `400` with error `-32022` whose `data` lists `supported` versions and the `requested` one. An unknown method SHALL yield `404` with error `-32601`. Successful results for modern requests SHALL include `"resultType": "complete"`.

#### Scenario: Valid modern request
- **WHEN** a client sends `tools/list` with matching headers and `_meta`
- **THEN** the response is `200` with a JSON-RPC result containing `resultType: "complete"` and a `tools` array

#### Scenario: Header and body version mismatch
- **WHEN** the `MCP-Protocol-Version` header differs from `_meta["io.modelcontextprotocol/protocolVersion"]`
- **THEN** the response is `400` with error code `-32020`

#### Scenario: Missing Mcp-Method
- **WHEN** a modern request omits `Mcp-Method` or it differs from the body `method`
- **THEN** the response is `400` with error code `-32020`

#### Scenario: Mcp-Name mismatch
- **WHEN** a `tools/call` request has `Mcp-Name: a` but `params.name` is `b`
- **THEN** the response is `400` with error code `-32020` and the tool is not executed

#### Scenario: Unsupported version
- **WHEN** the header declares `MCP-Protocol-Version: 1900-01-01`
- **THEN** the response is `400` with error code `-32022` and `error.data.supported` includes `2026-07-28` and `2025-11-25`

#### Scenario: Unknown method
- **WHEN** a client calls a method the server does not implement (for example `resources/list`)
- **THEN** the response is `404` with error code `-32601`

#### Scenario: Notification
- **WHEN** a client POSTs a JSON-RPC notification (no `id`) such as `notifications/initialized`
- **THEN** the response is `202` with an empty body

### Requirement: Caching hints on cacheable results
For modern (2026-07-28) requests, the `server/discover` and `tools/list` results with `resultType: "complete"` SHALL include `ttlMs` (an integer, at least 0) and `cacheScope` (`"public"` or `"private"`), as the MCP specification requires and current clients validate. The endpoint SHALL use `ttlMs` of 300000 and `cacheScope` of `"public"` for both, because the tool set is identical for every user and changes only when the addon is upgraded. Other results (`ping`, `tools/call`) and all legacy-revision results SHALL NOT carry these fields.

#### Scenario: tools/list carries cache hints
- **WHEN** a modern client calls `tools/list`
- **THEN** the result contains `resultType: "complete"`, an integer `ttlMs >= 0`, and `cacheScope` equal to `"public"` or `"private"`

#### Scenario: server/discover carries cache hints
- **WHEN** a modern client calls `server/discover`
- **THEN** the result contains an integer `ttlMs >= 0` and a valid `cacheScope`

#### Scenario: Non-cacheable and legacy results carry none
- **WHEN** a modern client calls `ping` or `tools/call`, or a legacy client calls `tools/list`
- **THEN** the result contains neither `ttlMs` nor `cacheScope`

#### Scenario: Tool entries match the tool schema
- **WHEN** `tools/list` is returned
- **THEN** each tool has a string `name` and `description`, an `inputSchema` of `type: "object"` with a `properties` object, and `annotations` limited to boolean hint fields

### Requirement: Discovery and legacy handshake
The endpoint SHALL implement `server/discover`, returning `supportedVersions` (`2026-07-28`, `2025-11-25`), `capabilities` declaring only `tools` (with `listChanged` false), `_meta["io.modelcontextprotocol/serverInfo"]` (name `odoo_mcp` and the addon version), and short `instructions` telling the agent that it acts with the authenticated user's Odoo permissions. The endpoint SHALL also implement the legacy `initialize` request statelessly: it SHALL respond with the client's requested `protocolVersion` if supported and otherwise with `2025-11-25`, the same capabilities and server info, and no session id. `ping` SHALL return an empty result.

#### Scenario: server/discover
- **WHEN** an authenticated client calls `server/discover`
- **THEN** the result lists both supported versions, declares the `tools` capability only, and includes server info

#### Scenario: Legacy initialize
- **WHEN** a client sends `initialize` with `protocolVersion: "2025-11-25"` and no `MCP-Protocol-Version` header
- **THEN** the response is a JSON-RPC result with `protocolVersion: "2025-11-25"`, `capabilities.tools`, `serverInfo`, and no `Mcp-Session-Id` header

#### Scenario: Legacy initialize with unknown version
- **WHEN** `initialize` requests `protocolVersion: "1999-01-01"`
- **THEN** the result's `protocolVersion` is `2025-11-25`

#### Scenario: Legacy follow-up requests
- **WHEN** a legacy client, after `initialize`, sends `tools/list` with `MCP-Protocol-Version: 2025-11-25` and no `_meta` or `Mcp-Method`
- **THEN** the request is processed without error and the result carries no `resultType`

### Requirement: Tool listing and calling boundary
`tools/list` SHALL return every registered tool with `name`, `description`, `inputSchema` (JSON Schema object) and `annotations` (`readOnlyHint`, `destructiveHint`, `idempotentHint`), in deterministic order (sorted by name), without pagination. `tools/call` for an unknown tool SHALL return JSON-RPC error `-32602`. A tool call SHALL execute with the authenticated `request.env`, inside a database savepoint that is flushed before it is released, so that an exception rolls back every change the call made. Tools SHALL NOT accept a `context` argument and SHALL NOT alter the environment's user. Tool input that fails validation (wrong type, unknown argument, missing required argument) SHALL be returned as a tool result with `isError: true`, not as a JSON-RPC error. A successful tool result SHALL contain a `structuredContent` object and a `content` text block with the same JSON serialized.

#### Scenario: Empty tool table
- **WHEN** no tool is registered and the client calls `tools/list`
- **THEN** the result contains `"tools": []`

#### Scenario: Unknown tool
- **WHEN** the client calls `tools/call` with `name: "does_not_exist"`
- **THEN** the response contains JSON-RPC error `-32602`

#### Scenario: Invalid arguments
- **WHEN** a registered tool is called with an unknown argument or a wrong-typed argument
- **THEN** the result has `isError: true` with a message naming the offending argument, and the handler is not executed

#### Scenario: Failure rolls back the call
- **WHEN** a tool handler performs a write and then raises an exception
- **THEN** the write is rolled back, the response is a tool result with `isError: true`, and later calls see no trace of the write

#### Scenario: Successful call commits
- **WHEN** a tool handler performs a write and returns normally
- **THEN** the change is committed by the surrounding Odoo request

#### Scenario: Deterministic listing
- **WHEN** `tools/list` is called twice
- **THEN** the tools appear in the same order (sorted by name) both times

### Requirement: Error mapping without leakage
Odoo user-facing exceptions raised by a tool (`AccessError`, `UserError`, `ValidationError`, `MissingError`, and their subclasses) SHALL be returned as a tool result with `isError: true` and Odoo's own message. Any other exception SHALL be logged server-side with its traceback and returned as a tool result with `isError: true` and generic text beginning with `Internal error`, with no traceback, SQL, file paths, or exception class names. Odoo's HTTP-layer debug data (`serialize_exception` output) SHALL never appear in any `/mcp` response, whatever the status.

#### Scenario: AccessError passes through as a tool error
- **WHEN** a tool triggers an `AccessError`
- **THEN** the result has `isError: true` and Odoo's access message, and the HTTP status is `200`

#### Scenario: Unexpected exception is generic
- **WHEN** a handler raises `RuntimeError("secret /path/x.py")`
- **THEN** the result text begins with `Internal error`, the traceback is in the server log, and the response contains neither the exception text nor a path

#### Scenario: No debug payload on protocol errors
- **WHEN** any protocol-level error is returned (including `400`, `401`, `403`, `405`, `413`, `415`)
- **THEN** the body contains no Odoo `debug` traceback, exception class name, or file path; JSON-RPC errors carry only `code`, `message`, and optional MCP-defined `data`

### Requirement: No implicit privilege escalation in the endpoint
The endpoint and tool boundary SHALL NOT call `sudo()`, `with_user(SUPERUSER_ID)`, or `with_env` to change the request user for any tool execution, and SHALL NOT expose arbitrary method invocation, Python evaluation, SQL, or shell execution.

#### Scenario: Source scan for escalation
- **WHEN** the addon's Python sources under `controllers/`, `protocol.py` and `tools/` are scanned
- **THEN** none contains `sudo(`, `SUPERUSER_ID`, `with_user(`, `eval(`, `safe_eval`, `execute(` on a cursor, or `subprocess`

#### Scenario: Tool executes as the key owner
- **WHEN** a test tool reports `env.uid` and `env.su`
- **THEN** it returns the API-key owner's uid and `su` is false
