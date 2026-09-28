# Tasks

## 1. Helpers

- [x] 1.1 Create `tools/read.py` with `MAX_RESPONSE_BYTES`, `_check_domain`, `_select_fields`, and `_check_size`; verify pure unit tests: valid/invalid/oversized/deeply nested domains, string domain rejection, default vs explicit vs unreadable fields, binary exclusion, size bound

## 2. Tools

- [x] 2.1 Implement and register `search_read` (limit+1 paging, `include_archived`, `order`, `ValueError` → `ToolError`); verify tests for default limit, max limit, ordering, invalid order/field, archived toggle
- [x] 2.2 Implement and register `search_count`; verify test that count equals `search_read` length for the same domain
- [x] 2.3 Implement and register `read` (ids 1..200 integers only, ordered output, no partial data on error); verify tests for missing id, hidden record, too many ids, non-integer ids
- [x] 2.4 Import `read.py` from `tools/__init__.py`; verify `tools/list` shows the three tools with read-only annotations and `additionalProperties: false` schemas

## 3. Parity and guard tests

- [x] 3.1 Add ACL/record-rule/field-`groups`/multi-company parity tests comparing each tool to the direct ORM call for the same user (own-records rule, no-ACL model, hidden field, second company); verify all pass
- [x] 3.2 Add source-scan test for `tools/read.py` (`sudo(`, `SUPERUSER_ID`, `with_user(`, `eval(`, `safe_eval`, `.execute(`) and a test that a `context` argument is rejected; verify they pass and that the scan fails on an injected token in a temp copy
- [x] 3.3 Run `python odoo-bin -d <scratch>-odoo --test-tags /odoo_mcp --stop-after-init` and `openspec validate add-mcp-read-tools --strict`; verify both pass
