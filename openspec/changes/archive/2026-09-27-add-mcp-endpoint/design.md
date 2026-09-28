# Design

## Context

See `proposal.md`. Facts established by reading the Odoo 19 source (`/Users/razs/production/odoo_src/odoo`) that this design relies on:

- `@http.route(auth='bearer')` is implemented by `ir.http._auth_method_bearer` (`odoo/addons/base/models/ir_http.py:212`). It reads `Authorization: Bearer`, calls `res.users.apikeys._check_credentials(scope='rpc', key=...)`, then `request.update_env(user=uid)` and marks the session unsaveable. It raises `Unauthorized` with `WWW-Authenticate: Bearer` on failure. With no header it falls back to a session cookie **only if** browser navigation `Sec-Fetch-*` headers are present, so API clients without a Bearer header get `401`. Routes with `auth='bearer'` default to `save_session=False`.
- Only *global* API keys (`scope IS NULL`) pass that check, and the UI only creates global keys for internal users. So the MCP credential is an ordinary Odoo API key; it also works on `/json/2` and XML-RPC. That is accepted: identity and ACLs are identical across all three.
- `type='jsonrpc'` is unsuitable: it ignores the JSON-RPC `method`, wraps every result in Odoo's own envelope and error shape, and answers notifications with a body (`odoo/http.py:2543-2636`). `type='json2'` (`Json2Dispatcher`, `http.py:2638`) returns the endpoint's value as the raw JSON body, but its error handler (`handle_error`) serializes *every* exception, including plain `Unauthorized`/`BadRequest`/`413`, through `serialize_exception`, which always includes a `debug` traceback (`http.py:469-479`) — so pre-controller errors (401, 400, 413, 415) would leak server file paths. `type='http'` (`HttpDispatcher`, `http.py:2472`) returns plain werkzeug error responses (no traceback) and, with `csrf=False`, leaves the body untouched. This evidence changes the exploration's preferred carrier: **use `type='http'`**.
- The request wrapper (`http.py:2300-2330`) runs the endpoint with `retrying`, commits on success, and rolls back if an exception escapes. Exceptions the controller *catches* do not roll back, hence the explicit savepoint. `cr.savepoint()` defaults to `flush=True` (`odoo/sql_db.py:217`), so deferred ORM writes and constraint errors surface inside the savepoint.
- Odoo runs with `workers = 2` in this deployment (`odoo.conf`), so any in-process state is per worker (relevant to change 5).
- MCP spec 2026-07-28 (fetched from modelcontextprotocol.io): single POST endpoint, no sessions, per-request `_meta`, `MCP-Protocol-Version`/`Mcp-Method`/`Mcp-Name` headers, `-32020` HeaderMismatch, `-32022` UnsupportedProtocolVersion, 404+`-32601` for unknown methods, 202 for notifications, `server/discover` mandatory. Legacy 2025-11-25 clients open with `initialize`; a dual-era server MAY serve both on one endpoint, and session ids are optional in the legacy revision, so a stateless server is compliant.

## Goals / Non-Goals

**Goals:**
- One route, one small pure-Python protocol module, one small tool table.
- Every tool executes as the key owner via `request.env`, in a rolled-back-on-failure unit.
- Protocol code testable without a running server (pure functions).

**Non-Goals:**
- OAuth / DCR / `WWW-Authenticate resource_metadata`, scoped keys, SSE, sessions, resources, prompts, pagination of tools, rate limiting (change 5), deny-list (change 5), any actual tool (changes 2-4).
- Supporting protocol versions other than `2026-07-28` and `2025-11-25`.

## Decisions

**D1. Layout (small, no layers).**
```
odoo_mcp/
  controllers/__init__.py
  controllers/main.py     # route: auth, Origin check, body parse, calls protocol.handle()
  protocol.py             # pure: framing, header validation, method table, error builders
  tools/__init__.py       # Tool NamedTuple + TOOLS registry + register()/call_tool()
  tests/                  # TransactionCase / HttpCase tests
```
`Tool = NamedTuple(name, title, description, input_schema, annotations, handler)`; `handler(env, arguments: dict) -> dict` returns the structured result. `register(tool)` adds to a module-level dict at import time; later changes add modules under `tools/` and import them from `tools/__init__.py`. Alternative considered: a plugin/entry-point framework — rejected (speculative, CLAUDE.md §13).

