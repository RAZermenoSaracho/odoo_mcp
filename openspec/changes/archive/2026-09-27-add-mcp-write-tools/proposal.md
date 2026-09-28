# Proposal

## Why

The module's purpose is to let an agent *change* Odoo data ("update this customer's phone number", "create a follow-up task", "delete the draft I created by mistake") with exactly the user's rights. Writes are the riskiest part, so they come after reads are proven, are deliberately narrow (one model, explicit ids, no method calls), and are atomic: a failed call leaves no trace.

## What Changes

- Add MCP tools `create` (one record), `write` (1..100 records, one values object), and `unlink` (1..100 records), thin wrappers over `Model.create`, `records.write`, `records.unlink` in the authenticated user's environment.
- Validate `values` shape and field names against the user-visible field set; reject `id`/magic fields; reject caller-supplied `context`.
- Verify all target ids exist before writing (no silent partial application).
- Rely on the change-1 savepoint so any failure (ACL, constraint, business logic, database error) rolls back the whole tool call.
- Annotate tools honestly (`destructiveHint` on `unlink`; `write` non-idempotent-safe flags per MCP annotations).
- Add tests for ACL/record-rule parity on writes, business-logic/constraint parity, atomic rollback, and absence of `sudo()`.

Non-goals: calling model methods (`action_confirm`, `action_post`, …), bulk import, `copy`, x2many command helpers beyond what the ORM accepts as plain JSON, file upload endpoints, chatter/message posting.

## Capabilities

### New Capabilities
- `mcp-write-tools`: ORM-backed, atomic create/write/unlink tools that inherit all Odoo access control and business logic.

### Modified Capabilities

(none)

## Impact

- New `odoo_mcp/tools/write.py` and tests; one import line in `tools/__init__.py`.
- Depends on `add-mcp-endpoint`, `add-mcp-model-discovery`, and `add-mcp-read-tools` (shared resolver, validator, size/`ToolError` helpers, and read tools used by tests for verification).
- No schema, no sudo, no raw SQL.
