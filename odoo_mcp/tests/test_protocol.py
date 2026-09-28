import base64

from odoo.addons.odoo_mcp import protocol
from odoo.tests import TransactionCase

from .common import LEGACY, MODERN, legacy_request, modern_request


class TestProtocol(TransactionCase):

    def handle(self, headers, body):
        return protocol.handle_message(body, headers, self.env)

    def test_invalid_requests(self):
        for body in ([], "x", 1, None, {}, {'jsonrpc': '1.0', 'id': 1, 'method': 'ping'},
                     {'jsonrpc': '2.0', 'id': 1}, {'jsonrpc': '2.0', 'id': True, 'method': 'ping'},
                     {'jsonrpc': '2.0', 'id': 1, 'method': 'ping', 'params': []}):
            status, response = self.handle({}, body)
            self.assertEqual(status, 400, body)
            self.assertEqual(response['error']['code'], protocol.INVALID_REQUEST)

    def test_notification(self):
        status, body = self.handle({}, {'jsonrpc': '2.0', 'method': 'notifications/initialized'})
        self.assertEqual((status, body), (202, None))

    def test_ping_modern_has_result_type(self):
        status, body = self.handle(*modern_request('ping'))
        self.assertEqual(status, 200)
        self.assertEqual(body, {'jsonrpc': '2.0', 'id': 1, 'result': {'resultType': 'complete'}})

    def test_ping_legacy_has_no_result_type(self):
        status, body = self.handle(*legacy_request('ping'))
        self.assertEqual((status, body['result']), (200, {}))

    def test_header_mismatches(self):
        headers, body = modern_request('tools/list')
        for change in ({'MCP-Protocol-Version': None}, {'Mcp-Method': 'ping'}, {'Mcp-Method': None}):
            bad = {k: v for k, v in dict(headers, **change).items() if v is not None}
            status, response = self.handle(bad, body)
            self.assertEqual(status, 400, change)
            self.assertEqual(response['error']['code'], protocol.HEADER_MISMATCH, change)

    def test_meta_version_mismatch(self):
        headers, body = modern_request('tools/list')
        body['params']['_meta'] = dict(body['params']['_meta'], **{protocol.META_VERSION: LEGACY})
        status, response = self.handle(headers, body)
        self.assertEqual((status, response['error']['code']), (400, protocol.HEADER_MISMATCH))

    def test_missing_meta(self):
        headers, body = modern_request('tools/list')
        del body['params']['_meta']
        status, response = self.handle(headers, body)
        self.assertEqual((status, response['error']['code']), (400, protocol.HEADER_MISMATCH))

    def test_mcp_name_mismatch_and_base64(self):
        headers, body = modern_request('tools/call', {'name': 'a'})
        status, response = self.handle(dict(headers, **{'Mcp-Name': 'b'}), body)
        self.assertEqual((status, response['error']['code']), (400, protocol.HEADER_MISMATCH))
        encoded = '=?base64?' + base64.b64encode(b'a').decode() + '?='
        status, response = self.handle(dict(headers, **{'Mcp-Name': encoded}), body)
        self.assertEqual(status, 200)  # header matches; the tool is simply unknown
        self.assertEqual(response['error']['code'], protocol.INVALID_PARAMS)

    def test_unsupported_version(self):
        status, response = self.handle({'MCP-Protocol-Version': '1900-01-01'},
                                       {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list'})
        self.assertEqual((status, response['error']['code']), (400, protocol.UNSUPPORTED_VERSION))
        self.assertEqual(response['error']['data']['supported'], [MODERN, LEGACY])
        self.assertEqual(response['error']['data']['requested'], '1900-01-01')

    def test_unknown_method(self):
        status, response = self.handle(*modern_request('resources/list'))
        self.assertEqual((status, response['error']['code']), (404, protocol.METHOD_NOT_FOUND))
        status, response = self.handle(*legacy_request('resources/list'))
        self.assertEqual((status, response['error']['code']), (200, protocol.METHOD_NOT_FOUND))

    def test_discover(self):
        status, body = self.handle(*modern_request('server/discover'))
        result = body['result']
        self.assertEqual(result['supportedVersions'], [MODERN, LEGACY])
        self.assertEqual(result['capabilities'], {'tools': {'listChanged': False}})
        self.assertEqual(result['_meta'][protocol.META_SERVER_INFO]['name'], 'odoo_mcp')
        self.assertRegex(result['_meta'][protocol.META_SERVER_INFO]['version'], r'^19\.0\.')
        self.assertIn('permissions', result['instructions'])

    def test_legacy_initialize(self):
        body = {'jsonrpc': '2.0', 'id': 7, 'method': 'initialize', 'params': {'protocolVersion': LEGACY}}
        status, response = self.handle({}, body)
        self.assertEqual(status, 200)
        self.assertEqual(response['result']['protocolVersion'], LEGACY)
        self.assertEqual(list(response['result']['capabilities']), ['tools'])
        self.assertNotIn('resultType', response['result'])
        body['params']['protocolVersion'] = '1999-01-01'
        self.assertEqual(self.handle({}, body)[1]['result']['protocolVersion'], LEGACY)

    def test_tools_call_params_validation(self):
        headers, body = legacy_request('tools/call', {'name': 5})
        status, response = self.handle(headers, body)
        self.assertEqual(response['error']['code'], protocol.INVALID_PARAMS)

    def test_unknown_tool(self):
        status, response = self.handle(*modern_request('tools/call', {'name': 'does_not_exist'}))
        self.assertEqual(response['error']['code'], protocol.INVALID_PARAMS)


class TestModernResultContract(TransactionCase):
    """Result shapes required by the 2026-07-28 spec (clients validate them strictly)."""

    def result(self, method, params=None):
        status, body = protocol.handle_message(*reversed(modern_request(method, params)), self.env)
        self.assertEqual(status, 200)
        return body['result']

    def assertCacheHints(self, result):
        self.assertIs(type(result['ttlMs']), int)
        self.assertGreaterEqual(result['ttlMs'], 0)
        self.assertIn(result['cacheScope'], ('public', 'private'))

    def test_tools_list_result(self):
        result = self.result('tools/list')
        self.assertEqual(result['resultType'], 'complete')
        self.assertCacheHints(result)
        self.assertLessEqual(set(result), {'resultType', 'tools', 'ttlMs', 'cacheScope', 'nextCursor', '_meta'})
        self.assertTrue(result['tools'])
        for tool in result['tools']:
            self.assertIsInstance(tool['name'], str)
            self.assertIsInstance(tool['description'], str)
            self.assertEqual(tool['inputSchema']['type'], 'object')
            self.assertIsInstance(tool['inputSchema']['properties'], dict)
            self.assertLessEqual(set(tool['annotations']), {'readOnlyHint', 'destructiveHint', 'idempotentHint', 'openWorldHint'})
            self.assertTrue(all(isinstance(v, bool) for v in tool['annotations'].values()))

    def test_discover_result(self):
        result = self.result('server/discover')
        self.assertEqual(result['resultType'], 'complete')
        self.assertCacheHints(result)

    def test_non_cacheable_results_carry_no_hints(self):
        for method, params in (('ping', {}), ('tools/call', {'name': 'list_models', 'arguments': {}})):
            result = self.result(method, params)
            self.assertNotIn('ttlMs', result, method)
            self.assertNotIn('cacheScope', result, method)

    def test_legacy_results_carry_no_hints(self):
        status, body = protocol.handle_message(*reversed(legacy_request('tools/list')), self.env)
        self.assertNotIn('ttlMs', body['result'])
        self.assertNotIn('cacheScope', body['result'])
