# -*- coding: utf-8 -*-
import json
from collections import defaultdict

from odoo import fields, models, api, _
from odoo.exceptions import AccessError, UserError, ValidationError
from datetime import datetime, date
import pdb
from markupsafe import Markup
from odoo.tools import html_sanitize


class CBTprogram(models.Model):
    _name = 'cbt.program'
    _description = 'program/Study Programs'

    name = fields.Char(string='Program', required=True)
    code = fields.Char(string='Code', required=True)
    old_id = fields.Integer(
        string='Old ID', index=True, copy=False,
        help='Record ID from the legacy system, used for data migration.')
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
    old_id = fields.Integer(
        string='Old ID', index=True, copy=False,
        help='Record ID from the legacy system, used for data migration.')
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
    old_id = fields.Integer(
        string='Old ID', index=True, copy=False,
        help='Record ID from the legacy system, used for data migration.')
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
    old_id = fields.Integer(
        string='Old ID', index=True, copy=False,
        help='Record ID from the legacy system, used for data migration.')
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

    @api.constrains('subject_id', 'topic_id', 'subtopic_id')
    def _check_subject_scope(self):
        for rec in self:
            if rec.topic_id and rec.topic_id.subject_id != rec.subject_id:
                raise ValidationError(_(
                    "The selected topic does not belong to the selected subject."))
            if rec.subtopic_id:
                if not rec.topic_id:
                    raise ValidationError(_(
                        "Select a topic before selecting a sub topic."))
                if rec.subtopic_id.topic_id != rec.topic_id:
                    raise ValidationError(_(
                        "The selected sub topic does not belong to the selected topic."))
                if rec.subtopic_id.subject_id != rec.subject_id:
                    raise ValidationError(_(
                        "The selected sub topic does not belong to the selected subject."))

    @api.onchange('subject_id')
    def _onchange_role_subject(self):
        self.topic_id = False
        self.subtopic_id = False

    @api.onchange('topic_id')
    def _onchange_role_topic(self):
        self.subtopic_id = False

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
    def _cleanup_legacy_faculty_rules(self):
        """Drop the broad rules shipped before subject-scoped access."""
        for xmlid in (
            'cbt.partner_view_rule_faculty_submitted',
            'cbt.paper_replacement_log_rule_faculty',
        ):
            rule = self.env.ref(xmlid, raise_if_not_found=False)
            if rule:
                rule.sudo().unlink()

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
    old_id = fields.Integer(
        string='Old ID', index=True, copy=False,
        help='Record ID from the legacy system, used for data migration.')
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    color = fields.Integer(string='Color Index')
    code = fields.Char(string="Code")
    description = fields.Char(string='Description')
    is_theory = fields.Boolean(
        string='Theory / Descriptive',
        help="Enable for question types that should be answered as a "
             "paragraph instead of multiple-choice options. A type whose "
             "name or code contains 'theory' is treated as descriptive "
             "automatically.")


class CBTQuestionSkill(models.Model):
    _name = 'cbt.question.skill'
    _description = 'Question Skill'

    name = fields.Char('Skill')
    old_id = fields.Integer(
        string='Old ID', index=True, copy=False,
        help='Record ID from the legacy system, used for data migration.')
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    color = fields.Integer(string='Color Index')
    description = fields.Char(string='Description')


