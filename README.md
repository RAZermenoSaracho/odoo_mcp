# Odoo MCP

A reusable Model Context Protocol (MCP) interface for Odoo 19. It lets
authenticated AI agents and MCP clients interact with Odoo through a controlled
interface, while Odoo remains the source of truth for identity, authorization,
business logic, and data access.

```text
AI Agent / MCP Client -> odoo_mcp -> Odoo ORM -> ACLs / Record Rules -> Database
```

Core principle: an MCP client acts as an Odoo user, not as a privileged
database or server process. Every MCP request authenticates as a real
`res.users` record, and every operation runs through the normal Odoo ORM under
that user's own access rights — no anonymous or privileged execution path.

`odoo_mcp` is designed as a generic, reusable module. It owns MCP protocol
integration, authentication, request context, tool exposure, and translation
between MCP requests and ORM operations — not domain-specific automation,
server/OS/Git/GitHub/AI-process execution, or a way to bypass Odoo security.

Design history is available through the OpenSpec specifications under
`openspec/`.

- Technical name: `odoo_mcp`
- Odoo version: 19
- Dependencies: `base`
- License: LGPL-3 (see `LICENSE`)

## Status

Implemented and tested: one stateless MCP endpoint (`POST /mcp`), Odoo API-key
authentication, permission-aware model/field discovery, bounded reads, atomic
writes, a sensitive-model deny-list, per-user rate limiting, and audit logging.

The implementation has been validated with real MCP clients, including Claude
Code and Claude custom connectors.

