"""Write tools: thin wrappers over the ORM's create/write/unlink.

Atomicity comes from the savepoint in `call_tool`; access control, constraints
and business logic are the ORM's. Nothing here elevates privileges.
"""
from . import Tool, ToolError, register
from .models import DENIED_MODELS, existing_records, resolve_model

MAX_VALUE_KEYS = 200
PROTECTED_FIELDS = ('id', 'create_uid', 'create_date', 'write_uid', 'write_date')


def check_values(model, values):
    """Validate field *names*; values go to the ORM unchanged."""
    if not values:
        raise ToolError("Argument 'values' must not be empty")
    if len(values) > MAX_VALUE_KEYS:
        raise ToolError(f"Argument 'values' has more than {MAX_VALUE_KEYS} fields")
    visible = {
        name: description
        for name, description in model.fields_get(attributes=['type', 'readonly', 'relation']).items()
        if description.get('relation') not in DENIED_MODELS
    }
    for name in values:
        if name in PROTECTED_FIELDS or (name == 'display_name' and visible.get(name, {}).get('readonly')):
            raise ToolError(f"Field '{name}' cannot be set")
        if name not in visible:
            raise ToolError(f"Unknown or unreadable field '{name}'")
    return values


def _create(env, arguments):
    model = resolve_model(env, arguments['model'])
    values = check_values(model, arguments['values'])
    try:
        return {'id': model.create(values).id}
    except (ValueError, TypeError) as exc:
        raise ToolError(str(exc)) from exc


def _write(env, arguments):
    model = resolve_model(env, arguments['model'])
    values = check_values(model, arguments['values'])
    records = existing_records(model, arguments['ids'])
    try:
        records.write(values)
    except (ValueError, TypeError) as exc:
        raise ToolError(str(exc)) from exc
    return {'updated': len(records)}


def _unlink(env, arguments):
    model = resolve_model(env, arguments['model'])
    records = existing_records(model, arguments['ids'])
    records.unlink()
    return {'deleted': len(records)}


_MODEL = {'type': 'string', 'minLength': 1, 'maxLength': 128}
_IDS = {'type': 'array', 'minItems': 1, 'maxItems': 100, 'items': {'type': 'integer', 'minimum': 1}}
_VALUES = {'type': 'object'}

register(Tool(
    name='create',
    title='Create a record',
    description="Create one record. `values` maps field names to values (many2one: the id; "
                "x2many: Odoo command lists such as [[0, 0, {...}]]). Returns the new id.",
    input_schema={
        'type': 'object',
        'properties': {'model': _MODEL, 'values': _VALUES},
        'required': ['model', 'values'],
        'additionalProperties': False,
    },
    annotations={'readOnlyHint': False, 'destructiveHint': False, 'idempotentHint': False},
    handler=_create,
))

register(Tool(
    name='write',
    title='Update records',
    description="Update 1 to 100 existing records with the same `values`. Nothing is changed "
                "if any id is missing or the update is refused.",
    input_schema={
        'type': 'object',
        'properties': {'model': _MODEL, 'ids': _IDS, 'values': _VALUES},
        'required': ['model', 'ids', 'values'],
        'additionalProperties': False,
    },
    annotations={'readOnlyHint': False, 'destructiveHint': False, 'idempotentHint': True},
    handler=_write,
))

register(Tool(
    name='unlink',
    title='Delete records',
    description="Delete 1 to 100 existing records. Destructive. Nothing is deleted if any id "
                "is missing or the deletion is refused.",
    input_schema={
        'type': 'object',
        'properties': {'model': _MODEL, 'ids': _IDS},
        'required': ['model', 'ids'],
        'additionalProperties': False,
    },
    annotations={'readOnlyHint': False, 'destructiveHint': True, 'idempotentHint': False},
    handler=_unlink,
))
