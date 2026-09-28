"""MCP JSON-RPC framing for the single stateless `/mcp` endpoint.

Serves the modern (2026-07-28, per-request `_meta`) and legacy (2025-11-25,
`initialize`) protocol revisions without any session state.
"""
import base64
import re

from odoo.modules.module import Manifest

from . import tools

MODERN_VERSION = '2026-07-28'
LEGACY_VERSION = '2025-11-25'
SUPPORTED_VERSIONS = [MODERN_VERSION, LEGACY_VERSION]

META_VERSION = 'io.modelcontextprotocol/protocolVersion'
META_SERVER_INFO = 'io.modelcontextprotocol/serverInfo'

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
HEADER_MISMATCH = -32020
UNSUPPORTED_VERSION = -32022
RATE_LIMITED = -32029

# The 2026-07-28 revision requires caching hints on these results. The tool
# list only changes when the addon is upgraded and is identical for every
# user, so it is safe to cache publicly for a few minutes.
CACHEABLE_METHODS = ('server/discover', 'tools/list')
CACHE_TTL_MS = 300_000
CACHE_SCOPE = 'public'

INSTRUCTIONS = (
    "Access to an Odoo database. Every operation runs with the permissions of "
    "the Odoo user who owns the API key; Odoo access rights and record rules "
    "apply, so an operation may be refused or return fewer records than expected."
)


def error_body(request_id, code, message, data=None):
    error = {'code': code, 'message': message}
    if data is not None:
        error['data'] = data
    return {'jsonrpc': '2.0', 'id': request_id, 'error': error}


def _server_version():
    manifest = Manifest.for_addon('odoo_mcp', display_warning=False)
    return manifest['version'] if manifest else 'unknown'


def _capabilities():
    return {'tools': {'listChanged': False}}


def _decode_header_value(value):
    """Decode the `=?base64?...?=` sentinel form used for Mcp-Name."""
    match = re.fullmatch(r'=\?base64\?(.*)\?=', value or '')
    if not match:
        return value
    try:
        return base64.b64decode(match.group(1), validate=True).decode()
    except ValueError:
        return None


def _rejected(status, request_id, code, message, data=None):
    return status, error_body(request_id, code, message, data)


def _validate_modern(headers, message, params):
    """Return an error `(status, body)` if the modern headers/_meta are wrong."""
    request_id = message['id']
    meta = params.get('_meta')
    if not isinstance(meta, dict) or meta.get(META_VERSION) != headers.get('mcp-protocol-version'):
        return _rejected(400, request_id, HEADER_MISMATCH,
                         f"Header mismatch: _meta['{META_VERSION}'] must equal MCP-Protocol-Version")
    if headers.get('mcp-method') != message['method']:
        return _rejected(400, request_id, HEADER_MISMATCH,
                         "Header mismatch: Mcp-Method must equal the request method")
    if message['method'] == 'tools/call':
        name = params.get('name')
        if _decode_header_value(headers.get('mcp-name')) != name:
            return _rejected(400, request_id, HEADER_MISMATCH,
                             "Header mismatch: Mcp-Name must equal params.name")
    return None


def _initialize(params):
    requested = params.get('protocolVersion')
    return {
        'protocolVersion': requested if requested in SUPPORTED_VERSIONS else LEGACY_VERSION,
        'capabilities': _capabilities(),
        'serverInfo': {'name': 'odoo_mcp', 'version': _server_version()},
        'instructions': INSTRUCTIONS,
    }


def _discover(params):
    return {
        'supportedVersions': SUPPORTED_VERSIONS,
        'capabilities': _capabilities(),
        '_meta': {META_SERVER_INFO: {'name': 'odoo_mcp', 'version': _server_version()}},
        'instructions': INSTRUCTIONS,
    }


def _tools_list(params):
    return {'tools': tools.list_tools()}


def handle_message(message, headers, env):
    """Handle one parsed JSON-RPC message.

    :param message: the decoded JSON body
    :param headers: HTTP request headers (any mapping, names case-insensitive)
    :param env: the authenticated user's environment
    :returns: ``(http_status, body)``; ``body`` is None for an empty response
    """
    if (
        not isinstance(message, dict)
        or message.get('jsonrpc') != '2.0'
        or not isinstance(message.get('method'), str)
        or ('id' in message and (isinstance(message['id'], bool) or not isinstance(message['id'], (int, str))))
        or ('params' in message and not isinstance(message['params'], dict))
    ):
        return _rejected(400, None, INVALID_REQUEST, "Invalid JSON-RPC request")

    if 'id' not in message:  # notification
        return 202, None

    headers = {name.lower(): value for name, value in headers.items()}
    method = message['method']
    params = message.get('params', {})
    request_id = message['id']

    if method == 'initialize':
        modern = False
    else:
        version = headers.get('mcp-protocol-version')
        if version is None:
            return _rejected(400, request_id, HEADER_MISMATCH, "Missing MCP-Protocol-Version header")
        if version not in SUPPORTED_VERSIONS:
            return _rejected(400, request_id, UNSUPPORTED_VERSION, "Unsupported protocol version",
                             {'supported': SUPPORTED_VERSIONS, 'requested': version})
        modern = version == MODERN_VERSION
        if modern and (rejection := _validate_modern(headers, message, params)):
            return rejection

    if method == 'tools/call':
        name, arguments = params.get('name'), params.get('arguments', {})
        if not isinstance(name, str):
            return _rejected(200, request_id, INVALID_PARAMS, "params.name must be a string")
        try:
            result = tools.call_tool(env, name, arguments)
        except tools.UnknownTool:
            return _rejected(200, request_id, INVALID_PARAMS, f"Unknown tool: {name}")
    elif method in _SIMPLE_METHODS:
        result = _SIMPLE_METHODS[method](params)
    else:
        return _rejected(404 if modern else 200, request_id, METHOD_NOT_FOUND, f"Method not found: {method}")

    if modern:
        result = dict(result, resultType='complete')
        if method in CACHEABLE_METHODS:
            result.update(ttlMs=CACHE_TTL_MS, cacheScope=CACHE_SCOPE)
    return 200, {'jsonrpc': '2.0', 'id': request_id, 'result': result}


_SIMPLE_METHODS = {
    'initialize': _initialize,
    'ping': lambda params: {},
    'server/discover': _discover,
    'tools/list': _tools_list,
}
