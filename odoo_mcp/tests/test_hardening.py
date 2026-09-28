import re

from odoo.addons.odoo_mcp import protocol, ratelimit, tools
from odoo.addons.odoo_mcp.tools.models import DENIED_MODELS
from odoo.exceptions import AccessError, MissingError, UserError, ValidationError
from odoo.tests import TransactionCase, tagged
from odoo.tools import mute_logger

from .common import McpHttpCase, McpToolCase, make_tool, modern_request, temporary_tools

TOOL_INVENTORY = ['create', 'describe_model', 'list_models', 'read', 'search_count', 'search_read', 'unlink', 'write']
MINIMUM_DENIED = {
    'res.users.apikeys', 'ir.config_parameter', 'ir.rule', 'ir.model.access', 'ir.model', 'ir.model.fields',
    'ir.actions.server', 'ir.cron', 'ir.module.module',
}
MODEL_TOOL_ARGUMENTS = {
    'describe_model': {},
    'search_read': {},
    'search_count': {},
    'read': {'ids': [1]},
    'create': {'values': {'name': 'x'}},
    'write': {'ids': [1], 'values': {'name': 'x'}},
    'unlink': {'ids': [1]},
}


class TestDenyList(McpToolCase):

    def setUp(self):
        super().setUp()
        self.admin = self._user('mcp_admin', 'base.group_user', 'base.group_system')

    def test_minimum_set_is_denied(self):
        self.assertLessEqual(MINIMUM_DENIED, DENIED_MODELS)

    def test_admin_holds_acls_on_denied_models_but_is_refused(self):
        env = self.env(user=self.admin)
        for name in ('res.users.apikeys', 'ir.config_parameter'):
            self.assertTrue(env[name].has_access('read'), name)

    def test_every_tool_every_denied_model(self):
        for name in sorted(DENIED_MODELS):
            for tool, extra in MODEL_TOOL_ARGUMENTS.items():
                message = self.error(self.admin, tool, dict({'model': name}, **extra))
                self.assertEqual(message, f"Unknown model '{name}'", (tool, name))

    def test_denied_models_are_not_listed(self):
        names = set()
        offset = 0
        while True:
            page = self.ok(self.admin, 'list_models', {'limit': 200, 'offset': offset})
            names.update(m['model'] for m in page['models'])
            offset += 200
            if offset >= page['total']:
                break
        self.assertIn('res.partner', names)
        self.assertFalse(names & DENIED_MODELS)
        self.assertFalse(
            {m['model'] for m in self.ok(self.admin, 'list_models', {'query': 'ir.', 'limit': 200})['models']}
            & DENIED_MODELS)

    def test_denied_indistinguishable_from_nonexistent(self):
        denied = self.error(self.admin, 'search_read', {'model': 'ir.cron'})
        missing = self.error(self.admin, 'search_read', {'model': 'ir.no_such'})
        self.assertEqual(denied.replace('ir.cron', 'X'), missing.replace('ir.no_such', 'X'))

    def test_writes_are_refused_and_change_nothing(self):
        before = self.env['ir.cron'].search_count([])
        self.error(self.admin, 'create', {'model': 'ir.cron', 'values': {'name': 'x'}})
        self.error(self.admin, 'write', {'model': 'ir.actions.server', 'ids': [1], 'values': {'name': 'x'}})
        self.assertEqual(self.env['ir.cron'].search_count([]), before)

    def test_deny_list_is_not_argument_controllable(self):
        for name in ('allow_denied', 'context', 'sudo'):
            self.assertIn(f"'{name}'", self.error(self.admin, 'search_read', {'model': 'ir.cron', name: True}))


