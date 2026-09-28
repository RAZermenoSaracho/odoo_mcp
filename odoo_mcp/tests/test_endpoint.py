import json

from odoo.addons.odoo_mcp import protocol
from odoo.tests import tagged
from odoo.tools import mute_logger

from .common import LEGACY, MODERN, McpHttpCase, make_tool, modern_request, temporary_tools


@tagged('post_install', '-at_install')
class TestEndpoint(McpHttpCase):

    def setUp(self):
        super().setUp()
        self.user = self.make_user('mcp_user')
        self.key = self.make_key(self.user)

    def assertNoLeak(self, response):
        for needle in ('Traceback', 'File "', 'debug', 'psycopg2'):
            self.assertNotIn(needle, response.text)

    # -- transport ----------------------------------------------------------

    def test_ping_returns_json_without_session_state(self):
        response = self.mcp_call(self.key, 'ping')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.headers['Content-Type'].startswith('application/json'))
        self.assertEqual(response.json()['id'], 1)
        self.assertNotIn('Set-Cookie', response.headers)
        self.assertNotIn('Mcp-Session-Id', response.headers)

    def test_session_id_header_is_ignored(self):
        headers, body = modern_request('ping')
        response = self.mcp_post(body, key=self.key, headers=dict(headers, **{'Mcp-Session-Id': 'abc'}))
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('Mcp-Session-Id', response.headers)

    def test_other_methods_rejected(self):
        for method in ('GET', 'DELETE', 'PUT'):
            response = self.mcp_post(None, key=self.key, method=method, data=b'')
            self.assertEqual(response.status_code, 405, method)
            self.assertNoLeak(response)

    def test_body_errors(self):
        response = self.mcp_post(None, key=self.key, data=b'[{"jsonrpc": "2.0"}]')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['error']['code'], protocol.INVALID_REQUEST)
        response = self.mcp_post(None, key=self.key, data=b'not json')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['error']['code'], protocol.PARSE_ERROR)
        response = self.mcp_post(None, key=self.key, data=b'123')
        self.assertEqual(response.status_code, 400)
        response = self.mcp_post(None, key=self.key, data=b'x' * (2 * 1024 * 1024 + 1))
        self.assertEqual(response.status_code, 413)
        self.assertNoLeak(response)

    def test_wrong_content_type(self):
        response = self.mcp_post(None, key=self.key, data=b'{}', headers={'Content-Type': 'text/plain'})
        self.assertEqual(response.status_code, 415)
        self.assertNoLeak(response)

    def test_notification_is_202_and_empty(self):
        body = {'jsonrpc': '2.0', 'method': 'notifications/initialized'}
        response = self.mcp_post(body, key=self.key, headers={'MCP-Protocol-Version': MODERN})
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.content, b'')

    # -- authentication -----------------------------------------------------

    def test_valid_key_runs_as_owner(self):
        def handler(env, arguments):
            return {'uid': env.uid, 'su': env.su, 'public': env.user._is_public()}

        with temporary_tools(make_tool('whoami', handler)):
            response = self.mcp_call(self.key, 'tools/call', {'name': 'whoami', 'arguments': {}})
        result = response.json()['result']
        self.assertEqual(result['structuredContent'], {'uid': self.user.id, 'su': False, 'public': False})

    def test_two_keys_two_identities(self):
        other = self.make_user('mcp_other')
        other_key = self.make_key(other)
        with temporary_tools(make_tool('whoami', lambda env, a: {'uid': env.uid})):
            params = {'name': 'whoami', 'arguments': {}}
            first = self.mcp_call(self.key, 'tools/call', params).json()['result']['structuredContent']
            second = self.mcp_call(other_key, 'tools/call', params).json()['result']['structuredContent']
        self.assertEqual((first['uid'], second['uid']), (self.user.id, other.id))

    def assertUnauthorized(self, response):
        self.assertEqual(response.status_code, 401)
        self.assertTrue(response.headers['WWW-Authenticate'].lower().startswith('bearer'))
        self.assertNoLeak(response)

    def test_missing_and_invalid_key(self):
        executed = []
        with temporary_tools(make_tool('spy', lambda env, a: executed.append(1) or {})):
            headers, body = modern_request('tools/call', {'name': 'spy', 'arguments': {}})
            self.assertUnauthorized(self.mcp_post(body, headers=headers))
            self.assertUnauthorized(self.mcp_post(body, key='invalid0key0value', headers=headers))
            self.assertUnauthorized(self.mcp_post(body, headers=dict(headers, Authorization='Basic abc')))
        self.assertFalse(executed)

    def test_expired_key(self):
        self.env.cr.execute("UPDATE res_users_apikeys SET expiration_date = now() at time zone 'utc' - interval '1 day'")
        self.assertUnauthorized(self.mcp_call(self.key, 'ping'))

    def test_revoked_key(self):
        self.env.cr.execute("DELETE FROM res_users_apikeys WHERE user_id = %s", [self.user.id])
        self.env.registry.clear_cache()
        self.assertUnauthorized(self.mcp_call(self.key, 'ping'))

    def test_archived_user_key(self):
        self.user.active = False
        self.assertUnauthorized(self.mcp_call(self.key, 'ping'))

    def test_session_cookie_alone_is_not_enough(self):
        self.authenticate('mcp_user', 'mcp_user')
        headers, body = modern_request('ping')
        response = self.url_open(
            '/mcp', data=json.dumps(body).encode(), allow_redirects=False,
            headers=dict(headers, **{'Content-Type': 'application/json'}))
        self.assertUnauthorized(response)

    # -- origin ---------------------------------------------------------------

    def test_origin(self):
        self.assertEqual(self.mcp_call(self.key, 'ping').status_code, 200)
        headers, body = modern_request('ping')
        for origin, status in (('https://evil.example', 403), ('null', 403), (self.base_url(), 200)):
            response = self.mcp_post(body, key=self.key, headers=dict(headers, Origin=origin))
            self.assertEqual(response.status_code, status, origin)
            self.assertNoLeak(response)

    # -- framing ----------------------------------------------------------------

    def test_modern_and_legacy_flows(self):
        response = self.mcp_call(self.key, 'tools/list')
        self.assertEqual(response.status_code, 200)
        result = response.json()['result']
        self.assertEqual(result['resultType'], 'complete')
        self.assertIsInstance(result['tools'], list)
        self.assertEqual((result['ttlMs'], result['cacheScope']), (protocol.CACHE_TTL_MS, 'public'))

        response = self.mcp_call(self.key, 'server/discover')
        self.assertEqual(response.json()['result']['supportedVersions'], [MODERN, LEGACY])

        body = {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {'protocolVersion': LEGACY}}
        response = self.mcp_post(body, key=self.key)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['result']['protocolVersion'], LEGACY)
        self.assertNotIn('Mcp-Session-Id', response.headers)

        response = self.mcp_call(self.key, 'tools/list', legacy=True)
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('resultType', response.json()['result'])

    def test_framing_errors_over_http(self):
        headers, body = modern_request('tools/list')
        response = self.mcp_post(body, key=self.key, headers=dict(headers, **{'Mcp-Method': 'ping'}))
        self.assertEqual((response.status_code, response.json()['error']['code']), (400, protocol.HEADER_MISMATCH))
        response = self.mcp_post(body, key=self.key, headers=dict(headers, **{'MCP-Protocol-Version': '1900-01-01'}))
        self.assertEqual((response.status_code, response.json()['error']['code']), (400, protocol.UNSUPPORTED_VERSION))
        response = self.mcp_call(self.key, 'resources/list')
        self.assertEqual((response.status_code, response.json()['error']['code']), (404, protocol.METHOD_NOT_FOUND))
        response = self.mcp_call(self.key, 'tools/call', {'name': 'does_not_exist'})
        self.assertEqual(response.json()['error']['code'], protocol.INVALID_PARAMS)

    def test_tool_errors_are_results_not_http_errors(self):
        def handler(env, arguments):
            raise RuntimeError('secret /path/x.py')

        with temporary_tools(make_tool('boom', handler)), mute_logger('odoo.addons.odoo_mcp.tools'):
            response = self.mcp_call(self.key, 'tools/call', {'name': 'boom', 'arguments': {}})
        self.assertEqual(response.status_code, 200)
        self.assertRegex(response.json()['result']['content'][0]['text'], r'^Internal error \(ref: [0-9a-f]{8}\)$')
        self.assertNotIn('secret', response.text)
        self.assertNoLeak(response)

    def test_writes_are_attributed_to_the_key_owner(self):
        editor = self.make_user('mcp_editor_http', 'base.group_user,base.group_partner_manager')
        key = self.make_key(editor)
        created = self.mcp_call(key, 'tools/call', {'name': 'create', 'arguments': {
            'model': 'res.partner', 'values': {'name': 'mcp http partner'}}}).json()['result']
        self.assertFalse(created['isError'], created)
        partner_id = created['structuredContent']['id']
        written = self.mcp_call(key, 'tools/call', {'name': 'write', 'arguments': {
            'model': 'res.partner', 'ids': [partner_id], 'values': {'phone': '123'}}}).json()['result']
        self.assertFalse(written['isError'], written)
        self.env.invalidate_all()
        partner = self.env['res.partner'].browse(partner_id)
        self.assertEqual((partner.phone, partner.create_uid, partner.write_uid), ('123', editor, editor))

    @mute_logger('odoo.addons.odoo_mcp.tools', 'odoo.sql_db')
    def test_failed_write_rolls_back_inside_a_real_request(self):
        admin = self.make_user('mcp_http_admin', 'base.group_user,base.group_system')
        key = self.make_key(admin)
        users = self.make_user('mcp_http_u1') | self.make_user('mcp_http_u2')
        result = self.mcp_call(key, 'tools/call', {'name': 'write', 'arguments': {
            'model': 'res.users', 'ids': users.ids, 'values': {'login': 'mcp_http_same'}}}).json()['result']
        self.assertTrue(result['isError'])
        self.env.invalidate_all()
        self.assertEqual(users.mapped('login'), ['mcp_http_u1', 'mcp_http_u2'])
        # the same key keeps working afterwards
        self.assertFalse(self.mcp_call(key, 'tools/call', {'name': 'list_models', 'arguments': {'limit': 1}})
                         .json()['result']['isError'])
