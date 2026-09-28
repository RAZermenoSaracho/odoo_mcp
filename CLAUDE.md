# odoo_mcp — Claude Code Guide

`odoo_mcp` is an Odoo 19 Community addon that allows MCP-compatible AI agents to interact with an Odoo database through the normal Odoo ORM and security model.

Read this file completely before exploring, designing, implementing, or modifying this module.

This repository must remain independently understandable and usable. Do not assume knowledge of unrelated custom modules or previous development sessions.

---

# 1. Purpose

The purpose of `odoo_mcp` is intentionally simple:

> Allow a user to ask an MCP-compatible AI agent to read or modify Odoo data, and translate the agent's requests into normal Odoo CRUD operations executed with that user's Odoo permissions.

Examples of the intended user experience:

```text
"Find task X and make its description more detailed."

"Create a new contact for John Smith."

"Show me my open tasks."

"Change the deadline of task X to Friday."

"Update this customer's phone number."

"Create a task in project X with this description."

"Delete the draft record I just created."
```

The AI agent interprets the natural-language request.

`odoo_mcp` does not interpret natural language itself.

Its responsibility begins when the MCP client invokes an MCP capability.

Conceptually:

```text
User
  │
  │ natural language
  ▼
AI Agent
(Claude, ChatGPT, Gemini, etc.)
  │
  │ MCP
  ▼
odoo_mcp
  │
  │ Odoo ORM
  ▼
Odoo models
  │
  │ ACLs + Record Rules
  ▼
Odoo Database
```

The AI agent performs the reasoning.

Odoo performs the business logic and authorization.

`odoo_mcp` is the controlled bridge between them.

---

# 2. Core goal

The core goal is to provide generic access to normal Odoo CRUD operations:

```text
Create
Read
Update
Delete
```

across Odoo models that the authenticated user is allowed to access.

Conceptually, an MCP client should eventually be able to perform operations equivalent to:

```python
env[model].search(...)
env[model].read(...)
env[model].search_read(...)
env[model].create(...)
records.write(...)
records.unlink(...)
```

without exposing Python itself.

The MCP interface should also provide enough model and field metadata for an AI agent to understand how to perform those operations correctly.

For example, an agent asked:

```text
"Update task X and make its description more detailed."
```

may need to:

```text
1. discover or know that tasks use `project.task`
2. discover the relevant fields
3. search for task X
4. read the existing description
5. generate the improved description itself
6. write the new value through MCP
```

`odoo_mcp` should provide the generic Odoo capabilities needed for those steps.

It should not contain task-specific logic.

---

# 3. The authorization rule

This is the most important invariant in the module:

> An AI agent connected as an Odoo user may perform only the operations that Odoo allows that user to perform.

The MCP layer must preserve Odoo's normal authorization model.

If the authenticated user can read a record through normal Odoo security:

```text
MCP → read → allowed
```

If the authenticated user cannot read it:

```text
MCP → read → Odoo AccessError
```

The same principle applies to:

```text
create
read
write
unlink
```

and any future operation exposed by the module.

The authorization architecture should therefore remain:

```text
MCP Client
     │
     ▼
Authenticated Odoo User
     │
     ▼
Odoo Environment
     │
     ▼
ORM operation
     │
     ├── ACL
     ├── Record Rules
     ├── Company restrictions
     ├── Field restrictions
     └── Model business logic
```

Do not reproduce Odoo's authorization logic inside MCP.

Use Odoo's security system as the authority.

---

# 4. Identity must be preserved

Every authenticated MCP session/request must have a clear Odoo identity.

Conceptually:

```text
Claude / ChatGPT / Gemini
          │
          │ credentials/session
          ▼
       odoo_mcp
          │
          ▼
       res.users
          │
          ▼
     Odoo Environment
```

CRUD operations execute through that user's environment.

Do not silently execute MCP requests as:

- superuser
- UID 1
- administrator
- public user
- a hard-coded service user

unless a future explicitly approved authentication mode defines such behavior.

The normal design is:

> The agent acts with the permissions of the Odoo user who authorized the connection.

---

# 5. No implicit sudo