See [Connecting an MCP client](#connecting-an-mcp-client) to use it.

## Deployment support

| Odoo deployment | Support |
|---|---|
| Odoo 19 self-hosted / on-premise | Supported |
| Odoo.sh 19 | Supported |
| Odoo Online / Odoo SaaS | Not supported |

`odoo_mcp` is a standard Python Odoo addon. It defines an HTTP controller and
server-side Python code for the MCP protocol and ORM tools.

Odoo Online/SaaS does not allow this kind of server-side Python addon to be
installed through its importable-module mechanism. Use Odoo.sh or a self-hosted
Odoo installation instead.

## Connecting an MCP client

### Prerequisites

- Odoo 19 with `odoo_mcp` installed in the target database.
- An **internal** Odoo user. The agent acts with exactly that user's
  permissions: Odoo access rights, record rules, field restrictions, company
  scope, and business logic all apply.
- An Odoo API key belonging to that user.

Portal and public users cannot create API keys.

### API key

1. Sign in as the user.
2. Open **Preferences → Account Security → API Keys**.
3. Choose **New API Key**.
4. Give it a description and preferably a short expiration.
5. Confirm your password and copy the key.

Odoo only shows the key when it is created. Revoke it from the same screen at
any time.

Treat the API key like a password. It represents the Odoo user and therefore
inherits that user's access rights.

### Endpoint URL

The endpoint is:

```text
https://<your-odoo-host>/mcp
```

For example:

```text
https://odoo.example.com/mcp
```

Database selection and hostname routing are deployment-specific. Configure
Odoo's normal `dbfilter`, reverse proxy, TLS, and hostname routing as appropriate
for your environment.

### Smoke test

```bash
curl -sS https://<your-odoo-host>/mcp \
  -H "Authorization: Bearer <api-key>" \
  -H "Content-Type: application/json" \
  -H "MCP-Protocol-Version: 2026-07-28" \
  -H "Mcp-Method: server/discover" \
  -d '{"jsonrpc":"2.0","id":1,"method":"server/discover","params":{"_meta":{"io.modelcontextprotocol/protocolVersion":"2026-07-28","io.modelcontextprotocol/clientInfo":{"name":"curl","version":"1"},"io.modelcontextprotocol/clientCapabilities":{}}}}'
```

A valid key returns `200` and a JSON-RPC result listing `supportedVersions` and
the `tools` capability.

A bad or missing key returns `401`.

### Claude Code

Add the remote MCP server with the Odoo API key as a bearer header:

```bash
claude mcp add --transport http odoo https://<your-odoo-host>/mcp \
  --header "Authorization: Bearer <api-key>"
```

Verify the connection:

```bash
claude mcp list
```

The server should appear connected and expose the eight Odoo MCP tools.

The same server can be represented in `.mcp.json`. Prefer an environment
variable over storing the API key directly:

```json
{
  "mcpServers": {
    "odoo": {
      "type": "http",
      "url": "https://<your-odoo-host>/mcp",
      "headers": {
        "Authorization": "Bearer ${ODOO_MCP_KEY}"
      }
    }
  }
}
```

### Claude custom connector

Claude custom connectors can connect to the same remote MCP endpoint.

Configure:

```text
URL: https://<your-odoo-host>/mcp
Authentication: No sign-in / API key
Header: Authorization
Value: Bearer <api-key>
```

Once connected, Claude can discover the same read and write tools exposed to
Claude Code. Tool permissions can additionally be controlled from the client.

### Other MCP clients

Any compatible remote MCP client that can send a custom:

```text
Authorization: Bearer <api-key>
```

header can connect to the endpoint.

Clients that require OAuth exclusively are not currently supported.

## Reverse proxies and access gateways

`/mcp` authenticates requests using the Odoo API key itself.

If Odoo is behind Cloudflare Access, another identity-aware proxy, or a similar
gateway, that gateway must also permit the MCP client to reach `/mcp`.

For example, a deployment may:

- allow `/mcp` through the gateway and rely on the Odoo bearer key for
  authentication, or
- require an additional service credential supported by the MCP client.

Keep administrative Odoo endpoints such as `/web/database/manager` protected
according to your normal deployment policy.

Proxy, tunnel, DNS, TLS, and access-gateway configuration are outside the scope
of this addon.

## Tools

Model names are Odoo technical names such as `res.partner`. Every tool runs as
the API key's Odoo user.

| Tool | Description | Arguments | Kind |
|---|---|---|---|
| `list_models` | List the models you may read (name and label). | optional `query`, `offset`, `limit` | read-only |
| `describe_model` | Your access rights on a model and its fields (type, required, readonly, relation, selection). | `model`; optional `fields` | read-only |
| `search_read` | Search records with a JSON domain and return fields; paged. | `model`; optional `domain`, `fields`, `offset`, `limit`, `order`, `include_archived` | read-only |
| `search_count` | Count records matching a domain. | `model`; optional `domain`, `include_archived` | read-only |
| `read` | Read records by ID. | `model`, `ids`; optional `fields` | read-only |
| `create` | Create one record. | `model`, `values` | writing |
| `write` | Update existing records with the same values. | `model`, `ids`, `values` | writing |
| `unlink` | Delete records. | `model`, `ids` | destructive |

## Limits

| Limit | Value |
|---|---|
| `limit` (`search_read`) | default 50, maximum 200 |
| `list_models` `limit` | default 100, maximum 200 |
| `ids` (`read`) | 1 to 200 |
| `ids` (`write`, `unlink`) | 1 to 100 |
| `fields` | at most 100 names |
| domain | at most 100 top-level elements, values nested at most 5 levels |
| response size | 1,000,000 bytes; larger results are refused, never truncated |
| request body | 2 MiB |
| rate limit | 120 requests per 60 seconds per user (`429` + `Retry-After`) |

The rate limiter lives in each Odoo worker process, so with N workers the
effective ceiling is up to N times the configured limit.

Every write tool call is atomic: if the operation fails, its changes are rolled
back.

## Security model

The MCP endpoint does not create a parallel authorization system.

Requests execute through the normal Odoo environment associated with the API
key's user:

```text
MCP request
    |
    v
Odoo API key
    |
    v
res.users
    |
    v
Odoo ORM
    |
    +--> Access rights
    +--> Record rules
    +--> Field restrictions
    +--> Company scope
    +--> Business logic
```

The addon never uses `sudo()` to turn an MCP request into privileged CRUD.

In addition to normal Odoo authorization, particularly sensitive technical
models are deliberately unavailable through the generic MCP tools.

## Limitations

- Authentication currently uses static Odoo API keys; clients that require an
  OAuth authorization flow cannot connect.
- No arbitrary model method calls (`action_confirm`, etc.).
- No arbitrary Python, SQL, shell, server process, Git, or operating-system
  execution.
- The generic interface is intentionally limited to discovery and CRUD.
- Binary fields are not returned unless explicitly listed in `fields`.
- A user needs read access to a model to use any tool on it, including
  create/write/delete.
- The following models are never accessible to any tool, even for
  administrators:
  - `res.users.apikeys` and its wizards
  - `ir.config_parameter`
  - `ir.rule`
  - `ir.model.access`
  - `ir.model`
  - `ir.model.fields`
  - `ir.actions.server`
  - `ir.cron`
  - `ir.module.module`
- Relations into denied models are also protected.
- Odoo Online/SaaS is not supported because the addon requires server-side
  Python code.

Denied models behave like nonexistent models to MCP clients.

## Troubleshooting

| Symptom | Cause |
|---|---|
| `401` | Missing, wrong, expired or revoked API key, or the key's user is archived. |
| `403` | The request contains an `Origin` header that does not match the server's accepted origin policy. |
| `415` | `Content-Type` is not `application/json`. |
| `429` | Rate limit exceeded; wait for the `Retry-After` interval. |
| `Unknown model '...'` | The model does not exist, is abstract or transient, is denied, or the user cannot read it. |
| Empty results | Record rules, company scope, or other Odoo authorization rules hide the records. |
| `Internal error (ref: xxxxxxxx)` | Unexpected server error; use the reference to find the corresponding traceback in the Odoo server log. |

## Development

The canonical behavioral specifications and design history live under
`openspec/`.

The test suite covers the MCP protocol, endpoint authentication, model
discovery, CRUD behavior, ORM security parity, hardening, documentation, and
source-level security invariants.

Contributions should preserve the central invariant:

> An MCP client may do what its Odoo user is authorized to do through the
> exposed MCP surface — never more.