from dateutil.relativedelta import relativedelta
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
import requests
import json
from datetime import *


class CBTParticipant(models.Model):
    _name = 'cbt.participant'
    _description = 'Participant for the Entry Test'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(string='Participant Name', tracking=True)
    login = fields.Char(string="Participant Login", tracking=True)
    password = fields.Char(string="Participant Password", tracking=True)
    center_id = fields.Many2one('cbt.center', 'Test Center', tracking=True)
    slot_id = fields.Many2one('cbt.slot', 'Time', tracking=True)
    program = fields.Many2one('cbt.program', 'program', tracking=True)
    degree = fields.Char('Degree Code', tracking=True)
    first_prefernce = fields.Char('First Preference', tracking=True)
    cid = fields.Integer('Entery Test Card Id')
    room = fields.Char(string='Room')

    def program_assigned(self, vals):
        if not self:
            if vals['degree'] == 'PREENG' or vals['degree'] == 'PREMEDMATH' or vals['degree'] == 'ALEVEL' or vals[
                    'degree'] == 'DAEMECH' or vals['degree'] == 'DAEELEC':
                vals['program'] = self.env['cbt.program'].search(
                    [('code', '=', 'BE')]).id
            elif vals['degree'] == 'PREMED' or vals['degree'] == 'ALEVELC' or vals['degree'] == 'DAECOMP' or vals[
                    'degree'] == 'ICS':
                vals['program'] = self.env['cbt.program'].search(
                    [('code', '=', 'BSCS')]).id
            elif vals['degree'] == 'DAECIVIL':
                if vals['first_prefernce'] == 'BSCE':
                    vals['program'] = self.env['cbt.program'].search(
                        [('code', '=', 'BE')]).id
                elif vals['first_prefernce'] == 'BETCE':
                    vals['program'] = self.env['cbt.program'].search(
                        [('code', '=', 'BTECH')]).id
        else:
            if self.degree == 'PREENG' or self.degree == 'PREMEDMATH' or self.degree == 'ALEVEL' or self.degree == 'DAEMECH' or self.degree == 'DAEELEC':
                self.program = self.env['cbt.program'].search(
                    [('code', '=', 'BE')]).id
            elif self.degree == 'PREMED' or self.degree == 'ALEVELC' or self.degree == 'DAECOMP' or self.degree == 'ICS':
                self.program = self.env['cbt.program'].search(
                    [('code', '=', 'BSCS')]).id
            elif self.degree == 'DAECIVIL':
                if self.first_prefernce == 'BSCE':
                    self.program = self.env['cbt.program'].search(
                        [('code', '=', 'BE')]).id
                elif self.first_prefernce == 'BETCE':
                    self.program = self.env['cbt.program'].search(
                        [('code', '=', 'BTECH')]).id

    @api.model
    def fetch_participant(self, *args, **kwargs):
        try:

            db = self.env['ir.config_parameter'].get_param('cbt.admission_db')
            url = self.env['ir.config_parameter'].get_param(
                'cbt.admission_url')
            login = self.env['ir.config_parameter'].get_param(
                'cbt.admission_login')
            password = self.env['ir.config_parameter'].get_param(
                'cbt.admission_password')

            # raise UserError('Mohon maaf tidak bisa ..')
            if not all([db, url, login, password]):
                raise UserError('Please Fill All Credentials In Configuration')

            if all([db, url, login, password]):
                auth_url = url + '/web/session/authenticate'
                user = requests.post(auth_url,
                                     json={
                                         "jsonrpc": "2.0",
                                         "params": {
                                             "db": db,
                                             "login": login,
                                             "password": password,
                                         }
                                     }, headers={"Content-Type": "application/json"})
                if json.loads(user.content).get('error', False):
                    return {'status': 'error', 'msg': 'Authentication Failed!'}
                entry_test_card = url + '/entry/test'
                student_data_response = requests.post(entry_test_card, json={"jsonrpc": "2.0"}, headers={
                    "Content-Type": "application/json", "Cookie": f"session_id={user.cookies.get_dict().get('session_id')}",
                    "X-Openerp": user.cookies.get_dict().get('session_id')
                })

                try:

                    student_data = json.loads(json.loads(
                        student_data_response.content).get('result'))
                except Exception as e:
                    error = f'{e}'
                    raise UserError(error)
                for student in student_data:
                    cid = student.get('cid')
                    if student.get('application_no'):
                        test_date = datetime.strptime(student.get(
                            'date'), "%Y-%m-%d") if student.get('date') else False
                        data = {
                            'name': student.get('name'),
                            'cid': student.get('cid'),
                            'password': student.get('password'),
                            'login': student.get('application_no'),
                            'room': student.get('room'),
                        }
                        program_admission = json.loads(
                            student.get('program_id'))
                        if program_admission.get('code') and program_admission.get('name'):
                            program_cbt = self.env['cbt.program'].search(
                                ['|', ('code', '=', program_admission.get('code')), ('name', '=', program_admission.get('name'))], limit=1)
                            if program_cbt:
                                data.update({
                                    'program': program_cbt.id
                                })
                            if not program_cbt:
                                cbt_dis = self.env['cbt.program'].create({
                                    'name': program_admission.get('name'),
                                    'code': program_admission.get('code'),
                                })
                                data.update({
                                    'program': cbt_dis.id,
                                })

                        # slot
                        slot_admission = json.loads(student.get('slot'))
                        slot_time_from = slot_admission.get('time_from')
                        slot_time_to = slot_admission.get('time_to')
                        slot_name = slot_admission.get('name')

                        slot_cbt = self.env['cbt.slot'].search(
                            [('name', '=', slot_name), ('date', '=', test_date)], limit=1)
                        if slot_cbt:
                            data.update({
                                'slot_id': slot_cbt.id
                            })
                        if not slot_cbt:
                            slot_cbt_new = self.env['cbt.slot'].create({
                                'time': float(slot_time_from),
                                'date': test_date,
                                'name': slot_name,
                            })
                            data.update({
                                'slot_id': slot_cbt_new.id
                            })

                        candidate = self.env['cbt.participant'].sudo().search(
                            [('login', '=', student.get('application_no'))])

                        candidate_user = self.env['res.users'].sudo().search(
                            [('login', '=', student.get('application_no'))])

                        if candidate:
                            candidate_paper = self.env['cbt.student.paper'].sudo().search(
                                [('participant_id', '=', candidate.id)])
                            candidate_paper.unlink()
                            candidate.unlink()
                        # if not candidate:
                        self.env['cbt.participant'].sudo().create(data)

                        if candidate_user:
                            test_paper = self.env['cbt.paper.export'].sudo().search(
                                [('login', '=', student.get('application_no')),('cid','=',cid)],limit=1)
                            if test_paper:
                                if test_paper.end_paper or test_paper.test_date < datetime.today().date():
                                    test_paper.active = False
                                    candidate_user.unlink()
                                    candidate_user = False  
                            if not test_paper:
                                candidate_user.unlink()
                                candidate_user = False
                                # if not test_date.end_paper:

                        if not candidate_user:
                            portal_group = self.env.ref('base.group_portal')
                            self.env['res.users'].sudo().create({
                                'name': student.get('name'),
                                'password': student.get('password'),
                                'login': student.get('application_no'),
                                'active': True,
                                'email': student.get('application_no'),
                                'groups_id': [(6, 0, [portal_group.id])]
                            })

                return {'status': 'updated'}

        except Exception as e:
            return {'status': 'error', 'msg': f'{e}'}

    @api.model
    def create(self, vals):
        # self.program_assigned(vals)
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
