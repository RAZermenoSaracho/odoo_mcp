"""Model resolution and discovery tools.

Discovery reveals only what the authenticated user may already read. It walks
the model registry and asks the ORM (`has_access`, `fields_get`) instead of
reading `ir.model`, which normal users cannot read.
"""
from . import Tool, ToolError, register

# Models no tool may ever touch, whatever the user's ACLs (defense in depth for
# prompt-injected agents): credentials, system parameters, security definitions,
# schema changes, scheduled/server-side code, and module installation.
DENIED_MODELS = frozenset({
    'res.users.apikeys',
    'res.users.apikeys.description',
    'res.users.apikeys.show',
    'ir.config_parameter',
    'ir.rule',
    'ir.model.access',
    'ir.model',
    'ir.model.fields',
    'ir.actions.server',
    'ir.cron',
    'ir.module.module',
})

FIELD_ATTRIBUTES = ['string', 'type', 'required', 'readonly', 'store', 'relation', 'selection', 'help']


def _is_exposed(env, name):
    """Whether `name` is a concrete, non-denied model the user may read."""
    if name in DENIED_MODELS:
        return False
    model = env.registry.get(name)
    if model is None or model._abstract or model._transient:
        return False
    return env[name].has_access('read')


def resolve_model(env, name):
    """Return the model `name` as a recordset, or raise the uniform "unknown" error.

    Every tool that takes a model name must come through here, so that
    nonexistent, abstract, transient and forbidden models look identical.
    """
    if not _is_exposed(env, name):
        raise ToolError(f"Unknown model '{name}'")
    return env[name]


def reaches_denied_model(model, path):
    """Whether the dotted field `path` (from `model`) leads into a denied model."""
    for part in path.split('.'):
        field = model._fields.get(part)
        if field is None or not field.relational:
            return False
        if field.comodel_name in DENIED_MODELS:
            return True
        model = model.env[field.comodel_name]
    return False


def existing_records(model, ids):
    """Return `model.browse(ids)` (de-duplicated), or fail if any id does not exist.

    The ORM silently skips missing ids in `read`; tools must not act on a partial set.
    """
    ids = list(dict.fromkeys(ids))
    records = model.browse(ids)
    missing = sorted(set(ids) - set(records.exists().ids))
    if missing:
        raise ToolError(f"Records not found: {missing}")
    return records


def _list_models(env, arguments):
    query = arguments.get('query', '').lower()
    offset = arguments.get('offset', 0)
    limit = arguments.get('limit', 100)
    matches = [
        name for name in sorted(env.registry)
        if not query or query in name.lower() or query in (env.registry[name]._description or '').lower()
    ]
    exposed = [name for name in matches if _is_exposed(env, name)]
    return {
        'models': [
            {'model': name, 'name': env[name]._description or name}
            for name in exposed[offset:offset + limit]
        ],
        'total': len(exposed),
        'offset': offset,
        'limit': limit,
    }


def _describe_model(env, arguments):
    model = resolve_model(env, arguments['model'])
    fields = {
        fname: description
        for fname, description in model.fields_get(allfields=arguments.get('fields'), attributes=FIELD_ATTRIBUTES).items()
        if description.get('relation') not in DENIED_MODELS
    }
    return {
        'model': model._name,
        'name': model._description or model._name,
        'access': {op: model.has_access(op) for op in ('read', 'create', 'write', 'unlink')},
        'fields': {
            fname: {key: value for key, value in description.items() if value is not None}
            for fname, description in fields.items()
        },
    }


_READ_ONLY = {'readOnlyHint': True, 'destructiveHint': False, 'idempotentHint': True}

register(Tool(
    name='list_models',
    title='List models',
    description="List the Odoo models you may read (technical name and label). "
                "Use `query` to filter by name or label.",
    input_schema={
        'type': 'object',
        'properties': {
            'query': {'type': 'string', 'maxLength': 100},
            'offset': {'type': 'integer', 'minimum': 0},
            'limit': {'type': 'integer', 'minimum': 1, 'maximum': 200},
        },
        'additionalProperties': False,
    },
    annotations=_READ_ONLY,
    handler=_list_models,
))

register(Tool(
    name='describe_model',
    title='Describe a model',
    description="Describe an Odoo model: your access rights on it and its fields "
                "(label, type, required, readonly, relation, selection values).",
    input_schema={
        'type': 'object',
        'properties': {
            'model': {'type': 'string', 'minLength': 1, 'maxLength': 128},
            'fields': {'type': 'array', 'maxItems': 100, 'items': {'type': 'string'}},
        },
        'required': ['model'],
        'additionalProperties': False,
    },
    annotations=_READ_ONLY,
    handler=_describe_model,
))
