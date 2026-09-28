# Tasks

## 1. Helpers

- [x] 1.1 Create `tools/write.py` with `check_values(model, values)` and use the shared `existing_records(model, ids)` from `tools/models.py` (de-dup, existence pre-check; introduced in change 3) per design D2/D3; verify unit tests for unknown/invisible/magic keys, empty/non-object/oversized values, missing ids, duplicate ids

## 2. Tools

- [x] 2.1 Implement and register `create` (`vals_list=[values]`, returns `{"id"}`, annotations per D6); verify tests: success with `create_uid` = user, ACL denial, constraint violation, required field missing, override side effects
- [x] 2.2 Implement and register `write` (`{"updated": n}`, one ORM `write` on the recordset); verify tests: single, multiple, missing id (nothing changed), record-rule denial (nothing changed), `groups`-restricted field
- [x] 2.3 Implement and register `unlink` (`{"deleted": n}`, `destructiveHint` true); verify tests: success, `@api.ondelete`/`UserError` block, access denial, 101 ids rejected
- [x] 2.4 Import `write.py` from `tools/__init__.py`; verify `tools/list` shows the three tools with the specified annotations and `additionalProperties: false` schemas

## 3. Atomicity, parity and guards

- [x] 3.1 Add rollback tests with a test-only model or override: side effect then constraint failure; multi-record write failing at flush; unique-constraint violation at flush (generic error message, no SQL text); next call succeeds; verify state unchanged after each failure
- [x] 3.2 Add ACL/record-rule/constraint parity tests comparing each tool with the direct ORM call for several users, including a user with create but no read (resolver denial); verify outcome classes and DB state match
- [x] 3.3 Add tests that `context`, `uid`, `tracking_disable` arguments are rejected and that audit fields equal the authenticated user; add the source-scan test for `tools/write.py` (`sudo(`, `SUPERUSER_ID`, `with_user(`, `eval(`, `safe_eval`, `.execute(`, `getattr(`); verify it passes and fails on an injected token in a temp copy
- [x] 3.4 Run `python odoo-bin -d <scratch>-odoo --test-tags /odoo_mcp --stop-after-init` and `openspec validate add-mcp-write-tools --strict`; verify both pass
