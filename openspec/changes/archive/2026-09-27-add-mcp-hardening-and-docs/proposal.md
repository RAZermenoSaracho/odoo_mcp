# Proposal

## Why

Changes 1-4 deliver a working, ACL-faithful bridge. Two gaps remain before it can be exposed to an internet-facing Odoo and to prompt-injectable agents: (1) an administrator's API key would let an agent touch credentials, system parameters, security definitions, schema, scheduled code, and module installation through plain CRUD; and (2) there is no request throttling, no consistent error hygiene, no audit trail, and no instructions for connecting a client. The MCP spec also requires servers to rate-limit and to validate tool inputs and sanitize outputs. Odoo ACLs stay authoritative; this change only adds defense in depth and operability.

## What Changes

- **Sensitive-model deny-list**: a small, explicit, hard-coded set of models (including at minimum `res.users.apikeys` and `ir.config_parameter`) that no tool can list, describe, read, or write — for every user including administrators. Implemented at the single resolver choke point from change 2.
- **Error sanitization**: bounded error messages, a correlation reference for internal errors, no exception class names, tracebacks, SQL, or file paths in any response.
- **Per-user rate limiting**: in-process sliding window on authenticated `/mcp` requests, `429` + `Retry-After` when exceeded.
- **Audit logging**: one structured log line per `tools/call` (who, which tool/model, how many ids, outcome, duration) without payload contents.
- **Client setup documentation**: README "Connecting an MCP client" (API key creation, endpoint URL, Claude Code / generic client configuration, Cloudflare Access note, limits, troubleshooting, tool reference) and a docs-consistency test; update README status and `CLAUDE.md`.
- **Adversarial test suite**: ACL parity across all tools, deny-list × every tool × admin, no-`sudo` source scan for the whole addon.

Non-goals: OAuth 2.1 / DCR, scoped API keys, a shared (DB or Redis) rate limiter, per-model allow-lists or configuration UI, IP allow-listing, chatter/method tools.

## Capabilities

### New Capabilities
- `mcp-hardening`: sensitive-model denial, error sanitization, rate limiting, audit logging, and addon-wide absence of privilege escalation.
- `mcp-client-setup`: operator and end-user documentation for connecting MCP clients, kept consistent with the actual tools.

### Modified Capabilities

(none — earlier capabilities are still un-archived changes, so requirements here are stated as new, additive, cross-cutting requirements)

## Impact

- Edits `tools/models.py` (`_is_exposed` gains the deny check), `tools/__init__.py` (error text/reference, audit hook), `controllers/main.py` (rate limit before dispatch); new `odoo_mcp/ratelimit.py` and tests; README and CLAUDE.md docs.
- Depends on changes 1-4. No schema, no config parameters, no `sudo`, no core changes. Deployment note: Cloudflare Access must allow bearer clients on `/mcp` (documented, not automated; `/etc/cloudflared` and `odoo.conf` are never touched).
