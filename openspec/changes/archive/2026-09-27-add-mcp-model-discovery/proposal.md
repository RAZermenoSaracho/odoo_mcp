# Proposal

## Why

An agent cannot use generic CRUD without knowing which models and fields exist. Discovery must be *permission-aware*: it may reveal only what the authenticated user may already read. `ir.model` is not readable by normal users (`base.group_user` has zero access, `ir.model.access.csv:18`), so discovery cannot be built on it without `sudo()`. The exploration found a `sudo`-free alternative: iterate the model registry and ask the ORM (`has_access('read')`, `fields_get`, which already filters by field access).

## What Changes

- Add MCP tools `list_models` and `describe_model`, registered in the change-1 tool table.
- Add one shared model resolver (`resolve_model`) that every current and future tool uses to turn a model name into a recordset. It hides abstract and transient models and models the user cannot read, so that "unknown", "abstract/transient" and "no access" are indistinguishable to the client. Change 5 adds the sensitive-model deny-list at this one choke point.
- Add tests proving permission awareness (model visibility, field visibility, access flags) with users of different rights.

Non-goals: metadata about views/actions/menus, model relations graph, any record data, any use of `ir.model`/`ir.model.fields` via `sudo()`.

## Capabilities

### New Capabilities
- `mcp-model-discovery`: permission-aware listing of models and description of a model's fields and access flags.

### Modified Capabilities

(none)

## Impact

- New files `odoo_mcp/tools/models.py` (resolver + the two tools) and tests; one import line in `tools/__init__.py`.
- Depends on `add-mcp-endpoint` (tool table, `tools/call` boundary).
- No schema, no security CSV, no sudo.
