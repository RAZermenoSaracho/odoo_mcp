# Tasks

## 1. Spike and skeleton

- [x] 1.1 In a scratch test (not committed), register a throwaway `type='http'`, `auth='bearer'`, `csrf=False` route and confirm with `HttpCase` that a valid key reaches the controller, that a missing key returns `401` with `WWW-Authenticate: Bearer`, and that 401/405/413 bodies contain no traceback; record the outcome in a comment at the top of `controllers/main.py` (stop and report if any check fails — do not switch to `type='json2'`)
- [x] 1.2 Create `controllers/__init__.py`, `controllers/main.py`, `protocol.py`, `tools/__init__.py`, `tests/__init__.py`; import them from `odoo_mcp/__init__.py`; verify the module still installs on a scratch test database (`odoo-bin -d <scratch>-odoo -i odoo_mcp --stop-after-init` in the `odoo19` env, never a production database)

## 2. Protocol module (`protocol.py`)

- [x] 2.1 Implement JSON-RPC parsing/validation (object body, `jsonrpc == "2.0"`, `method` str, `id` int/str/absent) and error builders for `-32700/-32600/-32601/-32602/-32020/-32022`; verify with pure unit tests
- [x] 2.2 Implement era detection, `MCP-Protocol-Version`/`_meta` match, `Mcp-Method` and `Mcp-Name` validation (including `=?base64?...?=` decoding) per spec "Modern protocol framing"; verify each spec scenario has a unit test
- [x] 2.3 Implement `server/discover`, legacy `initialize`, `ping`, notification handling (`202`), and `resultType` injection for modern results; `serverInfo.version` read from the manifest; verify with unit tests

- [x] 2.4 Add `ttlMs`/`cacheScope` to modern `server/discover` and `tools/list` results (design D5b); verify contract tests for cacheable, non-cacheable and legacy results

## 3. Tool table and call boundary (`tools/__init__.py`)

- [x] 3.1 Implement `Tool`, `ToolError`, `register()`, `TOOLS`, deterministic `tools/list` output, and the minimal input validator (`type`, `required`, `additionalProperties`, `minimum`, `maximum`, `minLength`, `maxLength`, `maxItems`, `enum`, `items`); verify with unit tests for each keyword
- [x] 3.2 Implement `call_tool(env, name, arguments)` with the savepoint, error mapping, and result shaping from design D5; verify with `TransactionCase` tests using a test-only tool that writes then raises (write rolled back) and one that reports `env.uid`/`env.su`

## 4. Route (`controllers/main.py`)

- [x] 4.1 Implement `POST /mcp` per design D2/D3 with Origin validation and `Response` construction; verify `HttpCase` tests for: valid key, missing key, invalid key, expired key, archived-user key, cookie-only request, Origin cases, 405 on GET/DELETE, 413, 415, invalid JSON (`-32700`), non-object bodies (`-32600`), no traceback in any error body, no `Set-Cookie`/`Mcp-Session-Id`
- [x] 4.2 Add `HttpCase` tests for modern and legacy framing scenarios in the spec (`tools/list`, `server/discover`, `initialize`, mismatch errors, unknown method, notification `202`, unknown tool)
- [x] 4.3 Add a source-scan test asserting `controllers/`, `protocol.py`, `tools/` contain none of `sudo(`, `SUPERUSER_ID`, `with_user(`, `eval(`, `safe_eval`, `subprocess`, `.execute(`; verify it passes and fails when a forbidden token is injected in a temp copy

## 5. Wrap-up

- [x] 5.1 Run `python odoo-bin -d <scratch>-odoo --test-tags /odoo_mcp --stop-after-init` and confirm all tests pass; run `openspec validate add-mcp-endpoint --strict`
