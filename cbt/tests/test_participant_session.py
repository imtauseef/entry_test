# -*- coding: utf-8 -*-
import json
import threading
from unittest.mock import patch

import odoo
import odoo.http
from odoo import SUPERUSER_ID, api, fields
from odoo.exceptions import AccessDenied, ValidationError
from odoo.tests.common import HttpCase, TransactionCase, tagged

PORTAL_GROUP = 'base.group_portal'
INTERNAL_GROUP = 'base.group_user'


class TestParticipantProvisioning(TransactionCase):

    def _participant(self, login='P001', password='secret', **vals):
        values = {'name': 'Student', 'login': login, 'password': password}
        values.update(vals)
        return self.env['cbt.participant'].create(values)

    def test_create_portal_user(self):
        participant = self._participant()
        result = participant._sync_portal_user()

        self.assertEqual(result['action'], 'created')
        self.assertTrue(participant.user_id)
        user = participant.user_id.sudo()
        self.assertTrue(user._cbt_is_portal_only())
        self.assertEqual(user.login, 'P001')
        self.assertEqual(user.partner_id, participant.partner_id)
        self.assertNotEqual(user.password, 'secret')
        self.assertTrue(user.password)

    def test_update_only_when_changed(self):
        participant = self._participant()
        participant._sync_portal_user()
        user = participant.user_id.sudo()
        old_hash = user.password

        participant.write({'name': 'Renamed'})
        result = participant._sync_portal_user(password_changed=False)
        self.assertEqual(result['action'], 'updated')
        self.assertEqual(user.name, 'Renamed')
        self.assertEqual(user.sudo().password, old_hash)

        participant.write({'password': 'new-secret'})
        participant._sync_portal_user(password_changed=True)
        self.assertNotEqual(user.sudo().password, old_hash)

    def test_skip_non_portal_login(self):
        internal_group = self.env.ref(INTERNAL_GROUP)
        internal = self.env['res.users'].create({
            'name': 'Internal User',
            'login': 'P001',
            'groups_id': [(6, 0, [internal_group.id])],
        })
        participant = self._participant()

        result = participant._sync_portal_user()

        self.assertEqual(result['action'], 'skipped')
        self.assertIn('non-portal', result['reason'])
        self.assertFalse(participant.user_id)
        self.assertTrue(internal.exists())
        self.assertIn(internal_group, internal.groups_id)

    def test_archive_missing_participants(self):
        participant = self._participant()
        participant._sync_portal_user()
        user = participant.user_id.sudo()
        user._cbt_claim_session()

        summary = self.env['cbt.participant']._archive_missing_portal_users(
            {'OTHER'})

        self.assertIn('P001', summary['archived'])
        self.assertFalse(participant.active)
        self.assertFalse(user.active)
        self.assertFalse(user.cbt_session_token)

    def test_login_and_password_required(self):
        with self.assertRaises(ValidationError):
            self._participant(login='   ')
        with self.assertRaises(ValidationError):
            self._participant(login='P002', password='   ')

    def test_login_unique(self):
        self._participant(login='P003')
        with self.assertRaises(Exception):
            with self.env.cr.savepoint():
                self._participant(login='P003')
                self.env.flush_all()

    def test_password_not_logged(self):
        participant = self._participant(password='super-secret-value')
        with patch('odoo.addons.cbt.models.test_schedule._logger') as logger:
            participant._sync_portal_user()
            for call in (logger.info.call_args_list
                         + logger.warning.call_args_list
                         + logger.exception.call_args_list):
                self.assertNotIn('super-secret-value', str(call))


