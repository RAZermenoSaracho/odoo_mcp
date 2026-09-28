# Design

## Context

See `proposal.md`. Depends on changes 1-3. Source facts:

- ORM write paths: `Model.create(vals_list)`, `records.write(vals)`, `records.unlink()` (`odoo/orm/models.py:4611, 4334, 4194`). ACLs, record rules, field `groups`, constraints and overrides all run inside them.
- `Model.browse(ids).exists()` filters to existing rows without ACL involvement; comparing with the requested ids detects missing ids (`read`/`write` on missing ids otherwise raise `MissingError` late or, for `write`, may act on a subset depending on model overrides).
- The change-1 boundary wraps every handler in `env.cr.savepoint()` (flush=True), so deferred ORM writes and SQL constraint errors surface inside the savepoint and are rolled back; a rolled-back savepoint clears the environment caches (`odoo/sql_db.py:217`).
- `fields_get()` returns only fields the user can read and marks `readonly` for non-writable fields (`orm/models.py:3343`).
- Odoo `create` on an unknown field name is not something to rely on across versions; we validate names ourselves.

## Goals / Non-Goals

**Goals:** three thin tools; atomicity; exact ORM parity; narrow validated input.

**Non-Goals:** method calls (`action_*`), bulk create, `copy`, attachments upload, posting chatter, idempotency keys, dry-run mode, confirmation flow (client-side human-in-the-loop is the MCP client's job).

## Decisions

**D1. One record per `create`.** Keeps atomicity, error messages, and the response (`{"id"}`) simple. Agents loop. Alternative: `values_list` — rejected as speculative.

**D2. Validate names, not values.** `_check_values(Model, values)`: object, 1..200 keys, each key in `Model.fields_get(attributes=['readonly'])`, none in `{'id','create_uid','create_date','write_uid','write_date'}`; readonly-for-user fields are not pre-rejected (the ORM/`groups` logic is authoritative) except that fields not visible at all are unknown. Values pass through unchanged to the ORM; ORM `ValueError`/`TypeError` from bad value shapes → `ToolError(str(exc))`.

**D3. Existence pre-check** (shared helper `existing_records(model, ids)` in `tools/models.py`, introduced by change 3 and reused here). For `write`/`unlink`: `records = Model.browse(ids)`; `missing = sorted(set(ids) - set(records.exists().ids))`; non-empty → `ToolError("Records not found: [...]")` before any write. Duplicate ids are de-duplicated preserving order.

**D4. Resolver.** Uses change-2's `resolve_model`, which requires model-level read access. Consequence: a user with create/write/unlink but *no read* on a model cannot use these tools. Accepted trade-off (rare; consistent with discovery; keeps a single choke point for the change-5 deny-list). Documented in the spec scenario.

**D5. Atomicity is inherited, not re-implemented.** The handler just performs the ORM call and returns; the savepoint/`isError` mapping is the change-1 boundary. Tests must prove it end-to-end: (a) override-with-side-effect then constraint failure, (b) multi-record write failing at flush, (c) a unique-constraint `IntegrityError` at flush (generic message), (d) subsequent successful call unaffected.

**D6. Annotations.** `create`: `readOnlyHint=false, destructiveHint=false, idempotentHint=false`; `write`: `readOnlyHint=false, destructiveHint=false, idempotentHint=true`; `unlink`: `readOnlyHint=false, destructiveHint=true, idempotentHint=false`. (Annotations are hints for clients; they are not a security boundary.)

**D7. No context.** Same as reads: schema has no `context`; `additionalProperties: false`. In particular `tracking_disable`, `mail_notrack`, `no_reset_password`, `install_mode` are unreachable.

**D8. Parity tests.** Same technique as change 3: a matrix of users/rules/ACLs comparing tool outcome + resulting DB state with the direct ORM call inside a test savepoint.

## Risks / Trade-offs

- [Prompt-injected agent deletes/modifies data] → Bounded by the user's own rights; sensitive system models denied in change 5; MCP clients should ask the human to confirm (annotations help). Not solvable in the server.
- [`write` on 100 records can be slow] → Bounded by `ids ≤ 100`; the ORM cost equals the user's UI action.
- [Users with create-but-no-read cannot use write tools] → Documented, accepted (D4).
- [`retrying` may re-run a request after a serialization failure] → Handlers are pure DB operations inside the savepoint/transaction, so a re-run is safe.
- [Field-name validation duplicates part of the ORM] → Deliberate: makes errors clear and keeps hidden fields indistinguishable from nonexistent.