class TestRelationsIntoDeniedModels(McpToolCase):
    """A denied model must not be reachable through a relation of an allowed one."""

    def setUp(self):
        super().setUp()
        self.admin = self._user('mcp_admin_rel', 'base.group_user', 'base.group_system')
        self.assertEqual(self.env['res.users']._fields['api_key_ids'].comodel_name, 'res.users.apikeys')

    def test_field_is_hidden_from_discovery_and_reads(self):
        described = self.ok(self.admin, 'describe_model', {'model': 'res.users'})['fields']
        self.assertNotIn('api_key_ids', described)
        self.assertIn('login', described)
        self.assertIn("'api_key_ids'", self.error(
            self.admin, 'search_read', {'model': 'res.users', 'fields': ['api_key_ids']}))
        default = self.ok(self.admin, 'search_read', {'model': 'res.users', 'limit': 1})['records'][0]
        self.assertNotIn('api_key_ids', default)

    def test_domains_cannot_traverse_into_denied_models(self):
        for path in ('api_key_ids', 'api_key_ids.name'):
            self.assertIn(f"'{path}'", self.error(
                self.admin, 'search_read', {'model': 'res.users', 'domain': [[path, '!=', False]]}))
            self.assertIn(f"'{path}'", self.error(
                self.admin, 'search_count', {'model': 'res.users', 'domain': [[path, '!=', False]]}))

    def test_writes_cannot_target_relations_into_denied_models(self):
        self.assertIn("'api_key_ids'", self.error(self.admin, 'write', {
            'model': 'res.users', 'ids': [self.admin.id], 'values': {'api_key_ids': [[0, 0, {'name': 'x'}]]}}))
        self.assertIn("'api_key_ids'", self.error(self.admin, 'create', {
            'model': 'res.users', 'values': {'name': 'x', 'login': 'mcp_rel_x', 'api_key_ids': [[5, 0, 0]]}}))


class TestToolInventory(TransactionCase):

    def test_exact_tool_set(self):
        self.assertEqual([tool['name'] for tool in tools.list_tools()], TOOL_INVENTORY)


class TestErrorSanitization(McpToolCase):

    def run_tool(self, handler):
        with temporary_tools(make_tool('t_err', handler)):
            return self.call(self.plain, 't_err')['content'][0]['text']

    def test_long_messages_are_truncated(self):
        def handler(env, arguments):
            raise ValidationError('x' * 5000)

        text = self.run_tool(handler)
        self.assertEqual(len(text), tools.MAX_MESSAGE_LENGTH + 1)
        self.assertTrue(text.endswith('…'))

    def test_short_messages_pass_through(self):
        def handler(env, arguments):
            raise AccessError('denied')

        self.assertEqual(self.run_tool(handler), 'denied')

    def test_internal_errors_carry_a_reference_that_is_logged(self):
        def handler(env, arguments):
            raise RuntimeError('SELECT secret FROM /path/x.py')

        refs = []
        for _ in range(2):
            with self.assertLogs('odoo.addons.odoo_mcp.tools', 'ERROR') as logs:
                text = self.run_tool(handler)
            match = re.fullmatch(r'Internal error \(ref: ([0-9a-f]{8})\)', text)
            self.assertTrue(match, text)
            self.assertNotIn('SELECT', text)
            self.assertIn(match.group(1), '\n'.join(logs.output))
            self.assertIn('Traceback', '\n'.join(logs.output))
            refs.append(match.group(1))
        self.assertNotEqual(*refs)


