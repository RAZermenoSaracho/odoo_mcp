# Spec Delta

## Purpose

Adds defense in depth to the MCP bridge: a fixed set of models that agents can never touch, sanitized errors, per-user request throttling and an audit trail, without weakening or replacing Odoo's own access control.

## ADDED Requirements

### Requirement: Sensitive-model deny-list
The module SHALL define a fixed, explicit deny-list of models that no MCP tool may list, describe, read, create, write, or delete, for any user including administrators and users who hold ACLs on those models. The deny-list SHALL contain at least: `res.users.apikeys`, `res.users.apikeys.description`, `res.users.apikeys.show`, `ir.config_parameter`, `ir.rule`, `ir.model.access`, `ir.model`, `ir.model.fields`, `ir.actions.server`, `ir.cron`, `ir.module.module`. A denied model SHALL be indistinguishable from a nonexistent one: `list_models` omits it and every other tool returns `Unknown model '<name>'`. The deny-list SHALL be enforced at the shared model resolver so that it applies to every current and future tool. The deny-list SHALL NOT be configurable at runtime and SHALL NOT be bypassable by any tool argument.

#### Scenario: Admin cannot read API keys
- **WHEN** a user in `base.group_system` calls `search_read` with `model: "res.users.apikeys"`
- **THEN** the result is `isError: true` with `Unknown model 'res.users.apikeys'`

#### Scenario: Admin cannot read system parameters
- **WHEN** an administrator calls `read`, `search_read`, `search_count`, or `describe_model` on `ir.config_parameter`
- **THEN** each result is `isError: true` with `Unknown model 'ir.config_parameter'`

#### Scenario: Denied models are not listed
- **WHEN** an administrator calls `list_models` with `query: "ir."` or no query
- **THEN** no denied model appears in `models` and `total` excludes them

#### Scenario: Every tool, every denied model
- **WHEN** each of the seven tools that take a `model` argument (all except `list_models`) is called for each deny-listed model as an administrator
- **THEN** every call returns `isError: true` with `Unknown model` and no data is read or changed

#### Scenario: Write attempts are refused
- **WHEN** an administrator calls `create` on `ir.cron` or `write` on `ir.actions.server`
- **THEN** the result is `isError: true` `Unknown model` and no record is created or changed

#### Scenario: Denied model indistinguishable from nonexistent
- **WHEN** the error text for a denied model is compared with the text for a nonexistent model name
- **THEN** they differ only in the model name

#### Scenario: Deny-list is not user-controllable
- **WHEN** a tool call includes any extra argument such as `allow_denied` or `context`
- **THEN** the result is `isError: true` for the unknown argument and the deny-list is unchanged

### Requirement: Denied models are not reachable through relations
A relational field whose target model is deny-listed SHALL be treated as unavailable by every tool: it SHALL be omitted from `describe_model`, from default field selection, and SHALL be rejected as unknown when named in `fields` or in `values`; a top-level domain leaf whose field path traverses into a denied model (for example `api_key_ids.name` on `res.users`) SHALL be rejected as an unknown field.

#### Scenario: Relation hidden from discovery and reads
- **WHEN** an administrator describes or reads `res.users`
- **THEN** `api_key_ids` (a relation to `res.users.apikeys`) is absent from `describe_model` and default reads, and requesting it in `fields` returns `isError: true`

#### Scenario: Domain traversal refused
- **WHEN** a domain leaf is `["api_key_ids.name", "!=", false]`
- **THEN** the result is `isError: true` naming the field and no query is executed

#### Scenario: Write through a relation refused
- **WHEN** `values` contains `api_key_ids`
- **THEN** the result is `isError: true` and nothing is changed

### Requirement: Error sanitization
Every tool error and protocol error returned by `/mcp` SHALL be free of tracebacks, exception class names, Python module or file paths, SQL text, and Odoo `debug` payloads. Messages from Odoo user-facing exceptions (`AccessError`, `UserError`, `ValidationError`, `MissingError`) and from deliberate tool errors SHALL be passed through, truncated to at most 1,000 characters (with a trailing `…` when truncated). Any other exception SHALL produce a result whose text is `Internal error (ref: <8 lowercase hex characters>)`, and the server log SHALL contain that same reference with the full traceback.

#### Scenario: Unexpected exception
- **WHEN** a handler raises an unexpected exception (for example a database `IntegrityError` whose text contains SQL)
- **THEN** the result text matches `^Internal error \(ref: [0-9a-f]{8}\)$`, contains no SQL, and the server log contains the same ref with the traceback

#### Scenario: Long Odoo message
- **WHEN** an Odoo `ValidationError` message is 5,000 characters long
- **THEN** the returned text is at most 1,001 characters and ends with `…`

