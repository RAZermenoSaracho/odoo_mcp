import base64

from odoo.addons.odoo_mcp.tools import read
from odoo.tests import TransactionCase

from .common import McpToolCase

PNG = base64.b64encode(
    base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==')
).decode()


class TestReadHelpers(TransactionCase):

    def test_domain_shapes(self):
        self.assertEqual(read.check_domain([]), [])
        read.check_domain(['|', ['a', '=', 1], '!', ['b', 'in', [1, 2, 3]]])
        for bad in ("[('a', '=', 1)]", {}, [['a', '=']], [['a', 1, 2]], [[1, '=', 2]], ['and'], [5],
                    [['a', '=', 1, 2]], ['&'] * 101):
            with self.assertRaises(read.ToolError, msg=repr(bad)):
                read.check_domain(bad)

    def test_domain_depth(self):
        deep = [1]
        for _ in range(read.MAX_VALUE_DEPTH):
            deep = [deep]
        with self.assertRaises(read.ToolError):
            read.check_domain([['a', 'in', deep]])
        ok = [1]
        for _ in range(read.MAX_VALUE_DEPTH - 1):
            ok = [ok]
        read.check_domain([['a', 'in', ok]])

    def test_default_and_explicit_fields(self):
        model = self.env['res.partner']
        default = read.select_fields(model, None)
        self.assertIn('name', default)
        self.assertIn('id', default)
        for excluded in ('image_1920', 'child_ids', 'category_id'):
            self.assertNotIn(excluded, default)
        self.assertEqual(read.select_fields(model, ['name', 'image_1920', 'name']), ['name', 'image_1920'])
        with self.assertRaisesRegex(read.ToolError, "'nope'"):
            read.select_fields(model, ['name', 'nope'])

    def test_size_bound(self):
        read.check_size({'a': 'x'})
        self.patch(read, 'MAX_RESPONSE_BYTES', 10)
        with self.assertRaisesRegex(read.ToolError, "lower 'limit'"):
            read.check_size({'a': 'x' * 20})


