# -*- coding: utf-8 -*-
from odoo import fields, models, api, _
from odoo.exceptions import UserError, ValidationError
from datetime import datetime, date
import pdb


class CBTprogram(models.Model):
    _name = 'cbt.program'
    _description = 'program/Study Programs'

    name = fields.Char(string='Program', required=True)
    code = fields.Char(string='Code', required=True)
    sequence = fields.Integer(default=10)
    description = fields.Char(string='Description')
    # paper_generator_id = fields.Many2one('cbt.paper.generator', string='Paper Generator')

    _sql_constraints = [
        ('name_uniq', 'unique(name)', "program name already exists!"),
        ('code_uniq', 'unique(code)', "program code already exists!"),
    ]


class CBTSubject(models.Model):
    _name = 'cbt.subject'
    _description = 'Subject'

    name = fields.Char(string='Course Name')
    code = fields.Char(string='Course Code')
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    topic_count = fields.Integer(
        compute='_compute_topics', string='Number of Topics')
    sub_topic_count = fields.Integer(
        compute='_compute_sub_topics', string='Number of Sub Topics')

    topic_ids = fields.One2many(
        'cbt.subject.topic', 'subject_id', string="Topics")
    role_ids = fields.One2many(
        'cbt.employee.role', 'subject_id', string='Faculty')

    # @api.onchange('topic_ids')
    def _compute_topics(self):
        for rec in self:
            subjects = self.env['cbt.subject.topic'].search([
                ('subject_id', '=', rec.id)])
            rec.topic_count = len(subjects)

    def _compute_sub_topics(self):
        for rec in self:
            sub_topics = self.env['cbt.subject.subtopic'].search([
                ('subject_id', '=', rec.id)])
            rec.sub_topic_count = len(sub_topics)


class CBTSubjectTopic(models.Model):
    _name = 'cbt.subject.topic'
    _description = 'Topics'

    subject_id = fields.Many2one(
        'cbt.subject', 'Subject', ondelete='cascade', required=True)
    name = fields.Char(string='Topic')
    code = fields.Char(string='Code')
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    sub_topic_count = fields.Integer(
        compute='_compute_sub_topics', string='Number of Sub Topics')

    sub_topic_ids = fields.One2many(
        'cbt.subject.subtopic', 'topic_id', string=" Sub Topics")
    role_ids = fields.One2many(
        'cbt.employee.role', 'topic_id', string='Faculty')

    def _compute_sub_topics(self):
        for rec in self:
            sub_topics = self.env['cbt.subject.subtopic'].search([
                ('topic_id', '=', rec.id)])
            rec.sub_topic_count = len(sub_topics)


class CBTSubjectSubTopic(models.Model):
    _name = 'cbt.subject.subtopic'
    _description = 'Sub Topic'

    name = fields.Char(string='Sub Topic', required=True)
    code = fields.Char(string='Code')
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)

    topic_id = fields.Many2one(
        'cbt.subject.topic', string="Topic", ondelete='cascade')
    subject_id = fields.Many2one(
        'cbt.subject', string="Subject", related='topic_id.subject_id', store=True)
    role_ids = fields.One2many(
        'cbt.employee.role', 'subtopic_id', string='Faculty')


