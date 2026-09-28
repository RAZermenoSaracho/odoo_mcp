"""Read tools: thin, bounded wrappers over the ORM's search/read methods."""
import json

from odoo.tools.json import json_default

from . import Tool, ToolError, register
from .models import DENIED_MODELS, existing_records, reaches_denied_model, resolve_model

MAX_RESPONSE_BYTES = 1_000_000
MAX_DOMAIN_ELEMENTS = 100
MAX_VALUE_DEPTH = 5
DOMAIN_OPERATORS = ('&', '|', '!')
# Excluded from the default field selection: bulky, or unbounded in size.
DEFAULT_EXCLUDED_TYPES = ('binary', 'one2many', 'many2many')


def check_domain(domain, model=None):
    """Validate the *shape* of a JSON domain; the ORM validates fields/operators.

    With `model`, top-level leaves must not traverse into a denied model.
    """
    if not isinstance(domain, list):
        raise ToolError("Argument 'domain' must be an array")
    if len(domain) > MAX_DOMAIN_ELEMENTS:
        raise ToolError(f"Argument 'domain' has more than {MAX_DOMAIN_ELEMENTS} elements")
    for element in domain:
        if isinstance(element, str):
            if element not in DOMAIN_OPERATORS:
                raise ToolError(f"Argument 'domain' has an invalid operator {element!r}")
        elif (
            isinstance(element, list) and len(element) == 3
            and isinstance(element[0], str) and isinstance(element[1], str)
        ):
            _check_depth(element[2])
            if model is not None and reaches_denied_model(model, element[0]):
                raise ToolError(f"Unknown or unreadable field '{element[0]}'")
        else:
            raise ToolError("Argument 'domain' elements must be '&', '|', '!' or [field, operator, value]")
    return domain


def _check_depth(value):
    pending = [(value, 1)]
    while pending:
        item, depth = pending.pop()
        if isinstance(item, (list, dict)):
            if depth > MAX_VALUE_DEPTH:
                raise ToolError(f"Argument 'domain' is nested deeper than {MAX_VALUE_DEPTH} levels")
            children = item.values() if isinstance(item, dict) else item
            pending.extend((child, depth + 1) for child in children)


def select_fields(model, requested):
    """Explicit fields must be readable; the default excludes binary and x2many fields."""
    readable = {
        name: description
        for name, description in model.fields_get(attributes=['type', 'store', 'relation']).items()
        if description.get('relation') not in DENIED_MODELS
    }
    if requested is None:
        return [
            name for name, description in readable.items()
            if description['store'] and description['type'] not in DEFAULT_EXCLUDED_TYPES
        ]
    for name in requested:
        if name not in readable:
            raise ToolError(f"Unknown or unreadable field '{name}'")
    return list(dict.fromkeys(requested))


def check_size(result):
    if len(json.dumps(result, ensure_ascii=False, default=json_default)) > MAX_RESPONSE_BYTES:
        raise ToolError(
            f"Result too large (over {MAX_RESPONSE_BYTES} bytes); lower 'limit' or request fewer 'fields'")
    return result


def _model_and_domain(env, arguments):
    model = resolve_model(env, arguments['model'])
    if arguments.get('include_archived'):
        model = model.with_context(active_test=False)
    return model, check_domain(arguments.get('domain', []), model)


def _search_read(env, arguments):
    model, domain = _model_and_domain(env, arguments)
    fields = select_fields(model, arguments.get('fields'))
    offset = arguments.get('offset', 0)
    limit = arguments.get('limit', 50)
    try:
        # one extra row tells us whether more records exist
        records = model.search_read(
            domain, fields, offset=offset, limit=limit + 1, order=arguments.get('order') or None)
    except (ValueError, TypeError) as exc:
        raise ToolError(str(exc)) from exc
    return check_size({
        'records': records[:limit],
        'count': min(len(records), limit),
        'offset': offset,
        'limit': limit,
        'has_more': len(records) > limit,
    })


def _search_count(env, arguments):
    model, domain = _model_and_domain(env, arguments)
    try:
        return {'count': model.search_count(domain)}
    except (ValueError, TypeError) as exc:
        raise ToolError(str(exc)) from exc


def _read(env, arguments):
    model = resolve_model(env, arguments['model'])
    fields = select_fields(model, arguments.get('fields'))
    try:
        existing_records(model, arguments['ids'])
        by_id = {row['id']: row for row in model.browse(arguments['ids']).read(fields)}
        return check_size({'records': [by_id[record_id] for record_id in arguments['ids']]})
    except (ValueError, TypeError) as exc:
        raise ToolError(str(exc)) from exc


_READ_ONLY = {'readOnlyHint': True, 'destructiveHint': False, 'idempotentHint': True}
_MODEL = {'type': 'string', 'minLength': 1, 'maxLength': 128}
_DOMAIN = {'type': 'array'}
_FIELDS = {'type': 'array', 'maxItems': 100, 'items': {'type': 'string'}}
_ARCHIVED = {'type': 'boolean'}

register(Tool(
    name='search_read',
    title='Search and read records',
    description="Search records of a model with an Odoo domain (JSON array, e.g. "
                "[[\"name\", \"ilike\", \"acme\"]]) and return their fields. Results are "
                "paged (default 50, max 200); binary and x2many fields are only returned "
                "when listed in `fields`.",
    input_schema={
        'type': 'object',
        'properties': {
            'model': _MODEL,
            'domain': _DOMAIN,
            'fields': _FIELDS,
            'offset': {'type': 'integer', 'minimum': 0},
            'limit': {'type': 'integer', 'minimum': 1, 'maximum': 200},
            'order': {'type': 'string', 'maxLength': 200},
            'include_archived': _ARCHIVED,
        },
        'required': ['model'],
        'additionalProperties': False,
    },
    annotations=_READ_ONLY,
    handler=_search_read,
))

register(Tool(
    name='search_count',
    title='Count records',
    description="Count the records of a model matching an Odoo domain.",
    input_schema={
        'type': 'object',
        'properties': {'model': _MODEL, 'domain': _DOMAIN, 'include_archived': _ARCHIVED},
        'required': ['model'],
        'additionalProperties': False,
    },
    annotations=_READ_ONLY,
    handler=_search_count,
))

register(Tool(
    name='read',
    title='Read records by id',
    description="Read records of a model by id (1 to 200 ids). Fails if any id is missing or not accessible.",
    input_schema={
        'type': 'object',
        'properties': {
            'model': _MODEL,
            'ids': {'type': 'array', 'minItems': 1, 'maxItems': 200,
                    'items': {'type': 'integer', 'minimum': 1}},
            'fields': _FIELDS,
        },
        'required': ['model', 'ids'],
        'additionalProperties': False,
    },
    annotations=_READ_ONLY,
    handler=_read,
))
