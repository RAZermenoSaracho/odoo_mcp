# Design

## Context

See `proposal.md`. Depends on change 1 (tool table, validator, `call_tool` savepoint/error mapping, `ToolError`) and change 2 (`resolve_model`). Source facts:

- `BaseModel.search_read(domain, fields, offset, limit, order)` runs `search_fetch` + `_read_format` and is fully ACL/record-rule/field-access aware (`odoo/orm/models.py:5748`). When `fields` is empty it reads *all* readable fields, including binaries, which is why we always pass an explicit list.
- `search_count`, `browse().read()` and `fields_get` are all ORM-native. `read` raises `MissingError`/`AccessError` for missing/forbidden ids.
- Many2one values come back as `[id, display_name]`; dates/datetimes are serialized by `odoo.tools.json.json_default` (`odoo/tools/json.py:62`).
- `request.env` for a bearer request already carries the user's context (lang, tz) set by `ir.http._pre_dispatch`.

## Goals / Non-Goals

**Goals:** three thin tools; explicit bounds; identical results to direct ORM use by the same user.

**Non-Goals:** aggregation, `name_search`, `web_*` helpers, cursor-based pagination, streaming, caching.

## Decisions

**D1. Thin wrappers.** Handlers resolve the model with `resolve_model`, validate arguments, optionally `with_context(active_test=False)`, call the ORM method, and return the shaped dict. No query building, no Python-side filtering.

**D1b. Missing ids.** `Model.browse(ids).read()` silently skips ids that do not exist (found during apply), which would violate the "no partial data" requirement. `read` therefore pre-checks with the shared helper `existing_records(model, ids)` (in `tools/models.py`, reused by the write tools), which raises `ToolError("Records not found: [...]")`.

**D2. Field selection helper (`_select_fields(Model, requested)`).** Compute `readable = Model.fields_get(attributes=['type','store'])`. Default = `id` + names where `store` is true and `type not in ('binary','one2many','many2many')`. Explicit list: each must be in `readable` (unreadable/unknown → `ToolError("Unknown or unreadable field 'x'")`). Passing an explicit list to the ORM prevents its "all fields" default.

**D3. Domain validation (`_check_domain`).** Iterative walk of the JSON value: top level must be a list; each element is one of `"&","|","!"` or a 3-list with `str,str,<any JSON>`; count top-level elements ≤ 100 (long `in` value lists are bounded by the 2 MiB body cap, not by this limit); nested list/dict value depth ≤ 5. It only checks *shape*; field and operator validity are left to the ORM, whose `ValueError`/`UserError` become tool errors via the boundary (`ValueError` is not a `UserError`, so the read handlers explicitly catch `ValueError` from search and re-raise as `ToolError(str(exc))`; other exceptions stay generic). The domain is never `eval`'d and never converted from a string. Alternative considered: hand-rolled operator allowlist — rejected as duplicating the ORM.

**D4. Ordering and paging.** `order` type/length check only; the ORM validates fields (`_order_to_sql`). `has_more` is computed by requesting `limit + 1` rows via `search_read(limit=limit+1)` and trimming, avoiding an extra count query.

**D5. Size bound.** After the ORM call, serialize `structuredContent` once with `json.dumps(default=json_default)`; if `len(...) > 1_000_000` return `ToolError("Result too large (> 1,000,000 bytes); lower 'limit' or request fewer 'fields'")`. The same serialized text is reused for the `content` block by `call_tool` if convenient (an optimization, not a requirement). The bound is a module constant `MAX_RESPONSE_BYTES`, not configuration.

**D6. Context.** No arguments influence context except `include_archived`. `context`, `uid`, `company`, `lang` are simply not in the schema and rejected by `additionalProperties: false`.

**D7. Parity tests.** For a matrix of users and record rules, compare `call_tool(...)` output to `env(user=U)[model].search_read(...)`; also test multi-company. Tests create their own rules/users inside the test transaction.

## Risks / Trade-offs

- [Requesting `limit + 1` rows for `has_more`] → One extra row; negligible.
- [Computed non-stored fields excluded by default] → Agents can still request them explicitly; avoids expensive computes by accident.
- [Domain over relational paths can hit heavy joins] → Bounded by domain size and `limit`; same cost as the user's own UI searches. Statement timeouts are Odoo's/PostgreSQL's job.
- [`>1 MB` responses rejected rather than truncated] → Truncated data would mislead an agent; a clear error is safer.
