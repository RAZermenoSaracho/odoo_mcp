from odoo.tests import tagged

from .common import McpHttpCase


class _Rollback(Exception):
    pass


@tagged('post_install', '-at_install')
class TestParityOverHttp(McpHttpCase):
    """Real authenticated `/mcp` calls must match direct ORM calls for the same user."""

    def setUp(self):
        super().setUp()
        Partner = self.env['res.partner']
        self.company_b = self.env['res.company'].create({'name': 'mcp parity company b'})
        self.partners = Partner.create([{'name': f'mcpp_{i}'} for i in range(1, 4)])
        self.hidden = Partner.create({'name': 'mcpp_hidden'})
        self.other_company = Partner.create({'name': 'mcpp_company_b', 'company_id': self.company_b.id})
        group = self.env['res.groups'].create({'name': 'mcp_parity_group'})
        model = self.env['ir.model']._get('res.partner')
        self.env['ir.rule'].create({
            'name': 'mcp parity rule', 'model_id': model.id, 'groups': [(6, 0, group.ids)],
            'domain_force': "[('name', '!=', 'mcpp_hidden')]",
        })
        manager = 'base.group_user,base.group_partner_manager'
        self.users = {
            'plain': self.make_user('mcp_par_plain'),
            'editor': self.make_user('mcp_par_editor', manager),
            'limited': self.make_user('mcp_par_limited', manager),
            'admin': self.make_user('mcp_par_admin', manager + ',base.group_system'),
        }
        self.users['limited'].group_ids = [(4, group.id)]
        for user in self.users.values():
            user.write({'company_ids': [(6, 0, self.env.company.ids)], 'company_id': self.env.company.id})
        self.keys = {name: self.make_key(user) for name, user in self.users.items()}

    def tool(self, who, name, arguments):
        response = self.mcp_call(self.keys[who], 'tools/call', {'name': name, 'arguments': arguments})
        self.assertEqual(response.status_code, 200)
        return response.json()['result']

    def direct_outcome(self, who, method):
        try:
            with self.env.cr.savepoint():
                method(self.env(user=self.users[who]))
                raise _Rollback
        except _Rollback:
            return 'ok'
        except Exception:  # noqa: BLE001
            return 'error'

    def test_reads_match_direct_orm(self):
        domain = [['name', 'like', 'mcpp_']]
        for who, user in self.users.items():
            direct = self.env(user=user)['res.partner'].search_read(domain, ['name'], order='name asc')
            result = self.tool(who, 'search_read', {
                'model': 'res.partner', 'domain': domain, 'fields': ['name'], 'order': 'name asc', 'limit': 200})
            self.assertFalse(result['isError'], (who, result))
            self.assertEqual(result['structuredContent']['records'], direct, who)
            count = self.tool(who, 'search_count', {'model': 'res.partner', 'domain': domain})
            self.assertEqual(count['structuredContent']['count'], len(direct), who)
        names = lambda who: [r['name'] for r in self.tool(who, 'search_read', {  # noqa: E731
            'model': 'res.partner', 'domain': domain, 'fields': ['name'], 'limit': 200})['structuredContent']['records']]
        self.assertNotIn('mcpp_hidden', names('limited'))
        self.assertIn('mcpp_hidden', names('editor'))
        self.assertNotIn('mcpp_company_b', names('editor'))   # other company is invisible to company-A users

    def test_reads_of_hidden_records_match(self):
        for who in self.users:
            direct = self.direct_outcome(who, lambda env: env['res.partner'].browse(self.hidden.id).read(['name']))
            result = self.tool(who, 'read', {'model': 'res.partner', 'ids': [self.hidden.id], 'fields': ['name']})
            self.assertEqual('error' if result['isError'] else 'ok', direct, who)
            if result['isError']:
                self.assertNotIn('mcpp_hidden', result['content'][0]['text'])

    def test_writes_and_deletes_match_direct_orm(self):
        ids = self.partners.ids + [self.hidden.id]
        for who in self.users:
            for tool, arguments, method in (
                ('write', {'model': 'res.partner', 'ids': ids, 'values': {'phone': '1'}},
                 lambda env: env['res.partner'].browse(ids).write({'phone': '1'})),
                ('write', {'model': 'res.partner', 'ids': ids[:1], 'values': {'phone': '2'}},
                 lambda env: env['res.partner'].browse(ids[:1]).write({'phone': '2'})),
                ('create', {'model': 'res.partner', 'values': {'name': 'mcpp_created'}},
                 lambda env: env['res.partner'].create({'name': 'mcpp_created'})),
            ):
                expected = self.direct_outcome(who, method)
                with self.env.cr.savepoint():
                    result = self.tool(who, tool, arguments)
                    actual = 'error' if result['isError'] else 'ok'
                    # roll back what a successful call committed to the test transaction
                    self.assertEqual(actual, expected, (who, tool, arguments))

    def test_alternating_keys_keep_identities_apart(self):
        ids = {}
        for who in ('editor', 'admin', 'editor', 'admin'):
            result = self.tool(who, 'create', {'model': 'res.partner', 'values': {'name': f'mcpp_by_{who}'}})
            self.assertFalse(result['isError'], result)
            ids.setdefault(who, []).append(result['structuredContent']['id'])
        self.env.invalidate_all()
        for who, created in ids.items():
            self.assertEqual(self.env['res.partner'].browse(created).mapped('create_uid'), self.users[who], who)