class TestReadTools(McpToolCase):

    def setUp(self):
        super().setUp()
        Partner = self.env['res.partner']
        self.partners = Partner.create([{'name': f'mcpv_{i}', 'email': f'mcpv{i}@example.com'} for i in range(1, 6)])
        self.other = Partner.create({'name': 'mcp_other'})

    def rows(self, user, arguments):
        return self.ok(user, 'search_read', dict({'model': 'res.partner'}, **arguments))

    def test_search_read_basic(self):
        result = self.rows(self.plain, {
            'domain': [['name', 'ilike', 'mcpv_']], 'fields': ['name', 'email'], 'order': 'name asc'})
        self.assertEqual([r['name'] for r in result['records']], [f'mcpv_{i}' for i in range(1, 6)])
        self.assertEqual(set(result['records'][0]), {'id', 'name', 'email'})
        self.assertEqual((result['count'], result['has_more'], result['limit'], result['offset']), (5, False, 50, 0))

    def test_paging_and_has_more(self):
        arguments = {'domain': [['name', 'ilike', 'mcpv_']], 'fields': ['name'], 'order': 'name asc'}
        page = self.rows(self.plain, dict(arguments, offset=1, limit=2))
        self.assertEqual([r['name'] for r in page['records']], ['mcpv_2', 'mcpv_3'])
        self.assertTrue(page['has_more'])
        last = self.rows(self.plain, dict(arguments, offset=4, limit=2))
        self.assertEqual([r['name'] for r in last['records']], ['mcpv_5'])
        self.assertFalse(last['has_more'])

    def test_default_limit_is_50(self):
        self.env['res.partner'].create([{'name': f'mcpbulk_{i}'} for i in range(60)])
        result = self.rows(self.plain, {'domain': [['name', 'like', 'mcpbulk_']], 'fields': ['name']})
        self.assertEqual((result['count'], result['has_more']), (50, True))

    def test_limit_bounds(self):
        self.assertIn("'limit'", self.error(self.plain, 'search_read', {'model': 'res.partner', 'limit': 201}))
        self.assertIn("'limit'", self.error(self.plain, 'search_read', {'model': 'res.partner', 'limit': 0}))

    def test_invalid_domain_and_order(self):
        self.assertIn('domain', self.error(self.plain, 'search_read', {'model': 'res.partner', 'domain': "[('a','=',1)]"}))
        self.assertTrue(self.error(self.plain, 'search_read', {'model': 'res.partner', 'domain': [['nope', '=', 1]]}))
        self.assertTrue(self.error(self.plain, 'search_read', {'model': 'res.partner', 'order': 'nope asc'}))
        self.assertTrue(self.error(self.plain, 'search_read', {'model': 'res.partner', 'order': 'name; drop table x'}))

    def test_archived(self):
        self.partners[0].active = False
        domain = [['name', 'ilike', 'mcpv_']]
        self.assertEqual(self.ok(self.plain, 'search_count', {'model': 'res.partner', 'domain': domain})['count'], 4)
        self.assertEqual(self.ok(self.plain, 'search_count', {
            'model': 'res.partner', 'domain': domain, 'include_archived': True})['count'], 5)
        result = self.rows(self.plain, {'domain': domain, 'fields': ['name'], 'include_archived': True})
        self.assertEqual(result['count'], 5)

    def test_count_matches_search(self):
        domain = [['name', 'ilike', 'mcpv_']]
        count = self.ok(self.plain, 'search_count', {'model': 'res.partner', 'domain': domain})['count']
        rows = self.rows(self.plain, {'domain': domain, 'limit': 200, 'fields': ['name']})
        self.assertEqual(count, len(rows['records']))

    def test_read_ordered_and_all_or_nothing(self):
        ids = [self.partners[2].id, self.partners[0].id]
        result = self.ok(self.plain, 'read', {'model': 'res.partner', 'ids': ids, 'fields': ['name']})
        self.assertEqual([r['name'] for r in result['records']], ['mcpv_3', 'mcpv_1'])
        missing = self.partners[4].id + 100000
        message = self.error(self.plain, 'read', {'model': 'res.partner', 'ids': [ids[0], missing]})
        self.assertNotIn('mcpv_', message)
        self.assertTrue(message)

    def test_read_returns_one_record_per_id_in_order(self):
        first, second = self.partner_ids_for_read()
        result = self.ok(self.plain, 'read', {'model': 'res.partner', 'ids': [second, first, second], 'fields': ['name']})
        self.assertEqual([r['id'] for r in result['records']], [second, first, second])

    def partner_ids_for_read(self):
        return self.partners[0].id, self.partners[1].id

    def test_read_id_bounds(self):
        self.assertIn("'ids'", self.error(self.plain, 'read', {'model': 'res.partner', 'ids': list(range(1, 202))}))
        self.assertIn("'ids'", self.error(self.plain, 'read', {'model': 'res.partner', 'ids': []}))
        self.assertIn("ids[0]", self.error(self.plain, 'read', {'model': 'res.partner', 'ids': ['1']}))
        self.assertIn("ids[0]", self.error(self.plain, 'read', {'model': 'res.partner', 'ids': [True]}))

    # -- fields -------------------------------------------------------------------

    def test_binary_excluded_by_default_but_available_on_request(self):
        self.partners[0].image_1920 = PNG
        default = self.rows(self.plain, {'domain': [['id', '=', self.partners[0].id]]})['records'][0]
        self.assertNotIn('image_1920', default)
        explicit = self.rows(self.plain, {
            'domain': [['id', '=', self.partners[0].id]], 'fields': ['name', 'image_1920']})['records'][0]
        self.assertTrue(explicit['image_1920'])

    def test_unknown_and_restricted_fields(self):
        self.assertIn("'nope'", self.error(self.plain, 'search_read', {'model': 'res.partner', 'fields': ['nope']}))
        self.patch(self.env.registry['res.partner']._fields['comment'], 'groups', 'base.group_system')
        self.assertIn("'comment'", self.error(self.plain, 'search_read', {'model': 'res.partner', 'fields': ['comment']}))
        self.assertNotIn('comment', self.rows(self.plain, {'limit': 1})['records'][0])
        admin = self._user('mcp_admin', 'base.group_user', 'base.group_system')
        self.assertIn('comment', self.rows(admin, {'fields': ['comment'], 'limit': 1})['records'][0])

    def test_response_size_bound(self):
        self.patch(read, 'MAX_RESPONSE_BYTES', 200)
        message = self.error(self.plain, 'search_read', {
            'model': 'res.partner', 'domain': [['name', 'ilike', 'mcpv_']], 'limit': 5})
        self.assertIn("lower 'limit'", message)

    def test_no_context_or_identity_arguments(self):
        for name in ('context', 'uid', 'user', 'company', 'lang'):
            for tool, extra in (('search_read', {}), ('search_count', {}), ('read', {'ids': [1]})):
                arguments = dict({'model': 'res.partner', name: 'x'}, **extra)
                self.assertIn(f"'{name}'", self.error(self.plain, tool, arguments))

    # -- ACL / record-rule parity -----------------------------------------------------

    def test_record_rule_parity(self):
        group = self.env['res.groups'].create({'name': 'mcp_rule_group'})
        self.env['ir.rule'].create({
            'name': 'mcp own', 'model_id': self.env['ir.model']._get('res.partner').id,
            'groups': [(6, 0, group.ids)], 'domain_force': "[('name', '=like', 'mcpv_%')]",
        })
        limited = self._user('mcp_limited', 'base.group_user', group)
        domain = [['name', 'like', 'mcp']]
        via_tool = self.rows(limited, {'domain': domain, 'fields': ['name'], 'order': 'name asc', 'limit': 200})
        direct = self.env(user=limited)['res.partner'].search_read(domain, ['name'], order='name asc')
        self.assertEqual(via_tool['records'], direct)
        self.assertEqual([r['name'] for r in via_tool['records']], [f'mcpv_{i}' for i in range(1, 6)])
        self.assertEqual(
            self.ok(limited, 'search_count', {'model': 'res.partner', 'domain': domain})['count'],
            self.env(user=limited)['res.partner'].search_count(domain))
        # an unrestricted user sees the other partner too
        unrestricted = self.rows(self.plain, {'domain': domain, 'fields': ['name'], 'limit': 200})
        self.assertIn('mcp_other', [r['name'] for r in unrestricted['records']])
        # a record the rule hides cannot be read
        message = self.error(limited, 'read', {'model': 'res.partner', 'ids': [self.other.id], 'fields': ['name']})
        self.assertNotIn('mcp_other', message)

    def test_model_without_access(self):
        for tool, extra in (('search_read', {}), ('search_count', {}), ('read', {'ids': [1]})):
            message = self.error(self.plain, tool, dict({'model': 'ir.mail_server'}, **extra))
            self.assertEqual(message, "Unknown model 'ir.mail_server'")

    def test_multi_company_scope(self):
        company_b = self.env['res.company'].create({'name': 'mcp company b'})
        in_b = self.env['res.partner'].create({'name': 'mcpv_company_b', 'company_id': company_b.id})
        user = self._user('mcp_company_a', 'base.group_user')
        user.write({'company_ids': [(6, 0, self.env.company.ids)], 'company_id': self.env.company.id})
        result = self.rows(user, {'domain': [['name', '=', 'mcpv_company_b']], 'fields': ['name']})
        self.assertEqual(result['records'], [])
        self.assertEqual(self.env(user=user)['res.partner'].search_count([('id', '=', in_b.id)]), 0)
        admin = self.env.ref('base.user_admin')
        admin.write({'company_ids': [(4, company_b.id)]})
        self.assertEqual(
            self.rows(admin, {'domain': [['name', '=', 'mcpv_company_b']], 'fields': ['name']})['count'], 1)
