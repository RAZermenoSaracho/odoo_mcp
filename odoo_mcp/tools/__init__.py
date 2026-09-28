"""Tool table and the `tools/call` execution boundary.

A tool is a `Tool` registered at import time; its handler receives the
authenticated `env` and validated arguments and returns a JSON-serializable
dict. `call_tool` runs it inside a savepoint and maps errors to MCP results.
"""
import json
import logging
import re
import time
import uuid
from typing import Any, Callable, NamedTuple

from odoo.exceptions import AccessError, MissingError, UserError, ValidationError
from odoo.tools.json import json_default

_logger = logging.getLogger(__name__)


class ToolError(Exception):
    """A deliberate, user-facing tool failure (returned as an `isError` result)."""


class UnknownTool(Exception):
    """`tools/call` named a tool that is not registered (protocol error)."""


class Tool(NamedTuple):
    name: str
    title: str
    description: str
    input_schema: dict
    annotations: dict
    handler: Callable[[Any, dict], dict]


TOOLS: dict[str, Tool] = {}


def register(tool):
    assert tool.name not in TOOLS, f"duplicate tool {tool.name!r}"
    TOOLS[tool.name] = tool
    return tool


def list_tools():
    """MCP `tools/list` entries, sorted by name for a deterministic order."""
    return [
        {
            'name': tool.name,
            'title': tool.title,
            'description': tool.description,
            'inputSchema': tool.input_schema,
            'annotations': tool.annotations,
        }
        for tool in sorted(TOOLS.values(), key=lambda t: t.name)
    ]


# --- minimal input validation (no jsonschema dependency) ---------------------

_TYPES = {
    'string': str,
    'boolean': bool,
    'array': list,
    'object': dict,
}


def _check_type(value, expected, path):
    if expected == 'integer':
        ok = isinstance(value, int) and not isinstance(value, bool)
    elif expected == 'number':
        ok = isinstance(value, (int, float)) and not isinstance(value, bool)
    else:
        ok = isinstance(value, _TYPES[expected])
    if not ok:
        raise ToolError(f"Argument '{path}' must be of type {expected}")


def _check_value(value, schema, path):
    expected = schema.get('type')
    if expected:
        _check_type(value, expected, path)
    if 'enum' in schema and value not in schema['enum']:
        raise ToolError(f"Argument '{path}' must be one of {schema['enum']}")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if 'minimum' in schema and value < schema['minimum']:
            raise ToolError(f"Argument '{path}' must be >= {schema['minimum']}")
        if 'maximum' in schema and value > schema['maximum']:
            raise ToolError(f"Argument '{path}' must be <= {schema['maximum']}")
    if isinstance(value, str):
        if 'minLength' in schema and len(value) < schema['minLength']:
            raise ToolError(f"Argument '{path}' must have at least {schema['minLength']} characters")
        if 'maxLength' in schema and len(value) > schema['maxLength']:
            raise ToolError(f"Argument '{path}' must have at most {schema['maxLength']} characters")
    if isinstance(value, list):
        if 'minItems' in schema and len(value) < schema['minItems']:
            raise ToolError(f"Argument '{path}' must have at least {schema['minItems']} items")
        if 'maxItems' in schema and len(value) > schema['maxItems']:
            raise ToolError(f"Argument '{path}' must have at most {schema['maxItems']} items")
        if 'items' in schema:
            for index, item in enumerate(value):
                _check_value(item, schema['items'], f"{path}[{index}]")
    if isinstance(value, dict) and 'properties' in schema:
        _check_object(value, schema, path)


def _check_object(value, schema, path=''):
    prefix = f"{path}." if path else ''
    properties = schema.get('properties', {})
    for name in schema.get('required', ()):
        if name not in value:
            raise ToolError(f"Missing required argument '{prefix}{name}'")
    for name, item in value.items():
        if name not in properties:
            if schema.get('additionalProperties') is False:
                raise ToolError(f"Unknown argument '{prefix}{name}'")
            continue
        _check_value(item, properties[name], f"{prefix}{name}")


def validate_arguments(schema, arguments):
    """Raise `ToolError` unless `arguments` satisfies the tool's input schema."""
    _check_type(arguments, 'object', 'arguments')
    _check_object(arguments, schema)


# --- execution boundary --------------------------------------------------------

_audit = logging.getLogger('odoo.addons.odoo_mcp.audit')
MAX_MESSAGE_LENGTH = 1000
_SAFE_NAME = re.compile(r'[A-Za-z0-9_.]{1,128}')
# Order matters: most specific first (all but ToolError are UserError subclasses).
_CATEGORIES = (
    (AccessError, 'access'),
    (ValidationError, 'validation'),
    (MissingError, 'missing'),
    (ToolError, 'tool'),
    (UserError, 'user'),
)


def _error_result(message):
    return {'content': [{'type': 'text', 'text': message}], 'isError': True}


def _truncate(message):
    if len(message) > MAX_MESSAGE_LENGTH:
        return message[:MAX_MESSAGE_LENGTH] + '…'
    return message


def _log_audit(env, name, arguments, category, started):
    """One line per call: who, what, outcome. Never argument values or results."""
    try:
        model = arguments.get('model') if isinstance(arguments, dict) else None
        ids = arguments.get('ids') if isinstance(arguments, dict) else None
        _audit.info(
            "db=%s uid=%s tool=%s model=%s ids=%s outcome=%s category=%s ms=%d",
            env.cr.dbname, env.uid,
            name if name in TOOLS else '?',
            model if isinstance(model, str) and _SAFE_NAME.fullmatch(model) else '-',
            len(ids) if isinstance(ids, list) else '-',
            'error' if category else 'ok', category or '-',
            (time.monotonic() - started) * 1000,
        )
    except Exception:  # noqa: BLE001 - auditing must never affect the result
        _logger.exception("MCP audit logging failed")


def call_tool(env, name, arguments):
    """Run tool `name` as `env`'s user and return an MCP `tools/call` result.

    The handler runs in a flushed savepoint so that any exception rolls back
    everything the call did, even though the surrounding request still commits.
    """
    started = time.monotonic()
    tool = TOOLS.get(name)
    if tool is None:
        _log_audit(env, name, arguments, 'tool', started)
        raise UnknownTool(name)
    category = None
    try:
        validate_arguments(tool.input_schema, arguments)
        with env.cr.savepoint():
            result = tool.handler(env, arguments)
    except (ToolError, UserError) as exc:
        category = next(label for cls, label in _CATEGORIES if isinstance(exc, cls))
        response = _error_result(_truncate(str(exc)))
    except Exception:  # noqa: BLE001 - anything else must not leak details
        category = 'internal'
        ref = uuid.uuid4().hex[:8]
        _logger.exception("MCP tool %r failed (ref: %s)", name, ref)
        response = _error_result(f"Internal error (ref: {ref})")
    else:
        text = json.dumps(result, ensure_ascii=False, default=json_default)
        response = {
            'content': [{'type': 'text', 'text': text}],
            'structuredContent': json.loads(text),
            'isError': False,
        }
    _log_audit(env, name, arguments, category, started)
    return response


# Importing the tool modules registers their tools.
from . import models, read, write  # noqa: E402,F401
