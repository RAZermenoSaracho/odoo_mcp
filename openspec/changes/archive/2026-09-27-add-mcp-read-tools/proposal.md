# Proposal

## Why

With discovery in place, an agent needs to find and read records ("show me my open tasks", "find customer ACME") under exactly the user's rights. This is the first change that touches record data, so it must be read-only, bounded, and ORM-only. Starting with reads (before writes) follows the module's "start read-only" rule and lets ACL/record-rule parity be proven before any mutation exists.

## What Changes

- Add MCP tools `search_read`, `search_count`, and `read`, thin wrappers over `Model.search_read`, `Model.search_count`, and `Model.browse(ids).read`.
- Validate domains as JSON arrays only (never strings/expressions), bound `limit`, `offset`, `ids`, `fields`, domain size, and total response size.
- Exclude binary fields from default field selection; allow explicit binary requests only within the response-size bound.
- Reject any caller-supplied `context`; expose only an `include_archived` flag (maps to `active_test=False`).
- Add ACL / record-rule / field-access parity tests against direct ORM calls.

Non-goals: `read_group`/aggregations, `name_search`, `web_*` methods, attachments/file download, chatter, any write.

## Capabilities

### New Capabilities
- `mcp-read-tools`: bounded, ORM-backed record search, count and read tools that inherit all Odoo access control.

### Modified Capabilities

(none)

## Impact

- New `odoo_mcp/tools/read.py` and tests; one import line in `tools/__init__.py`.
- Depends on `add-mcp-endpoint` and `add-mcp-model-discovery` (uses `resolve_model`, `ToolError`).
- No schema, no sudo, no raw SQL.