class TestAudit(McpToolCase):

    def lines(self, user, name, arguments):
        with self.assertLogs('odoo.addons.odoo_mcp.audit', 'INFO') as logs:
            self.call(user, name, arguments)
        self.assertEqual(len(logs.records), 1)
        return logs.records[0].getMessage()

    def test_success_line(self):
        line = self.lines(self.plain, 'search_read', {'model': 'res.partner', 'domain': [['name', '=', 'SECRET']]})
        self.assertRegex(line, rf'db={self.env.cr.dbname} uid={self.plain.id} tool=search_read model=res.partner '
                               r'ids=- outcome=ok category=- ms=\d+')
        self.assertNotIn('SECRET', line)

    def test_failure_categories(self):
        self.assertIn('outcome=error category=access', self.lines(
            self.reader, 'create', {'model': 'ir.mail_server', 'values': {'name': 'x'}}))
        self.assertIn('category=tool', self.lines(self.plain, 'read', {'model': 'ir.cron', 'ids': [1]}))
        self.assertIn('category=tool', self.lines(self.plain, 'search_read', {'model': 'res.partner', 'bogus': 1}))
        raising = {
            'validation': ValidationError('v'),
            'missing': MissingError('m'),
            'user': UserError('u'),
        }
        for category, exc in raising.items():
            def handler(env, arguments, exc=exc):
                raise exc
            with temporary_tools(make_tool('t_cat', handler)):
                self.assertIn(f'outcome=error category={category}', self.lines(self.plain, 't_cat', {}))
        with mute_logger('odoo.addons.odoo_mcp.tools'), temporary_tools(make_tool('t_boom', lambda env, a: 1 / 0)):
            self.assertIn('category=internal', self.lines(self.plain, 't_boom', {}))

    def test_values_and_hostile_names_never_logged(self):
        editor = self._user('mcp_editor_b', 'base.group_user', 'base.group_partner_manager')
        partner = self.env['res.partner'].create({'name': 'mcpa'})
        line = self.lines(editor, 'write', {
            'model': 'res.partner', 'ids': [partner.id], 'values': {'phone': '+1-555-0100'}})
        self.assertNotIn('+1-555-0100', line)
        self.assertIn('ids=1', line)
        hostile = self.lines(self.plain, 'search_read', {'model': 'res.partner\nFAKE line', 'limit': 1})
        self.assertNotIn('\n', hostile)
        self.assertIn('model=-', hostile)

    def test_unknown_tool_is_logged(self):
        with self.assertLogs('odoo.addons.odoo_mcp.audit', 'INFO') as logs:
            with self.assertRaises(tools.UnknownTool):
                tools.call_tool(self.env, 'evil\nname', {})
        self.assertNotIn('evil', logs.records[0].getMessage())
        self.assertIn('outcome=error category=tool', logs.records[0].getMessage())

    def test_logging_failure_does_not_break_the_call(self):
        self.patch(tools._audit, 'info', lambda *a, **k: 1 / 0)
        with mute_logger('odoo.addons.odoo_mcp.tools'):
            self.assertFalse(self.call(self.plain, 'list_models', {'limit': 1})['isError'])


class TestSlidingWindow(TransactionCase):

    def make(self, limit=3, window=60.0):
        self.now = 1000.0
        return ratelimit.SlidingWindow(limit=limit, window=window, clock=lambda: self.now)

    def test_under_and_over_the_limit(self):
        limiter = self.make()
        self.assertEqual([limiter.check('a')[0] for _ in range(3)], [True] * 3)
        allowed, retry_after = limiter.check('a')
        self.assertFalse(allowed)
        self.assertEqual(retry_after, 60)

    def test_rejected_requests_do_not_extend_the_block(self):
        limiter = self.make()
        for _ in range(3):
            limiter.check('a')
        self.now += 30
        self.assertEqual(limiter.check('a'), (False, 30))
        self.now += 30.5
        self.assertTrue(limiter.check('a')[0])

    def test_window_slides(self):
        limiter = self.make()
        limiter.check('a')
        self.now += 20
        limiter.check('a')
        limiter.check('a')
        self.assertFalse(limiter.check('a')[0])
        self.now += 41   # the first request is now outside the window
        self.assertTrue(limiter.check('a')[0])
        self.assertFalse(limiter.check('a')[0])

    def test_keys_are_independent(self):
        limiter = self.make(limit=1)
        self.assertTrue(limiter.check(('db1', 1))[0])
        self.assertFalse(limiter.check(('db1', 1))[0])
        self.assertTrue(limiter.check(('db1', 2))[0])
        self.assertTrue(limiter.check(('db2', 1))[0])

    def test_idle_buckets_are_discarded(self):
        limiter = self.make(limit=1)
        for user in range(ratelimit.PRUNE_ABOVE + 5):
            limiter.check(user)
        self.assertGreater(len(limiter._buckets), ratelimit.PRUNE_ABOVE)
        self.now += 61
        limiter.check('fresh')
        self.assertEqual(list(limiter._buckets), ['fresh'])


