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
    # Shares the relation table of ``cbt.employee.role.subject_ids`` so both
    # the legacy single subject and the new multi-select subjects are visible
    # from the subject form.
    role_ids = fields.Many2many(
        'cbt.employee.role', 'cbt_employee_role_subject_rel',
        'subject_id', 'role_id', string='Faculty')

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
    _inherit = ['cbt.line.access']

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
    role_ids = fields.Many2many(
        'cbt.employee.role', 'cbt_employee_role_topic_rel',
        'topic_id', 'role_id', string='Faculty')

    def _compute_sub_topics(self):
        for rec in self:
            sub_topics = self.env['cbt.subject.subtopic'].search([
                ('topic_id', '=', rec.id)])
            rec.sub_topic_count = len(sub_topics)


class CBTSubjectSubTopic(models.Model):
    _name = 'cbt.subject.subtopic'
    _description = 'Sub Topic'
    _inherit = ['cbt.line.access']

    name = fields.Char(string='Sub Topic', required=True)
    code = fields.Char(string='Code')
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)

    topic_id = fields.Many2one(
        'cbt.subject.topic', string="Topic", ondelete='cascade')
    subject_id = fields.Many2one(
        'cbt.subject', string="Subject", related='topic_id.subject_id', store=True)
    role_ids = fields.Many2many(
        'cbt.employee.role', 'cbt_employee_role_subtopic_rel',
        'subtopic_id', 'role_id', string='Faculty')