class CBTQuestionDifficultySetup(models.Model):
    _name = 'cbt.question.difficulty.level'
    _description = 'Question Difficulty'

    name = fields.Char(string='Difficulty Level')
    old_id = fields.Integer(
        string='Old ID', index=True, copy=False,
        help='Record ID from the legacy system, used for data migration.')
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
        if self.env.su or self.env.user.has_group('cbt.group_cbt_admin'):
            return []
        employees = self.env['cbt.employee.role'].search([
            ('create_access', '=', True),
            ('employee_id.user_id', '=', self.env.user.id),
        ])
        return [('id', 'in', employees.mapped('subject_id').ids)]

    @api.model
    def _get_generation_pool(self, domain=None):
        """Single source of truth for questions eligible for paper generation.

        Always returns approved, non-reserve, non-suspended questions matching
        ``domain``. Any future change to the generation policy (reserve flag,
        suspension, states, ...) must be made here only.
        """
        pool_domain = list(domain or [])
        pool_domain += [
            ('state', '=', 'approved'),
            ('is_reserve', '=', False),
            ('is_suspended', '=', False),
        ]
        return self.search(pool_domain)

    def _cbt_faculty_subject_roles(self, subject_id, permission=None):
        domain = [
            ('employee_id.user_id', '=', self.env.user.id),
            ('subject_id', '=', subject_id),
        ]
        if permission:
            domain.append((permission, '=', True))
        return self.env['cbt.employee.role'].search(domain)

    def _cbt_has_review_access(self, subject_id):
        return bool(self._cbt_faculty_subject_roles(
            subject_id, 'review_access'))

    @api.model
    def _cbt_is_theory_type(self, type_id):
        """Return whether a question type is answered as a paragraph."""
        question_type = self.env['cbt.question.type'].browse(type_id) \
            if type_id else self.env['cbt.question.type']
        if not question_type:
            return False
        label = ' '.join(filter(None, [
            question_type.name, question_type.code])).lower()
        return bool(question_type.is_theory or 'theory' in label)

    def _cbt_check_question_scope(self, subject_id, topic_id=False,
                                  stopic_id=False):
        """Enforce the faculty role boundary for writes done over RPC."""
        if self.env.su or self.env.user.has_group('cbt.group_cbt_admin'):
            return
        roles = self._cbt_faculty_subject_roles(subject_id, 'create_access')
        if not roles:
            raise UserError(_(
                "You do not have create access for this subject."))
        topic = (self.env['cbt.subject.topic'].browse(topic_id)
                 if topic_id else self.env['cbt.subject.topic'])
        if topic and topic.subject_id.id != subject_id:
            raise UserError(_(
                "The selected topic does not belong to the selected subject."))
        if topic_id and not any(
                not role.topic_id or role.topic_id.id == topic_id
                for role in roles):
            raise UserError(_(
                "You can only use topics assigned to you for this subject."))
        if stopic_id:
            if not topic_id:
                raise UserError(_(
                    "Select a topic before selecting a sub topic."))
            subtopic = self.env['cbt.subject.subtopic'].browse(stopic_id)
            if subtopic.topic_id.id != topic_id:
                raise UserError(_(
                    "The selected sub topic does not belong to the selected "
                    "topic."))
            if subtopic.subject_id.id != subject_id:
                raise UserError(_(
                    "The selected sub topic does not belong to the selected "
                    "subject."))
            if not any(
                    (not role.topic_id or role.topic_id.id == topic_id)
                    and (not role.subtopic_id
                         or role.subtopic_id.id == stopic_id)
                    for role in roles):
                raise UserError(_(
                    "You can only use sub topics assigned to you for this "
                    "subject."))

    def _cbt_check_state_transition(self, target_state):
        user = self.env.user
        for rec in self:
            if rec.state == target_state:
                continue
            if rec.state == 'draft' and target_state == 'submitted':
                if rec.current_user.id != user.id:
                    raise UserError(_(
                        "You can only submit questions created by you."))
            elif (rec.state == 'submitted'
                  and target_state in ('approved', 'draft', 'cancel')):
                if rec.current_user.id == user.id:
                    raise UserError(_(
                        "You cannot review or withdraw your own submitted "
                        "question."))
                if not self._cbt_has_review_access(rec.subject_id.id):
                    raise UserError(_(
                        "You need review access for this subject to review "
                        "questions."))
            else:
                raise UserError(_(
                    "You are not allowed to change the question status from "
                    "%(old)s to %(new)s.") % {
                        'old': rec.state,
                        'new': target_state,
                    })

    subject_id = fields.Many2one(
        'cbt.subject', 'Subject', required=True, tracking=True,
        domain=_get_default_subjects)
    old_id = fields.Integer(
        string='Old ID', index=True, copy=False,
        help='Record ID from the legacy system, used for data migration.')
    topic_id = fields.Many2one(
        'cbt.subject.topic', 'Topic', required=True, tracking=True)
    stopic_id = fields.Many2one(
        'cbt.subject.subtopic', 'Sub Topic', required=True, tracking=True)
    type_id = fields.Many2one(
        'cbt.question.type', required=True, tracking=True)
    is_theory = fields.Boolean(
        string='Theory Question', compute='_compute_is_theory',
        help="Theory questions are answered as a paragraph in the portal "
             "and do not use multiple-choice options.")
    skill_id = fields.Many2one(
        'cbt.question.skill', required=True, tracking=True)
    difficulty_level_id = fields.Many2one(
        'cbt.question.difficulty.level', required=True, tracking=True)
    time_id = fields.Many2one(
        'cbt.question.time', required=True, tracking=True)
    question = fields.Html(string='Question', required=True, tracking=True)
    is_reserve = fields.Boolean(
        string='Reserve Question', default=False, index=True, tracking=True,
        help="Reserve questions are kept out of paper generation and out of "
             "the replacement pool. A question is moved here when it is "
             "replaced on a paper.")
    is_suspended = fields.Boolean(
        string='Suspended / Dormant', default=False, index=True,
        tracking=True, copy=False,
        help="Suspended questions stay in the question bank but are excluded "
             "from paper generation until their suspension period ends.")
    suspension_reason = fields.Text(
        string='Suspension Reason', tracking=True, copy=False)
    suspended_from = fields.Datetime(
        string='Suspended From', tracking=True, copy=False)
    suspended_until = fields.Datetime(
        string='Suspended Until', tracking=True, copy=False)
    suspended_by = fields.Many2one(
        'res.users', string='Suspended By', readonly=True, tracking=True,
        copy=False)
    option_quantity = fields.Selection([
        ('2', '2'),
        ('3', '3'),
        ('4', '4'),
        ('5', '5'),
        ('6', '6'),
    ], string='Number of Options', default='4', required=True,
        tracking=True,
        help="Select how many answer options this question should have. "
             "Only the selected number of options will be shown and used.")
    ans1 = fields.Html(string='Option 1', tracking=True)
    ans1_correct = fields.Boolean(
        string='Option 1 is Correct Answer?', tracking=True)
    ans2 = fields.Html(string='Option 2', tracking=True)
    ans2_correct = fields.Boolean(
        string='Option 2 is Correct Answer?', tracking=True)
    ans3 = fields.Html(string='Option 3', tracking=True)
    ans3_correct = fields.Boolean(
        string='Option 3 is Correct Answer?', tracking=True)
    ans4 = fields.Html(string='Option 4', tracking=True)
    ans4_correct = fields.Boolean(
        string='Option 4 is Correct Answer?', tracking=True)
    ans5_correct = fields.Boolean(
        string='Option 5 is Correct Answer?', tracking=True)
    ans5 = fields.Html(string='Option 5', tracking=True)
    ans6_correct = fields.Boolean(
        string='Option 6 is Correct Answer?', tracking=True)
    ans6 = fields.Html(string='Option 6', tracking=True)
    current_user = fields.Many2one(
        'res.users', 'Created By', default=lambda self: self.env.user,
        tracking=True)
    reviewed_user = fields.Many2one(
        'res.users', 'Reviewed By', readonly=True, tracking=True)
    reviewer_remarks = fields.Text(
        string='Reviewer Remarks', tracking=True)
    state = fields.Selection([
        ('draft', 'Draft'), ('submitted', 'Under Review'),
        ('approved', 'Approved'), ('cancel', 'Cancel')
    ], 'Status', default='draft', tracking=True)
    paper_id = fields.Many2one(
        'cbt.paper.criteria', 'Paper ID', tracking=True)
    question_repeat_ids = fields.One2many(
        'cbt.question.repeat.track', 'question_id', "Questions Track")
    feedback_ids = fields.One2many(
        'cbt.mcqs.feedback', 'question_id', string='Candidate Feedback',
        readonly=True, groups='cbt.group_cbt_admin')
    audit_log_ids = fields.One2many(
        'cbt.mcqs.audit.log', 'question_id', string='Audit Log',
        readonly=True)
    can_submit = fields.Boolean(
        string='Can Submit', compute='_compute_can_submit')
    can_review = fields.Boolean(
        string='Can Review', compute='_compute_can_review')
    can_suspend = fields.Boolean(
        string='Can Suspend', compute='_compute_can_suspend')
    question_health_html = fields.Html(
        string='Question Health', compute='_compute_question_health_html',
        sanitize=True, readonly=True,
        groups='cbt.group_cbt_reviewer,cbt.group_cbt_admin',
        help='Live counts from completed candidate papers for this question.')

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

    @api.depends('type_id', 'type_id.name', 'type_id.code',
                 'type_id.is_theory')
    def _compute_is_theory(self):
        for rec in self:
            rec.is_theory = rec._cbt_is_theory_type(rec.type_id.id)

    @staticmethod
    def _cbt_question_health_option_classes(option_counts, correct_index):
        """Return highlight classes using the required correct-vs-wrong rules."""
        classes = {index: '' for index in option_counts}
        if correct_index not in option_counts:
            return classes

        incorrect_indices = [
            index for index in option_counts if index != correct_index]
        correct_count = option_counts[correct_index]
        highest_incorrect = max(
            (option_counts[index] for index in incorrect_indices),
            default=0)
        if correct_count > highest_incorrect:
            classes[correct_index] = 'o_cbt_health_correct'
        elif highest_incorrect > correct_count:
            classes[correct_index] = 'o_cbt_health_warning'
            for index in incorrect_indices:
                if option_counts[index] == highest_incorrect:
                    classes[index] = 'o_cbt_health_distractor'
        return classes

    def _cbt_question_health_counts(self):
        """Aggregate imported answers from completed generated papers."""
        counts = defaultdict(lambda: defaultdict(int))
        if not self.ids:
            return counts

        self.env.cr.execute("""
            WITH latest_attempt_answers AS (
                SELECT answer.question_id,
                       answer.participant_answer,
                       ROW_NUMBER() OVER (
                           PARTITION BY conduct.paper_id, answer.question_id
                           ORDER BY conduct.id DESC, answer.id DESC
                       ) AS answer_rank
                  FROM cbt_paper_attempt AS answer
                  JOIN cbt_paper_conduct AS conduct
                    ON conduct.id = answer.attempt_id
                  JOIN student_paper_questions_rel AS attempt_question
                    ON attempt_question.student_paper_id = conduct.paper_id
                   AND attempt_question.questions_id = answer.question_id
                 WHERE answer.question_id = ANY(%s)
                   AND answer.participant_answer IN ('A', 'B', 'C', 'D', 'E', 'F')
            )
            SELECT question_id,
                   ASCII(participant_answer) - ASCII('A') + 1,
                   COUNT(*)
              FROM latest_attempt_answers
             WHERE answer_rank = 1
             GROUP BY question_id, participant_answer
        """, [self.ids])
        for question_id, option_position, selection_count in (
                self.env.cr.fetchall()):
            counts[question_id][option_position] = selection_count
        return counts

    def _cbt_can_view_question_health(self):
        self.ensure_one()
        return bool(
            self.env.su
            or self.env.user.has_group('cbt.group_cbt_admin')
            or (self.env.user.has_group('cbt.group_cbt_reviewer')
                and self._cbt_has_review_access(self.subject_id.id)))

    def action_refresh_question_health(self):
        self.ensure_one()
        if not self._cbt_can_view_question_health():
            raise AccessError(_(
                'Only reviewers for this subject and CBT administrators can '
                'refresh Question Health.'))
        self.invalidate_recordset(['question_health_html'])
        return {'type': 'ir.actions.client', 'tag': 'reload'}

    def _compute_question_health_html(self):
        allowed_records = self.filtered(
            lambda rec: rec._cbt_can_view_question_health())
        counts_by_question = allowed_records._cbt_question_health_counts()
        alphabet = 'ABCDEF'
        for rec in self:
            if rec not in allowed_records:
                rec.question_health_html = Markup(
                    '<p class="text-muted">{}</p>').format(_(
                        'Question Health is available to reviewers for this '
                        'subject and CBT administrators.'))
                continue
            if rec.is_theory:
                rec.question_health_html = Markup(
                    '<p class="text-muted">{}</p>').format(_(
                        'Answer-selection statistics do not apply to '
                        'descriptive questions.'))
                continue

            options = []
            correct_indices = []
            for index, letter in enumerate(alphabet, start=1):
                option_text = rec['ans%s' % index]
                if not option_text:
                    continue
                options.append((index, letter, option_text))
                if rec['ans%s_correct' % index]:
                    correct_indices.append(index)

            if not options:
                rec.question_health_html = Markup(
                    '<p class="text-muted">{}</p>').format(_(
                        'No answer options are configured for this question.'))
                continue

            option_counts = {
                index: counts_by_question[rec.id].get(index, 0)
                for index, _letter, _text in options
            }
            correct_index = (
                correct_indices[0] if len(correct_indices) == 1 else None)
            classes = self._cbt_question_health_option_classes(
                option_counts, correct_index)

            rows = []
            for index, letter, option_text in options:
                label = _('Option %s') % letter
                if index == correct_index:
                    label = _('%s — Correct answer') % label
                safe_option = Markup(html_sanitize(option_text))
                rows.append(Markup(
                    '<tr class="{}"><th scope="row">{}</th>'
                    '<td>{}</td><td>{}</td></tr>').format(
                        classes[index], label, safe_option,
                        option_counts[index]))

            if len(correct_indices) != 1:
                rows.insert(0, Markup(
                    '<tr><td colspan="3" class="text-muted">{}</td></tr>'
                ).format(_(
                    'Correct answer is not configured uniquely; no option '
                    'will be highlighted.')))
            rec.question_health_html = Markup(
                '<table class="table table-sm table-hover '
                'o_cbt_question_health">'
                '<thead><tr><th>{}</th><th>{}</th><th>{}</th></tr></thead>'
                '<tbody>{}</tbody></table>').format(
                    _('Option'), _('Answer choice'),
                    _('Candidate selections'), Markup('').join(rows))

    def _cbt_used_in_active_paper(self):
        """Return True when the question belongs to a live candidate paper."""
        self.ensure_one()
        PaperLine = self.env.get('cbt.paper.line.export')
        if PaperLine is not None:
            lines = PaperLine.sudo().search([('server_id', '=', self.id)])
            if lines:
                return any(not line.paper_id.end_paper for line in lines)
        return bool(self.env['cbt.paper'].sudo().search_count([
            ('questions', 'in', [self.id]),
            ('student_paper_gen', '=', True),
        ]))

    def _cbt_has_suspend_access(self):
        """Return whether the current user may suspend this question."""
        self.ensure_one()
        if self.env.su or self.env.user.has_group('cbt.group_cbt_admin'):
            return True
        if not self.env.user.has_group('cbt.group_cbt_faculty'):
            return False
        return bool(self.env['cbt.employee.role'].search_count([
            ('employee_id.user_id', '=', self.env.user.id),
            ('subject_id', '=', self.subject_id.id),
            '|',
            ('create_access', '=', True),
            ('review_access', '=', True),
        ]))

    @api.depends('state', 'is_suspended')
    def _compute_can_suspend(self):
        for rec in self:
            rec.can_suspend = bool(
                rec._cbt_has_suspend_access()
                and rec.state == 'approved'
                and not rec.is_suspended
                and not rec._cbt_used_in_active_paper()
            )

    def action_suspend(self):
        """Open the suspension wizard for a question that is safe to suspend."""
        self.ensure_one()
        if not self.can_suspend or self._cbt_used_in_active_paper():
            raise UserError(_(
                "This question cannot be suspended because it is not approved, "
                "is already suspended, or is used in an active paper."))
        return {
            'name': _('Suspend Question'),
            'type': 'ir.actions.act_window',
            'res_model': 'cbt.mcqs.suspend.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_question_id': self.id},
        }

    def _cbt_suspend(self, reason, suspended_from, suspended_until):
        """Apply suspension after validating the reason and date range."""
        self.ensure_one()
        reason = (reason or '').strip()
        if not reason:
            raise ValidationError(_("A suspension reason is required."))
        if not suspended_from or not suspended_until:
            raise ValidationError(_(
                "Both the suspension start and end dates are required."))
        if suspended_until <= suspended_from:
            raise ValidationError(_(
                "The suspension end date must be after the start date."))
        if not self.can_suspend or self._cbt_used_in_active_paper():
            raise UserError(_(
                "This question cannot be suspended because it is not approved, "
                "is already suspended, or is used in an active paper."))
        self.sudo().with_context(cbt_suspension_write=True).write({
            'is_suspended': True,
            'suspension_reason': reason,
            'suspended_from': suspended_from,
            'suspended_until': suspended_until,
            'suspended_by': self.env.user.id,
        })
        return True

    @api.constrains('is_suspended', 'suspension_reason',
                    'suspended_from', 'suspended_until')
    def _check_suspension_details(self):
        for rec in self:
            if not rec.is_suspended:
                continue
            if not (rec.suspension_reason or '').strip():
                raise ValidationError(_("A suspension reason is required."))
            if not rec.suspended_from or not rec.suspended_until:
                raise ValidationError(_(
                    "Both the suspension start and end dates are required."))
            if rec.suspended_until <= rec.suspended_from:
                raise ValidationError(_(
                    "The suspension end date must be after the start date."))

    @api.model
    def _cron_resume_suspended_questions(self):
        """Release questions whose suspension period has ended."""
        now = fields.Datetime.now()
        questions = self.sudo().search([
            ('is_suspended', '=', True),
            ('suspended_until', '!=', False),
            ('suspended_until', '<=', now),
        ])
        if questions:
            questions.with_context(cbt_suspension_write=True).write({
                'is_suspended': False,
                'suspension_reason': False,
                'suspended_from': False,
                'suspended_until': False,
                'suspended_by': False,
            })
        return True

    _CBT_AUDIT_FIELDS = (
        'subject_id', 'topic_id', 'stopic_id', 'type_id', 'skill_id',
        'difficulty_level_id', 'time_id', 'question', 'option_quantity',
        'ans1', 'ans2', 'ans3', 'ans4', 'ans5', 'ans6',
        'ans1_correct', 'ans2_correct', 'ans3_correct', 'ans4_correct',
        'ans5_correct', 'ans6_correct', 'is_reserve', 'is_suspended',
        'suspension_reason', 'suspended_from', 'suspended_until',
        'suspended_by', 'current_user', 'reviewed_user', 'reviewer_remarks',
        'state', 'paper_id',
    )
    _CBT_SUSPENSION_FIELDS = {
        'is_suspended', 'suspension_reason', 'suspended_from',
        'suspended_until', 'suspended_by',
    }

    def _cbt_audit_snapshot(self):
        self.ensure_one()
        values = {}
        for name in self._CBT_AUDIT_FIELDS:
            value = self[name]
            if hasattr(value, 'display_name'):
                value = value.display_name or ''
            elif (value is not None
                  and not isinstance(value, (bool, int, float, str))):
                value = str(value)
            values[name] = value
        return values

    @api.model
    def _cbt_audit_display(self, value):
        if value is None or value is False:
            return ''
        text = str(value).replace('\n', ' ').strip()
        return text if len(text) <= 250 else text[:247] + '...'

    def _cbt_log_audit(self, action, old_values=None, new_values=None):
        self.ensure_one()
        Audit = self.env.get('cbt.mcqs.audit.log')
        if Audit is None:
            return
        old_values = old_values or {}
        new_values = new_values or {}
        changed = {}
        for name in self._CBT_AUDIT_FIELDS:
            old = old_values.get(name)
            new = new_values.get(name)
            if old != new:
                changed[name] = (old, new)
        if action == 'update' and not changed:
            return
        if action == 'create':
            old_payload = {}
            new_payload = new_values
            summary = _("Question created.")
        elif action == 'delete':
            old_payload = old_values
            new_payload = {}
            summary = _("Question deleted.")
        else:
            old_payload = {
                name: values[0] for name, values in changed.items()}
            new_payload = {
                name: values[1] for name, values in changed.items()}
            parts = []
            for name, (old, new) in changed.items():
                label = self._fields[name].string or name
                parts.append("%s: %s -> %s" % (
                    label, self._cbt_audit_display(old),
                    self._cbt_audit_display(new)))
            summary = "\n".join(parts)
        Audit.sudo().create({
            'question_id': self.id,
            'question_ref': self.id,
            'question_name': self.display_name,
            'subject_id': self.subject_id.id,
            'question_owner_id': self.current_user.id,
            'question_state': self.state,
            'action': action,
            'user_id': self.env.user.id,
            'change_summary': summary,
            'old_values': json.dumps(
                old_payload, ensure_ascii=False, default=str,
                sort_keys=True),
            'new_values': json.dumps(
                new_payload, ensure_ascii=False, default=str,
                sort_keys=True),
        })

    def _cbt_clean_option_vals(self, vals):
        """Drop unused option values and clear options for theory questions."""
        vals = dict(vals)
        is_theory = False
        if 'type_id' in vals:
            is_theory = self._cbt_is_theory_type(vals.get('type_id'))
        elif self:
            is_theory = all(self.mapped('is_theory'))
        if is_theory:
            for index in range(1, 7):
                vals['ans%s' % index] = False
                vals['ans%s_correct' % index] = False
            return vals
        if 'option_quantity' not in vals:
            return vals
        try:
            count = int(vals.get('option_quantity') or 4)
        except (TypeError, ValueError):
            count = 4
        for index in range(count + 1, 7):
            vals['ans%s' % index] = False
            vals['ans%s_correct' % index] = False
        return vals

    @api.constrains(
        'option_quantity', 'ans1', 'ans2', 'ans3', 'ans4', 'ans5', 'ans6',
        'ans1_correct', 'ans2_correct', 'ans3_correct', 'ans4_correct',
        'ans5_correct', 'ans6_correct')
    def _check_question_options(self):
        for rec in self:
            if rec._cbt_is_theory_type(rec.type_id.id):
                continue
            if not rec.option_quantity:
                continue
            count = int(rec.option_quantity)
            for index in range(1, count + 1):
                if not (rec['ans%s' % index] or '').strip():
                    raise ValidationError(_(
                        "Option %s is required for the selected number of "
                        "options.") % index)
            correct_options = [
                index for index in range(1, count + 1)
                if rec['ans%s_correct' % index]
            ]
            if len(correct_options) != 1:
                raise ValidationError(_(
                    "Please mark exactly one of the selected options as the "
                    "correct answer."))
            for index in range(count + 1, 7):
                if rec['ans%s' % index] or rec['ans%s_correct' % index]:
                    raise ValidationError(_(
                        "Option %s is not available for the selected number "
                        "of options.") % index)

    @api.constrains('subject_id', 'topic_id', 'stopic_id')
    def _check_subject_topic_hierarchy(self):
        for rec in self:
            if rec.topic_id and rec.topic_id.subject_id != rec.subject_id:
                raise ValidationError(_(
                    "The selected topic does not belong to the selected "
                    "subject."))
            if rec.stopic_id:
                if rec.stopic_id.topic_id != rec.topic_id:
                    raise ValidationError(_(
                        "The selected sub topic does not belong to the "
                        "selected topic."))
                if rec.stopic_id.subject_id != rec.subject_id:
                    raise ValidationError(_(
                        "The selected sub topic does not belong to the "
                        "selected subject."))

    @api.onchange('option_quantity')
    def _onchange_option_quantity(self):
        try:
            count = int(self.option_quantity or 4)
        except (TypeError, ValueError):
            count = 4
        for index in range(count + 1, 7):
            self['ans%s' % index] = False
            self['ans%s_correct' % index] = False

    @api.model
    def create(self, vals):
        if not (self.env.su or self.env.user.has_group('cbt.group_cbt_admin')):
            current_user_id = vals.get('current_user') or self.env.user.id
            if current_user_id != self.env.user.id:
                raise UserError(_(
                    "You cannot create a question for another user."))
            if (vals.get('state') or 'draft') != 'draft':
                raise UserError(_("New questions must be created as drafts."))
            self._cbt_check_question_scope(
                vals.get('subject_id'), vals.get('topic_id'),
                vals.get('stopic_id'))
            vals = dict(vals)
            vals['current_user'] = self.env.user.id
            vals['state'] = 'draft'
        vals = self._cbt_clean_option_vals(vals)
        record = super().create(vals)
        record._cbt_log_audit(
            'create', {}, record._cbt_audit_snapshot())
        return record

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
        if (self._CBT_SUSPENSION_FIELDS.intersection(vals)
                and not self.env.context.get('cbt_suspension_write')
                and not self.env.su):
            raise UserError(_(
                "Please use the Suspend button to change a question's "
                "suspension details."))
        if 'is_reserve' in vals:
            self._check_reserve_toggle_access()
        vals = self._cbt_clean_option_vals(vals)
        if not (self.env.su or self.env.user.has_group('cbt.group_cbt_admin')):
            if 'current_user' in vals and vals['current_user'] != self.env.user.id:
                raise UserError(_(
                    "You cannot change the owner of a question."))
            if {'subject_id', 'topic_id', 'stopic_id'}.intersection(vals):
                for rec in self:
                    self._cbt_check_question_scope(
                        vals.get('subject_id', rec.subject_id.id),
                        vals.get('topic_id', rec.topic_id.id),
                        vals.get('stopic_id', rec.stopic_id.id))
            if 'state' in vals:
                self._cbt_check_state_transition(vals['state'])
        old_snapshots = {
            rec.id: rec._cbt_audit_snapshot() for rec in self}
        result = super().write(vals)
        for rec in self:
            rec._cbt_log_audit(
                'update', old_snapshots[rec.id],
                rec._cbt_audit_snapshot())
        return result

    def unlink(self):
        snapshots = {
            rec.id: rec._cbt_audit_snapshot() for rec in self}
        for rec in self:
            rec._cbt_log_audit('delete', snapshots[rec.id], {})
        return super().unlink()

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

    @api.onchange('ans1_correct', 'ans2_correct', 'ans3_correct',
                  'ans4_correct', 'ans5_correct', 'ans6_correct')
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
        if self.topic_id and self.topic_id.subject_id != self.subject_id:
            self.topic_id = False
        if self.stopic_id and (
                self.stopic_id.subject_id != self.subject_id
                or self.stopic_id.topic_id != self.topic_id):
            self.stopic_id = False
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
        if self.stopic_id and self.stopic_id.topic_id != self.topic_id:
            self.stopic_id = False
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