class CBTEmployeeRole(models.Model):
    _name = 'cbt.employee.role'
    _description = 'Employee Role'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    employee_id = fields.Many2one(
        'hr.employee', "Faculty", required="True", tracking=True)
    subject_id = fields.Many2one(
        'cbt.subject', "Subject", required="True", tracking=True)
    topic_id = fields.Many2one('cbt.subject.topic', "Topic", tracking=True)
    subtopic_id = fields.Many2one(
        'cbt.subject.subtopic', "Sub Topic", tracking=True)
    create_access = fields.Boolean(
        'Create Access', default=True, tracking=True)
    review_access = fields.Boolean(
        'Review Access', default=True, tracking=True)

    @api.depends('employee_id', 'subject_id')
    def _compute_display_name(self):
        for rec in self:
            name = 'New'
            if rec.employee_id and rec.subject_id:
                name = rec.employee_id.name + ' - ' + rec.subject_id.name
            rec.display_name = name

    def _sync_groups_for_users(self, users):
        creator = self.env.ref(
            'cbt.group_cbt_creator', raise_if_not_found=False)
        reviewer = self.env.ref(
            'cbt.group_cbt_reviewer', raise_if_not_found=False)
        if not creator or not reviewer:
            return
        Role = self.env['cbt.employee.role'].sudo()
        for user in users.sudo():
            if not user:
                continue
            roles = Role.search([('employee_id.user_id', '=', user.id)])
            if any(roles.mapped('create_access')):
                creator.sudo().write({'users': [(4, user.id)]})
            else:
                creator.sudo().write({'users': [(3, user.id)]})
            if any(roles.mapped('review_access')):
                reviewer.sudo().write({'users': [(4, user.id)]})
            else:
                reviewer.sudo().write({'users': [(3, user.id)]})

    def _sync_role_groups(self):
        self._sync_groups_for_users(self.mapped('employee_id.user_id'))

    @api.model
    def _sync_all_role_groups(self):
        self._sync_groups_for_users(
            self.search([]).mapped('employee_id.user_id'))

    @api.model
    def create(self, vals):
        record = super().create(vals)
        record._sync_role_groups()
        return record

    def write(self, vals):
        result = super().write(vals)
        self._sync_role_groups()
        return result

    def unlink(self):
        users = self.mapped('employee_id.user_id')
        result = super().unlink()
        self._sync_groups_for_users(users)
        return result


class CBTTasks(models.Model):
    _name = 'cbt.jobs'
    _description = 'Jobs/Tasks Setup'

    name = fields.Char('Job Name')
    description = fields.Text('Description')
    date = fields.Datetime(string='Date Created', default=datetime.now())
    from_time = fields.Float(string='Start Time')
    to_time = fields.Float(string='End Time')
    state = fields.Selection([
        ('inprogress', 'Inprogress'),
        ('processed', 'Processed'),
    ], string='Status')
    failure = fields.Text('Exception')
    clear = fields.Char('Clear')
    active = fields.Boolean('Active', default=True)


class CBTQuestionType(models.Model):
    _name = 'cbt.question.type'
    _description = 'Question Type'

    name = fields.Char('Question Type')
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    color = fields.Integer(string='Color Index')
    code = fields.Char(string="Code")
    description = fields.Char(string='Description')


class CBTQuestionSkill(models.Model):
    _name = 'cbt.question.skill'
    _description = 'Question Skill'

    name = fields.Char('Skill')
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    color = fields.Integer(string='Color Index')
    description = fields.Char(string='Description')


class CBTQuestionDifficultySetup(models.Model):
    _name = 'cbt.question.difficulty.level'
    _description = 'Question Difficulty'

    name = fields.Char(string='Difficulty Level')
    code = fields.Integer(string='Code')
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    color = fields.Integer(string='Color Index')
    description = fields.Char(string='Description')


class CBTQuestionTime(models.Model):
    _name = 'cbt.question.time'
    _description = 'Question Time'

    name = fields.Char(string='Time (Seconds)')
    code = fields.Integer(string='Code')
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    description = fields.Char(string='Description')


class CBTTest(models.Model):
    _name = 'cbt.test'
    _description = 'Entry Test'

    name = fields.Char(string='Entry Test Name')
    code = fields.Integer(string='Code')
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    description = fields.Char(string='Description')


class CBTTestType(models.Model):
    _name = 'cbt.test.type'
    _description = 'Test Type'

    name = fields.Char(string='Test Type')
    code = fields.Integer(string='Code')
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    color = fields.Integer(string='Color Index')
    description = fields.Char(string='Description')


