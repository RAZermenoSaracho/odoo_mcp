# Design

## Context

See `proposal.md`. Depends on changes 1-4. Facts this design relies on:

- Change 2 created the single choke point `tools/models.py::_is_exposed(env, name)` used by `resolve_model` and `list_models`; changes 3-4 reach models only through `resolve_model`. That is where the deny-list goes.
- Change 1's `call_tool` boundary maps exceptions to `isError`; change 1 emits generic text beginning with `Internal error` and logs the traceback.
- The deployment runs `workers = 2` (`odoo.conf`), so any in-process state (the rate limiter) is per worker. A shared limiter would need a database table or external store, which is new infrastructure that CLAUDE.md §13/§14 discourages for this scope.
- Admins hold ACLs on the risky models: `res.users.apikeys` (credentials), `ir.config_parameter` (system parameters, may hold secrets), `ir.rule`/`ir.model.access` (security definitions), `ir.model`/`ir.model.fields` (schema changes), `ir.actions.server`/`ir.cron` (scheduled Python execution), `ir.module.module` (install/upgrade). Plain CRUD on these amounts to privilege escalation or code execution for a prompt-injected agent, even though each is "allowed" by ACL for an admin.
- `res.users.apikeys.description`/`.show` are transient/abstract and already hidden by the resolver; listing them documents intent.

## Goals / Non-Goals

**Goals:** a tiny, explicit, code-reviewed deny-list; consistent error hygiene; simple throttling; a useful audit line; docs that cannot drift from the tool set.

**Non-Goals:** runtime configuration of the deny-list or limits, per-model allow-lists, a shared/distributed rate limiter, IP allow-listing, alerting, log shipping, OAuth, scoped keys.

## Decisions

**D1. Deny-list as a module constant.** `DENIED_MODELS = frozenset({...})` in `tools/models.py`, checked first inside `_is_exposed` (before registry/ACL) so denied models cost nothing and reveal nothing. Exact model-name match only (no wildcards, no `_inherit` traversal). Relational fields pointing at denied models remain readable as ids/display names where the user's ACL allows (e.g. `res.users.api_key_ids` reads ids); the list guards model-level CRUD, not id references. Alternative: an `ir.config_parameter`-configurable list: rejected (an agent able to write parameters could try to alter it, and reading it needs a sudo).

**D1b. Relations into denied models.** Model-level denial alone leaves `res.users.api_key_ids` (a one2many to `res.users.apikeys`) reachable through an allowed model, so relational fields whose `comodel_name` is denied are filtered out wherever fields are chosen (`describe_model`, default/explicit read fields, write `values`), and top-level domain leaves are walked with `reaches_denied_model(model, path)`. Nested sub-domains inside values (e.g. `any`) are not walked; the ORM's own ACLs still apply there.

**D2. Error text.** In `call_tool`: `_message(exc)` truncates pass-through messages to 1,000 characters with `…`; unexpected exceptions get `ref = uuid4().hex[:8]`, log `"MCP internal error ref=%s"` with `exc_info`, and return `Internal error (ref: <ref>)`. This only appends the ref to change 1's text, consistent with its "begins with `Internal error`". A scan test fires every error path and asserts no `Traceback`, `.py`, `psycopg2`, `File "`, or `debug` substring.

**D3. Rate limiter.** `ratelimit.py`: `class SlidingWindow(limit=120, window=60.0)` holding `dict[(db, uid)] -> deque[float]` behind one `threading.Lock`; `check(key, now)` drops timestamps older than `window`, then either appends and returns `(True, 0)` or returns `(False, retry_after_seconds)`; opportunistic cleanup removes empty/idle buckets when the dict exceeds 1,000 entries and on every 256th call. The clock (`time.monotonic`) is injectable for tests. It is called in `controllers/main.py` right after authentication and before parsing the body, so garbage or oversized bodies from an authenticated key also count. Response: `429`, `Retry-After`, JSON-RPC `-32029 Rate limit exceeded`. Constants live in the module, not in configuration. Per-worker trade-off documented.

**D4. Audit line.** In `call_tool`, once the outcome is known: `_audit.info("db=%s uid=%s tool=%s model=%s ids=%s outcome=%s category=%s ms=%d", ...)` on logger `odoo.addons.odoo_mcp.audit`. Only whitelisted scalar fields are formatted; `arguments` are never logged wholesale. Category derives from the exception class (`AccessError→access`, `ValidationError→validation`, `MissingError→missing`, `UserError→user`, `ToolError→tool`, else `internal`). The logging call is wrapped in `try/except Exception` that swallows and continues.

**D5. Addon-wide source scan.** One test walks all non-test `.py` files and rejects the forbidden tokens (a superset of the per-module scans in changes 1-4).

**D6. Tool inventory pin.** A test asserts `tools/list` names equal the approved eight, so adding a tool forces a conscious decision and a docs update.

**D7. Docs and consistency test.** README section per the spec; `tests/test_docs.py` parses the README tool table (rows starting with a backticked tool name inside the "Tools" sub-section) and compares it with the registry. Client configuration snippets are illustrative and marked as such. For Claude Code the expected shape is `claude mcp add --transport http <name> <url> --header "Authorization: Bearer <api-key>"`; the apply agent MUST verify that against Claude Code's current documentation before writing it. CLAUDE.md gains a short "Implemented surface" section. No real hostnames or keys.

**D8. Parity matrix over real HTTP.** One `HttpCase` builds users (plain internal, extra groups, second company, own-records rule, administrator), creates an API key per user in test setup through `res.users.apikeys._generate(None, name, expiration)`, and runs each tool via `url_open('/mcp', headers=Bearer)`, comparing with `env(user=U)` ORM calls.

## Risks / Trade-offs

- [Deny-list is name-based; a custom model with similar power is not covered] → It is a *minimum* defense in depth; adding a name is a one-line change; ACLs remain the primary control.
- [Per-worker limiter allows up to `workers ×` 120/min] → Documented; enough to stop runaway loops; a shared limiter could be a later change.
- [Denying `ir.model`/`ir.model.fields` blocks harmless admin reads] → `list_models`/`describe_model` already cover discovery; the block prevents schema mutation.
- [Truncating messages could cut useful validation detail] → 1,000 characters is far above normal Odoo messages.
- [README client snippets can rot as clients change] → Marked illustrative; the smoke-tested `curl` is the anchor.