**D2. Route.** `@http.route('/mcp', type='http', auth='bearer', methods=['POST'], csrf=False, save_session=False, max_content_length=2 * 1024 * 1024)`. `csrf=False` is safe because authentication is a Bearer header, not a cookie (the bearer method rejects cookie-only requests that lack browser navigation headers). Werkzeug's method routing produces `405` for other verbs. The controller reads `request.httprequest.get_data()`, requires `mimetype == 'application/json'` (else `415`), parses JSON itself (`-32700`/`-32600` on failure), and always returns either `request.make_json_response(...)` (which sets JSON `Content-Type`) or an empty `Response(status=202)`. `max_content_length` makes werkzeug raise `413` when the body is read. `HttpDispatcher.handle_error` turns `Unauthorized`/`HTTPException` into plain responses without tracebacks. Do not use `type='jsonrpc'` (wrong envelope) or `type='json2'` (leaks `debug` on pre-controller errors). **Task 1.1 is a spike** to confirm on the real dispatcher that a valid call reaches the controller, that `401` carries `WWW-Authenticate: Bearer`, and that no traceback appears in 401/405/413 bodies.

**D3. Era detection.** A request is *legacy* when its method is `initialize`, or its `MCP-Protocol-Version` header is `2025-11-25`. It is *modern* when the header is `2026-07-28`. A missing header on any method other than `initialize` → `400` `-32020`. Modern requests get the full header/`_meta` validation and `resultType: "complete"`; legacy requests get neither. Any other header value → `400` `-32022`. `Accept` is not validated (lenient). `Origin` validation happens after authentication and before dispatch (`403`).

**D4. Method table (in `protocol.py`).** `initialize`, `ping`, `server/discover`, `tools/list`, `tools/call`, and notifications (any method starting with `notifications/`, or any message without `id`) → `202`. Everything else → `404`/`-32601` (modern) or `200` + `-32601` body (legacy, since legacy clients treat 404 specially). Capability advertised: `{"tools": {"listChanged": false}}`. `serverInfo.version` is read from the addon manifest at import time (not hard-coded).

**D5. `tools/call` boundary (in `tools/__init__.py`, `call_tool(env, name, arguments)`):**
0. `ToolError(message)` (defined here, in `tools/__init__.py`) is the tool-level, user-facing error a handler raises deliberately; it is mapped to `isError` with its message.
1. Unknown name → protocol error `-32602`.
2. Reject unknown/missing/wrong-typed arguments against the tool's `input_schema` using a tiny in-repo validator (`type`, `required`, `additionalProperties: false`, `minimum/maximum`, `minLength/maxLength`, `maxItems`, `items` type, `enum`). No `jsonschema` dependency (nothing may be installed); each tool keeps its schema simple enough for this validator.
3. `with env.cr.savepoint(): result = tool.handler(env, arguments)`. Mapping: `(AccessError, UserError, ValidationError, MissingError)` (all `UserError`/`AccessError` subclasses; `ValidationError` is a `UserError`) and `ToolError` → `isError` with `str(exc)`. Any other `Exception` → `_logger.exception(...)` and `isError` with text `Internal error` (change 5 appends a correlation reference).
4. Success → `{content:[{type:"text", text: json.dumps(result, default=json_default)}], structuredContent: result, isError: false}`.
`env` is exactly `request.env`. The `tools/call` params never influence `env` (no `context`, no `uid`).

**D5b. Caching hints.** The 2026-07-28 caching page says servers MUST include `ttlMs` (integer >= 0) and `cacheScope` (`public`|`private`) on complete `server/discover`, `tools/list` (and other list/read) results; Claude Code rejects a `tools/list` result without them (found in live testing). `protocol.handle_message` adds `ttlMs=300000`, `cacheScope='public'` for those two methods, modern requests only. `public` is correct because the tool list does not vary per user; the list of *models* (a per-user result) is returned by a tool call, which is never given cache hints.

**D6. Rejected alternatives.** Reusing `/json/2/<model>/<method>` directly (exposes every public method, not MCP-framed); a `mcp.session`/token model (Odoo API keys already exist); a custom `_auth_method_mcp` with scoped keys (no UI to create scoped keys; only extra surface); SSE (nothing streams).

## Risks / Trade-offs

- [The MCP key is a global RPC key, usable on `/json/2` too] → Same user, same ACLs; documented in change 5. Scoped keys deliberately not built.
- [Pre-controller failures (401, 405, 413) have plain werkzeug bodies, not JSON-RPC] → The spec pins only status (and `WWW-Authenticate` for 401) and forbids tracebacks; MCP clients key off status.
- [Some MCP clients (web connectors) require OAuth] → Out of scope; documented in change 5.
- [`type='http'` + `csrf=False` on a bearer route is unproven here] → Task 1.1 spike before anything else; if a blocker appears, stop and report rather than switching to `json2` (which leaks tracebacks).
- [Savepoint + `retrying`: Odoo may re-run the request on serialization failure] → Tool handlers must be free of non-DB side effects before commit; true for CRUD tools.
- [`workers = 2`] → No shared in-process state is introduced here.
