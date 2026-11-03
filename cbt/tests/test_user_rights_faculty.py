# -*- coding: utf-8 -*-
from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase

from ..hooks import post_init_hook


class TestUserRightsFaculty(TransactionCase):
    """User Rights: Admin / Faculty flag and multi-select faculty roles."""

    def setUp(self):
        super().setUp()
        self.subject_a = self.env['cbt.subject'].create({'name': 'Physics'})
        self.subject_b = self.env['cbt.subject'].create({'name': 'Chemistry'})
        self.topic_a = self.env['cbt.subject.topic'].create({
            'name': 'Mechanics', 'subject_id': self.subject_a.id})
        self.topic_b = self.env['cbt.subject.topic'].create({
            'name': 'Optics', 'subject_id': self.subject_a.id})
        self.subtopic_a = self.env['cbt.subject.subtopic'].create({
            'name': 'Kinematics', 'topic_id': self.topic_a.id})

    def _user(self, login, **vals):
        values = {
            'name': login,
            'login': login,
            'password': 'secret',
        }
        values.update(vals)
        # The menu auto-population is not relevant for these tests.
        return self.env['res.users'].with_context(
            no_cbt_auto_populate=True).create(values)

    def test_cbt_role_defaults_to_admin(self):
        user = self._user('admin-default')
        self.assertEqual(user.cbt_role, 'admin')
        self.assertFalse(
            self.env['hr.employee'].search([('user_id', '=', user.id)]))

    def test_first_install_hook_grants_cbt_admin_to_odoo_admin(self):
        user = self.env.ref('base.user_admin')
        group = self.env.ref('cbt.group_cbt_admin')
        user.sudo().write({'groups_id': [(3, group.id)]})

        post_init_hook(self.env)

        self.assertIn(group, user.sudo().groups_id)
        post_init_hook(self.env)
        self.assertIn(group, user.sudo().groups_id)

    def test_faculty_user_gets_an_employee(self):
        user = self._user('faculty-employee', cbt_role='faculty')
        employee = self.env['hr.employee'].search([('user_id', '=', user.id)])
        self.assertTrue(employee)
        self.assertEqual(employee.user_id, user)

    def test_faculty_roles_from_user_rights_form(self):
        Role = self.env['cbt.employee.role']
        user = self._user('faculty-roles', cbt_role='faculty', **{
            'cbt_faculty_role_ids': [(0, 0, {
                'subject_ids': [(6, 0, [self.subject_a.id, self.subject_b.id])],
                'topic_ids': [(6, 0, [self.topic_a.id])],
                'subtopic_ids': [(6, 0, [self.subtopic_a.id])],
                'create_access': True,
                'review_access': False,
            })],
        })

        roles = Role.search([('user_id', '=', user.id)])
        self.assertEqual(len(roles), 1)
        self.assertTrue(roles.employee_id)
        self.assertEqual(roles.employee_id.user_id, user)
        self.assertEqual(
            set(roles.subject_ids.ids),
            {self.subject_a.id, self.subject_b.id})
        self.assertEqual(roles.topic_ids.ids, [self.topic_a.id])
        self.assertEqual(roles.subtopic_ids.ids, [self.subtopic_a.id])

        self.assertTrue(Role._cbt_has_access(
            user, self.subject_a.id, 'create_access'))
        self.assertTrue(Role._cbt_has_access(
            user, self.subject_b.id, 'create_access'))
        self.assertFalse(Role._cbt_has_access(
            user, self.subject_a.id, 'review_access'))

    def test_role_row_added_by_write_links_user(self):
        user = self._user('faculty-write', cbt_role='faculty')
        user.write({
            'cbt_faculty_role_ids': [(0, 0, {
                'subject_ids': [(6, 0, [self.subject_b.id])],
                'create_access': False,
                'review_access': True,
            })],
        })
        role = user.cbt_faculty_role_ids
        self.assertEqual(len(role), 1)
        self.assertEqual(role.user_id, user)
        self.assertTrue(role.employee_id)
        self.assertTrue(self.env['cbt.employee.role']._cbt_has_access(
            user, self.subject_b.id, 'review_access'))

    def test_legacy_single_subject_role_still_grants_access(self):
        user = self._user('faculty-legacy')
        employee = self.env['hr.employee'].create({
            'name': 'Legacy Faculty', 'user_id': user.id})
        self.env['cbt.employee.role'].create({
            'employee_id': employee.id,
            'subject_id': self.subject_a.id,
            'create_access': True,
            'review_access': True,
        })
        self.assertTrue(self.env['cbt.employee.role']._cbt_has_access(
            user, self.subject_a.id, 'create_access'))
        self.assertTrue(self.env['cbt.employee.role']._cbt_has_access(
            user, self.subject_a.id, 'review_access'))
        self.assertFalse(self.env['cbt.employee.role']._cbt_has_access(
            user, self.subject_b.id, 'create_access'))

    def test_default_subjects_follow_faculty_access(self):
        user = self._user('faculty-default-subjects', cbt_role='faculty', **{
            'cbt_faculty_role_ids': [(0, 0, {
                'subject_ids': [(6, 0, [self.subject_a.id])],
                'create_access': True,
                'review_access': True,
            })],
        })
        domain = self.env['cbt.mcqs'].with_user(user)._get_default_subjects()
        self.assertEqual(domain, [('id', 'in', [self.subject_a.id])])

    def test_faculty_role_requires_a_subject(self):
        user = self._user('faculty-no-subject', cbt_role='faculty')
        with self.assertRaises(ValidationError):
            self.env['cbt.employee.role'].create({
                'user_id': user.id,
                'create_access': True,
            })

    def test_password_required_on_user_rights_screen(self):
        Users = self.env['res.users'].with_context(
            cbt_user_rights_screen=True, no_cbt_auto_populate=True)
        with self.assertRaises(ValidationError):
            Users.create({'name': 'No Password', 'login': 'no-password'})
        with self.assertRaises(ValidationError):
            Users.create({
                'name': 'Blank Password',
                'login': 'blank-password',
                'password': '   ',
            })

    def test_password_not_required_outside_the_screen(self):
        # Normal user creation (portal provisioning, signup, ...) is not
        # affected by the User Rights screen rule.
        user = self.env['res.users'].with_context(
            no_cbt_auto_populate=True).create({
                'name': 'No Screen Password',
                'login': 'no-screen-password',
            })
        self.assertTrue(user.exists())

    def test_admin_user_requires_and_accepts_explicit_menu_access(self):
        manager = self.env['res.users'].sudo().create({
            'name': 'CBT Rights Manager',
            'login': 'cbt-rights-manager-test',
            'groups_id': [(6, 0, [
                self.env.ref('base.group_user').id,
                self.env.ref('cbt.group_cbt_rights_manager').id,
            ])],
        })
        Users = self.env['res.users'].with_user(manager).sudo().with_context(
            cbt_user_rights_screen=True,
            no_cbt_auto_populate=True,
        )
        base_values = {
            'name': 'Managed Admin',
            'login': 'managed-admin-test',
            'password': 'secret',
            'cbt_role': 'admin',
        }

        with self.assertRaisesRegex(
                ValidationError,
                'Select at least one CBT menu under CBT Menu Permissions'):
            Users.create(dict(base_values))

        MenuSec = self.env['cbt.menu.security'].sudo()
        MenuSec.sync_all(reapply=False)
        menu = self.env.ref('cbt.cbt_sub')
        security = MenuSec.search([('menu_id', '=', menu.id)], limit=1)
        self.assertTrue(security)

        values = dict(base_values)
        values['login'] = 'managed-admin-with-menu-test'
        values['cbt_right_ids'] = [(0, 0, {
            'menu_id': menu.id,
            'menu_security_id': security.id,
            'can_see': True,
            'can_read': True,
            'can_write': True,
            'can_create': True,
        })]
        user = Users.create(values)

        self.assertTrue(user.cbt_managed_user)
        self.assertTrue(user.cbt_right_ids.filtered(
            lambda right: right.menu_id == menu and right.can_see))

    def test_user_rights_menu_access_includes_child_permission_model(self):
        self.env['cbt.menu.security'].sudo().sync_all(reapply=False)
        menu = self.env.ref('cbt.menu_cbt_user_rights')
        menu_security = self.env['cbt.menu.security'].sudo().search(
            [('menu_id', '=', menu.id)], limit=1)
        self.assertTrue(menu_security)
        user = self._user('user-rights-child-access')

        permission = self.env['cbt.user.right'].sudo().create({
            'user_id': user.id,
            'menu_id': menu.id,
            'menu_security_id': menu_security.id,
            'can_see': True,
            'can_read': True,
            'can_write': True,
            'can_create': True,
        })

        ChildRights = self.env['cbt.user.right'].with_user(user)
        for operation in ('read', 'write', 'create'):
            self.assertTrue(ChildRights.check_access_rights(
                operation, raise_exception=False), operation)

        permission.write({'can_write': False, 'can_create': False})
        self.assertTrue(ChildRights.check_access_rights(
            'read', raise_exception=False))
        self.assertFalse(ChildRights.check_access_rights(
            'write', raise_exception=False))
        self.assertFalse(ChildRights.check_access_rights(
            'create', raise_exception=False))

    def test_managed_user_cannot_switch_to_admin_without_menu_access(self):
        user = self._user('managed-faculty-to-admin', cbt_role='faculty')
        managed_group = self.env.ref('cbt.group_cbt_managed')
        user.sudo().with_context(no_cbt_lockdown=True).write({
            'cbt_managed_user': True,
            'groups_id': [(4, managed_group.id)],
        })

        with self.assertRaisesRegex(
                ValidationError,
                'Select at least one CBT menu under CBT Menu Permissions'):
            user.with_context(cbt_user_rights_screen=True).write({
                'cbt_role': 'admin',
            })
