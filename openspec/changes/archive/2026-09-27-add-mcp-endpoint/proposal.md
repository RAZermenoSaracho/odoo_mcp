# Proposal

## Why

`odoo_mcp` is a scaffold with no runtime code. Before any Odoo data can be exposed, an MCP client needs an endpoint it can connect to, authenticate against, and speak MCP to. The exploration of the Odoo 19 source showed that Odoo already provides the hard parts: per-user API keys (`res.users.apikeys`) and `auth='bearer'` routing that binds a request to the key owner's `request.env`. What is missing is only the MCP wire protocol and a small tool table for later changes to plug into.

## What Changes

- Add a single stateless MCP endpoint `POST /mcp` protected by Odoo's existing `auth='bearer'` (Odoo API keys created in *Preferences → Account Security → API Keys*). No new auth, session, or token infrastructure.
- Implement MCP JSON-RPC framing for the current revision (2026-07-28: per-request `_meta`, `MCP-Protocol-Version`, `Mcp-Method`/`Mcp-Name` headers, `server/discover`) and the legacy `initialize` handshake (2025-11-25), served statelessly with no `Mcp-Session-Id`.
- Support `tools/list` and `tools/call` plus `ping` and `notifications/*` (202). Register no real tools yet; provide the small tool table and the `tools/call` execution boundary (savepoint, error mapping) that changes 2-4 use.
- Enforce protocol-level safety: `Origin` validation, request-size cap, JSON-only responses, no GET/DELETE.
- Add a test suite proving valid/invalid API-key behavior and protocol framing.

Non-goals: OAuth 2.1 / dynamic client registration, SSE/streaming, sessions, resources, prompts, sampling/elicitation, `subscriptions/listen`, scoped `mcp` API keys, any model discovery or CRUD (later changes).

## Capabilities

### New Capabilities
- `mcp-endpoint`: authenticated, stateless MCP-over-HTTP endpoint with protocol framing, version negotiation, tool listing/calling boundary, and safe error mapping.

### Modified Capabilities

(none — `openspec/specs/` is empty)

## Impact

- New files under `odoo_mcp/` (`controllers/`, `protocol.py`, `tools/`, `tests/`); `__manifest__.py` gains no new dependency (`depends: ["base"]` — `auth='bearer'` lives in `base`).
- Adds one public HTTP route `/mcp` (`auth='bearer'`, stateless). Deployment note: `/mcp` must be reachable by bearer clients through Cloudflare Access (documented in change 5).
- No models, no `ir.model.access.csv` rows, no database schema, no changes to Odoo core or `odoo.conf`.