class CBTSession(models.Model):
    _name = 'cbt.session'
    _description = 'Sessions'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    etest_id = fields.Many2one('cbt.test', required=True, tracking=True)
    type_id = fields.Many2one('cbt.test.type', required=True, tracking=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    line_ids = fields.One2many('cbt.session.line', 'session_id', string='Sessions list',
                               required=True, tracking=True)

    @api.depends('etest_id', 'type_id')
    def _compute_display_name(self):
        for record in self:
            name = 'New'
            if record.etest_id and record.type_id:
                name = record.type_id.name
            record.display_name = name


class CBTSessionLine(models.Model):
    _name = 'cbt.session.line'
    _description = 'Sessions list'

    session_no = fields.Integer(string='Session No.')
    time = fields.Float('Session Time')
    date = fields.Date(string='Session Date', default=date.today())
    session_id = fields.Many2one('cbt.session')

    @api.depends('date', 'time')
    def _compute_display_name(self):
        for record in self:
            name = 'New'
            if record.date:
                time = '%02d:%02d' % (divmod(record.time * 60, 60))
                name = str(record.date) + ' ( ' + str(time) + ' )'
            record.display_name = name


class CBTprogramCourses(models.Model):
    _name = 'cbt.program.courses'
    _description = 'Allocation of Subject to Study Program'

    etest_id = fields.Many2one('cbt.test', 'Entry Test')
    type_id = fields.Many2one('cbt.test.type', 'Test Type')
    program_id = fields.Many2one('cbt.program', 'program')
    subject_ids = fields.Many2many('cbt.subject', 'program_course_rel',
                                   'program_id', 'subject_id', string="program Courses")


class CBTQuestionRepeatTrack(models.Model):
    _name = 'cbt.question.repeat.track'
    _description = 'Track Quesions repeat'

    paper_id = fields.Many2one('cbt.paper', 'Paper ID', required=True)
    date = fields.Datetime(string='Date', default=datetime.now())
    question_id = fields.Many2one('cbt.mcqs', 'Question', required=True)


class CBTMCQS(models.Model):
    _name = 'cbt.mcqs'
    _description = 'CBT Question'
    _order = "subject_id desc"
    _inherit = ['mail.thread', 'mail.activity.mixin']

    def _get_default_subjects(self):
        subject_list = []
        employees = self.env['cbt.employee.role'].search([
            ('create_access', '=', True), ('employee_id.user_id', '=', self.env.user.id)])
        if employees:
            for employee in employees:
                for sub_id in employee.subject_id:
                    subject_list.append(sub_id.id)
        return [('id', 'in', subject_list)]

    @api.model
    def _get_generation_pool(self, domain=None):
        """Single source of truth for questions eligible for paper generation.

        Always returns approved, non-reserve questions matching ``domain``.
        Any future change to the generation policy (reserve flag, states, ...)
        must be made here only.
        """
        pool_domain = list(domain or [])
        pool_domain += [('state', '=', 'approved'), ('is_reserve', '=', False)]
        return self.search(pool_domain)

    subject_id = fields.Many2one(
        'cbt.subject', 'Subject', required=True, domain=_get_default_subjects)
    topic_id = fields.Many2one('cbt.subject.topic', 'Topic', required=True)
    stopic_id = fields.Many2one(
        'cbt.subject.subtopic', 'Sub Topic', required=True)
    type_id = fields.Many2one('cbt.question.type', required=True)
    skill_id = fields.Many2one('cbt.question.skill', required=True)
    difficulty_level_id = fields.Many2one(
        'cbt.question.difficulty.level', required=True)
    time_id = fields.Many2one('cbt.question.time', required=True)
    question = fields.Html(string='Question', required=True)
    is_reserve = fields.Boolean(
        string='Reserve Question', default=False, index=True, tracking=True,
        help="Reserve questions are kept out of paper generation and out of "
             "the replacement pool. A question is moved here when it is "
             "replaced on a paper.")
    option_quantity = fields.Selection([
        ('2', '2'),
        ('3', '3'),
        ('4', '4'),
        ('5', '5'),
        ('6', '6'),
    ], string='Option Count', default='4')
    ans1 = fields.Html(string='Option 1', required=True)
    ans1_correct = fields.Boolean(
        string='Option 1 is Correct Answer?', tracking=True)
    ans2 = fields.Html(string='Option 2', required=True)
    ans2_correct = fields.Boolean(
        string='Option 2 is Correct Answer?', tracking=True)
    ans3 = fields.Html(string='Option 3', required=True)
    ans3_correct = fields.Boolean(
        string='Option 3 is Correct Answer?', tracking=True)
    ans4 = fields.Html(string='Option 4', required=True)
    ans4_correct = fields.Boolean(
        string='Option 4 is Correct Answer?', tracking=True)
    ans5_correct = fields.Boolean(
        string='Option 5 is Correct Answer?', tracking=True)
    ans5 = fields.Html(string='Option 5', )
    ans6_correct = fields.Boolean(
        string='Option 6 is Correct Answer?', tracking=True)
    ans6 = fields.Html(string='Option 6', )
    current_user = fields.Many2one(
        'res.users', 'Created By', default=lambda self: self.env.user)
    reviewed_user = fields.Many2one('res.users', 'Reviewed By', readonly=True)
    reviewer_remarks = fields.Text(
        string='Reviewer Remarks', tracking=True)
    state = fields.Selection([
        ('draft', 'Draft'), ('submitted', 'Submitted'),
        ('approved', 'Approved'), ('cancel', 'Cancel')
    ], 'Status', default='draft')
    paper_id = fields.Many2one('cbt.paper.criteria', 'Paper ID')
    question_repeat_ids = fields.One2many(
        'cbt.question.repeat.track', 'question_id', "Questions Track")
    can_submit = fields.Boolean(
        string='Can Submit', compute='_compute_can_submit')
    can_review = fields.Boolean(
        string='Can Review', compute='_compute_can_review')

    @api.depends('current_user', 'state')
    def _compute_can_submit(self):
        user = self.env.user
        for rec in self:
            rec.can_submit = bool(
                rec.state == 'draft'
                and rec.current_user.id == user.id
            )

    @api.depends('current_user', 'state', 'subject_id')
    def _compute_can_review(self):
        user = self.env.user
        for rec in self:
            is_reviewer = bool(self.env['cbt.employee.role'].search_count([
                ('review_access', '=', True),
                ('employee_id.user_id', '=', user.id),
                ('subject_id', '=', rec.subject_id.id),
            ]))
            rec.can_review = bool(
                rec.state == 'submitted'
                and rec.current_user.id != user.id
                and is_reviewer
            )

    @api.model
    def create(self, vals):
        if not (self.env.su or self.env.user.has_group('cbt.group_cbt_admin')):
            subject_id = vals.get('subject_id')
            allowed = bool(self.env['cbt.employee.role'].search_count([
                ('create_access', '=', True),
                ('employee_id.user_id', '=', self.env.user.id),
                ('subject_id', '=', subject_id),
            ]))
            if not allowed:
                raise UserError(_(
                    "You are not allowed to create questions. Only users with "
                    "Create Access for this subject can create questions."))
        return super().create(vals)

    def _check_reserve_toggle_access(self):
        """Validate that the current user may toggle ``is_reserve``.

        * users with Create or Review access for the subject may toggle it on
          questions that are not approved yet;
        * only reviewers (Review access) or admins may toggle it once the
          question has been approved.
        """
        if self.env.su or self.env.user.has_group('cbt.group_cbt_admin'):
            return
        for rec in self:
            roles = self.env['cbt.employee.role'].search([
                ('employee_id.user_id', '=', self.env.user.id),
                ('subject_id', '=', rec.subject_id.id),
            ])
            has_create = any(roles.mapped('create_access'))
            has_review = any(roles.mapped('review_access'))
            if rec.state == 'approved':
                if not has_review:
                    raise UserError(_(
                        "Only reviewers or administrators can change the "
                        "Reserve flag on an approved question."))
            elif not (has_create or has_review):
                raise UserError(_(
                    "You need Create or Review access for this subject to "
                    "change the Reserve flag."))

    def write(self, vals):
        if 'is_reserve' in vals:
            self._check_reserve_toggle_access()
        return super().write(vals)

    def action_replace_question(self):
        """Line-level button entry point shown on draft paper question lists.

        The button is rendered on ``cbt.mcqs`` rows embedded in the paper form,
        so the target paper is passed through the button context.
        """
        self.ensure_one()
        paper_id = self.env.context.get('cbt_paper_id')
        if not paper_id:
            raise UserError(_(
                "Please use the Replace button from within a draft paper."))
        return self.env['cbt.paper'].browse(paper_id).action_replace_question(
            self.id)

    def get_filtered_record(self):
        subject_list = []
        record_ids = []
        employees = self.env['cbt.employee.role'].search([
            ('review_access', '=', True), ('employee_id.user_id', '=', self.env.user.id)])
        if employees:
            for employee in employees:
                for sub_id in employee.subject_id:
                    subject_list.append(sub_id.id)
        review_questions = self.env['cbt.mcqs'].search([
            ('current_user', '!=', self.env.user.id), ('subject_id', 'in', subject_list), ('state', '=', 'submitted')])
        for qes in review_questions:
            record_ids.append(qes.id)
        treeview_id = self.env.ref('cbt.cbt_question_review_tree').id
        formview_id = self.env.ref('cbt.cbt_question_review_form').id
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'cbt.mcqs',
            
            'name': 'Review Questions',
            'view_mode': 'tree,form',
            'views': [(treeview_id, 'tree'), (formview_id, 'form')],
            'domain': [('id', 'in', record_ids)],
            'context': {'cbt_hide_action_menu': True},
        }

    @api.onchange('ans1_correct', 'ans2_correct', 'ans3_correct', 'ans4_correct', 'ans5_correct', 'ans5_correct')
    def correct_option(self):
        if self.ans1_correct:
            self.ans2_correct = False
            self.ans3_correct = False
            self.ans4_correct = False
            self.ans5_correct = False
            self.ans6_correct = False
        elif self.ans2_correct:
            self.ans1_correct = False
            self.ans3_correct = False
            self.ans4_correct = False
            self.ans5_correct = False
            self.ans6_correct = False
        elif self.ans3_correct:
            self.ans1_correct = False
            self.ans2_correct = False
            self.ans4_correct = False
            self.ans5_correct = False
            self.ans6_correct = False
        elif self.ans4_correct:
            self.ans1_correct = False
            self.ans2_correct = False
            self.ans3_correct = False
            self.ans5_correct = False
            self.ans6_correct = False
        elif self.ans5_correct:
            self.ans1_correct = False
            self.ans2_correct = False
            self.ans3_correct = False
            self.ans4_correct = False
            self.ans6_correct = False
        elif self.ans6_correct:
            self.ans1_correct = False
            self.ans2_correct = False
            self.ans3_correct = False
            self.ans4_correct = False
            self.ans5_correct = False

    @api.depends('subject_id')
    def _compute_display_name(self):
        for record in self:
            name = 'New'
            if record.subject_id:
                name = record.subject_id.name + ' - Question'
            record.display_name = name

    @api.onchange('subject_id')
    def _get_topic(self):
        topic_list = []
        if self.subject_id:
            topics = self.env['cbt.subject.topic'].search([
                ('role_ids.employee_id.user_id', '=', self.current_user.id), ('subject_id', '=', self.subject_id.id)])
            if topics:
                for topic in topics:
                    topic_list.append(topic.id)
                return {'domain': {'topic_id': [('id', 'in', topic_list)]}}
            else:
                topics_else = self.env['cbt.subject.topic'].search(
                    [('subject_id', '=', self.subject_id.id)])
                for topic in topics_else:
                    topic_list.append(topic.id)
                return {'domain': {'topic_id': [('id', 'in', topic_list)]}}
        else:
            return {'domain': {'topic_id': [('id', 'in', topic_list)]}}

    @api.onchange('topic_id')
    def _get_subtopic(self):
        subtopic_list = []
        if self.subject_id and self.topic_id:
            subtopics = self.env['cbt.subject.subtopic'].search([
                ('role_ids.employee_id.user_id', '=', self.current_user.id), ('topic_id', '=', self.topic_id.id)])
            if subtopics:
                for subtopic in subtopics:
                    subtopic_list.append(subtopic.id)
                return {'domain': {'stopic_id': [('id', 'in', subtopic_list)]}}
            else:
                subtopics_else = self.env['cbt.subject.subtopic'].search(
                    [('topic_id', '=', self.topic_id.id)])
                for subtopic in subtopics_else:
                    subtopic_list.append(subtopic.id)
                return {'domain': {'stopic_id': [('id', 'in', subtopic_list)]}}
        else:
            return {'domain': {'stopic_id': [('id', 'in', subtopic_list)]}}

    def _action_question_list(self):
        return {
            'type': 'ir.actions.act_window',
            'name': _('Questions'),
            'res_model': 'cbt.mcqs',
            'view_mode': 'tree,form',
            'domain': [('current_user', '=', self.env.user.id),
                       ('state', '!=', 'submitted')],
            'target': 'current',
        }

    def action_submit(self):
        for rec in self:
            if rec.state != 'draft':
                raise UserError(
                    _("Only draft questions can be submitted."))
            if rec.current_user.id != self.env.user.id:
                raise UserError(
                    _("You can only submit questions created by you."))
        self.write({'state': 'submitted'})
        return self._action_question_list()

    def action_submit_all(self):
        self.env['cbt.mcqs'].search([
            ('current_user', '=', self.env.user.id),
            ('state', '=', 'draft'),
        ]).write({'state': 'submitted'})
        return self._action_question_list()

    def action_submit_selected(self):
        ids = self.env.context.get('active_ids') or self.ids
        records = self.browse(ids).filtered(
            lambda r: r.state == 'draft'
            and r.current_user.id == self.env.user.id)
        records.write({'state': 'submitted'})
        return self._action_question_list()

    def action_request_correction(self):
        for rec in self:
            if not rec.can_review:
                raise UserError(
                    _("You are not allowed to review this question."))
            if not rec.reviewer_remarks:
                raise UserError(
                    _("Please mention the reason / remarks before returning "
                      "the question for correction."))
            rec.state = 'draft'
            rec.reviewed_user = self.env.user
            rec.message_post(body=_(
                "Question returned for correction by %s. Remarks: %s") % (
                self.env.user.name, rec.reviewer_remarks))
        return self.get_filtered_record()

    def approve_question(self):
        for rec in self:
            if not rec.can_review:
                raise UserError(
                    _("You are not allowed to review this question."))
            rec.state = 'approved'
            rec.reviewed_user = self.env.user
            rec.message_post(body=_("Question approved by %s.") % (
                self.env.user.name))

    def reject_question(self):
        for rec in self:
            if not rec.can_review:
                raise UserError(
                    _("You are not allowed to review this question."))
            if not rec.reviewer_remarks:
                raise UserError(
                    _("Please mention the reason / remarks for rejection."))
            rec.state = 'draft'
            rec.reviewed_user = self.env.user
            rec.message_post(body=_(
                "Question rejected and returned to the developer by %s. "
                "Remarks: %s") % (
                self.env.user.name, rec.reviewer_remarks))
        return self.get_filtered_record()


class CBTQuestionattempdemo(models.Model):
    _name = 'cbt.question.attempt.demo'
    _description = 'Questions Attempt'

    paper_id_portal = fields.Integer('Paper ID', required=True)
    question_server_id = fields.Integer(string='Question Server ID')
    answer = fields.Char("Answer")


class CBTPaperattempdemo(models.Model):
    _name = 'cbt.paper.attempt.demo'
    _description = 'Paper Attempt'

    paper_id_portal = fields.Integer('Paper ID', required=True)
    paper_server_id = fields.Integer(string='paper Server ID')
    date = fields.Datetime(string='Date Created')





class CBTPaperSession(models.Model):
    _name = 'cbt.paper.session'
    _description = 'Paper Sessions'

    #session = fields.Encrypted()  # ,encrypt='session'
    paper_id = fields.Many2one('cbt.paper.export', string="Paper")
    name = fields.Char(string="Session Name")
    start_time = fields.Char(string="Start Time")
    end_time = fields.Char(string="End Time")
    