class CBTEmployeeRole(models.Model):
    _name = 'cbt.employee.role'
    _description = 'Employee Role'
    _inherit = ['cbt.line.access', 'mail.thread', 'mail.activity.mixin']

    @api.onchange('user_id')
    def _onchange_user_id(self):
        if self.user_id and not self.employee_id:
            employee = self._cbt_employee_for_user(self.user_id)
            if employee:
                self.employee_id = employee.id

    employee_id = fields.Many2one(
        'hr.employee', "Faculty", required=True, tracking=True)
    user_id = fields.Many2one(
        'res.users', "User", index=True, ondelete='cascade', tracking=True,
        help="CBT user this faculty role applies to. It is filled "
             "automatically when the faculty employee is linked to a user.")
    # Legacy single-value fields. They are kept so existing data, imports and
    # custom code keep working; the User Rights screen uses the multi-select
    # fields below.
    subject_id = fields.Many2one(
        'cbt.subject', "Subject", tracking=True,
        help="Legacy single subject. New records use Subjects.")
    topic_id = fields.Many2one(
        'cbt.subject.topic', "Topic", tracking=True,
        help="Legacy single topic. New records use Topics.")
    subtopic_id = fields.Many2one(
        'cbt.subject.subtopic', "Sub Topic", tracking=True,
        help="Legacy single sub topic. New records use Sub Topics.")
    subject_ids = fields.Many2many(
        'cbt.subject', 'cbt_employee_role_subject_rel', 'role_id',
        'subject_id', string="Subjects", tracking=True)
    topic_ids = fields.Many2many(
        'cbt.subject.topic', 'cbt_employee_role_topic_rel', 'role_id',
        'topic_id', string="Topics", tracking=True)
    subtopic_ids = fields.Many2many(
        'cbt.subject.subtopic', 'cbt_employee_role_subtopic_rel', 'role_id',
        'subtopic_id', string="Sub Topics", tracking=True)
    create_access = fields.Boolean(
        'Question Creator', default=True, tracking=True)
    review_access = fields.Boolean(
        'Reviewer', default=True, tracking=True)

    # ------------------------------------------------------------------
    # Selection helpers (accept both the legacy m2o and the new m2m fields)
    # ------------------------------------------------------------------
    def _cbt_subjects(self):
        self.ensure_one()
        return self.subject_id | self.subject_ids

    def _cbt_topics(self):
        self.ensure_one()
        return self.topic_id | self.topic_ids

    def _cbt_subtopics(self):
        self.ensure_one()
        return self.subtopic_id | self.subtopic_ids

    @api.model
    def _cbt_user_domain(self, user):
        """Match the roles attached to ``user`` (new and legacy rows)."""
        return ['|', ('user_id', '=', user.id),
                ('employee_id.user_id', '=', user.id)]

    @api.model
    def _cbt_subject_domain(self, subject_id):
        """Match the roles covering ``subject_id`` (new and legacy rows)."""
        return ['|', ('subject_id', '=', subject_id),
                ('subject_ids', 'in', [subject_id])]

    @api.model
    def _cbt_user_roles(self, user, access_field=None):
        """Roles of ``user``, optionally only those granting ``access_field``."""
        domain = self._cbt_user_domain(user)
        if access_field:
            domain.append((access_field, '=', True))
        return self.sudo().search(domain)

    @api.model
    def _cbt_has_access(self, user, subject_id, access_field):
        """Whether ``user`` is granted ``access_field`` on ``subject_id``."""
        if not user or not subject_id:
            return False
        domain = (self._cbt_user_domain(user)
                  + self._cbt_subject_domain(subject_id)
                  + [(access_field, '=', True)])
        return bool(self.sudo().search_count(domain))

    @api.model
    def _cbt_employee_for_user(self, user):
        """Return the ``hr.employee`` of ``user``, creating it when missing."""
        Employee = self.env['hr.employee'].sudo()
        # ``employee_id`` is the employee of the current company: prefer it so
        # a role does not land on an unrelated (other company) employee.
        employee = getattr(user.sudo(), 'employee_id', False)
        if not employee:
            employee = Employee.with_context(active_test=False).search(
                [('user_id', '=', user.id)], limit=1)
        email = False
        try:
            email = getattr(user, 'email', False) or \
                    getattr(user.partner_id, 'email', False)
        except Exception:
            email = False
        if not employee:
            vals = {
                'name': user.name or user.login or _('Faculty'),
                'user_id': user.id,
            }
            if email:
                vals['work_email'] = email
            try:
                employee = Employee.create(vals)
            except Exception:
                employee = Employee.create({
                    'name': user.name or user.login or _('Faculty'),
                    'user_id': user.id,
                })
        try:
            if employee and not getattr(employee, 'work_email', False) and email:
                employee.sudo().write({'work_email': email})
            partner = getattr(employee, 'work_contact_id', False) or getattr(employee, 'address_id', False)
            if not partner and getattr(user, 'partner_id', False):
                partner = user.partner_id
            if partner and not getattr(partner, 'email', False) and email:
                partner.sudo().write({'email': email})
        except Exception:
            pass
        return employee

    @api.model
    def _cbt_vals_has_subject(self, vals):
        """Whether the create values already carry at least one subject."""
        if vals.get('subject_id'):
            return True
        value = vals.get('subject_ids')
        if not value:
            return False
        # A recordset may be passed by Python callers.
        if getattr(value, '_ids', None) is not None:
            return bool(value._ids)
        if isinstance(value, (list, tuple)):
            for command in value:
                if isinstance(command, int):
                    return True
                if not isinstance(command, (list, tuple)) or len(command) < 2:
                    continue
                if command[0] == 6:
                    if command[2]:
                        return True
                elif command[0] in (0, 4):
                    return True
        return False

    @api.model
    def _cbt_prepare_vals(self, vals, records=None):
        """Derive the user / employee link before storing a role row."""
        vals = dict(vals)
        vals.pop('id', None)
        explicit_employee = bool(vals.get('employee_id'))
        user = (self.env['res.users'].sudo().browse(vals['user_id'])
                if vals.get('user_id') else None)
        employee = (self.env['hr.employee'].sudo().browse(vals['employee_id'])
                    if explicit_employee else None)
        if not employee and records is not None and len(records) == 1:
            employee = records.employee_id
        if explicit_employee and not user and employee and employee.user_id:
            vals['user_id'] = employee.user_id.id
            user = employee.user_id
        if user and not employee:
            # Prefer existing employee linked to this user
            user_emp = getattr(user, 'employee_id', False) or \
                       self.env['hr.employee'].sudo().with_context(
                           active_test=False).search(
                           [('user_id', '=', user.id)], limit=1)
            if user_emp:
                vals['employee_id'] = user_emp.id
                employee = user_emp
            elif records is None or len(records) == 1:
                vals['employee_id'] = self._cbt_employee_for_user(user).id
                employee = self.env['hr.employee'].sudo().browse(vals['employee_id'])
        if user and employee and not getattr(employee, 'user_id', False):
            other = self.env['hr.employee'].sudo().with_context(
                active_test=False).search([
                    ('user_id', '=', user.id),
                    ('company_id', '=', employee.company_id.id),
                ], limit=1)
            if other and other != employee:
                # If another employee already linked to same user, use it
                vals['employee_id'] = other.id
                employee = other
            else:
                try:
                    employee.sudo().write({'user_id': user.id})
                except Exception:
                    # If constraint fails, try to find/use existing employee for user
                    user_emp = getattr(user, 'employee_id', False)
                    if user_emp:
                        vals['employee_id'] = user_emp.id
                    else:
                        raise
        elif user and employee and employee.user_id and employee.user_id.id != user.id:
            # Another employee is linked to this user - use the user's employee
            user_emp = getattr(user, 'employee_id', False)
            if user_emp and user_emp.id != employee.id:
                vals['employee_id'] = user_emp.id
            else:
                raise ValidationError(_(
                    "The user '%s' is already linked to another employee.") % user.name)
        return vals

    @api.constrains('subject_id', 'subject_ids')
    def _check_at_least_one_subject(self):
        for rec in self:
            if not rec.subject_id and not rec.subject_ids:
                raise ValidationError(_(
                    "Select at least one subject for the faculty role."))

    @api.constrains('employee_id', 'user_id')
    def _check_employee_user(self):
        for rec in self:
            if not rec.employee_id:
                continue
            employee_user = rec.employee_id.user_id
            if rec.user_id and employee_user and employee_user != rec.user_id:
                raise ValidationError(_(
                    "The faculty '%s' is already linked to another user.")
                    % rec.employee_id.name)

    @api.depends('employee_id', 'subject_id', 'subject_ids')
    def _compute_display_name(self):
        for rec in self:
            name = 'New'
            subjects = rec._cbt_subjects()
            if subjects:
                owner = rec.employee_id.name or rec.user_id.name or ''
                if owner:
                    name = owner + ' - ' + ', '.join(subjects.mapped('name'))
                else:
                    name = ', '.join(subjects.mapped('name'))
            rec.display_name = name

    def _sync_groups_for_users(self, users):
        creator = self.env.ref(
            'cbt.group_cbt_creator', raise_if_not_found=False)
        reviewer = self.env.ref(
            'cbt.group_cbt_reviewer', raise_if_not_found=False)
        if not creator or not reviewer:
            return
        managed = self.env.ref(
            'cbt.group_cbt_managed', raise_if_not_found=False)
        faculty_group = self.env.ref(
            'cbt.group_cbt_faculty', raise_if_not_found=False)
        Role = self.env['cbt.employee.role'].sudo()
        for user in users.sudo():
            if not user:
                continue
            roles = Role.search(Role._cbt_user_domain(user))
            if managed and managed in user.groups_id and not roles:
                continue
            if roles and faculty_group and faculty_group not in user.groups_id:
                faculty_group.sudo().write({'users': [(4, user.id)]})
            has_create = any(r.create_access for r in roles)
            has_review = any(r.review_access for r in roles)
            if has_create:
                if creator not in user.groups_id:
                    creator.sudo().write({'users': [(4, user.id)]})
            else:
                if creator in user.groups_id:
                    creator.sudo().write({'users': [(3, user.id)]})
            if has_review:
                if reviewer not in user.groups_id:
                    reviewer.sudo().write({'users': [(4, user.id)]})
            else:
                if reviewer in user.groups_id:
                    reviewer.sudo().write({'users': [(3, user.id)]})

    def _sync_role_groups(self):
        self._sync_groups_for_users(
            self.mapped('user_id') | self.mapped('employee_id.user_id'))

    @api.model
    def _sync_all_role_groups(self):
        records = self.search([])
        self._sync_groups_for_users(
            records.mapped('user_id') | records.mapped('employee_id.user_id'))

    @api.model_create_multi
    def create(self, vals_list):
        prepared = []
        for vals in vals_list:
            vals = self._cbt_prepare_vals(vals)
            if not vals.get('employee_id'):
                raise ValidationError(_(
                    "A faculty employee (or a user) is required for a faculty "
                    "role."))
            if not self._cbt_vals_has_subject(vals):
                raise ValidationError(_(
                    "Select at least one subject for the faculty role."))
            prepared.append(vals)
        if self._cbt_can_elevate():
            records = super(CBTEmployeeRole, self.sudo()).create(prepared)
        else:
            records = super().create(prepared)
        records._sync_role_groups()
        return records

    def write(self, vals):
        vals = self._cbt_prepare_vals(vals, records=self)
        if self._cbt_can_elevate():
            result = super(CBTEmployeeRole, self.sudo()).write(vals)
        else:
            result = super().write(vals)
        self._sync_role_groups()
        return result

    def unlink(self):
        users = self.mapped('user_id') | self.mapped('employee_id.user_id')
        if self._cbt_can_elevate():
            result = super(CBTEmployeeRole, self.sudo()).unlink()
        else:
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
    _inherit = ['cbt.line.access']

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
    _inherit = ['cbt.line.access']

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
        role_model = self.env['cbt.employee.role']
        roles = role_model._cbt_user_roles(self.env.user, 'create_access')
        subject_list = set(roles.mapped('subject_id').ids)
        subject_list.update(roles.mapped('subject_ids').ids)
        return [('id', 'in', list(subject_list))]

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
    # time_id = fields.Many2one('cbt.question.time', required=False)
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
    is_reviewer = fields.Boolean(compute='_compute_is_reviewer', store=False)
    state = fields.Selection([
        ('draft', 'Draft'), ('submitted', 'Submitted'),
        ('approved', 'Approved'), ('cancel', 'Cancel')
    ], 'Status', default='draft')

    @api.depends()
    def _compute_is_reviewer(self):
        role_model = self.env['cbt.employee.role']
        user = self.env.user
        for rec in self:
            if user.has_group('cbt.group_cbt_admin'):
                rec.is_reviewer = True
                continue
            if rec.subject_id and role_model._cbt_has_access(user, rec.subject_id.id, 'review_access'):
                rec.is_reviewer = True
            else:
                rec.is_reviewer = False
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
        role_model = self.env['cbt.employee.role']
        for rec in self:
            is_reviewer = bool(rec.subject_id) and role_model._cbt_has_access(
                user, rec.subject_id.id, 'review_access')
            rec.can_review = bool(
                rec.state == 'submitted'
                and rec.current_user.id != user.id
                and is_reviewer
            )

    @api.model
    def create(self, vals):
        if not (self.env.su or self.env.user.has_group('cbt.group_cbt_admin')):
            subject_id = vals.get('subject_id')
            employee_role = self.env['cbt.employee.role']
            allowed = employee_role._cbt_has_access(
                self.env.user, subject_id, 'create_access')
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
        role_model = self.env['cbt.employee.role']
        for rec in self:
            subject_id = rec.subject_id.id
            has_create = role_model._cbt_has_access(
                self.env.user, subject_id, 'create_access')
            has_review = role_model._cbt_has_access(
                self.env.user, subject_id, 'review_access')
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
        role_model = self.env['cbt.employee.role']
        roles = role_model._cbt_user_roles(self.env.user, 'review_access')
        subject_list = set(roles.mapped('subject_id').ids)
        subject_list.update(roles.mapped('subject_ids').ids)
        review_questions = self.env['cbt.mcqs'].search([
            ('current_user', '!=', self.env.user.id),
            ('subject_id', 'in', list(subject_list)),
            ('state', '=', 'submitted')])
        record_ids = review_questions.ids
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
            role_model = self.env['cbt.employee.role']
            role_user = self.current_user or self.env.user
            roles = role_model.sudo().search(
                role_model._cbt_user_domain(role_user)
                + role_model._cbt_subject_domain(self.subject_id.id))
            # Roles without any topic restriction grant the whole subject.
            restricted = set(roles.mapped('topic_id').ids)
            restricted.update(roles.mapped('topic_ids').ids)
            topics = self.env['cbt.subject.topic'].browse(
                list(restricted)).filtered(
                    lambda topic: topic.subject_id.id == self.subject_id.id)
            if not topics:
                topics = self.env['cbt.subject.topic'].search(
                    [('subject_id', '=', self.subject_id.id)])
            topic_list = topics.ids
        return {'domain': {'topic_id': [('id', 'in', topic_list)]}}

    @api.onchange('topic_id')
    def _get_subtopic(self):
        subtopic_list = []
        if self.topic_id:
            role_model = self.env['cbt.employee.role']
            role_user = self.current_user or self.env.user
            roles = role_model.sudo().search(
                role_model._cbt_user_domain(role_user))
            # Roles without any sub topic restriction grant every sub topic
            # of the selected topic.
            restricted = set(roles.mapped('subtopic_id').ids)
            restricted.update(roles.mapped('subtopic_ids').ids)
            subtopics = self.env['cbt.subject.subtopic'].browse(
                list(restricted)).filtered(
                    lambda subtopic: subtopic.topic_id.id == self.topic_id.id)
            if not subtopics:
                subtopics = self.env['cbt.subject.subtopic'].search(
                    [('topic_id', '=', self.topic_id.id)])
            subtopic_list = subtopics.ids
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
            try:
                company = self.env.company.sudo()
                if not getattr(company, 'email', False):
                    try:
                        domain = (company.name or 'cbt').lower().replace(' ', '').replace('.', '')
                        company.write({'email': 'noreply@%s.local' % domain})
                    except Exception:
                        pass
                user = self.env.user.sudo()
                partner = user.partner_id.sudo() if user.partner_id else False
                email_from = getattr(company, 'email', False) or \
                             (getattr(partner, 'email', False) if partner else False) or \
                             getattr(user, 'email', False) or \
                             'noreply@localhost'
                try:
                    if partner and not getattr(partner, 'email', False):
                        partner.write({'email': email_from})
                    if user and not getattr(user, 'email', False) and partner and partner.email:
                        user.write({'email': partner.email})
                    ICP = self.env['ir.config_parameter'].sudo()
                    if not ICP.get_param('mail.default.from'):
                        ICP.set_param('mail.default.from', email_from)
                except Exception:
                    pass
                try:
                    rec.sudo().with_context(
                        mail_notify_force_send=False,
                        mail_create_nosubscribe=True,
                        mail_notrack=True,
                        mail_auto_subscribe_no_notify=True,
                        mail_server_id=False,
                        default_email_from=email_from,
                        email_from=email_from,
                    ).message_post(body=_(
                        "Question returned for correction by %s. Remarks: %s") % (
                        self.env.user.name, rec.reviewer_remarks),
                        message_type='comment', subtype_xmlid='mail.mt_note',
                        author_id=partner.id if partner else self.env.user.partner_id.id)
                except Exception:
                    try:
                        rec.sudo().with_context(mail_notify_force_send=False, mail_create_nosubscribe=True, default_email_from=email_from).message_post(body=_(
                            "Question returned for correction by %s. Remarks: %s") % (
                            self.env.user.name, rec.reviewer_remarks),
                            message_type='comment', subtype_xmlid='mail.mt_note')
                    except Exception:
                        pass
            except Exception:
                pass
        return self.get_filtered_record()

    def approve_question(self):
        for rec in self:
            if not rec.can_review:
                raise UserError(
                    _("You are not allowed to review this question."))
            rec.state = 'approved'
            rec.reviewed_user = self.env.user
            try:
                company = self.env.company.sudo()
                if not getattr(company, 'email', False):
                    try:
                        domain = (company.name or 'cbt').lower().replace(' ', '').replace('.', '')
                        company.write({'email': 'noreply@%s.local' % domain})
                    except Exception:
                        pass
                user = self.env.user.sudo()
                partner = user.partner_id.sudo() if user.partner_id else False
                email_from = getattr(company, 'email', False) or \
                             (getattr(partner, 'email', False) if partner else False) or \
                             getattr(user, 'email', False) or \
                             'noreply@localhost'
                try:
                    if partner and not getattr(partner, 'email', False):
                        partner.write({'email': email_from})
                    if user and not getattr(user, 'email', False) and partner and partner.email:
                        user.write({'email': partner.email})
                    ICP = self.env['ir.config_parameter'].sudo()
                    ICP.set_param('mail.default.from', email_from)
                    if not ICP.get_param('mail.catchall.domain'):
                        ICP.set_param('mail.catchall.domain', email_from.split('@')[-1] if '@' in email_from else 'localhost')
                except Exception:
                    pass
                try:
                    rec.sudo().with_context(
                        mail_notify_force_send=False,
                        mail_create_nosubscribe=True,
                        mail_notrack=True,
                        mail_auto_subscribe_no_notify=True,
                        mail_server_id=False,
                        default_email_from=email_from,
                        email_from=email_from,
                    ).message_post(body=_("Question approved by %s.") % (
                        self.env.user.name),
                        message_type='comment', subtype_xmlid='mail.mt_note',
                        author_id=partner.id if partner else self.env.user.partner_id.id)
                except Exception:
                    try:
                        rec.sudo().with_context(mail_notify_force_send=False, mail_create_nosubscribe=True).message_post(body=_("Question approved by %s.") % (
                            self.env.user.name),
                            message_type='comment', subtype_xmlid='mail.mt_note')
                    except Exception:
                        pass
            except Exception:
                pass
        return self.get_filtered_record()

    def reject_question(self):
        for rec in self:
            # Validate review permission
            if not rec.can_review:
                raise UserError(
                    _("You are not allowed to review this question.")
                )

            # Require rejection remarks
            if not rec.reviewer_remarks:
                raise UserError(
                    _("Please mention the reason / remarks for rejection.")
                )

            # Update the question with elevated rights after validation
            rec.sudo().write({
                'state': 'draft',
                'reviewed_user': self.env.user.id,
            })

            try:
                company = self.env.company.sudo()

                # Get a sender email
                if not getattr(company, 'email', False):
                    try:
                        domain = (
                            (company.name or 'cbt')
                            .lower()
                            .replace(' ', '')
                            .replace('.', '')
                        )
                        company.write({
                            'email': 'noreply@%s.local' % domain
                        })
                    except Exception:
                        pass

                user = self.env.user.sudo()
                partner = (
                    user.partner_id.sudo()
                    if user.partner_id
                    else False
                )

                email_from = (
                        getattr(company, 'email', False)
                        or (
                            getattr(partner, 'email', False)
                            if partner else False
                        )
                        or getattr(user, 'email', False)
                        or 'noreply@localhost'
                )

                try:
                    if partner and not getattr(partner, 'email', False):
                        partner.write({'email': email_from})

                    if (
                            user
                            and not getattr(user, 'email', False)
                            and partner
                            and partner.email
                    ):
                        user.write({'email': partner.email})

                    ICP = self.env['ir.config_parameter'].sudo()

                    if not ICP.get_param('mail.default.from'):
                        ICP.set_param('mail.default.from', email_from)

                except Exception:
                    pass

                # Post the rejection message in the chatter
                try:
                    rec.sudo().with_context(
                        mail_notify_force_send=False,
                        mail_create_nosubscribe=True,
                        mail_notrack=True,
                        mail_auto_subscribe_no_notify=True,
                        mail_server_id=False,
                        default_email_from=email_from,
                        email_from=email_from,
                    ).message_post(
                        body=_(
                            "Question rejected and returned to the developer "
                            "by %s. Remarks: %s"
                        ) % (
                                 self.env.user.name,
                                 rec.reviewer_remarks,
                             ),
                        message_type='comment',
                        subtype_xmlid='mail.mt_note',
                        author_id=partner.id if partner
                        else self.env.user.partner_id.id,
                    )

                except Exception:
                    try:
                        rec.sudo().with_context(
                            mail_notify_force_send=False,
                            mail_create_nosubscribe=True,
                            default_email_from=email_from,
                        ).message_post(
                            body=_(
                                "Question rejected and returned to the developer "
                                "by %s. Remarks: %s"
                            ) % (
                                     self.env.user.name,
                                     rec.reviewer_remarks,
                                 ),
                            message_type='comment',
                            subtype_xmlid='mail.mt_note',
                        )
                    except Exception:
                        pass

            except Exception:
                # Preserve the original behavior if notification setup fails.
                pass

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
    