@tagged('post_install', '-at_install')
class TestEndpointHardening(McpHttpCase):

    def setUp(self):
        super().setUp()
        ratelimit.LIMITER.clear()
        self.addCleanup(ratelimit.LIMITER.clear)
        self.user = self.make_user('mcp_hard_user')
        self.key = self.make_key(self.user)

    def test_rate_limit_over_http(self):
        self.patch(ratelimit.LIMITER, 'limit', 3)
        other_key = self.make_key(self.make_user('mcp_hard_other'))
        executed = []
        with temporary_tools(make_tool('spy', lambda env, a: executed.append(1) or {})):
            params = {'name': 'spy', 'arguments': {}}
            for _ in range(3):
                self.assertEqual(self.mcp_call(self.key, 'tools/call', params).status_code, 200)
            response = self.mcp_call(self.key, 'tools/call', params)
            self.assertEqual(response.status_code, 429)
            self.assertGreaterEqual(int(response.headers['Retry-After']), 1)
            self.assertEqual(response.json()['error']['code'], protocol.RATE_LIMITED)
            self.assertEqual(len(executed), 3)
            self.assertEqual(self.mcp_call(other_key, 'tools/call', params).status_code, 200)
        # unauthenticated floods neither succeed nor consume the budget
        self.patch(ratelimit.LIMITER, 'limit', 4)
        for _ in range(5):
            self.assertEqual(self.mcp_call('invalid0key0value', 'ping').status_code, 401)
        self.assertEqual(self.mcp_call(other_key, 'ping').status_code, 200)

    def test_notifications_count(self):
        self.patch(ratelimit.LIMITER, 'limit', 1)
        body = {'jsonrpc': '2.0', 'method': 'notifications/initialized'}
        self.assertEqual(self.mcp_post(body, key=self.key).status_code, 202)
        self.assertEqual(self.mcp_post(body, key=self.key).status_code, 429)

    def test_no_implementation_details_in_any_error(self):
        self.patch(ratelimit.LIMITER, 'limit', 1000)
        headers, body = modern_request('tools/list')
        responses = [
            self.mcp_post(body, headers=headers),                                        # 401
            self.mcp_post(None, key=self.key, data=b'not json'),                         # 400 parse
            self.mcp_post(None, key=self.key, data=b'[]'),                               # 400 invalid
            self.mcp_post(body, key=self.key, headers=dict(headers, **{'Mcp-Method': 'x'})),   # header mismatch
            self.mcp_call(self.key, 'tools/call', {'name': 'nope'}),                     # unknown tool
            self.mcp_call(self.key, 'resources/list'),                                   # 404
            self.mcp_call(self.key, 'tools/call', {'name': 'search_read', 'arguments': {'model': 'ir.cron'}}),
            self.mcp_post(None, key=self.key, data=b'x' * (2 * 1024 * 1024 + 1)),        # 413
            self.mcp_post(None, key=self.key, method='GET', data=b''),                   # 405
            self.mcp_post(body, key=self.key, headers={'Content-Type': 'text/plain'}),   # 415
        ]
        with temporary_tools(make_tool('boom', lambda env, a: 1 / 0)), mute_logger('odoo.addons.odoo_mcp.tools'):
            responses.append(self.mcp_call(self.key, 'tools/call', {'name': 'boom', 'arguments': {}}))
        self.patch(ratelimit.LIMITER, 'limit', 1)
        ratelimit.LIMITER.clear()
        self.mcp_call(self.key, 'ping')
        responses.append(self.mcp_call(self.key, 'ping'))                                # 429
        self.assertEqual(
            [r.status_code for r in responses], [401, 400, 400, 400, 200, 404, 200, 413, 405, 415, 200, 429])
        for response in responses:
            for needle in ('Traceback', '.py', 'psycopg2', 'File "', 'debug'):
                self.assertNotIn(needle, response.text, (response.status_code, needle))

    def test_key_and_values_never_appear_in_audit_log(self):
        editor = self.make_user('mcp_hard_editor', 'base.group_user,base.group_partner_manager')
        key = self.make_key(editor)
        with self.assertLogs('odoo.addons.odoo_mcp.audit', 'INFO') as logs:
            self.mcp_call(key, 'tools/call', {'name': 'create', 'arguments': {
                'model': 'res.partner', 'values': {'name': 'mcp audit', 'phone': '+1-555-0199'}}})
        text = '\n'.join(logs.output)
        self.assertIn('tool=create model=res.partner', text)
        self.assertNotIn(key, text)
        self.assertNotIn('+1-555-0199', text)
