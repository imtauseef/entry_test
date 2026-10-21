# -*- coding: utf-8 -*-
import json
import logging
from datetime import datetime

import requests

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


class CBTParticipant(models.Model):
    _name = 'cbt.participant'
    _description = 'Participant for the Entry Test'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(string='Participant Name', tracking=True)
    login = fields.Char(string="Participant Login", tracking=True, index=True)
    # Not tracked: tracking a Char stores its value in the chatter, which would
    # leak the plaintext password.
    password = fields.Char(string="Participant Password")
    center_id = fields.Many2one('cbt.center', 'Test Center', tracking=True)
    slot_id = fields.Many2one('cbt.slot', 'Time', tracking=True)
    program = fields.Many2one('cbt.program', 'program', tracking=True)
    degree = fields.Char('Degree Code', tracking=True)
    first_prefernce = fields.Char('First Preference', tracking=True)
    cid = fields.Integer('Entery Test Card Id')
    room = fields.Char(string='Room')
    active = fields.Boolean(default=True)

    user_id = fields.Many2one(
        'res.users', string='Portal User', readonly=True, copy=False,
        ondelete='set null')
    partner_id = fields.Many2one(
        'res.partner', string='Portal Partner', readonly=True, copy=False,
        ondelete='set null')
    session_active = fields.Boolean(
        string='Active Session', compute='_compute_session_active')

    _sql_constraints = [
        ('login_uniq', 'unique(login)', 'Participant login must be unique.'),
    ]

    @api.constrains('login', 'password')
    def _check_login_password(self):
        for rec in self:
            if not (rec.login or '').strip():
                raise ValidationError(_('Participant login is required.'))
            if not (rec.password or '').strip():
                raise ValidationError(_('Participant password is required.'))

    @api.depends('user_id', 'login', 'user_id.cbt_session_token',
                 'user_id.cbt_last_seen')
    def _compute_session_active(self):
        value = self.env['ir.config_parameter'].sudo().get_param(
            'cbt.session_timeout_seconds', 120)
        try:
            timeout = max(1, int(value))
        except (TypeError, ValueError):
            timeout = 120
        now = fields.Datetime.now()
        for rec in self:
            user = rec._get_portal_user()
            token = user.sudo().cbt_session_token if user else False
            last_seen = user.sudo().cbt_last_seen if user else False
            rec.session_active = bool(
                token and last_seen
                and (now - last_seen).total_seconds() <= timeout)

    # --------------------------------------------------------------- portal user
    def _get_portal_user(self):
        self.ensure_one()
        if self.user_id:
            return self.user_id.sudo()
        if (self.login or '').strip():
            return self.env['res.users'].sudo().with_context(
                active_test=False).search(
                    [('login', '=', self.login.strip())], limit=1)
        return self.env['res.users']

    def _sync_portal_user(self, password_changed=True):
        """Create/update the portal ``res.users`` for this participant.

        Returns ``{'action': 'created'|'updated'|'skipped', ...}``.  Matches on
        ``login`` and never touches a non-portal user with the same login.
        """
        self.ensure_one()
        login = (self.login or '').strip()
        password = self.password or ''
        if not login or not password:
            return {'action': 'skipped', 'reason': 'Missing login or password.'}

        Users = self.env['res.users'].sudo().with_context(
            no_reset_password=True, active_test=False)
        user = Users.search([('login', '=', login)], limit=1)
        if user and not user._cbt_is_portal_only():
            _logger.warning(
                "CBT participant %s: login %s already belongs to a non-portal "
                "user; portal user not modified.", self.name, login)
            return {'action': 'skipped',
                    'reason': 'Login already used by a non-portal user.'}

        company = self.env.company
        if not user:
            partner = self.env['res.partner'].sudo().create({
                'name': self.name or login,
                'email': login,
            })
            user = Users.create({
                'name': self.name or login,
                'login': login,
                'password': password,
                'partner_id': partner.id,
                'email': login,
                'groups_id': [(6, 0, [self.env.ref('base.group_portal').id])],
                'company_id': company.id,
                'company_ids': [(6, 0, [company.id])],
                'active': True,
            })
            action = 'created'
        else:
            values = {}
            if user.name != (self.name or login):
                values['name'] = self.name or login
            if not user.active:
                values['active'] = True
            if password_changed:
                values['password'] = password
            if user.company_id != company:
                values['company_id'] = company.id
                values['company_ids'] = [(4, company.id)]
            if values:
                user.write(values)
            action = 'updated'

        if self.user_id != user:
            self.sudo().write({'user_id': user.id})
        if self.partner_id != user.partner_id:
            self.sudo().write({'partner_id': user.partner_id.id})
        return {'action': action, 'user_id': user.id}

    def action_force_logout(self):
        """Clear the active session; used by the form button/server action."""
        for rec in self:
            user = rec._get_portal_user()
            if user:
                user.sudo()._cbt_clear_session()
            rec.message_post(body=_(
                "Portal session reset by %s.") % self.env.user.name)
        return True

    # ------------------------------------------------------------------- import
    @api.model
    def _archive_missing_portal_users(self, incoming_logins):
        """Archive participants (and portal users) absent from the feed."""
        if not incoming_logins:
            return {'archived': []}

        removed = self.sudo().with_context(active_test=False).search([
            ('active', '=', True),
            ('login', 'not in', list(incoming_logins)),
        ])
        archived = []
        for participant in removed:
            try:
                with self.env.cr.savepoint():
                    user = participant._get_portal_user()
                    participant.write({'active': False})
                    if user and user._cbt_is_portal_only():
                        user.sudo()._cbt_clear_session()
                        if user.active:
                            user.sudo().write({'active': False})
                    archived.append(participant.login)
            except Exception:  # noqa: BLE001 - one row must not stop the rest
                _logger.warning("CBT: could not archive participant %s",
                                participant.login, exc_info=True)
        return {'archived': archived}

    @api.model
    def fetch_participant(self, *args, **kwargs):
        summary = {
            'status': 'updated',
            'created': [],
            'updated': [],
            'archived': [],
            'skipped': [],
            'warnings': [],
            'plaintext_passwords': True,
            'security_warning': (
                'cbt.participant.password is still stored in plaintext. '
                'Consider keeping it only until the portal user is created, '
                'or storing a one-way hash/external reference.'),
        }
        try:
            db = self.env['ir.config_parameter'].get_param('cbt.admission_db')
            url = self.env['ir.config_parameter'].get_param('cbt.admission_url')
            admission_login = self.env['ir.config_parameter'].get_param(
                'cbt.admission_login')
            admission_password = self.env['ir.config_parameter'].get_param(
                'cbt.admission_password')

            if not all([db, url, admission_login, admission_password]):
                raise UserError(
                    'Please Fill All Credentials In Configuration')

            auth_url = url + '/web/session/authenticate'
            user = requests.post(
                auth_url,
                json={
                    "jsonrpc": "2.0",
                    "params": {
                        "db": db,
                        "login": admission_login,
                        "password": admission_password,
                    },
                },
                headers={"Content-Type": "application/json"})
            if json.loads(user.content).get('error', False):
                return {'status': 'error', 'msg': 'Authentication Failed!'}

            entry_test_card = url + '/entry/test'
            student_data_response = requests.post(
                entry_test_card, json={"jsonrpc": "2.0"}, headers={
                    "Content-Type": "application/json",
                    "Cookie": "session_id=%s" % user.cookies.get_dict().get(
                        'session_id'),
                    "X-Openerp": user.cookies.get_dict().get('session_id'),
                })

            try:
                student_data = json.loads(json.loads(
                    student_data_response.content).get('result'))
            except Exception as exc:
                raise UserError(f'{exc}')

            if not isinstance(student_data, list):
                raise UserError('Unexpected response from the admission system.')

            seen = set()
            Participant = self.env['cbt.participant'].sudo().with_context(
                active_test=False)

            for student in student_data:
                login = str(student.get('application_no') or '').strip()
                password = str(student.get('password') or '')
                if not login:
                    summary['skipped'].append({
                        'login': None,
                        'reason': 'Missing application number.'})
                    continue
                if not password.strip():
                    summary['skipped'].append({
                        'login': login, 'reason': 'Missing password.'})
                    continue
                if login in seen:
                    summary['skipped'].append({
                        'login': login,
                        'reason': 'Duplicate login in the incoming list.'})
                    continue
                seen.add(login)

                try:
                    with self.env.cr.savepoint():
                        test_date = (datetime.strptime(
                            student.get('date'), "%Y-%m-%d")
                            if student.get('date') else False)
                        data = {
                            'name': student.get('name'),
                            'cid': student.get('cid'),
                            'password': password,
                            'login': login,
                            'room': student.get('room'),
                        }

                        program_admission = json.loads(
                            student.get('program_id'))
                        if (program_admission.get('code')
                                and program_admission.get('name')):
                            program_cbt = self.env['cbt.program'].search([
                                '|',
                                ('code', '=', program_admission.get('code')),
                                ('name', '=', program_admission.get('name')),
                            ], limit=1)
                            if not program_cbt:
                                program_cbt = self.env['cbt.program'].create({
                                    'name': program_admission.get('name'),
                                    'code': program_admission.get('code'),
                                })
                            data['program'] = program_cbt.id

                        slot_admission = json.loads(student.get('slot'))
                        slot_name = slot_admission.get('name')
                        slot_cbt = self.env['cbt.slot'].search([
                            ('name', '=', slot_name),
                            ('date', '=', test_date),
                        ], limit=1)
                        if not slot_cbt:
                            slot_cbt = self.env['cbt.slot'].create({
                                'time': float(slot_admission.get('time_from')),
                                'date': test_date,
                                'name': slot_name,
                            })
                        data['slot_id'] = slot_cbt.id

                        participant = Participant.search(
                            [('login', '=', login)], limit=1)
                        if participant:
                            changes = {}
                            for fname, value in data.items():
                                current = participant[fname]
                                if participant._fields[fname].type == 'many2one':
                                    current = current.id
                                if current != value:
                                    changes[fname] = value
                            if not participant.active:
                                changes['active'] = True
                            password_changed = (
                                (participant.password or '') != password)
                            if changes:
                                participant.write(changes)
                            result = participant._sync_portal_user(
                                password_changed=password_changed)
                        else:
                            participant = Participant.create(data)
                            result = participant._sync_portal_user(
                                password_changed=True)

                        # Keep the old behaviour of hiding ended papers, but
                        # never delete the participant or its portal user.
                        PaperExport = self.env.get('cbt.paper.export')
                        test_paper = PaperExport and PaperExport.sudo().search([
                            ('login', '=', login),
                            ('cid', '=', student.get('cid')),
                        ], limit=1)
                        if test_paper and (
                                test_paper.end_paper
                                or (test_paper.test_date
                                    and test_paper.test_date
                                    < datetime.today().date())):
                            test_paper.active = False

                        if result.get('action') == 'skipped':
                            summary['skipped'].append({
                                'login': login,
                                'reason': result.get('reason'),
                            })
                        else:
                            summary[result['action']].append(login)
                except Exception as exc:  # noqa: BLE001 - isolate one row
                    _logger.warning(
                        "CBT: participant import failed for login %s: %s",
                        login, exc, exc_info=True)
                    summary['skipped'].append({
                        'login': login, 'reason': str(exc)})

            summary.update(self._archive_missing_portal_users(seen))
            _logger.info(
                "CBT participant import: created=%d updated=%d archived=%d "
                "skipped=%d", len(summary['created']), len(summary['updated']),
                len(summary['archived']), len(summary['skipped']))
            return summary

        except Exception as exc:  # noqa: BLE001 - API/config failure
            return {'status': 'error', 'msg': f'{exc}'}

    @api.model
    def create(self, vals):
        return super(CBTParticipant, self).create(vals)