class CBTMcqsAuditLog(models.Model):
    _name = 'cbt.mcqs.audit.log'
    _description = 'CBT Question Audit Log'
    _order = 'create_date desc, id desc'
    _rec_name = 'question_name'

    question_id = fields.Many2one(
        'cbt.mcqs', string='Question', ondelete='set null',
        readonly=True, index=True)
    question_ref = fields.Integer(
        string='Question ID', readonly=True, index=True)
    question_name = fields.Char(
        string='Question Reference', readonly=True, index=True)
    subject_id = fields.Many2one(
        'cbt.subject', string='Subject', ondelete='set null',
        readonly=True, index=True)
    question_owner_id = fields.Many2one(
        'res.users', string='Question Owner', readonly=True, index=True)
    question_state = fields.Selection([
        ('draft', 'Draft'),
        ('submitted', 'Under Review'),
        ('approved', 'Approved'),
        ('cancel', 'Cancel'),
    ], string='Question Status', readonly=True, index=True)
    action = fields.Selection([
        ('create', 'Created'),
        ('update', 'Updated'),
        ('delete', 'Deleted'),
    ], string='Action', required=True, readonly=True, index=True)
    user_id = fields.Many2one(
        'res.users', string='Changed By', readonly=True, index=True)
    change_summary = fields.Text(string='Change Summary', readonly=True)
    old_values = fields.Text(string='Before', readonly=True)
    new_values = fields.Text(string='After', readonly=True)


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
    