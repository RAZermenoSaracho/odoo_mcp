import json

from odoo.addons.odoo_mcp import tools
from odoo.addons.odoo_mcp.tools.models import resolve_model
from odoo.tests import TransactionCase

from .common import McpToolCase


class TestResolver(McpToolCase):

    def test_uniform_unknown_model(self):
        env = self.env(user=self.plain)
        for name in ('no.such.model', 'ir.mail_server', 'mail.thread', 'res.config.settings'):
            with self.assertRaises(tools.ToolError) as caught:
                resolve_model(env, name)
            self.assertEqual(str(caught.exception), f"Unknown model '{name}'")

    def test_readable_model_resolves(self):
        self.assertEqual(resolve_model(self.env(user=self.plain), 'res.partner')._name, 'res.partner')
        self.assertEqual(resolve_model(self.env(user=self.reader), 'ir.mail_server')._name, 'ir.mail_server')


class TestListModels(McpToolCase):

    def names(self, user, **arguments):
        return [m['model'] for m in self.ok(user, 'list_models', dict(arguments, limit=200))['models']]

    def test_visibility_follows_acl(self):
        self.assertIn('res.partner', self.names(self.plain))
        self.assertNotIn('ir.mail_server', self.names(self.plain))
        self.assertIn('ir.mail_server', self.names(self.reader))

    def test_superset_for_more_rights(self):
        # neither user sees abstract or transient models
        plain, reader = set(self.names(self.plain)), set(self.names(self.reader))
        self.assertLess(plain, reader)
        for name in list(reader):
            model = self.env.registry[name]
            self.assertFalse(model._abstract or model._transient, name)

    def test_plain_user_without_ir_model_access_succeeds(self):
        self.assertFalse(self.env(user=self.plain)['ir.model'].has_access('read'))
        self.assertTrue(self.ok(self.plain, 'list_models')['models'])

    def test_query_filter(self):
        result = self.ok(self.plain, 'list_models', {'query': 'PARTNER', 'limit': 200})
        self.assertTrue(result['models'])
        for entry in result['models']:
            self.assertTrue('partner' in entry['model'].lower() or 'partner' in entry['name'].lower(), entry)
        self.assertEqual(result['total'], len(result['models']))

    def test_paging_and_bounds(self):
        first = self.ok(self.plain, 'list_models', {'limit': 5})
        self.assertEqual((len(first['models']), first['limit'], first['offset']), (5, 5, 0))
        second = self.ok(self.plain, 'list_models', {'limit': 5, 'offset': 5})
        self.assertEqual(first['total'], second['total'])
        self.assertFalse({m['model'] for m in first['models']} & {m['model'] for m in second['models']})
        self.assertEqual(first['models'], sorted(first['models'], key=lambda m: m['model']))
        default = self.ok(self.plain, 'list_models')
        self.assertLessEqual(len(default['models']), 100)
        self.assertEqual(default['limit'], 100)
        self.assertIn('limit', self.error(self.plain, 'list_models', {'limit': 500}))
        self.assertIn('offset', self.error(self.plain, 'list_models', {'offset': -1}))


class TestDescribeModel(McpToolCase):

    def test_describe_partner(self):
        result = self.ok(self.plain, 'describe_model', {'model': 'res.partner'})
        self.assertEqual(result['model'], 'res.partner')
        self.assertTrue(result['access']['read'])
        self.assertEqual(result['fields']['name']['type'], 'char')
        parent = result['fields']['parent_id']
        self.assertEqual((parent['type'], parent['relation']), ('many2one', 'res.partner'))
        selection = result['fields']['type']['selection']
        self.assertIn(['contact', 'Contact'], selection)
        json.dumps(result)

    def test_access_flags_follow_acl(self):
        self.assertEqual(
            self.ok(self.reader, 'describe_model', {'model': 'ir.mail_server'})['access'],
            {'read': True, 'create': False, 'write': False, 'unlink': False})
        writer = self._user('mcp_writer', 'base.group_user', self.writer_group)
        self.assertEqual(
            self.ok(writer, 'describe_model', {'model': 'ir.mail_server'})['access'],
            {'read': True, 'create': True, 'write': True, 'unlink': True})

    def test_field_groups(self):
        admin = self._user('mcp_admin', 'base.group_user', 'base.group_system')
        self.patch(self.env.registry['res.partner']._fields['comment'], 'groups', 'base.group_system')
        self.assertNotIn('comment', self.ok(self.plain, 'describe_model', {'model': 'res.partner'})['fields'])
        self.assertIn('comment', self.ok(admin, 'describe_model', {'model': 'res.partner'})['fields'])

    def test_fields_filter(self):
        result = self.ok(self.plain, 'describe_model', {'model': 'res.partner', 'fields': ['name', 'email', 'nope']})
        self.assertEqual(sorted(result['fields']), ['email', 'name'])
        self.assertIn('fields', self.error(self.plain, 'describe_model',
                                           {'model': 'res.partner', 'fields': ['name'] * 101}))

    def test_binary_fields_are_described(self):
        self.assertEqual(
            self.ok(self.plain, 'describe_model', {'model': 'res.partner'})['fields']['image_1920']['type'], 'binary')

    def test_unknown_or_forbidden_model(self):
        for name in ('no.such.model', 'ir.mail_server'):
            self.assertEqual(self.error(self.plain, 'describe_model', {'model': name}), f"Unknown model '{name}'")


class TestDiscoveryToolsListing(TransactionCase):

    def test_tools_are_listed_read_only(self):
        listed = {tool['name']: tool for tool in tools.list_tools()}
        for name in ('list_models', 'describe_model'):
            self.assertEqual(listed[name]['inputSchema']['type'], 'object')
            self.assertIs(listed[name]['inputSchema']['additionalProperties'], False)
            self.assertTrue(listed[name]['annotations']['readOnlyHint'])
            self.assertFalse(listed[name]['annotations']['destructiveHint'])