class CBTCenter(models.Model):
    _name = "cbt.center"
    _description = "Admission Test Center"

    name = fields.Char(string='City Name', required=True)
    code = fields.Char(string='City Code', required=True)
    etest_id = fields.Many2one('cbt.test', tracking=True)
    type_id = fields.Many2one('cbt.test.type', tracking=True)
    test_type = fields.Selection(
        [('cbt', 'Computer Based Test'), ('pbt', 'Paper Based Test')], default="cbt")
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)

    slot_ids = fields.One2many('cbt.slot', 'center_id', 'Test Time')


class CBTSlot(models.Model):
    _name = "cbt.slot"
    _description = "Test Time"
    _rec_name = 'date'

    name = fields.Char(string='Name')
    date = fields.Date('Test Date', required=True)
    time = fields.Float(string='Test Time', required=True)
    time_to = fields.Float(string='Time To')
    duration = fields.Float('Duration (M)')
    active_time = fields.Boolean('Active', default=True)
    capacity = fields.Integer('Capacity')
    center_id = fields.Many2one('cbt.center')

    @api.depends('date', 'time')
    def _compute_display_name(self):
        for record in self:
            name = 'New'
            if record.date:
                time = '%02d:%02d' % (divmod(record.time * 60, 60))
                name = str(record.date) + ' ( ' + str(time) + ' )'
            record.display_name = name