Do not use `sudo()` to make a requested operation succeed.

For example:

```python
env["project.task"].sudo().write(...)
```

would defeat the central security contract.

The expected behavior is:

```python
env["project.task"].write(...)
```

using the authenticated user's environment.

If Odoo denies the operation, MCP must report the denial.

That denial is correct behavior.

---

# 6. Generic, not application-specific

`odoo_mcp` should not contain special implementations such as:

```text
update_project_task
create_contact
update_sale_order
change_crm_lead
```

when those behaviors can be expressed through the generic ORM interface.

Prefer a generic model interface capable of supporting:

```text
project.task
res.partner
crm.lead
sale.order
helpdesk.ticket
custom.model
...
```

according to what is installed in that Odoo database and what the authenticated user can access.

This allows an AI agent to reason about Odoo dynamically rather than requiring `odoo_mcp` to know every Odoo application in advance.

---

# 7. Model discovery

For generic CRUD to be useful, AI agents need enough metadata to understand Odoo models.

The MCP interface should therefore investigate and, where safe, expose capabilities for discovering information such as:

```text
model technical name
model description
field names
field labels
field types
required fields
readonly fields
relational targets
selection values
```

This enables workflows such as:

```text
User:
"Create a new contact for John."

Agent:
What model represents contacts?
        ↓
res.partner

What fields can I use?
        ↓
name, email, phone, ...

Create record.
        ↓
MCP create
```

Discovery should remain bounded and should respect the module's security design.

---

# 8. CRUD surface

The initial architecture should focus on the smallest generic surface necessary to provide useful Odoo data access.

Likely primitives include concepts equivalent to:

```text
search
read
search_read
create
write
unlink
```

and model/field discovery.

The exact MCP tool design must be researched and specified before implementation.

Do not expose more power than necessary.

In particular, generic CRUD does not imply generic Python or arbitrary method execution.

---

# 9. Odoo owns business behavior

`odoo_mcp` should invoke normal ORM operations.

That means existing Odoo behavior remains active:

```text
MCP write
    ↓
model.write()
    ↓
Odoo overrides
    ↓
constraints
    ↓
business logic
    ↓
ACLs / record rules
    ↓
database
```

Do not recreate model business logic inside MCP.

Do not write directly to PostgreSQL as a shortcut.

Do not bypass model overrides.

This is important because CRUD operations in Odoo often trigger behavior beyond simply changing a database row.

---

# 10. Natural language is not this module's responsibility

`odoo_mcp` is not an LLM application.

It does not need to understand:

```text
"Make Ricardo's task description better."
```

Claude, ChatGPT, Gemini, or another AI client performs that reasoning.

The MCP server should expose sufficiently clear tools and metadata for the agent to translate that intent into something structured such as:

```text
search:
    model: project.task
    domain: ...

read:
    model: project.task
    ids: [...]
    fields: [...]

write:
    model: project.task
    ids: [...]
    values:
        description: ...
```

Keep reasoning in the AI client.

Keep Odoo operations in Odoo.

Keep `odoo_mcp` as the bridge.

---

# 11. No arbitrary execution

Generic CRUD must not gradually become generic remote execution.

Do not expose tools equivalent to:

```text
execute_python
eval
safe_eval
execute_sql
shell
bash
run_command
run_script
```

Do not accept Python expressions and evaluate them.

Do not expose arbitrary operating-system access.

Do not expose arbitrary PostgreSQL access.

The intended power comes from Odoo's ORM, not from remote code execution.

---

# 12. Method calls are separate from CRUD

Do not assume that generic CRUD requires arbitrary Odoo method execution.

Operations such as:

```python
record.action_confirm()
record.action_post()
record.some_method()
```

have different security and side-effect characteristics from:

```python
create()
read()
write()
unlink()
```

The first implementation should focus on generic CRUD and discovery.

If arbitrary or controlled business-method invocation becomes desirable later, treat that as a separate architectural problem with its own security analysis and OpenSpec change.

Do not sneak arbitrary method invocation into the CRUD interface.

---

# 13. Simplicity

Keep the implementation as small as the problem allows.

