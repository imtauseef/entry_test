from odoo import fields, models, api, _
from odoo.exceptions import UserError
from datetime import date, timedelta
from math import ceil

class CBTSessionExport(models.Model):
    _name = 'cbt.session.export'
    _description = 'Sessions Export'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    server_id = fields.Integer(string='Server ID')
    name = fields.Char('Session')
    time = fields.Float('Session Time')
    date = fields.Date(string='Session Date', default=date.today())
    
    
class CBTPaperExport(models.Model):
    _name = 'cbt.paper.export'
    _description = 'Paper Export'
    _rec_name = 'login'

    #data = fields.Encrypted()   # ,encrypt='data'
    # encrypted_password = fields.Encrypted()

    source_export_id = fields.Char(string='Source Export ID', index=True, copy=False)
    source_student_id = fields.Char(string='Source Student ID', index=True, copy=False)
    source_paper_id = fields.Char(string='Source Paper ID', index=True, copy=False)
    source_template_paper_id = fields.Char(
        string='Source Template Paper ID', index=True, copy=False)
    source_payload_hash = fields.Char(string='Source Payload Hash', copy=False)
    batch_id = fields.Many2one(
        'cbt.paper.export.batch', string='Test Batch',
        index=True, ondelete='restrict', copy=False)
    participant_id = fields.Many2one(
        'cbt.participant', string='Portal Participant',
        index=True, ondelete='restrict', copy=False,
        help=(
            'Optional local participant link. Offline imports use the portal '
            'user and login because admin-server participants are not present here.'
        ))
    server_id = fields.Integer(string='Server ID')
    user_id = fields.Integer(
        'Portal User ID',
        help='Local res.users ID resolved by login when the allocation workbook is imported.')
    login = fields.Char(string="Application Number")
    name = fields.Char(string="Candidate Name")
    paper_name = fields.Char(string="Paper Name")
    program = fields.Char(string="Program")
    test_center = fields.Char(string="Test Center")
    test_date = fields.Date(string="Test Date")
    test_time = fields.Float(string="Start Time")
    test_duration = fields.Integer(string="Duration")
    shuffle_section = fields.Boolean('Shuffle Section',default=False)
    current_q = fields.Integer(default=1)
    time_remaining = fields.Char('Rem. Time')
    line_ids = fields.One2many('cbt.paper.line.export', 'paper_id', string="Questions")
    feedback_ids = fields.One2many(
        'cbt.paper.question.feedback', 'paper_id', string='Question Feedback')
    last_session_id = fields.Char('last Session ID')
    last_session_token = fields.Char('Last Session Token')
    session_ids = fields.One2many('cbt.paper.session', 'paper_id', 'Sessions')
    end_paper = fields.Boolean(string='End Paper', default=False)
    end_paper_time = fields.Datetime(string='Candidate Attempt End Time')
    paper_started = fields.Datetime('Candidate Attempt Time')
    is_login = fields.Boolean(string='Login Status', default=False)
    answered_q = fields.Integer('Q.Att',compute='_get_stats')
    reviewed_q = fields.Integer('Q.Rev',compute='_get_stats')
    cid = fields.Integer('Entery Test Card Id')
    active = fields.Boolean(default=True, help="Set active to false to hide  without removing it.")

    _sql_constraints = [
        ('source_export_id_uniq', 'unique(source_export_id)',
         'An allocation from this source export has already been imported.'),
    ]

    @api.depends('line_ids.answer', 'line_ids.theory_answer',
                 'line_ids.is_theory')
    def _get_stats(self):
        for rec in self:
            rec.answered_q = len(rec.line_ids.filtered(lambda l: l.is_answered))
            rec.reviewed_q = len(rec.line_ids.filtered(lambda l: l.mark_review == True))

    def clear(self):
        for rec in self:
            rec.last_session_id = ''
            rec.last_session_token = ''

    def restore(self):
        for rec in self:
            rec.end_paper = False
            rec.end_paper_time = False
            rec.time_remaining = False

    def action_start_candidate_test(self):
        self.ensure_one()
        if not self.env.user.has_group('cbt.group_cbt_admin'):
            raise UserError(_('Only CBT administrators may start a candidate paper.'))
        if not self.batch_id:
            raise UserError(_('This candidate paper is not linked to a test batch.'))
        if self.batch_id.state != 'active':
            raise UserError(_(
                'The parent test batch must be active before a candidate can start.'
            ))
        if self.paper_started:
            raise UserError(_('This candidate paper has already started.'))
        now = fields.Datetime.now()
        self.write({'paper_started': now})
        if not self.session_ids:
            self.env['cbt.paper.session'].sudo().create({
                'paper_id': self.id,
                'name': self.batch_id.name,
                'start_time': fields.Datetime.to_string(now),
            })
        elif not self.session_ids[-1].end_time:
            self.session_ids[-1].write({
                'start_time': fields.Datetime.to_string(now),
            })
        return True

    def action_finish_candidate_test(self):
        self.ensure_one()
        if not self.env.user.has_group('cbt.group_cbt_admin'):
            raise UserError(_('Only CBT administrators may finish a candidate paper.'))
        if not self.batch_id:
            raise UserError(_('This candidate paper is not linked to a test batch.'))
        if self.batch_id.state not in ('active', 'finished'):
            raise UserError(_(
                'The parent test batch must be active or finished before finishing a candidate.'
            ))
        if not self.paper_started:
            raise UserError(_('This candidate paper has not started yet.'))
        if self.end_paper:
            raise UserError(_('This candidate paper is already finished.'))
        now = fields.Datetime.now()
        self.write({
            'end_paper': True,
            'end_paper_time': now,
        })
        if self.session_ids:
            self.session_ids[-1].write({
                'end_time': fields.Datetime.to_string(now),
            })
        return True

    def _cbt_remaining_seconds(self, now=None):
        self.ensure_one()
        if not self.paper_started:
            return max(0, self.test_duration or 0) * 60
        deadline = self.paper_started + timedelta(
            minutes=self.test_duration or 0)
        remaining = (deadline - (now or fields.Datetime.now())).total_seconds()
        return max(0, ceil(remaining))

    def _cbt_expire_if_time_up(self, now=None):
        self.ensure_one()
        if self.end_paper or not self.paper_started:
            return bool(self.end_paper)
        deadline = self.paper_started + timedelta(
            minutes=self.test_duration or 0)
        if (now or fields.Datetime.now()) < deadline:
            return False
        self.write({
            'end_paper': True,
            'end_paper_time': deadline,
        })
        if self.session_ids:
            self.session_ids[-1].write({
                'end_time': fields.Datetime.to_string(deadline),
            })
        return True


