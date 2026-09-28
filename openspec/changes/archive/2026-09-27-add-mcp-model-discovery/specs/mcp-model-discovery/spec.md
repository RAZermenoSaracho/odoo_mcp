# Spec Delta

## Purpose

Lets an MCP agent discover which Odoo models and fields exist and how they can be used, revealing only what the authenticated user is already permitted to read.

## ADDED Requirements

### Requirement: Model resolution is centralized and permission-aware
Every tool that accepts a `model` argument SHALL resolve it through one shared resolver. The resolver SHALL treat a model as unknown when its name is not in the registry, when the model is abstract or transient, or when the authenticated user lacks model-level `read` access. All these cases SHALL produce the identical tool error `Unknown model '<name>'`, so that a client cannot distinguish a nonexistent model from a forbidden one. The resolver SHALL use the authenticated user's environment without `sudo()`.

#### Scenario: Nonexistent model
- **WHEN** a tool is called with `model: "no.such.model"`
- **THEN** the result is `isError: true` with text `Unknown model 'no.such.model'`

#### Scenario: Model the user cannot read
- **WHEN** a tool is called with a model for which the user has no `read` ACL
- **THEN** the result is `isError: true` with exactly the same text pattern as a nonexistent model

#### Scenario: Abstract and transient models
- **WHEN** a tool is called with an abstract model (for example `mail.thread`) or a transient/wizard model
- **THEN** the result is `isError: true` with `Unknown model '<name>'`

### Requirement: list_models tool
The `list_models` tool SHALL return the models the authenticated user may read. Input: optional `query` (string, case-insensitive substring matched against the technical name and the human-readable description), optional `offset` (integer ≥ 0, default 0), optional `limit` (integer 1..200, default 100). Output: `{"models": [{"model": <technical name>, "name": <description>}], "total": <count after filtering, before paging>, "offset": n, "limit": n}` sorted by technical name. It SHALL exclude abstract models, transient models, and models the user cannot read. It SHALL NOT read `ir.model` and SHALL NOT use `sudo()`. Its annotations SHALL mark it read-only and non-destructive.

#### Scenario: Only readable models are listed
- **WHEN** user A has read access to `res.partner` but not to `account.move`, and calls `list_models`
- **THEN** `res.partner` is in the result and `account.move` is not

#### Scenario: Different users see different lists
- **WHEN** an internal user and a user with additional groups each call `list_models`
- **THEN** the second user's list is a superset reflecting their extra ACLs, and neither includes models neither can read

#### Scenario: Query filter
- **WHEN** `query` is `"partner"`
- **THEN** every returned model's technical name or description contains `partner` (case-insensitive) and `total` counts only matches

#### Scenario: Paging is bounded
- **WHEN** `limit` is 500
- **THEN** the result is `isError: true` naming `limit`
- **AND WHEN** `limit` is omitted
- **THEN** at most 100 models are returned and `total` reports the full match count

#### Scenario: Abstract and transient models are hidden
- **WHEN** `list_models` is called
- **THEN** no returned model is abstract or transient

### Requirement: describe_model tool
The `describe_model` tool SHALL describe one model. Input: `model` (required string), optional `fields` (array of at most 100 field names to restrict the output). Output: `{"model": name, "name": description, "access": {"read": bool, "create": bool, "write": bool, "unlink": bool}, "fields": {<field name>: {"string", "type", "required", "readonly", "store", "relation"?, "selection"?, "help"?}}}`. The `access` flags SHALL reflect the ORM's model-level ACL for the authenticated user (`has_access`). Field entries SHALL come from the ORM's `fields_get`, so fields the user cannot read are absent, and `readonly` SHALL be true for fields the user cannot write. `selection` SHALL be a list of `[value, label]` pairs for selection fields. Binary fields SHALL be described (with `type: "binary"`) so the agent knows they exist. The tool SHALL be read-only and SHALL NOT use `sudo()` or read `ir.model.fields`.

#### Scenario: Describe a readable model
- **WHEN** an internal user calls `describe_model` with `model: "res.partner"`
- **THEN** the result includes `fields.name` with `type: "char"`, and `access.read` is true

#### Scenario: Access flags follow the ACL
- **WHEN** a user with read-only ACL on a model calls `describe_model` for it
- **THEN** `access` is `{"read": true, "create": false, "write": false, "unlink": false}`

#### Scenario: Field-level group restrictions
- **WHEN** a field is restricted with `groups` to a group the user is not in
- **THEN** that field is absent from `fields` for that user and present for a member of the group

#### Scenario: Relational and selection metadata
- **WHEN** describing a model with a many2one and a selection field
- **THEN** the many2one entry has `relation` set to the comodel name, and the selection entry has `selection` as `[value, label]` pairs

#### Scenario: Restricting to named fields
- **WHEN** `fields` is `["name", "email"]`
- **THEN** only those readable fields are returned; unknown or unreadable names are ignored

#### Scenario: Too many field names
- **WHEN** `fields` has more than 100 entries
- **THEN** the result is `isError: true`

#### Scenario: Unknown or forbidden model
- **WHEN** the model is unknown or unreadable for the user
- **THEN** the result is `isError: true` with `Unknown model '<name>'`

### Requirement: Discovery never uses elevated privileges
Discovery tools SHALL run with the authenticated user's environment only, and their sources SHALL NOT contain `sudo(`, `SUPERUSER_ID`, or `with_user(`.

#### Scenario: Source scan
- **WHEN** the sources of `odoo_mcp/tools/models.py` are scanned
- **THEN** none of `sudo(`, `SUPERUSER_ID`, `with_user(` appears

#### Scenario: Works for a user without ir.model access
- **WHEN** a plain internal user (no access to `ir.model`) calls `list_models`
- **THEN** the call succeeds and returns models
