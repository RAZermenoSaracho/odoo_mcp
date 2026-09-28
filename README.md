# Odoo MCP

A reusable Model Context Protocol (MCP) interface for Odoo 19: it lets
authenticated AI agents and MCP clients interact with Odoo through a
controlled interface, while Odoo remains the source of truth for identity,
authorization, business logic, and data access.

```
AI Agent / MCP Client -> odoo_mcp -> Odoo ORM -> ACLs / Record Rules -> Database
```

Core principle: an MCP client acts as an Odoo user, not as a privileged
database or server process. Every active MCP connection maps to a real
`res.users` record, and every operation runs through the normal Odoo ORM under
that user's own access rights — no anonymous or privileged execution path.

`odoo_mcp` is designed as a generic, reusable module. It owns MCP protocol
integration, connection authentication, session/request context, tool and
resource exposure, and translation between MCP requests and ORM operations —
not domain-specific automation, not server/OS/Git/GitHub/AI-process execution,
and not a way to bypass Odoo security. It does not depend on any private RAZS
module.

Design history: [ODOO_MCP_IMPLEMENTATION_PLAN.md](../ODOO_MCP_IMPLEMENTATION_PLAN.md) and the OpenSpec changes under `openspec/`.

- Technical name: `odoo_mcp`
- Scope: `shared` — installable in any database whose manifest dependencies
  are satisfied. Placement under `user/` declares this and `tenancy_guard`
  enforces it at install time (see the project root `CLAUDE.md`, "Addon scope
  hierarchy").
- License: LGPL-3 (open source — see `LICENSE`), matching the convention
  already established by [many2many_razs_widget](../many2many_razs_widget).

## Status

Implemented: one stateless MCP endpoint (`POST /mcp`), Odoo API-key authentication, permission-aware
model/field discovery, bounded reads, atomic writes, a sensitive-model deny-list, per-user rate
limiting, and audit logging. See [Connecting an MCP client](#connecting-an-mcp-client) to use it.

## Connecting an MCP client

### Prerequisites

- Odoo 19 with `odoo_mcp` installed in the target database (it depends only on `base`).
- An **internal** Odoo user. The agent acts with exactly that user's permissions: Odoo access
  rights, record rules, field restrictions and business logic all apply. Portal and public users
  cannot create API keys.

### API key

1. Sign in as the user, open *Preferences → Account Security → API Keys* and choose *New API Key*.
2. Give it a description and a **short expiration**, confirm your password, and copy the key once
   (Odoo never shows it again). Revoke it from the same screen at any time.

The key is a normal Odoo API key: treat it like a password. It also works on Odoo's other
programmatic APIs (`/json/2`, XML-RPC) with the same user rights.

### Endpoint URL

```text
https://<database>-odoo.<domain>/mcp
```

Odoo picks the database from the first label of the hostname (`dbfilter = ^%d$`), so
`<database>-odoo.<domain>` serves the database `<database>-odoo`.

### Smoke test

```bash
curl -sS https://<database>-odoo.<domain>/mcp \
  -H "Authorization: Bearer <api-key>" \
  -H "Content-Type: application/json" \
  -H "MCP-Protocol-Version: 2026-07-28" \
  -H "Mcp-Method: server/discover" \
  -d '{"jsonrpc":"2.0","id":1,"method":"server/discover","params":{"_meta":{"io.modelcontextprotocol/protocolVersion":"2026-07-28","io.modelcontextprotocol/clientInfo":{"name":"curl","version":"1"},"io.modelcontextprotocol/clientCapabilities":{}}}}'
```

A valid key returns `200` and a JSON-RPC result listing `supportedVersions` and the `tools`
capability. A bad or missing key returns `401`.

### Client configuration

These examples are illustrative; your client's current documentation is authoritative.

Claude Code (remote HTTP server with a bearer header):

```bash
claude mcp add --transport http odoo https://<database>-odoo.<domain>/mcp \
  --header "Authorization: Bearer <api-key>"
```

The same server in `.mcp.json` (prefer an environment variable over a literal key):

```json
{
  "mcpServers": {
    "odoo": {
      "type": "http",
      "url": "https://<database>-odoo.<domain>/mcp",
      "headers": { "Authorization": "Bearer ${ODOO_MCP_KEY}" }
    }
  }
}
```

Other clients: any MCP client that speaks Streamable HTTP and can send a custom
`Authorization: Bearer <api-key>` header works. Clients that only support stdio can use a bridge
such as `mcp-remote` with the URL above and the same header.

### Cloudflare Access

`/mcp` authenticates with the bearer key itself, so it must be reachable by non-browser clients:
give the `/mcp` path an Access bypass (or use an Access service token), while
`/web/database/manager` stays protected. Tunnel and Access changes are applied by the operator;
this module never touches them.

### Tools

Model names are Odoo technical names such as `res.partner`. Every tool runs as the key's user.

| Tool | Description | Arguments | Kind |
|---|---|---|---|
| `list_models` | List the models you may read (name and label). | optional `query`, `offset`, `limit` | read-only |
| `describe_model` | Your access rights on a model and its fields (type, required, readonly, relation, selection). | `model`; optional `fields` | read-only |
| `search_read` | Search records with a JSON domain and return fields; paged. | `model`; optional `domain`, `fields`, `offset`, `limit`, `order`, `include_archived` | read-only |
| `search_count` | Count records matching a domain. | `model`; optional `domain`, `include_archived` | read-only |
| `read` | Read records by id. | `model`, `ids`; optional `fields` | read-only |
| `create` | Create one record. | `model`, `values` | writing |
| `write` | Update existing records with the same values. | `model`, `ids`, `values` | writing |
| `unlink` | Delete records. | `model`, `ids` | destructive |

### Limits

| Limit | Value |
|---|---|
| `limit` (search_read) | default 50, maximum 200 |
| `list_models` `limit` | default 100, maximum 200 |
| `ids` (read) | 1 to 200 |
| `ids` (write, unlink) | 1 to 100 |
| `fields` | at most 100 names |
| domain | at most 100 top-level elements, values nested at most 5 levels |
| response size | 1,000,000 bytes (larger results are refused, never truncated) |
| request body | 2 MiB |
| rate limit | 120 requests per 60 seconds per user (`429` + `Retry-After`) |

The rate limiter lives in each Odoo worker process, so with N workers the effective ceiling is up
to N times the limit. Every write tool call is atomic: on any error nothing is changed.

### Limitations

- Static API keys only: clients that require an OAuth authorization flow cannot connect.
- No model method calls (`action_confirm`, ...), no Python, SQL or shell: only create, read, write, delete.
- Binary fields are not returned unless explicitly listed in `fields`.
- A user needs read access to a model to use any tool on it (create/write/delete included).
- These models are never accessible to any tool, even for administrators: `res.users.apikeys`
  (and its wizards), `ir.config_parameter`, `ir.rule`, `ir.model.access`, `ir.model`,
  `ir.model.fields`, `ir.actions.server`, `ir.cron`, `ir.module.module`. They behave like
  nonexistent models.

### Troubleshooting

| Symptom | Cause |
|---|---|
| `401` | Missing, wrong, expired or revoked key, or the key's user is archived. |
| `403` | The request carries an `Origin` header that does not match the server (browser-based clients are not supported). |
| `415` | `Content-Type` is not `application/json`. |
| `429` | Rate limit exceeded; wait for `Retry-After` seconds. |
| `Unknown model '...'` | The model does not exist, is abstract or a wizard, is denied, or the user cannot read it. |
| Empty results | Record rules or the user's company scope hide the records; the agent sees what the user sees. |
| `Internal error (ref: xxxxxxxx)` | An unexpected server error; the full traceback is in the Odoo log under that reference. |