class CBTPaperLineExport(models.Model):
    _name = 'cbt.paper.line.export'
    _description = 'Paper Questions Export'
    _order = 'sequence, id'

    #question = fields.Encrypted()  # ,encrypt='question'
    source_question_id = fields.Char(string='Source Question ID', index=True, copy=False)
    source_paper_id = fields.Char(string='Source Paper ID', index=True, copy=False)
    source_student_id = fields.Char(string='Source Student ID', index=True, copy=False)
    sequence = fields.Integer(string='Question Sequence', default=10, index=True)
    server_id = fields.Integer(string='Server ID', index=True)
    paper_id = fields.Many2one('cbt.paper.export', string="Paper")
    subject_id = fields.Many2one('cbt.subject.export', string="Section/Subject")
    name = fields.Html(string="Question")
    option_ids = fields.One2many('cbt.paper.line.option.export', 'question_id', string="Options")
    answer = fields.Integer('Selected Option')
    correct_answer = fields.Char(
        'Correct Answer', invisible=True, groups='cbt.group_cbt_admin')
    # answer = fields.Many2one('cbt.paper.line.option.export','Selected Option')
    answer_alphabet = fields.Char(string="Answer")
    is_theory = fields.Boolean(string='Theory Question', default=False)
    theory_answer = fields.Text(string='Theory Answer')
    uses_paragraph = fields.Boolean(
        string='Uses Paragraph Answer', compute='_compute_uses_paragraph')
    is_answered = fields.Boolean(
        string='Answered', compute='_compute_is_answered')
    answer_recorded_time = fields.Datetime('Recorded Date')
    mark_review = fields.Boolean(string='Review', default=False)
    feedback_ids = fields.One2many(
        'cbt.paper.question.feedback', 'question_id',
        string='Candidate Feedback')

    @api.depends('is_theory', 'option_ids.name')
    def _compute_uses_paragraph(self):
        for rec in self:
            rec.uses_paragraph = bool(
                rec.is_theory
                or not rec.option_ids.filtered(lambda option: option.name))

    @api.depends('is_theory', 'option_ids.name', 'answer', 'theory_answer')
    def _compute_is_answered(self):
        for rec in self:
            rec.is_answered = bool(
                (rec.theory_answer or '').strip()
                if rec.uses_paragraph else rec.answer > 0)

    

class CBTPaperLineOptionExport(models.Model):
    _name = 'cbt.paper.line.option.export'
    _description = 'Question Options Export'
    _order = 'sequence, id'

    #option = fields.Encrypted()  # ,encrypt='option'
    source_option_id = fields.Char(string='Source Option ID', index=True, copy=False)
    source_question_id = fields.Char(string='Source Question ID', index=True, copy=False)
    source_paper_id = fields.Char(string='Source Paper ID', index=True, copy=False)
    source_student_id = fields.Char(string='Source Student ID', index=True, copy=False)
    sequence = fields.Integer(string='Option Sequence', default=10, index=True)
    server_id = fields.Integer(string='Server ID')
    question_id = fields.Many2one('cbt.paper.line.export', string='Question')
    name = fields.Html(string="Choice")


class CBTPaperSession(models.Model):
    _name = 'cbt.paper.session'
    _description = 'Paper Sessions'

    #session = fields.Encrypted()  # ,encrypt='session'
    paper_id = fields.Many2one('cbt.paper.export', string="Paper")
    name = fields.Char(string="Session Name")
    start_time = fields.Char(string="Start Time")
    end_time = fields.Char(string="End Time")
    

class OdoocmsCBTSubjectExport(models.Model):
    _name = 'cbt.subject.export'
    _description = 'Subjects Export'

    #subject = fields.Encrypted()  # ,encrypt='subject'
    server_id = fields.Integer('Server ID')
    paper_id = fields.Many2one('cbt.paper.export','Paper')
    sequence_no = fields.Integer(string='Sequence')
    name = fields.Char(string="Subject/Topic")
    question_ids = fields.One2many('cbt.paper.line.export', 'subject_id','Questions')


class OdoocmsCBTInstructionExport(models.Model):
    _name = 'cbt.instruction.export'
    _description = 'Instructions Export'

    name = fields.Char('Name')
    instruction = fields.Html(string="Paper Guide lines / Instructions")


 