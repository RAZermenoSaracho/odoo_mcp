# Spec Delta

## Purpose

Tells operators and end users how to connect MCP clients to an Odoo database safely, and keeps that documentation consistent with the tools the endpoint actually exposes.

## ADDED Requirements

### Requirement: Client setup guide
The repository `README.md` SHALL contain a section "Connecting an MCP client" covering, in order: (1) prerequisites (Odoo 19 with `odoo_mcp` installed, an internal user); (2) creating an API key in *Preferences → Account Security → API Keys* with a short expiration, and the fact that only internal users can create keys and the key acts with that user's exact permissions; (3) the endpoint URL form `https://<database>-odoo.<domain>/mcp` and why the hostname's first label selects the database; (4) a `curl` smoke test that sends `server/discover` (or `tools/list`) with the Bearer header; (5) a configuration example for Claude Code (remote HTTP server with an `Authorization: Bearer` header) and a generic JSON/`mcp-remote`-style example for other clients, each stating that the client's current documentation is authoritative; (6) a Cloudflare Access note that `/mcp` must be reachable by bearer clients (path bypass or service token) while `/web/database/manager` stays protected, and that the operator applies tunnel/Access changes themselves; (7) a tool reference table; (8) limits (bounded reads and writes, body size, rate limit, per-worker caveat); (9) known limitations (no OAuth-only clients, no method calls, no binary by default, deny-listed models); (10) troubleshooting (`401`, `403` Origin, `415`, `429`, `Unknown model`, empty results due to record rules).

#### Scenario: Required sections exist
- **WHEN** `README.md` is parsed
- **THEN** it contains the section "Connecting an MCP client" with sub-headings for API key, endpoint URL, smoke test, client configuration, Cloudflare Access, tools, limits, limitations, and troubleshooting

#### Scenario: Smoke test is accurate
- **WHEN** the documented `curl` smoke test is run against a scratch database with a valid key
- **THEN** it returns HTTP `200` and a JSON-RPC result, and with a bad key it returns `401`

#### Scenario: No secrets in docs
- **WHEN** the README and CLAUDE.md are scanned
- **THEN** they contain no real API key, password, or private hostname; only placeholders such as `<api-key>` and `<database>-odoo.<domain>`

### Requirement: Documentation matches the tool surface
The tool reference in the README SHALL list exactly the tools returned by `tools/list`, with a one-line description, required arguments, and whether the tool is read-only, writing, or destructive. A test SHALL fail when a registered tool is undocumented or a documented tool does not exist.

#### Scenario: Consistency check passes
- **WHEN** the docs-consistency test runs against the registered tools
- **THEN** the documented tool names equal the registered tool names

#### Scenario: New tool without docs fails the test
- **WHEN** a tool is registered but not documented
- **THEN** the docs-consistency test fails

### Requirement: Project guidance is current
The `README.md` "Status" section SHALL state that the module is implemented (no longer a pre-implementation scaffold), and the repository `CLAUDE.md` SHALL gain a short "Implemented surface" section listing the eight tools, the deny-list location, the rate-limit and audit behavior, and the rule that new tools must resolve models only through the shared resolver.

#### Scenario: Status updated
- **WHEN** `README.md` is read after this change
- **THEN** it no longer says "Pre-implementation scaffold" and links to the setup guide

#### Scenario: CLAUDE.md lists the surface
- **WHEN** `CLAUDE.md` is read
- **THEN** it names all eight tools and the resolver rule