#### Scenario: No implementation details anywhere
- **WHEN** error responses of every kind (auth failure, malformed JSON, header mismatch, unknown tool, tool error, unexpected exception, `413`, `429`) are scanned
- **THEN** none contains `Traceback`, `.py`, `psycopg2`, `File "`, or `debug`

#### Scenario: Correlation refs are unique
- **WHEN** two unexpected exceptions occur
- **THEN** their refs differ

### Requirement: Per-user rate limiting
The endpoint SHALL limit each authenticated user to 120 requests per rolling 60 seconds per database, counted after successful authentication and before dispatch (notifications count). A request over the limit SHALL be rejected with HTTP `429`, a `Retry-After` header (integer seconds, at least 1), and a JSON-RPC error with code `-32029` and message `Rate limit exceeded`, and SHALL execute nothing. Different users, and different databases, SHALL have independent budgets. Unauthenticated requests SHALL NOT consume any user's budget. The limiter SHALL keep only in-process state, SHALL bound its memory (idle buckets are discarded), and SHALL be documented as per-worker best effort (with `N` workers the effective ceiling is up to `N` times the limit).

#### Scenario: Under the limit
- **WHEN** a user sends 120 requests within a minute
- **THEN** all are processed

#### Scenario: Over the limit
- **WHEN** the same user sends a 121st request within the 60-second window
- **THEN** the response is `429` with `Retry-After` and error code `-32029`, and no tool executes

#### Scenario: Budget recovers
- **WHEN** the window slides past the oldest requests
- **THEN** new requests are processed again

#### Scenario: Users are independent
- **WHEN** user A exhausts the budget
- **THEN** user B's requests are still processed

#### Scenario: Unauthenticated floods do not affect users
- **WHEN** requests with invalid keys are sent repeatedly
- **THEN** they return `401` and do not reduce any user's budget

#### Scenario: Memory is bounded
- **WHEN** many distinct users each send one request and then go idle
- **THEN** their buckets are discarded after the window elapses

### Requirement: Audit logging
Each `tools/call` SHALL produce exactly one log line at INFO level on the logger `odoo.addons.odoo_mcp.audit` containing: database name, user id, tool name, `model` argument if present, number of ids if present, outcome (`ok` or `error`), the error category (`access`, `user`, `validation`, `missing`, `tool`, `internal`) when it failed, and duration in milliseconds. The line SHALL NOT contain domains, field values, `values`, record contents, API keys, or the `Authorization` header. A logging failure SHALL NOT affect the tool result.

#### Scenario: Successful call is logged
- **WHEN** a user calls `search_read` on `res.partner`
- **THEN** one audit line exists with the user id, `tool=search_read`, `model=res.partner`, `outcome=ok`, and a duration

#### Scenario: Failed call is logged with category
- **WHEN** a write is denied by ACL
- **THEN** the audit line has `outcome=error` and `category=access`

#### Scenario: No payload in the log
- **WHEN** a `write` sets `phone` to `+1-555-0100` using key `K`
- **THEN** neither `+1-555-0100` nor `K` appears in any audit line

#### Scenario: Denied-model attempts are logged
- **WHEN** a call targets a deny-listed model
- **THEN** an audit line with `outcome=error` and `category=tool` is emitted

### Requirement: No privilege escalation anywhere in the addon
No Python source of the addon outside `tests/` SHALL contain `sudo(`, `SUPERUSER_ID`, `with_user(`, `with_env(`, `eval(`, `safe_eval`, `exec(`, `subprocess`, `os.system`, `.execute(`, or `getattr(` applied to a caller-supplied name. No tool SHALL be exposed that calls a model method by name.

#### Scenario: Addon-wide source scan
- **WHEN** all non-test `.py` files of the addon are scanned for the forbidden tokens
- **THEN** none is found

#### Scenario: Tool inventory is exactly the approved set
- **WHEN** `tools/list` is called
- **THEN** the names are exactly `create`, `describe_model`, `list_models`, `read`, `search_count`, `search_read`, `unlink`, `write`

### Requirement: ACL parity across the whole surface
For a fixed matrix of users (plain internal, with extra groups, multi-company, record-rule-restricted, administrator) and every tool, the outcome and data returned through `/mcp` SHALL equal those of the equivalent direct ORM call by the same user, except where the deny-list or the resolver explicitly hides a model.

#### Scenario: End-to-end parity over HTTP
- **WHEN** the parity matrix is run through real authenticated `/mcp` HTTP calls with per-user API keys
- **THEN** every outcome class and result set matches the direct ORM call for the same user

#### Scenario: Key of user A never acts as user B
- **WHEN** two users' keys are used alternately
- **THEN** each call sees exactly its own user's records and audit fields
