# Tasks

## 1. Shared pieces

- [x] 1.1 Create `tools/models.py` with `_is_exposed(env, name)` and `resolve_model(env, name)` per design D2; verify unit tests for nonexistent, abstract, transient, no-ACL, and readable models (identical error text for the first four)

## 2. Tools

- [x] 2.1 Implement and register `list_models` (registry iteration, `query`, `offset`, `limit`, sorted output, `total`, read-only annotations); verify tests for per-user visibility, query filter, paging bounds, and that a plain internal user without `ir.model` access succeeds
- [x] 2.2 Implement and register `describe_model` (`fields_get` attributes, `access` flags, optional `fields` filter); verify tests for field-level `groups`, read-only ACL flags, relational/selection metadata, and unknown/forbidden model
- [x] 2.3 Import the module from `tools/__init__.py`; verify `tools/list` now reports both tools with valid `inputSchema` and read-only annotations

## 3. Guard tests

- [x] 3.1 Add a source-scan test for `tools/models.py` (`sudo(`, `SUPERUSER_ID`, `with_user(` absent) and a test that no tool module indexes `env[...]` with a caller-supplied name except through `resolve_model`; verify they fail when a forbidden pattern is injected in a temp copy
- [x] 3.2 Run `python odoo-bin -d <scratch>-odoo --test-tags /odoo_mcp --stop-after-init` and `openspec validate add-mcp-model-discovery --strict`; verify both pass