Prefer:

```text
MCP tool
   ↓
validation
   ↓
authenticated env
   ↓
ORM
```

over:

```text
MCP tool
   ↓
controller
   ↓
service
   ↓
provider
   ↓
adapter
   ↓
dispatcher
   ↓
repository
   ↓
ORM
```

unless concrete requirements demonstrate why those layers are necessary.

Do not build:

- custom dependency injection
- custom ORM abstractions
- custom authorization frameworks
- plugin frameworks
- generic dispatch frameworks
- speculative extension points

Odoo already provides most of the application infrastructure this module needs.

Use it.

---

# 14. Odoo-native first

When choosing an implementation, prefer in this order:

1. existing Odoo mechanism
2. small extension of an Odoo mechanism
3. simple local implementation
4. reusable abstraction
5. new framework

Moving downward requires increasing justification.

Inspect actual Odoo 19 source before inventing replacements for existing behavior.

Never modify Odoo core.

---

# 15. Guiding architecture

The intended end state should remain understandable as:

```text
"Update my task X"
        │
        ▼
Claude / ChatGPT / Gemini
        │
        │ reasons about request
        ▼
MCP CRUD request
        │
        ▼
odoo_mcp
        │
        │ validates request
        ▼
Authenticated Odoo Environment
        │
        ▼
project.task
        │
        │ normal ORM
        ▼
ACLs + Record Rules + Business Logic
        │
        ▼
Database
```

The same architecture should work for any other Odoo model:

```text
AI Agent
    │
    ▼
odoo_mcp
    │
    ▼
env[model]
    │
    ├── search
    ├── read
    ├── create
    ├── write
    └── unlink
         │
         ▼
normal Odoo security
```

That is the module.

Do not make it more complicated than that.

---

# 16. Definition of architectural success

`odoo_mcp` succeeds when an authenticated user can connect an MCP-compatible AI agent to Odoo and say things such as:

```text
"Show me my open tasks."

"Find customer ACME."

"Change ACME's phone number."

"Create a follow-up task."

"Improve the description of task X."

"Delete the draft record I created by mistake."
```

and the AI agent can translate those requests into generic MCP CRUD operations that Odoo executes with exactly that user's permissions.

If the user has permission:

```text
operation succeeds
```

If the user does not have permission:

```text
Odoo denies it
```

No hidden privilege escalation.

No application-specific MCP implementation.

No arbitrary Python.

No arbitrary SQL.

No duplicate business logic.

Just a clean, generic, secure MCP bridge to the Odoo ORM.

---

# 17. Implemented surface

The module is implemented (see `README.md` for operator documentation):

- Endpoint: `POST /mcp`, `type='http'`, `auth='bearer'` (Odoo API keys), stateless, JSON only
  (`controllers/main.py`, framing in `protocol.py`).
- Tools (exactly eight): `list_models`, `describe_model`, `search_read`, `search_count`, `read`,
  `create`, `write`, `unlink` (`tools/`). A new tool requires editing the inventory test and the
  README table.
- **Every tool must obtain its model through `tools.models.resolve_model`** (and multi-id tools
  through `existing_records`). That single resolver hides nonexistent, abstract, transient,
  unreadable and deny-listed models identically. Never index `env[...]` with a caller-supplied
  name anywhere else (a test enforces this).
- Deny-list: `DENIED_MODELS` in `tools/models.py` (credentials, system parameters, security
  definitions, schema, scheduled/server code, module installation). It is a code constant on
  purpose; it is not configurable at runtime.
- Errors and auditing: `tools.call_tool` runs each handler in a flushed savepoint, returns
  user-facing Odoo errors (truncated) as `isError` results, hides everything else behind
  `Internal error (ref: ...)`, and writes one audit line per call on the logger
  `odoo.addons.odoo_mcp.audit` (never argument values).
- Rate limit: in-process sliding window per (database, user) in `ratelimit.py` (per worker).
- Tests: `odoo-bin -d <scratch>-odoo -i odoo_mcp --test-enable --test-tags /odoo_mcp --stop-after-init`
  against a scratch database, never a production one.

