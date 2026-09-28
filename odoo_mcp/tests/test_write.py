from odoo.addons.odoo_mcp.tools import write
from odoo.tests import TransactionCase
from odoo.tools import mute_logger

from .common import McpToolCase


class TestWriteHelpers(TransactionCase):

    def test_values_validation(self):
        model = self.env['res.partner']
        write.check_values(model, {'name': 'x', 'email': 'a@b.c'})
        for bad in ({}, {'nope': 1}, {'id': 1}, {'create_uid': 1}, {'write_date': '2020-01-01'}):
            with self.assertRaises(write.ToolError, msg=repr(bad)):
                write.check_values(model, bad)
        with self.assertRaises(write.ToolError):
            write.check_values(model, {f'f{i}': 1 for i in range(201)})


class TestWriteTools(McpToolCase):

    def setUp(self):
        super().setUp()
        self.editor = self._user('mcp_editor', 'base.group_user', 'base.group_partner_manager')
        self.partners = self.env['res.partner'].create([{'name': f'mcpw_{i}'} for i in range(1, 4)])
        self.partner_ids = self.partners.ids

    def name_of(self, record_id):
        self.env.invalidate_all()
        return self.env['res.partner'].browse(record_id).name

    def partner_names(self):
        self.env.invalidate_all()
        return self.env['res.partner'].browse(self.partner_ids).mapped('name')

    # -- create -----------------------------------------------------------------

    def test_create(self):
        result = self.ok(self.editor, 'create', {'model': 'res.partner', 'values': {'name': 'mcpw_new'}})
        record = self.env['res.partner'].browse(result['id'])
        self.assertEqual((record.name, record.create_uid), ('mcpw_new', self.editor))
        self.assertEqual(list(result), ['id'])

    def test_create_relational_values(self):
        parent = self.partners[0]
        child_id = self.ok(self.editor, 'create', {'model': 'res.partner', 'values': {
            'name': 'mcpw_child', 'parent_id': parent.id,
            'child_ids': [[0, 0, {'name': 'mcpw_grandchild'}]]}})['id']
        child = self.env['res.partner'].browse(child_id)
        self.assertEqual((child.parent_id, child.child_ids.name), (parent, 'mcpw_grandchild'))

    def test_create_acl_denied_and_no_record(self):
        message = self.error(self.reader, 'create', {'model': 'ir.mail_server', 'values': {'name': 'x', 'smtp_host': 'h'}})
        self.assertIn('not allowed', message)
        self.assertFalse(self.env['ir.mail_server'].search([('name', '=', 'x')]))

    def test_create_without_read_access_is_unknown_model(self):
        model = self.env['ir.model']._get('ir.mail_server')
        group = self._group('mcp_creators', model, create=True)
        creator = self._user('mcp_creator', 'base.group_user', group)
        self.assertTrue(self.env(user=creator)['ir.mail_server'].has_access('create'))
        self.assertEqual(
            self.error(creator, 'create', {'model': 'ir.mail_server', 'values': {'name': 'x'}}),
            "Unknown model 'ir.mail_server'")

    # -- write ------------------------------------------------------------------

    def test_write_single_and_multiple(self):
        self.assertEqual(self.ok(self.editor, 'write', {
            'model': 'res.partner', 'ids': self.partner_ids[:1], 'values': {'phone': '111'}}), {'updated': 1})
        self.assertEqual(self.ok(self.editor, 'write', {
            'model': 'res.partner', 'ids': self.partner_ids, 'values': {'phone': '222'}}), {'updated': 3})
        self.env.invalidate_all()
        self.assertEqual(set(self.partners.mapped('phone')), {'222'})

    def test_write_missing_id_changes_nothing(self):
        message = self.error(self.editor, 'write', {
            'model': 'res.partner', 'ids': self.partner_ids + [99999999], 'values': {'name': 'changed'}})
        self.assertIn('99999999', message)
        self.assertEqual(self.partner_names(), ['mcpw_1', 'mcpw_2', 'mcpw_3'])

    def test_write_record_rule_denies_one_record(self):
        group = self.env['res.groups'].create({'name': 'mcp_write_rule_group'})
        self.env['ir.rule'].create({
            'name': 'mcp write', 'model_id': self.env['ir.model']._get('res.partner').id, 'groups': [(6, 0, group.ids)],
            'perm_read': False, 'perm_write': True, 'perm_create': False, 'perm_unlink': False,
            'domain_force': "[('name', '!=', 'mcpw_3')]",
        })
        limited = self._user('mcp_limited_w', 'base.group_user', 'base.group_partner_manager', group)
        self.error(limited, 'write', {'model': 'res.partner', 'ids': self.partner_ids, 'values': {'name': 'changed'}})
        self.assertEqual(self.partner_names(), ['mcpw_1', 'mcpw_2', 'mcpw_3'])
        self.assertEqual(self.ok(limited, 'write', {
            'model': 'res.partner', 'ids': self.partner_ids[:2], 'values': {'phone': '5'}}), {'updated': 2})

    def test_write_restricted_or_unknown_field(self):
        self.patch(self.env.registry['res.partner']._fields['comment'], 'groups', 'base.group_system')
        for field in ('comment', 'nope', 'create_uid', 'id', 'display_name'):
            self.error(self.editor, 'write', {'model': 'res.partner', 'ids': self.partner_ids[:1], 'values': {field: 'x'}})
        self.assertEqual(self.partner_names(), ['mcpw_1', 'mcpw_2', 'mcpw_3'])

    def test_write_business_constraint(self):
        parent = self.partners[0]
        message = self.error(self.editor, 'write', {
            'model': 'res.partner', 'ids': [parent.id], 'values': {'parent_id': parent.id}})
        self.assertIn('recursive', message.lower())

    def test_values_shapes(self):
        for values in ({}, [], 'x', None):
            self.error(self.editor, 'write', {'model': 'res.partner', 'ids': self.partner_ids[:1], 'values': values})

    # -- unlink -------------------------------------------------------------------

    def test_unlink(self):
        self.assertEqual(self.ok(self.editor, 'unlink', {
            'model': 'res.partner', 'ids': self.partner_ids[:2]}), {'deleted': 2})
        self.assertEqual(self.env['res.partner'].browse(self.partner_ids).exists().ids, self.partner_ids[2:])

    def test_unlink_business_rule_blocks(self):
        admin = self._user('mcp_admin', 'base.group_user', 'base.group_system')
        message = self.error(admin, 'unlink', {'model': 'res.users', 'ids': [self.env.ref('base.user_admin').id]})
        self.assertTrue(message)
        self.assertTrue(self.env.ref('base.user_admin').exists())

    def test_unlink_access_denied(self):
        server = self.env['ir.mail_server'].create({'name': 'mcpw_server', 'smtp_host': 'localhost'})
        self.error(self.reader, 'unlink', {'model': 'ir.mail_server', 'ids': [server.id]})
        self.assertTrue(server.exists())
        writer = self._user('mcp_writer', 'base.group_user', self.writer_group)
        self.assertEqual(self.ok(writer, 'unlink', {'model': 'ir.mail_server', 'ids': [server.id]}), {'deleted': 1})

    def test_id_bounds(self):
        self.assertIn("'ids'", self.error(self.editor, 'unlink', {'model': 'res.partner', 'ids': list(range(1, 102))}))
        self.assertIn("'ids'", self.error(self.editor, 'write', {'model': 'res.partner', 'ids': [], 'values': {'name': 'x'}}))
        self.assertIn('not found', self.error(self.editor, 'unlink', {'model': 'res.partner', 'ids': [99999999]}))

    # -- atomicity ------------------------------------------------------------------

    @mute_logger('odoo.addons.odoo_mcp.tools', 'odoo.sql_db')
    def test_side_effects_roll_back_when_create_fails(self):
        before = self.env['res.partner'].search_count([('name', '=', 'mcpw_dup_user')])
        admin = self._user('mcp_admin_dup', 'base.group_user', 'base.group_system')
        self.assertTrue(self.error(admin, 'create', {'model': 'res.users', 'values': {
            'name': 'mcpw_dup_user', 'login': 'mcp_admin_dup'}}).startswith('Internal error'))
        self.assertEqual(self.env['res.partner'].search_count([('name', '=', 'mcpw_dup_user')]), before)
        # a following call is unaffected
        created = self.ok(admin, 'create', {'model': 'res.partner', 'values': {'name': 'mcpw_after'}})['id']
        self.assertTrue(self.env['res.partner'].browse(created).exists())

    @mute_logger('odoo.addons.odoo_mcp.tools', 'odoo.sql_db')
    def test_multi_record_write_failing_at_flush_changes_nothing(self):
        admin = self._user('mcp_admin_w', 'base.group_user', 'base.group_system')
        users = self._user('mcp_u1', 'base.group_user') | self._user('mcp_u2', 'base.group_user')
        self.assertTrue(self.error(admin, 'write', {
            'model': 'res.users', 'ids': users.ids, 'values': {'login': 'mcp_same_login'}}).startswith('Internal error'))
        self.env.invalidate_all()
        self.assertEqual(users.mapped('login'), ['mcp_u1', 'mcp_u2'])

    # -- no context / identity / privilege ------------------------------------------

    def test_no_context_or_identity_arguments(self):
        for name in ('context', 'uid', 'user', 'company', 'lang', 'tracking_disable'):
            for tool, extra in (('create', {'values': {'name': 'x'}}),
                                ('write', {'ids': [1], 'values': {'name': 'x'}}),
                                ('unlink', {'ids': [1]})):
                self.assertIn(f"'{name}'", self.error(self.editor, tool, dict({'model': 'res.partner', name: 1}, **extra)))
        self.assertEqual(self.env['res.partner'].search_count([('name', '=', 'x')]), 0)

    # -- parity -----------------------------------------------------------------------

    def direct_outcome(self, user, method):
        """'ok'/'error' of running `method(env_of_user)` directly, leaving no trace."""
        try:
            with self.env.cr.savepoint():
                method(self.env(user=user))
                raise _Rollback
        except _Rollback:
            return 'ok'
        except Exception:  # noqa: BLE001
            return 'error'

    def test_parity_with_direct_orm(self):
        server = self.env['ir.mail_server'].create({'name': 'mcpw_parity', 'smtp_host': 'localhost'})
        writer = self._user('mcp_writer_p', 'base.group_user', self.writer_group)
        cases = [
            (self.editor, 'create', {'model': 'res.partner', 'values': {'name': 'p'}},
             lambda env: env['res.partner'].create({'name': 'p'})),
            (self.editor, 'write', {'model': 'res.partner', 'ids': self.partner_ids, 'values': {'name': 'p'}},
             lambda env: env['res.partner'].browse(self.partner_ids).write({'name': 'p'})),
            (self.editor, 'write', {'model': 'res.partner', 'ids': self.partner_ids[:1], 'values': {'parent_id': self.partner_ids[0]}},
             lambda env: env['res.partner'].browse(self.partner_ids[:1]).write({'parent_id': self.partner_ids[0]})),
            (self.reader, 'unlink', {'model': 'ir.mail_server', 'ids': [server.id]},
             lambda env: env['ir.mail_server'].browse(server.id).unlink()),
            (self.reader, 'write', {'model': 'ir.mail_server', 'ids': [server.id], 'values': {'name': 'n'}},
             lambda env: env['ir.mail_server'].browse(server.id).write({'name': 'n'})),
            (writer, 'write', {'model': 'ir.mail_server', 'ids': [server.id], 'values': {'name': 'n'}},
             lambda env: env['ir.mail_server'].browse(server.id).write({'name': 'n'})),
            (self.editor, 'create', {'model': 'ir.mail_server', 'values': {'name': 'n'}},
             lambda env: env['ir.mail_server'].create({'name': 'n'})),
        ]
        for user, tool, arguments, method in cases:
            expected = self.direct_outcome(user, method)
            with self.env.cr.savepoint():
                result = self.call(user, tool, arguments)
                actual = 'error' if result['isError'] else 'ok'
            self.assertEqual(actual, expected, (user.login, tool, arguments))


class _Rollback(Exception):
    pass
