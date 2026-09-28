# mcp-write-tools Specification

## Purpose
Lets an MCP agent create, update and delete Odoo records through the normal ORM with the authenticated user's permissions, so all Odoo constraints and business logic apply and failed operations leave no partial changes.

## Requirements

### Requirement: create tool
The `create` tool SHALL create exactly one record. Input: `model` (required), `values` (required non-empty object mapping field names to JSON values). Output: `{"id": <new record id>}`. It SHALL call the ORM's `create` on the model resolved through the shared resolver in the authenticated user's environment, so Odoo defaults, constraints, overrides, mail tracking and access rules apply. Its annotations SHALL mark it as not read-only and not destructive.

#### Scenario: Successful create
- **WHEN** an internal user calls `create` with `model: "res.partner"` and `values: {"name": "John Smith"}`
- **THEN** the result is `{"id": <int>}` and the partner exists afterwards, created by that user (`create_uid` equals the user)

#### Scenario: Model-level ACL denial
- **WHEN** the user has no `create` access on the model
- **THEN** the result is `isError: true` with Odoo's access message and no record is created

#### Scenario: Business constraint violation
- **WHEN** `values` violates a `@api.constrains` rule or a required field is missing
- **THEN** the result is `isError: true` with Odoo's validation message and no record exists

#### Scenario: Business logic still runs
- **WHEN** the model's `create` override sets a computed default or sends a tracking message
- **THEN** that behavior occurs as with a direct ORM call by the same user

### Requirement: write tool
The `write` tool SHALL update existing records. Input: `model`, `ids` (array of 1..100 integers), `values` (non-empty object). Output: `{"updated": <number of ids>}`. It SHALL verify that every id exists before writing and, if any does not, return `isError: true` listing the missing ids without modifying anything. It SHALL apply the ORM `write` once to the whole recordset in the authenticated user's environment.

#### Scenario: Successful write
- **WHEN** a user with write access updates `phone` on one partner
- **THEN** the result is `{"updated": 1}` and reading the record shows the new value

#### Scenario: Multiple records
- **WHEN** `ids` has three ids and `values` sets one field
- **THEN** all three records are updated in one ORM `write` call

#### Scenario: Missing id
- **WHEN** one of the ids does not exist
- **THEN** the result is `isError: true` naming the missing id and none of the records is changed

#### Scenario: Record rule denies one record
- **WHEN** a record rule forbids writing one of the ids
- **THEN** the result is `isError: true` with Odoo's access message and none of the records is changed

#### Scenario: Read-only field
- **WHEN** `values` targets a field the ORM treats as read-only for the user (for example a field restricted by `groups`)
- **THEN** the result is `isError: true` and nothing is changed

### Requirement: unlink tool
The `unlink` tool SHALL delete records. Input: `model`, `ids` (array of 1..100 integers). Output: `{"deleted": <number of ids>}`. It SHALL verify that every id exists, then call the ORM `unlink` on the whole recordset in the authenticated user's environment. Odoo's own restrictions (ACL, record rules, `ondelete` constraints, `@api.ondelete` checks) SHALL apply. Its annotations SHALL set `destructiveHint` true.

#### Scenario: Successful delete
- **WHEN** a user with unlink access deletes a draft record they created
- **THEN** the result is `{"deleted": 1}` and the record no longer exists

#### Scenario: Business rule blocks deletion
- **WHEN** Odoo raises a `UserError` because the record cannot be deleted (for example a posted entry)
- **THEN** the result is `isError: true` with Odoo's message and the record still exists

#### Scenario: Access denied
- **WHEN** the user lacks unlink access or a record rule hides the record
- **THEN** the result is `isError: true` and nothing is deleted

#### Scenario: Too many ids
- **WHEN** `ids` has 101 entries
- **THEN** the result is `isError: true` naming `ids` and nothing is executed

