# Tasks

## 1. Sensitive-model deny-list

- [x] 1.1 Add `DENIED_MODELS` and the deny check (first) to `_is_exposed` in `tools/models.py`; verify unit tests that each listed model is hidden from `list_models` and returns the same `Unknown model` text as a nonexistent model, for an administrator
- [x] 1.2 Add the parametrized test "every model-taking tool × every denied model × administrator" (read, search_read, search_count, describe_model, create, write, unlink) plus the extra-argument scenario; verify all return `isError` `Unknown model` and change nothing

- [x] 1.3 Treat relational fields whose comodel is denied as unavailable (hidden from `describe_model`/default reads, rejected in `fields`/`values`, and top-level domain paths traversing into them rejected) via `reaches_denied_model` in `tools/models.py`; verify tests with `res.users.api_key_ids` (found by the implementation review)

## 2. Error hygiene

- [x] 2.1 Implement message truncation (1,000 chars + `…`) and the `Internal error (ref: xxxxxxxx)` reference with matching log entry in `tools/__init__.py`; verify tests for long messages, unique refs, and the log containing the ref and traceback
- [x] 2.2 Add the error-scan test that triggers auth failure, malformed JSON, header mismatch, unknown tool, tool error, unexpected exception (including a psycopg `IntegrityError` at flush), `413`, and `429`, and asserts no `Traceback`, `.py`, `psycopg2`, `File "`, or `debug` in any body; verify it passes

## 3. Rate limiting

- [x] 3.1 Create `ratelimit.py` (`SlidingWindow`, injectable clock, bounded memory) per design D3; verify unit tests: under limit, over limit with `Retry-After`, window recovery, per-(db,user) independence, idle-bucket cleanup
- [x] 3.2 Call the limiter in `controllers/main.py` after authentication and before body parsing, returning `429` + `Retry-After` + JSON-RPC `-32029`; verify `HttpCase` tests: 121st request rejected and executes nothing, another user unaffected, invalid-key floods return `401` without consuming a budget

## 4. Audit logging

- [x] 4.1 Add the audit line per design D4 (whitelisted fields, category mapping, exceptions swallowed); verify tests using `assertLogs('odoo.addons.odoo_mcp.audit')` for success, ACL denial (`category=access`), denied model (`category=tool`), and that a written value and the API key never appear in any line

## 5. Guards and parity

- [x] 5.1 Add the addon-wide source-scan test and the exact-tool-inventory test (design D5/D6); verify they pass and fail on an injected forbidden token / an extra registered tool in a temp copy
- [x] 5.2 Add the end-to-end parity `HttpCase` matrix from design D8 (all tools × user matrix, plus alternating keys of two users); verify outcome classes and data equal the direct ORM calls except for resolver/deny-list hiding

## 6. Documentation

- [x] 6.1 Write README "Connecting an MCP client" with all sub-sections required by the `mcp-client-setup` spec, using only placeholders (`<api-key>`, `<database>-odoo.<domain>`); verify Claude Code syntax against Claude Code's current documentation and run the `curl` smoke test on a scratch database (valid key → `200`, bad key → `401`)
- [x] 6.2 Add `tests/test_docs.py` (README tool table equals the registry; required headings present; no key/password/hostname patterns in README and CLAUDE.md); verify it passes and fails when a tool is added without docs (temp copy)
- [x] 6.3 Update README "Status" and add the "Implemented surface" section to `CLAUDE.md`; verify by reading both and by the docs test

## 7. Wrap-up

- [x] 7.1 Run `python odoo-bin -d <scratch>-odoo --test-tags /odoo_mcp --stop-after-init` and `openspec validate --all --strict`; verify both pass
- [x] 7.2 Operator live acceptance (performed by the operator against the production Odoo): Claude Code connected with an Odoo API key; tool discovery, reads, an update of an existing `project.task`, and a disposable create/read/unlink cycle all succeeded
