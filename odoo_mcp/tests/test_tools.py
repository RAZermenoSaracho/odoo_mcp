from odoo.addons.odoo_mcp import protocol, tools
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import TransactionCase

from .common import make_tool, modern_request, temporary_tools


class TestValidator(TransactionCase):

    schema = {
        'type': 'object',
        'properties': {
            'name': {'type': 'string', 'minLength': 2, 'maxLength': 4},
            'n': {'type': 'integer', 'minimum': 1, 'maximum': 3},
            'flag': {'type': 'boolean'},
            'ids': {'type': 'array', 'maxItems': 2, 'minItems': 1, 'items': {'type': 'integer'}},
            'kind': {'type': 'string', 'enum': ['a', 'b']},
            'obj': {'type': 'object'},
        },
        'required': ['name'],
        'additionalProperties': False,
    }

    def bad(self, arguments, fragment):
        with self.assertRaisesRegex(tools.ToolError, fragment):
            tools.validate_arguments(self.schema, arguments)

    def test_valid(self):
        tools.validate_arguments(self.schema, {'name': 'ab', 'n': 3, 'flag': True, 'ids': [1, 2], 'kind': 'a', 'obj': {}})

    def test_invalid(self):
        self.bad({}, "Missing required argument 'name'")
        self.bad({'name': 'ab', 'x': 1}, "Unknown argument 'x'")
        self.bad({'name': 5}, "'name' must be of type string")
        self.bad({'name': 'a'}, "at least 2")
        self.bad({'name': 'abcde'}, "at most 4")
        self.bad({'name': 'ab', 'n': 0}, ">= 1")
        self.bad({'name': 'ab', 'n': 4}, "<= 3")
        self.bad({'name': 'ab', 'n': True}, "'n' must be of type integer")
        self.bad({'name': 'ab', 'n': 1.5}, "'n' must be of type integer")
        self.bad({'name': 'ab', 'flag': 1}, "'flag' must be of type boolean")
        self.bad({'name': 'ab', 'ids': []}, "at least 1")
        self.bad({'name': 'ab', 'ids': [1, 2, 3]}, "at most 2")
        self.bad({'name': 'ab', 'ids': ['x']}, r"ids\[0\]")
        self.bad({'name': 'ab', 'kind': 'c'}, "one of")
        self.bad({'name': 'ab', 'obj': []}, "'obj' must be of type object")

    def test_arguments_must_be_object(self):
        with self.assertRaises(tools.ToolError):
            tools.validate_arguments(self.schema, [])


class TestCallTool(TransactionCase):

    def test_empty_table_and_ordering(self):
        with temporary_tools(make_tool('zz_b', lambda env, a: {}), make_tool('zz_a', lambda env, a: {})):
            names = [tool['name'] for tool in tools.list_tools()]
            self.assertEqual(names, sorted(names))
            self.assertLess(names.index('zz_a'), names.index('zz_b'))
            self.assertEqual(names, [t['name'] for t in tools.list_tools()])

    def test_unknown_tool(self):
        with self.assertRaises(tools.UnknownTool):
            tools.call_tool(self.env, 'does_not_exist', {})

    def test_success_shape(self):
        user = self.env['res.users'].create({'name': 'u', 'login': 'mcp_tools_u'})
        with temporary_tools(make_tool('t_ok', lambda env, a: {'uid': env.uid, 'su': env.su})):
            result = tools.call_tool(self.env(user=user), 't_ok', {})
        self.assertFalse(result['isError'])
        self.assertEqual(result['structuredContent'], {'uid': user.id, 'su': False})
        self.assertEqual(result['content'][0]['type'], 'text')
        self.assertEqual(result['content'][0]['text'], '{"uid": %d, "su": false}' % user.id)

    def test_invalid_arguments_do_not_run_handler(self):
        calls = []
        with temporary_tools(make_tool('t_args', lambda env, a: calls.append(a) or {})):
            result = tools.call_tool(self.env, 't_args', {'bogus': 1})
        self.assertTrue(result['isError'])
        self.assertIn("'bogus'", result['content'][0]['text'])
        self.assertFalse(calls)

    def test_failure_rolls_back(self):
        def handler(env, arguments):
            env['res.partner'].create({'name': 'mcp-rollback-partner'})
            raise ValidationError("nope")

        with temporary_tools(make_tool('t_fail', handler)):
            result = tools.call_tool(self.env, 't_fail', {})
        self.assertTrue(result['isError'])
        self.assertEqual(result['content'][0]['text'], 'nope')
        self.assertFalse(self.env['res.partner'].search([('name', '=', 'mcp-rollback-partner')]))

    def test_success_keeps_changes(self):
        def handler(env, arguments):
            return {'id': env['res.partner'].create({'name': 'mcp-kept-partner'}).id}

        with temporary_tools(make_tool('t_write', handler)):
            result = tools.call_tool(self.env, 't_write', {})
        self.assertTrue(self.env['res.partner'].browse(result['structuredContent']['id']).exists())

    def test_odoo_errors_pass_through(self):
        for exc in (AccessError("denied"), UserError("user"), ValidationError("invalid"),
                    tools.ToolError("tool")):
            def handler(env, arguments, exc=exc):
                raise exc
            with temporary_tools(make_tool('t_err', handler)):
                result = tools.call_tool(self.env, 't_err', {})
            self.assertEqual(result, {'content': [{'type': 'text', 'text': str(exc)}], 'isError': True})

    def test_unexpected_exception_is_generic(self):
        def handler(env, arguments):
            raise RuntimeError("secret /path/x.py")

        with temporary_tools(make_tool('t_boom', handler)):
            with self.assertLogs('odoo.addons.odoo_mcp.tools', 'ERROR') as logs:
                result = tools.call_tool(self.env, 't_boom', {})
        self.assertRegex(result['content'][0]['text'], r'^Internal error \(ref: [0-9a-f]{8}\)$')
        self.assertTrue(result['isError'])
        self.assertIn('secret /path/x.py', '\n'.join(logs.output))  # traceback stays server-side

    def test_tools_list_through_protocol(self):
        with temporary_tools(make_tool('t_listed', lambda env, a: {})):
            status, body = protocol.handle_message(*reversed(modern_request('tools/list')), self.env)
        listed = {tool['name']: tool for tool in body['result']['tools']}
        self.assertEqual(listed['t_listed']['inputSchema']['type'], 'object')
        self.assertEqual(listed['t_listed']['annotations'], {'readOnlyHint': True})
