import contextlib
import datetime
import json

from odoo.addons.odoo_mcp import tools
from odoo.tests import HttpCase, TransactionCase

MODERN = '2026-07-28'
LEGACY = '2025-11-25'
META = {
    'io.modelcontextprotocol/protocolVersion': MODERN,
    'io.modelcontextprotocol/clientInfo': {'name': 'test', 'version': '1'},
    'io.modelcontextprotocol/clientCapabilities': {},
}


def modern_request(method, params=None, request_id=1):
    """Return ``(headers, body)`` of a valid modern-revision request."""
    params = dict(params or {}, _meta=META)
    headers = {'MCP-Protocol-Version': MODERN, 'Mcp-Method': method}
    if method == 'tools/call':
        headers['Mcp-Name'] = params['name']
    return headers, {'jsonrpc': '2.0', 'id': request_id, 'method': method, 'params': params}


def legacy_request(method, params=None, request_id=1):
    headers = {'MCP-Protocol-Version': LEGACY}
    return headers, {'jsonrpc': '2.0', 'id': request_id, 'method': method, 'params': params or {}}


@contextlib.contextmanager
def temporary_tools(*tool_list):
    """Register test-only tools for the duration of a test."""
    for tool in tool_list:
        tools.register(tool)
    try:
        yield
    finally:
        for tool in tool_list:
            tools.TOOLS.pop(tool.name, None)


def make_tool(name, handler, schema=None, annotations=None):
    return tools.Tool(
        name=name, title=name, description=name,
        input_schema=schema or {'type': 'object', 'properties': {}, 'additionalProperties': False},
        annotations=annotations or {'readOnlyHint': True},
        handler=handler,
    )


class McpHttpCase(HttpCase):
    """HttpCase with helpers to call `/mcp` with real API keys."""

    def make_user(self, login, groups='base.group_user', password=None):
        user = self.env['res.users'].create({
            'name': login,
            'login': login,
            'password': password or login,
            'group_ids': [(6, 0, [self.env.ref(g).id for g in groups.split(',')])],
        })
        return user

    def make_key(self, user, days=1):
        expiration = datetime.datetime.now() + datetime.timedelta(days=days)
        return self.env['res.users.apikeys'].with_user(user)._generate(None, 'mcp test', expiration)

    def mcp_post(self, body, key=None, headers=None, data=None, method=None):
        all_headers = {'Content-Type': 'application/json', 'X-Odoo-Database': self.env.cr.dbname}
        if key:
            all_headers['Authorization'] = f'Bearer {key}'
        all_headers.update(headers or {})
        if data is None:
            data = json.dumps(body).encode()
        return self.url_open('/mcp', data=data, headers=all_headers, allow_redirects=False, method=method)

    def mcp_call(self, key, method, params=None, legacy=False):
        headers, body = (legacy_request if legacy else modern_request)(method, params)
        return self.mcp_post(body, key=key, headers=headers)


class McpToolCase(TransactionCase):
    """Shared users and helpers to call tools as a given user.

    A plain internal user and users holding extra ACLs.

    `ir.mail_server` is used as "a model plain internal users cannot read".
    """

    def setUp(self):
        super().setUp()
        self.plain = self._user('mcp_plain', 'base.group_user')
        model = self.env['ir.model']._get('ir.mail_server')
        self.reader_group = self._group('mcp_readers', model, read=True)
        self.writer_group = self._group('mcp_writers', model, read=True, write=True, create=True, unlink=True)
        self.reader = self._user('mcp_reader', 'base.group_user', self.reader_group)
        self.assertFalse(self.env(user=self.plain)['ir.mail_server'].has_access('read'))

    def _user(self, login, *groups):
        xmlids = [g for g in groups if isinstance(g, str)]
        records = [g for g in groups if not isinstance(g, str)]
        ids = [self.env.ref(x).id for x in xmlids] + [g.id for g in records]
        return self.env['res.users'].create({'name': login, 'login': login, 'group_ids': [(6, 0, ids)]})

    def _group(self, name, model, read=False, write=False, create=False, unlink=False):
        group = self.env['res.groups'].create({'name': name})
        self.env['ir.model.access'].create({
            'name': name, 'model_id': model.id, 'group_id': group.id,
            'perm_read': read, 'perm_write': write, 'perm_create': create, 'perm_unlink': unlink,
        })
        return group

    def call(self, user, name, arguments=None):
        return tools.call_tool(self.env(user=user), name, arguments or {})

    def ok(self, user, name, arguments=None):
        result = self.call(user, name, arguments)
        self.assertFalse(result['isError'], result['content'][0]['text'])
        return result['structuredContent']

    def error(self, user, name, arguments=None):
        result = self.call(user, name, arguments)
        self.assertTrue(result['isError'], result)
        return result['content'][0]['text']
