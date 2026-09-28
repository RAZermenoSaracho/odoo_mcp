# Spec Delta

## Purpose

Lets an MCP agent search, count and read Odoo records through the normal ORM with the authenticated user's permissions, in bounded, predictable results.

## ADDED Requirements

### Requirement: search_read tool
The `search_read` tool SHALL return records matching a domain. Input: `model` (required), `domain` (array, default `[]`), `fields` (array of at most 100 field names; default described below), `offset` (integer ≥ 0, default 0), `limit` (integer 1..200, default 50), `order` (string of at most 200 characters, optional), `include_archived` (boolean, default false). Output: `{"records": [...], "count": <number returned>, "offset": n, "limit": n, "has_more": bool}` where `has_more` is true when more matching records exist beyond `offset + limit`. The tool SHALL execute `search_read` on the model resolved through the shared resolver, in the authenticated user's environment, and SHALL NOT use `sudo()`, raw SQL, or `search` results filtered in Python. It SHALL be annotated read-only.

#### Scenario: Basic search
- **WHEN** a user calls `search_read` with `model: "res.partner"`, `domain: [["name", "ilike", "acme"]]`, `fields: ["name", "email"]`
- **THEN** the result contains only matching partners with `id`, `name`, `email`

#### Scenario: Default limit
- **WHEN** `limit` is omitted and more than 50 records match
- **THEN** exactly 50 records are returned and `has_more` is true

#### Scenario: Limit above the maximum
- **WHEN** `limit` is 201
- **THEN** the result is `isError: true` naming `limit` and no query is executed

#### Scenario: Ordering and paging
- **WHEN** `order` is `"name asc"`, `offset` is 10 and `limit` is 10
- **THEN** the records are the 11th to 20th by name, as the ORM would return them

#### Scenario: Invalid order
- **WHEN** `order` names a nonexistent field
- **THEN** the result is `isError: true` with the ORM's message and no data

#### Scenario: Archived records
- **WHEN** `include_archived` is false (default)
- **THEN** archived records are excluded, and when true they are included

### Requirement: search_count tool
The `search_count` tool SHALL return `{"count": n}` for the same `model`, `domain`, and `include_archived` inputs as `search_read`, using the ORM's `search_count`, and SHALL be read-only.

#### Scenario: Count matches search
- **WHEN** `search_count` and `search_read` (with a large enough limit) are called with the same domain
- **THEN** `count` equals the number of records returned

### Requirement: read tool
The `read` tool SHALL return the requested records by id. Input: `model`, `ids` (array of 1..200 integers), `fields` (array of at most 100 names; default described below). Output: `{"records": [...]}` in the order given, using the ORM's `read`. If any id does not exist or is not accessible, the ORM's `MissingError`/`AccessError` SHALL be returned as a tool error and no partial data returned.

#### Scenario: Read existing records
- **WHEN** `ids` are valid and readable
- **THEN** the result contains one record per id with the requested fields

#### Scenario: Missing id
- **WHEN** one of the ids does not exist
- **THEN** the result is `isError: true` (missing record) and includes no records

#### Scenario: Too many ids
- **WHEN** `ids` has 201 entries
- **THEN** the result is `isError: true` naming `ids`

#### Scenario: Non-integer ids
- **WHEN** `ids` contains a string or boolean
- **THEN** the result is `isError: true` naming `ids`

### Requirement: Default field selection excludes binary and unbounded data
When `fields` is omitted, the tools SHALL return only fields that are readable by the user, stored, and not of type `binary`, `one2many`, or `many2many`, plus `id`. When `fields` is given, each name SHALL exist and be readable by the user, otherwise the call is an `isError` result naming the field. Binary fields SHALL be returned only when explicitly requested in `fields`.

#### Scenario: Binary excluded by default
- **WHEN** `search_read` on `res.partner` omits `fields`
- **THEN** no returned record contains `image_1920` or any other binary field

#### Scenario: Binary on explicit request
- **WHEN** `fields` includes `image_1920` for a partner with an image and the response fits the size bound
- **THEN** the field is returned

#### Scenario: Unknown or unreadable field
- **WHEN** `fields` includes a name that does not exist or is restricted by `groups` from the user
- **THEN** the result is `isError: true` naming that field

### Requirement: Domain validation
`domain` SHALL be a JSON array whose elements are either the operators `"&"`, `"|"`, `"!"` or arrays `[field, operator, value]` with a string `field` and string `operator`. A string (or any non-array) domain SHALL be rejected without evaluation. A domain SHALL contain at most 100 top-level elements and nest values at most 5 levels deep. Field names and operators SHALL be validated by the ORM; ORM `ValueError`/`UserError` for an invalid leaf SHALL be returned as a tool error.

#### Scenario: String domain rejected
- **WHEN** `domain` is the string `"[('name','=','x')]"`
- **THEN** the result is `isError: true`, and nothing is evaluated

#### Scenario: Malformed leaf
- **WHEN** a leaf has two items or a non-string operator
- **THEN** the result is `isError: true` naming `domain`

#### Scenario: Oversized domain
- **WHEN** the domain has more than 100 top-level elements
- **THEN** the result is `isError: true`

#### Scenario: Invalid field in domain
- **WHEN** a leaf references a nonexistent field
- **THEN** the result is `isError: true` with the ORM's message

### Requirement: Response size bound
A read result whose serialized `structuredContent` exceeds 1,000,000 bytes SHALL NOT be returned; instead the tool SHALL return `isError: true` with a message telling the agent to reduce `limit` or `fields`.

#### Scenario: Oversized response
- **WHEN** a request selects enough data to exceed 1,000,000 bytes serialized
- **THEN** the result is `isError: true`, contains no records, and suggests lowering `limit` or requesting fewer fields

### Requirement: No caller-controlled context
Read tools SHALL NOT accept `context`, `uid`, `user`, `company`, or `lang` arguments. Unknown arguments SHALL be rejected. The only context change permitted SHALL be `active_test=False` when `include_archived` is true.

#### Scenario: Context argument rejected
- **WHEN** a call includes `"context": {"active_test": false}`
- **THEN** the result is `isError: true` naming `context`

### Requirement: ACL, record-rule and field-access parity
For every read tool, the set of records and field values returned to the authenticated user SHALL equal what the same ORM call returns for that user directly. Record rules SHALL filter results; model-level ACL denial SHALL produce a tool error; `groups`-restricted fields SHALL be unreadable.

#### Scenario: Record rule filters results
- **WHEN** a record rule limits user U to records they own, and records owned by others exist
- **THEN** `search_read` and `search_count` for U return only U's records, identical to `env(user=U)[model].search_read(...)`

#### Scenario: Different users, different results
- **WHEN** two users with different record rules run the same `search_read`
- **THEN** each receives only their permitted records

#### Scenario: Read of an inaccessible record
- **WHEN** U calls `read` with the id of a record that a record rule hides from U
- **THEN** the result is `isError: true` and contains no field data of that record

#### Scenario: Model without access
- **WHEN** U calls any read tool on a model U cannot read
- **THEN** the result is `isError: true` `Unknown model '<name>'`

#### Scenario: Multi-company scope
- **WHEN** U belongs to company A only and records of company B exist
- **THEN** records of company B are not returned

### Requirement: Read tools use no elevated privileges
Read tool sources SHALL NOT contain `sudo(`, `SUPERUSER_ID`, `with_user(`, `eval(`, `safe_eval`, or raw cursor `.execute(`.

#### Scenario: Source scan
- **WHEN** `odoo_mcp/tools/read.py` is scanned
- **THEN** none of the forbidden tokens appears