### Requirement: Values validation
`values` SHALL be a JSON object with at most 200 keys. Every key SHALL be the name of a field that exists on the model and is visible to the user (present in the ORM's `fields_get` for that user); unknown or invisible names SHALL yield `isError: true` naming the field. The keys `id` and the magic fields (`create_uid`, `create_date`, `write_uid`, `write_date`, `display_name` when not writable) SHALL be rejected. Values SHALL be JSON scalars, arrays or objects passed to the ORM as-is (many2one ids, x2many command lists, ISO date strings); the tool SHALL NOT interpret strings as code. The serialized request is already bounded by the endpoint's 2 MiB body cap.

#### Scenario: Unknown field
- **WHEN** `values` contains `{"no_such_field": 1}`
- **THEN** the result is `isError: true` naming `no_such_field` and nothing is created or changed

#### Scenario: Magic field rejected
- **WHEN** `values` contains `create_uid`
- **THEN** the result is `isError: true` and nothing is changed

#### Scenario: Empty values
- **WHEN** `values` is `{}`
- **THEN** the result is `isError: true`

#### Scenario: Wrong shape
- **WHEN** `values` is an array or a string
- **THEN** the result is `isError: true` naming `values`

#### Scenario: Relational values
- **WHEN** `values` sets a many2one to an integer id and an x2many with the ORM command list
- **THEN** they are applied exactly as the ORM would apply them for the same user

### Requirement: Atomic rollback of failed writes
Each write tool call SHALL be atomic. When any error occurs — validation, access, constraint, business logic, database error, or unexpected exception — every change made during that call SHALL be rolled back, including changes made by ORM overrides and side effects flushed to the database, and the tool SHALL return `isError: true`. Errors SHALL NOT commit partial data through the surrounding request.

#### Scenario: Constraint failure after side effects
- **WHEN** an override writes a related record and then a constraint on the main record fails
- **THEN** neither the related write nor the main write persists

#### Scenario: Multi-record write fails midway
- **WHEN** a `write` over several records fails on the last record at flush time (for example a unique constraint)
- **THEN** none of the records shows the new values

#### Scenario: Database error at flush
- **WHEN** the change violates a database constraint detected only at flush
- **THEN** the result is `isError: true` (generic or mapped message, no SQL text) and no change persists

#### Scenario: Following call unaffected
- **WHEN** a failed write tool call is followed by a successful one in the same session of requests
- **THEN** the second call succeeds and only its changes persist

### Requirement: No caller-controlled context or identity
Write tools SHALL NOT accept `context`, `uid`, `user`, `company`, `lang`, `tracking_disable`, or any other environment-altering argument, and unknown arguments SHALL be rejected. The ORM SHALL run with the authenticated user's default request context.

#### Scenario: Context argument rejected
- **WHEN** a write tool is called with `"context": {"tracking_disable": true}`
- **THEN** the result is `isError: true` naming `context` and nothing is executed

### Requirement: Write tools use the authenticated identity only
Write tools SHALL NOT use `sudo()`, `SUPERUSER_ID`, `with_user(`, `eval(`, `safe_eval`, raw SQL, or method invocation by name. Audit fields SHALL reflect the authenticated user.

#### Scenario: Source scan
- **WHEN** `odoo_mcp/tools/write.py` is scanned
- **THEN** none of `sudo(`, `SUPERUSER_ID`, `with_user(`, `eval(`, `safe_eval`, `.execute(`, `getattr(` appears

#### Scenario: Audit fields
- **WHEN** a user creates and then updates a record through the tools
- **THEN** `create_uid` and `write_uid` equal that user, not the superuser

#### Scenario: A model the user cannot read
- **WHEN** a user with `create` but no `read` access on a model calls `create`
- **THEN** the result is `isError: true` `Unknown model '<name>'` (the shared resolver hides models the user cannot read)

### Requirement: Access-control parity for writes
For each write tool, the outcome (success, `AccessError`, `ValidationError`, `UserError`) for the authenticated user SHALL equal the outcome of the same direct ORM call by that user.

#### Scenario: Parity matrix
- **WHEN** the same create/write/unlink is attempted by users with different ACLs and record rules through the tools and directly through the ORM
- **THEN** each pair produces the same outcome class and the same resulting database state
