# -*- coding: utf-8 -*-
from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase


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