class TestParticipantSession(TransactionCase):

    def setUp(self):
        super().setUp()
        self.portal_group = self.env.ref(PORTAL_GROUP)
        self.user = self.env['res.users'].create({
            'name': 'Portal Participant',
            'login': 'portal-participant',
            'password': 'secret',
            'groups_id': [(6, 0, [self.portal_group.id])],
        })

    def test_first_claim_wins_second_rejected(self):
        token = self.user._cbt_claim_session()
        self.assertTrue(token)
        self.assertEqual(self.user.cbt_session_token, token)
        self.assertFalse(self.user._cbt_claim_session())

    def test_claim_after_timeout(self):
        token = self.user._cbt_claim_session()
        self.user.env.cr.execute(
            "UPDATE res_users SET cbt_last_seen = "
            "(NOW() AT TIME ZONE 'UTC') - interval '10 minutes' "
            "WHERE id = %s", [self.user.id])
        self.user.invalidate_recordset(['cbt_last_seen'])

        new_token = self.user._cbt_claim_session()
        self.assertTrue(new_token)
        self.assertNotEqual(new_token, token)

    def test_claim_after_force_logout(self):
        self.user._cbt_claim_session()
        self.user._cbt_clear_session()
        self.assertFalse(self.user.cbt_session_token)
        self.assertFalse(self.user.cbt_last_seen)
        self.assertTrue(self.user._cbt_claim_session())

    def test_internal_users_are_exempt(self):
        self.assertTrue(self.user._cbt_is_portal_only())
        self.assertFalse(self.env.user._cbt_is_portal_only())
        internal = self.env['res.users'].create({
            'name': 'Internal',
            'login': 'internal-user',
            'groups_id': [(6, 0, [self.env.ref(INTERNAL_GROUP).id])],
        })
        self.assertFalse(internal._cbt_is_portal_only())

    def test_session_matches(self):
        token = self.user._cbt_claim_session()
        self.assertTrue(self.user._cbt_session_matches(token))
        self.assertFalse(self.user._cbt_session_matches('wrong'))

    def test_force_logout_button(self):
        participant = self.env['cbt.participant'].create({
            'name': 'Student', 'login': 'P100', 'password': 'secret'})
        participant._sync_portal_user()
        user = participant.user_id.sudo()
        user._cbt_claim_session()

        participant.action_force_logout()

        self.assertFalse(user.cbt_session_token)
        self.assertFalse(user.cbt_last_seen)
        self.assertTrue(participant.message_ids)


@tagged('post_install', '-at_install')
class TestSingleSessionHttp(HttpCase):

    def _create_portal_user(self, login='http-portal', password='secret'):
        user = self.env['res.users'].create({
            'name': 'HTTP Portal',
            'login': login,
            'password': password,
            'groups_id': [(6, 0, [self.env.ref(PORTAL_GROUP).id])],
        })
        self.env.cr.commit()
        return user

    def _cleanup_user(self, user):
        with self.env.registry.cursor() as cr:
            env = api.Environment(cr, SUPERUSER_ID, {})
            existing = env['res.users'].browse(user.id).exists()
            partner = existing.partner_id
            if existing:
                existing.unlink()
            if partner and not partner.user_ids:
                partner.unlink()

    def test_second_login_from_another_device_rejected(self):
        user = self._create_portal_user()
        try:
            session = self.authenticate('http-portal', 'secret')
            self.assertEqual(session.uid, user.id)
            token = user.sudo().cbt_session_token
            self.assertTrue(token)

            with self.assertRaises(AccessDenied) as error:
                self.authenticate('http-portal', 'secret')
            self.assertIn('already logged in', str(error.exception))

            user.sudo()._cbt_clear_session()
            self.env.cr.commit()
            session = self.authenticate('http-portal', 'secret')
            self.assertEqual(session.uid, user.id)
        finally:
            user.sudo()._cbt_clear_session()
            self.env.cr.commit()
            self._cleanup_user(user)

    def test_old_session_is_redirected(self):
        user = self._create_portal_user(login='http-old')
        try:
            self.authenticate('http-old', 'secret')
            self.session['cbt_token'] = user.sudo().cbt_session_token
            odoo.http.root.session_store.save(self.session)
            response = self.url_open('/cbt/home', allow_redirects=False)
            self.assertNotEqual(response.status_code, 303)

            self.session['cbt_token'] = 'stale-token'
            odoo.http.root.session_store.save(self.session)
            response = self.url_open('/cbt/home', allow_redirects=False)
            self.assertEqual(response.status_code, 303)
            self.assertIn('cbt_session_ended', response.headers.get('Location', ''))
        finally:
            user.sudo()._cbt_clear_session()
            self.env.cr.commit()
            self._cleanup_user(user)

    def test_heartbeat_returns_json_on_stale_session(self):
        user = self._create_portal_user(login='http-beat')
        try:
            self.authenticate('http-beat', 'secret')
            self.session['cbt_token'] = 'stale-token'
            odoo.http.root.session_store.save(self.session)
            response = self.url_open(
                '/cbt/time/remaining', data={'time': '1:00'},
                allow_redirects=False)
            payload = json.loads(response.text)
            self.assertTrue(payload.get('session_ended'))
        finally:
            user.sudo()._cbt_clear_session()
            self.env.cr.commit()
            self._cleanup_user(user)

    def test_concurrent_claims_only_one_wins(self):
        user = self._create_portal_user(login='http-race')
        try:
            registry = self.env.registry
            results = []
            barrier = threading.Barrier(2)

            def claim():
                with registry.cursor() as cr:
                    env = api.Environment(cr, SUPERUSER_ID, {})
                    record = env['res.users'].browse(user.id)
                    barrier.wait(timeout=10)
                    results.append(bool(record._cbt_claim_session()))

            threads = [threading.Thread(target=claim) for _ in range(2)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=20)
            self.assertEqual(results.count(True), 1)
        finally:
            user.sudo()._cbt_clear_session()
            self.env.cr.commit()
            self._cleanup_user(user)
