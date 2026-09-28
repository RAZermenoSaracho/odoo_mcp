# Design

## Context

See `proposal.md`. Depends on `add-mcp-endpoint` (tool table `register()`, `call_tool` boundary, tool-arg validator). Source facts:

- `ir.model` / `ir.model.fields` grant nothing to `base.group_user` (`odoo/addons/base/security/ir.model.access.csv:18`), so a normal user cannot search them; `sudo()` is forbidden here.
- `env.registry` maps model names to classes; `env[name]` works for any registered model, and `BaseModel.has_access('read')` on an empty recordset checks the model-level ACL only (`odoo/orm/models.py:4100-4135`).
- `fields_get` already drops fields the user cannot read and flags `readonly` for fields it cannot write (`orm/models.py:3343-3375`).
- Model description is `Model._description`; abstract models have `_abstract = True`, wizards `_transient = True`.

## Goals / Non-Goals

**Goals:** two read-only tools and one resolver; no `sudo`; results bounded.

**Non-Goals:** view/action/menu discovery; relation graph; caching layer (the ORM's ACL cache already helps); pagination cursors (offset/limit is enough).

## Decisions

**D1. Registry iteration, not `ir.model`.** `list_models` iterates `env.registry` (names in sorted order), skips abstract/transient classes, keeps `env[name].has_access('read')`, applies `query`, then pages. Cost is one cached ACL lookup per model; acceptable for the ~hundreds of models in a typical DB. Alternative: `sudo()` on `ir.model` and post-filter — rejected (violates the no-sudo invariant even if filtered).

**D2. Single resolver.** `tools/models.py` exposes `resolve_model(env, name) -> Model` raising `ToolError("Unknown model '<name>'")` (`ToolError` is defined by change 1 and mapped by `call_tool` to `isError` with its message) in all of: not in registry, abstract, transient, no read access. Same text for all so existence is not an oracle. `list_models` also reuses the same predicate (`_is_exposed(env, name)`) so list and resolve can never disagree. **Every later tool must obtain its model only via `resolve_model`** (enforced by a test that greps tool modules for direct `env[` use with a caller-supplied name). Change 5 adds the deny-list inside `_is_exposed`.

**D3. `describe_model` output.** Call `Model.fields_get(allfields=fields or None, attributes=['string','type','required','readonly','store','relation','selection','help'])`, drop attributes that are absent/`None`, and build `access` with `has_access` for `read/create/write/unlink`. `readonly` is used as returned (already merged with write access). Note that `describe_model` requires read access (via the resolver) — a create-only model is not describable; acceptable and consistent with "discovery reveals only readable models".

**D4. Bounds.** `limit` max 200 default 100, `fields` max 100 — validated by change 1's minimal validator (`minimum`/`maximum`/`maxItems`/`minLength`).

## Risks / Trade-offs

- [`has_access` per model on every `list_models` call] → Bounded by registry size; ORM caches ACL lookups (`ir.model.access` ormcache). If measurably slow in apply, add `query`-first filtering before the ACL check (already the order).
- [Read access is required to describe a model, so a create-only user cannot discover fields for creating] → Accepted; it is rare and can be revisited by a separate change.
- [Field `help`/labels are translated per user language] → Expected; the request context lang is the user's.
