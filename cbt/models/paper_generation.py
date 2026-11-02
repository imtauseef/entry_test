import base64
import hashlib
import html
import json
import re
import uuid
from datetime import datetime, timedelta
from urllib.parse import unquote, urlsplit

from odoo import fields, models, _, api
from datetime import date
from dateutil.relativedelta import relativedelta
from odoo.tools.safe_eval import safe_eval
import pdb
import math
from odoo.exceptions import AccessError, UserError, RedirectWarning, ValidationError

from odoo.http import content_disposition, Controller, request, route
import random

from .allocation_xlsx import (
    build_allocation_xlsx,
    encrypt_xlsx,
    excel_password_prompt_action,
    offline_image_key,
    offline_image_placeholder,
    transform_html_image_sources,
    verify_excel_admin_password,
)


class CBTPaperGenerator(models.Model):
    _name = 'cbt.paper.generator'
    _description = 'Generate Paper'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    current_user = fields.Many2one(
        'res.users', 'Created By', default=lambda self: self.env.user, readonly="True")
    name = fields.Char(string='Paper Name', tracking=True, required=True)
    criteria_id = fields.Many2one('cbt.paper.criteria', 'Paper Criteria', tracking=True, required=True)
    etest_id = fields.Many2one('cbt.test', 'Entry Test', tracking=True, readonly=True)
    type_id = fields.Many2one('cbt.test.type', 'Test Type', tracking=True, readonly=True)
    program_ids = fields.Many2many(
        'cbt.program', string='Programs', required=True, readonly=True, compute='_total_paper')
    configure_paper = fields.Boolean('Configure Paper', default=False)
    total_paper = fields.Integer(
        string="No of Papers",  compute='_total_paper', store=True)
    papers = fields.One2many('cbt.paper', 'generator_id',
                             string="Papers", tracking=True)
    slot_id = fields.Many2one('cbt.slot', 'Session', required=True, tracking=True)
    state = fields.Selection(
        [('draft', 'Draft'), ('assign', 'Assign Student'), ('done', 'Done')], 'Status', default='draft')
    enable_repeat_question = fields.Boolean(
        'Enable Repeat Question', default=False)

    @api.depends('program_ids', 'criteria_id', 'slot_id')
    def _total_paper(self):
        for rec in self:
            rec.etest_id = self.criteria_id.etest_id
            rec.type_id = self.criteria_id.type_id
            rec.write({
                'program_ids': [(4, program.id) for program in self.criteria_id.program_ids]
            })
            if not rec.configure_paper:
                participant_candidates = self.env['cbt.participant'].sudo().search(
                    [('program', 'in', rec.criteria_id.program_ids.ids), ('slot_id', '=', rec.slot_id.id)])
                rec.total_paper = len(participant_candidates)

    def papers_generation(self):
        if (self.total_paper or 0) <= 0:
            raise UserError(_(
                "No paper to generate: set 'No of Papers' (enable 'Configure "
                "Paper' to enter it manually) or make sure candidates are "
                "available for the selected session and programs."))
        if self.criteria_id.unique_questions:
            return self._generate_unique_papers()
        i = 1
        no_of_papers = self.total_paper
        tracked = self.env['cbt.question.repeat.track'].search(
            []).mapped('question_id')
        while (no_of_papers > 0):
            list = []
            for rules in self.criteria_id.rules_ids:
                rules_id = []
                rules_number = []
                rules_remain_number = []
                if not self.enable_repeat_question:
                    count_subject_questions = len(self.env['cbt.mcqs']._get_generation_pool(
                        [('subject_id', '=', rules.subjects.id), ('state', '=', 'approved'), ('id', 'not in', tracked.ids)]))
                if self.enable_repeat_question:
                    count_subject_questions = len(self.env['cbt.mcqs']._get_generation_pool(
                        [('subject_id', '=', rules.subjects.id), ('state', '=', 'approved')]))

                if count_subject_questions < int(rules.no_questions):
                    raise ValidationError(_(
                        "%s has less then " + rules.no_questions + " questions in question bank defined in paper criteria") % (
                        rules.subjects.name))

                elif count_subject_questions >= int(rules.no_questions):
                    if self.env['cbt.mcqs']._get_generation_pool([('subject_id', '=', rules.subjects.id)]):
                        if not self.enable_repeat_question:
                            question_env_list = self.env['cbt.mcqs']._get_generation_pool(
                                [('subject_id', '=', rules.subjects.id), ('state', '=', 'approved'), ('id', 'not in', tracked.ids)])
                        if self.enable_repeat_question:
                            question_env_list = self.env['cbt.mcqs']._get_generation_pool(
                                [('subject_id', '=', rules.subjects.id), ('state', '=', 'approved')])

                        if not rules.difficulty_rules:
                            random_id = []
                            no_of_questions = rules.no_questions
                            while (no_of_questions):
                                random.choice(question_env_list)
                                list.append(random.choice(
                                    question_env_list).id)
                                no_of_questions = int(no_of_questions) - 1
                        elif rules.difficulty_rules:
                            if not rules.topic_rules and not rules.type_rules:
                                for rules_diff in rules.difficulty_rules:
                                    if not self.enable_repeat_question:
                                        count_subject_questions = len(self.env['cbt.mcqs']._get_generation_pool([('subject_id', '=', rules.subjects.id), ('state', '=', 'approved'), ('id', 'not in', tracked.ids),
                                                                                                   ('difficulty_level_id', '=', rules_diff.difficulty_level_id.id)]))
                                    if self.enable_repeat_question:
                                        count_subject_questions = len(self.env['cbt.mcqs']._get_generation_pool([('subject_id', '=', rules.subjects.id), ('state', '=', 'approved'),
                                                                                                   ('difficulty_level_id', '=', rules_diff.difficulty_level_id.id)]))

                                    if count_subject_questions < int(rules_diff.no_questions):
                                        raise ValidationError(_(
                                            "%s has less then " + rules_diff.no_questions + " questions in question bank defined in difficulty rule in paper criteria ") % (
                                            rules.subjects.name))

                                    elif count_subject_questions >= int(rules_diff.no_questions):
                                        no_of_questions = rules_diff.no_questions
                                        while (no_of_questions):
                                            random_id = random.choice(
                                                question_env_list)
                                            if rules_diff.difficulty_level_id.id == random_id.difficulty_level_id.id:
                                                value_bool = False
                                                i_value = int(len(list))
                                                while (i_value):
                                                    if int(list[i_value - 1]) == random_id.id:
                                                        value_bool = True
                                                        break
                                                    i_value = int(
                                                        i_value) - 1
                                                if value_bool == False:
                                                    list.append(
                                                        random_id.id)
                                                    no_of_questions = int(
                                                        no_of_questions) - 1

                            elif rules.topic_rules:
                                for rules_diff in rules.difficulty_rules:
                                    rules_id.append(
                                        rules_diff.difficulty_level_id.id)
                                    rules_number.append(
                                        rules_diff.no_questions)
                                    rules_remain_number.append(
                                        rules_diff.no_questions)
                                list_rules = [
                                    [0] * 3 for i in range(len(rules_id))]
                                m = 0
                                for i, j, k in zip(rules_id, rules_number, rules_remain_number):
                                    list_rules[m][0] = i
                                    list_rules[m][1] = j
                                    list_rules[m][2] = k
                                    m += 1
                                for rules_topic in rules.topic_rules:
                                    if not self.enable_repeat_question:
                                        count_subject_questions = len(self.env['cbt.mcqs']._get_generation_pool(
                                            [('subject_id', '=', rules.subjects.id), ('state', '=', 'approved'), ('id', 'not in', tracked.ids),
                                                ('topic_id', '=', rules_topic.topic_id.id)]))
                                    if self.enable_repeat_question:
                                        count_subject_questions = len(self.env['cbt.mcqs']._get_generation_pool(
                                            [('subject_id', '=', rules.subjects.id), ('state', '=', 'approved'),
                                                ('topic_id', '=', rules_topic.topic_id.id)]))

                                    if count_subject_questions < int(rules_topic.no_questions):
                                        raise ValidationError(_(
                                            "%s topic " + rules_topic.topic_id.name + " has less then " + rules_topic.no_questions + " questions in question bank defined in topic rule in paper criteria ") % (
                                            rules.subjects.name))

                                    elif count_subject_questions >= int(rules_diff.no_questions):
                                        no_of_questions_topic = rules_topic.no_questions
                                        count_question = 0
                                        while (no_of_questions_topic):
                                            count = len(list_rules)
                                            while (count):
                                                diff_list = list_rules[count - 1]
                                                if int(diff_list[2]) != 0:
                                                    random_id = random.choice(
                                                        question_env_list)
                                                    if rules_topic.sub_topic_id:
                                                        if diff_list[
                                                                0] == random_id.difficulty_level_id.id and rules_topic.topic_id.id == random_id.topic_id.id and rules_topic.sub_topic_id.id == random_id.stopic_id.id:

                                                            value_bool = False
                                                            i_value = int(
                                                                len(list))
                                                            while (i_value):
                                                                if int(list[i_value - 1]) == random_id.id:
                                                                    value_bool = True
                                                                    break
                                                                i_value = int(
                                                                    i_value) - 1
                                                            if value_bool == False:
                                                                list.append(
                                                                    random_id.id)
                                                                list_rules[int(count) - 1][2] = str(
                                                                    int(diff_list[2]) - 1)
                                                                list_rules[int(count) - 1][1] = str(
                                                                    int(diff_list[1]) - 1)
                                                                count = int(
                                                                    count) - 1
                                                                count_question = int(
                                                                    count_question) + 1
                                                                if count_question == int(rules_topic.no_questions):
                                                                    count = 0
                                                    elif not rules_topic.sub_topic_id:
                                                        if not self.enable_repeat_question:
                                                            count_topic_questions = self.env['cbt.mcqs']._get_generation_pool(
                                                                [('subject_id', '=', rules.subjects.id),
                                                                 ('state', '=',
                                                                 'approved'),
                                                                 ('topic_id', '=',
                                                                 rules_topic.topic_id.id),
                                                                 ('id', 'not in',
                                                                 tracked.ids),
                                                                 ('difficulty_level_id', '=', diff_list[
                                                                     0])])
                                                        if self.enable_repeat_question:
                                                            count_topic_questions = self.env['cbt.mcqs']._get_generation_pool(
                                                                [('subject_id', '=', rules.subjects.id),
                                                                 ('state', '=',
                                                                 'approved'),
                                                                 ('topic_id', '=',
                                                                 rules_topic.topic_id.id),
                                                                 ('difficulty_level_id', '=', diff_list[
                                                                     0])])

                                                        if not count_topic_questions:
                                                            raise ValidationError(
                                                                _("Topic criteria defined not correct. There are less "
                                                                  "questions in question bank then the defined "
                                                                  "criteria."))
                                                        random_id = random.choice(
                                                            count_topic_questions)
                                                        if count_topic_questions:
                                                            if diff_list[
                                                                    0] == random_id.difficulty_level_id.id and rules_topic.topic_id.id == random_id.topic_id.id:

                                                                value_bool = False
                                                                i_value = int(
                                                                    len(list))
                                                                while (i_value):
                                                                    if int(list[i_value - 1]) == random_id.id:
                                                                        value_bool = True
                                                                        break
                                                                    i_value = int(
                                                                        i_value) - 1
                                                                if value_bool == False:
                                                                    list.append(
                                                                        random_id.id)
                                                                    list_rules[int(count) - 1][2] = str(
                                                                        int(diff_list[2]) - 1)
                                                                    list_rules[int(count) - 1][1] = str(
                                                                        int(diff_list[1]) - 1)
                                                                    count = int(
                                                                        count) - 1
                                                                    count_question = int(
                                                                        count_question) + 1
                                                                    if count_question == int(rules_topic.no_questions):
                                                                        break
                                                        else:
                                                            raise ValidationError(
                                                                _("Topic criteria defined not correct. There are less "
                                                                    "questions in question bank then the defined "
                                                                    "criteria."))
                                                elif int(diff_list[2]) == 0:
                                                    count = int(count) - 1

                                            if count_question == int(rules_topic.no_questions):
                                                no_of_questions_topic = 0

                                            else:
                                                no_of_questions_topic = int(
                                                    no_of_questions_topic) - 1

                    else:
                        raise ValidationError(
                            _("%s has no questions as per paper criteria") % (rules.subjects.name))

            papers_data = {
                'name': 'Paper ' + str(no_of_papers),
                'questions': [(6, 0, list)],
                'generator_id': self.id,
                'slot_id': self.slot_id.id,
                # 'discipline_id': self.criteria_id.discipline_id.id,
            }
            qes_en = self.env['cbt.paper'].create(papers_data)
            qes_en.write({
                'program_ids': [(4, program.id) for program in self.criteria_id.program_ids]
            })
            self.env.cr.commit()
            for qes in list:
                qustion_track = {
                    'question_id': qes,
                    'paper_id': qes_en.id,
                }
                self.env['cbt.question.repeat.track'].create(qustion_track)
                self.env.cr.commit()

            no_of_papers = int(no_of_papers) - 1
        self.state = 'assign'

    def _generate_unique_papers(self):
        """Generate the number of papers the generator needs (``total_paper``)
        with mutually disjoint question sets, up to the capacity announced by
        the criteria.

        ``criteria.papers_count`` is a read-only estimate of the maximum number
        of unique papers the question bank can supply; it does not drive
        generation. The whole batch runs in a single transaction: if any paper
        cannot be satisfied, everything is rolled back and a clear error is
        raised, so a half-generated batch can never be persisted.
        """
        self.ensure_one()
        criteria = self.criteria_id
        max_papers = criteria.papers_count or 0
        papers_count = self.total_paper or 0
        if papers_count <= 0:
            raise UserError(_(
                "No paper to generate: set 'No of Papers' or make sure "
                "candidates are available for the selected session and "
                "programs."))
        if max_papers and papers_count > max_papers:
            raise UserError(_(
                "Cannot generate %(need)s unique papers from the current "
                "question bank. At most %(max)s unique papers are possible "
                "for this criteria.") % {
                'need': papers_count,
                'max': max_papers,
            })
        buckets = criteria._iter_rule_buckets()
        if not buckets:
            raise UserError(_("No paper rules defined on the selected criteria."))

        tracked = self.env['cbt.question.repeat.track'].search([]).mapped('question_id')
        pool_model = self.env['cbt.mcqs']

        # Compute one question list per paper. Search the pool once per bucket
        # and split it with random.sample for efficiency.
        per_paper = [[] for _ in range(papers_count)]
        for bucket in buckets:
            domain = list(bucket['domain'])
            if not self.enable_repeat_question and tracked:
                domain.append(('id', 'not in', tracked.ids))
            pool = pool_model._get_generation_pool(domain).ids
            required_each = int(bucket['required'])
            required_total = required_each * papers_count
            if required_each and len(pool) < required_total:
                raise UserError(_(
                    "Cannot generate %(papers)s unique papers. "
                    "%(label)s: need %(need)s, available %(avail)s."
                ) % {
                    'papers': papers_count,
                    'label': bucket['label'],
                    'need': required_total,
                    'avail': len(pool),
                })
            picked = random.sample(pool, required_total) if required_total else []
            for index in range(papers_count):
                per_paper[index].extend(
                    picked[index * required_each:(index + 1) * required_each])

        # Persist the whole batch inside a savepoint; any failure rolls back
        # every paper created for this batch.
        with self.env.cr.savepoint():
            for index, question_ids in enumerate(per_paper):
                paper = self.env['cbt.paper'].create({
                    'name': 'Paper ' + str(index + 1),
                    'questions': [(6, 0, question_ids)],
                    'generator_id': self.id,
                    'slot_id': self.slot_id.id,
                })
                paper.write({
                    'program_ids': [(4, program.id) for program in criteria.program_ids]
                })
                for question_id in question_ids:
                    self.env['cbt.question.repeat.track'].create({
                        'question_id': question_id,
                        'paper_id': paper.id,
                    })
        self.state = 'assign'

    def action_open_allocation_export_password_prompt(self):
        return excel_password_prompt_action(
            self, '_export_allocation_workbook', 'export',
            _('Export Allocation Workbook'))

    def _export_allocation_workbook(
            self, odoo_password=None, workbook_password=None):
        """Export this generator's student-paper allocations without portal models."""
        self.ensure_one()
        verify_excel_admin_password(self.env, odoo_password)

        now = fields.Datetime.now()
        self._check_allocation_export_window(self.slot_id, now)
        allocated_papers = self.env['cbt.student.paper'].search([
            ('main_paper_id.generator_id', '=', self.id),
        ], order='id')
        if not allocated_papers:
            raise UserError(_('No students have been allocated papers from this generator.'))

        parameters = self.env['ir.config_parameter'].sudo()
        source_system_id = parameters.get_param('cbt.offline_source_system_id')
        if not source_system_id:
            source_system_id = uuid.uuid4().hex
            parameters.set_param('cbt.offline_source_system_id', source_system_id)

        def source_id(model, record_id):
            return '%s:%s:%s' % (source_system_id, model, record_id)

        manifest_rows = [
            ['schema_version', '4.0'],
            ['source_system_id', source_system_id],
            ['exported_at', fields.Datetime.now()],
            ['source_generator_id', source_id('cbt.paper.generator', self.id)],
            ['source_generator_name', self.name or ''],
            ['export_id', uuid.uuid4().hex],
            ['paper_export_count', len(allocated_papers)],
            ['participant_count', len(set(
                allocated_papers.mapped('participant_id').ids))],
            ['image_count', 0],
            ['paper_export_model', 'cbt.paper.export'],
            [
                'credential_warning',
                'The Participants sheet contains candidate passwords. '
                'The workbook is encrypted; share its password separately and '
                'delete temporary copies after transfer.',
            ],
            [
                'allocation_warning',
                self.env.context.get('cbt_allocation_warning', ''),
            ],
        ]
        participant_rows = [[
            'source_student_id',
            'login',
            'name',
            'password',
        ]]
        paper_rows = [[
            'source_export_id',
            'source_generator_id',
            'source_student_id',
            'login',
            'name',
            'cid',
            'source_paper_id',
            'source_template_paper_id',
            'paper_name',
            'program',
            'test_center',
            'test_date',
            'test_time',
            'test_duration',
            'shuffle_section',
            'source_schedule_id',
            'payload_sha256',
        ]]
        question_rows = [[
            'source_student_id',
            'source_paper_id',
            'source_question_id',
            'subject_name',
            'name',
            'question_order',
            'is_theory',
            'correct_answer',
        ]]
        option_rows = [[
            'source_student_id',
            'source_paper_id',
            'source_question_id',
            'source_option_id',
            'sequence',
            'option_label',
            'name',
        ]]
        image_rows = [[
            'image_key', 'mimetype', 'chunk_index', 'chunk_count', 'data_base64',
        ]]
        images_by_key = {}
        exported_students = set()

        def image_content(src, question):
            source = html.unescape(src)
            if source.startswith('data:'):
                header, separator, encoded_image = source.partition(',')
                if (
                        not separator
                        or not header.startswith('data:image/')
                        or ';base64' not in header):
                    raise UserError(_(
                        'Question %s contains an unsupported embedded image.'
                    ) % question.display_name)
                mimetype = header[5:].split(';', 1)[0].lower()
                try:
                    image_data = base64.b64decode(
                        encoded_image, validate=True)
                except (ValueError, TypeError) as exc:
                    raise UserError(_(
                        'Question %s contains an invalid embedded image.'
                    ) % question.display_name) from exc
            else:
                path = unquote(urlsplit(source).path).strip('/').split('/')
                attachment_id = False
                if (
                        len(path) >= 4
                        and path[0] == 'web'
                        and path[1] in ('image', 'content')
                        and path[2] == 'ir.attachment'):
                    attachment_id = path[3]
                elif (
                        len(path) >= 3
                        and path[0] == 'web'
                        and path[1] in ('image', 'content')
                        and path[2].split('-', 1)[0].isdigit()):
                    attachment_id = path[2].split('-', 1)[0]
                if not attachment_id or not attachment_id.isdigit():
                    raise UserError(_(
                        'Question %s contains an image URL that cannot be '
                        'included in an offline workbook.'
                    ) % question.display_name)
                attachment = self.env['ir.attachment'].sudo().browse(
                    int(attachment_id)).exists()
                if not attachment or not attachment.datas:
                    raise UserError(_(
                        'Question %s refers to an image attachment that no '
                        'longer exists.'
                    ) % question.display_name)
                mimetype = (attachment.mimetype or '').lower()
                if not re.fullmatch(r'image/[a-z0-9.+-]+', mimetype):
                    raise UserError(_(
                        'Question %s refers to an attachment that is not an image.'
                    ) % question.display_name)
                image_data = base64.b64decode(attachment.datas)
            if (
                    not image_data
                    or not re.fullmatch(r'image/[a-z0-9.+-]+', mimetype)):
                raise UserError(_(
                    'Question %s contains an empty or invalid image.'
                ) % question.display_name)
            image_key = offline_image_key(mimetype, image_data)
            images_by_key.setdefault(image_key, (mimetype, image_data))
            return offline_image_placeholder(image_key)

        def portable_html(value, question):
            return transform_html_image_sources(
                value, lambda src: image_content(src, question))

        for allocated in allocated_papers:
            participant = allocated.participant_id
            generated_paper = allocated.main_paper_id
            if not participant.login:
                raise UserError(_(
                    'Participant %s has no login and cannot be mapped on the portal instance.'
                ) % participant.display_name)
            if not participant.password:
                raise UserError(_(
                    'Participant %s has no password to provision a portal account.'
                ) % participant.display_name)

            student_key = source_id('cbt.participant', participant.id)
            if student_key not in exported_students:
                participant_rows.append([
                    student_key,
                    participant.login,
                    participant.name or participant.login,
                    participant.password,
                ])
                exported_students.add(student_key)
            allocation_key = source_id('cbt.student.paper', allocated.id)
            template_key = source_id('cbt.paper', generated_paper.id)
            slot = participant.slot_id
            if not slot or not slot.date or slot.time is False:
                raise UserError(_(
                    'Participant %s is missing a valid examination schedule.'
                ) % participant.display_name)
            test_time = float(slot.time)
            if not math.isfinite(test_time) or not 0 <= test_time < 24:
                raise UserError(_(
                    'Participant %s has an invalid examination start time.'
                ) % participant.display_name)
            duration = float(slot.duration or 0)
            if not math.isfinite(duration) or not duration.is_integer():
                raise UserError(_(
                    'The examination duration must be a whole number of minutes.'
                ))
            test_duration = int(duration)
            if test_duration <= 0:
                raise UserError(_(
                    'The examination duration must be greater than zero.'
                ))
            test_center = participant.center_id or slot.center_id
            self._check_allocation_export_window(slot, now)
            allocation_values = [
                allocation_key,
                source_id('cbt.paper.generator', self.id),
                student_key,
                participant.login,
                participant.name or participant.login,
                participant.cid or 0,
                allocation_key,
                template_key,
                generated_paper.name or '',
                participant.program.name if participant.program else '',
                test_center.name if test_center else '',
                fields.Date.to_string(slot.date) if slot and slot.date else '',
                test_time,
                test_duration,
                bool(self.criteria_id.random_section),
                source_id('cbt.slot', slot.id) if slot else '',
            ]

            question_ids = allocated.question_sequence or allocated.questions.ids
            question_ids = [int(question_id) for question_id in question_ids]
            if len(question_ids) != len(set(question_ids)):
                raise UserError(_(
                    'An allocated paper has duplicate question ordering data.'
                ))
            question_ids.extend(
                question_id for question_id in allocated.questions.ids
                if question_id not in question_ids
            )
            if not question_ids:
                raise UserError(_(
                    'Allocated paper %s does not contain any questions.'
                ) % generated_paper.display_name)
            questions_by_id = {
                question.id: question for question in allocated.questions
            }

            allocation_questions = []
            allocation_options = []
            for position, question_id in enumerate(question_ids, start=1):
                question = questions_by_id.get(question_id)
                if not question:
                    raise UserError(_(
                        'An allocated paper has a question order referencing a missing question.'
                    ))
                question_key = source_id('cbt.mcqs', question.id)
                source_answer = generated_paper._question_correct_answer(question)
                answer_key = ''
                question_options = [
                    (index, option) for index, option in enumerate([
                        question.ans1, question.ans2, question.ans3,
                        question.ans4, question.ans5, question.ans6,
                    ], start=1) if option
                ]
                if not question.is_theory and not question_options:
                    raise UserError(_(
                        'Multiple-choice question %s has no answer options.'
                    ) % question.display_name)
                if source_answer:
                    correct_source_position = ord(source_answer) - 64
                    visible_positions = [
                        position for position, option in question_options
                    ]
                    if correct_source_position not in visible_positions:
                        raise UserError(_(
                            'Question %s marks an empty option as correct.'
                        ) % question.display_name)
                    answer_key = chr(
                        64 + visible_positions.index(correct_source_position) + 1)
                question_text = portable_html(question.question or '', question)
                if len(question_text) > 32767:
                    raise UserError(_(
                        'Question %s exceeds Excel\'s maximum cell length.'
                    ) % question.display_name)
                allocation_questions.append([
                    student_key,
                    allocation_key,
                    question_key,
                    question.subject_id.name if question.subject_id else '',
                    question_text,
                    position,
                    bool(question.is_theory),
                    answer_key,
                ])
                if not question.is_theory:
                    for option_position, (source_position, option_text) in enumerate(
                            question_options, start=1):
                        allocation_options.append([
                            student_key,
                            allocation_key,
                            question_key,
                            '%s:option:%s' % (question_key, source_position),
                            option_position,
                            chr(64 + option_position),
                            portable_html(option_text, question),
                        ])

            payload = {
                'paper_export': allocation_values,
                'questions': allocation_questions,
                'options': allocation_options,
            }
            payload_hash = hashlib.sha256(json.dumps(
                payload, ensure_ascii=False, sort_keys=True,
                separators=(',', ':'),
            ).encode('utf-8')).hexdigest()
            paper_rows.append(allocation_values + [payload_hash])
            question_rows.extend(allocation_questions)
            option_rows.extend(allocation_options)

        for image_key, (mimetype, image_data) in sorted(images_by_key.items()):
            image_base64 = base64.b64encode(image_data).decode('ascii')
            chunks = [
                image_base64[index:index + 30000]
                for index in range(0, len(image_base64), 30000)
            ]
            for chunk_index, chunk in enumerate(chunks, start=1):
                image_rows.append([
                    image_key,
                    mimetype,
                    chunk_index,
                    len(chunks),
                    chunk,
                ])
        manifest_rows = [
            [key, len(images_by_key) if key == 'image_count' else value]
            for key, value in manifest_rows
        ]

        workbook = build_allocation_xlsx([
            ('Manifest', manifest_rows),
            ('Participants', participant_rows),
            ('Papers', paper_rows),
            ('Questions', question_rows),
            ('Answer Options', option_rows),
            ('Images', image_rows),
        ])
        encoded = base64.b64encode(
            encrypt_xlsx(workbook, workbook_password))
        attachment = self.env['ir.attachment'].sudo().create({
            'name': '%s_allocation.xlsx' % (self.name or 'paper_allocation'),
            'datas': encoded,
            'mimetype': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            'res_model': 'cbt.paper.generator',
            'res_id': self.id,
            'type': 'binary',
        })
        return {
            'type': 'ir.actions.act_url',
            'url': '/web/content/%s?download=1' % attachment.id,
            'target': 'new',
        }

    def _check_allocation_export_window(self, slot, now):
        if not slot or not slot.date or slot.time is False:
            raise UserError(_(
                'A valid test slot with a date and start time is required '
                'before exporting the allocation workbook.'
            ))

        start_hour = float(slot.time)
        if not math.isfinite(start_hour) or not 0 <= start_hour < 24:
            raise UserError(_('The test slot has an invalid start time.'))

        slot_date = fields.Date.to_date(slot.date)
        start_at = datetime.combine(
            slot_date, datetime.min.time()) + timedelta(hours=start_hour)
        if slot.time_to is not False and slot.time_to is not None:
            end_hour = float(slot.time_to)
            if not math.isfinite(end_hour) or not 0 <= end_hour < 24:
                raise UserError(_('The test slot has an invalid end time.'))
            end_at = datetime.combine(
                slot_date, datetime.min.time()) + timedelta(hours=end_hour)
            if end_at <= start_at:
                end_at += timedelta(days=1)
        else:
            duration = float(slot.duration or 0)
            if not math.isfinite(duration) or duration <= 0:
                raise UserError(_(
                    'The test slot must have a valid end time or positive duration.'
                ))
            end_at = start_at + timedelta(minutes=duration)

        now_local = fields.Datetime.context_timestamp(
            self, now).replace(tzinfo=None)
        if now_local <= start_at - timedelta(hours=24):
            raise UserError(_(
                'The allocation workbook can only be exported during the '
                '24 hours before the test slot starts. Export opens at %s.'
            ) % (start_at - timedelta(hours=24)).strftime('%Y-%m-%d %H:%M'))
        if now_local > end_at:
            raise UserError(_(
                'The allocation workbook cannot be exported after the test '
                'slot ends at %s.'
            ) % end_at.strftime('%Y-%m-%d %H:%M'))

    def generate_multi_paper_student(self):
        '''
        allocate papers to students
        '''
        if not self.env.user.has_group('cbt.group_cbt_admin'):
            raise AccessError(_('Only CBT administrators may allocate candidate papers.'))
        # active_id = self.env.context.get('active_id')

        paper_generator = self.env['cbt.paper.generator'].sudo().search(
            [('id', '=', self.id)])

        participants = self.env['cbt.participant'].search(
            [('program', 'in', paper_generator.program_ids.ids), ('slot_id', '=', paper_generator.slot_id.id)])

        papers = paper_generator.papers
        paper_ids = papers.ids
        available_paper_ids = paper_ids[:]
        unique_mode = paper_generator.criteria_id.unique_questions
        warning_message = ''
        if not papers:
            raise UserError(_(
                "No paper has been generated yet. Run 'Generate Papers' "
                "before allocating them to students."))
        if unique_mode:
            if len(participants) > len(papers):
                warning_message = _(
                    "There are %(participants)s participants but only "
                    "%(papers)s generated papers. Some candidates will share "
                    "the same paper.") % {
                    'participants': len(participants),
                    'papers': len(papers),
                }
        existing_allocations = self.env['cbt.student.paper'].search([
            ('main_paper_id.generator_id', '=', paper_generator.id),
            ('participant_id', 'in', participants.ids),
        ])
        already_allocated = set(existing_allocations.mapped('participant_id').ids)
        for index, participant in enumerate(participants):
            if participant.id in already_allocated:
                continue
            if unique_mode:
                paper = papers[index % len(papers)]
            else:
                if not available_paper_ids:
                    available_paper_ids = paper_ids[:]
                random.shuffle(available_paper_ids)
                paper = self.env['cbt.paper'].browse(
                    available_paper_ids.pop())
            question_list = [ques.id for ques in paper.questions]
            random.shuffle(question_list)
            papers_data = {
                'main_paper_id': paper.id,
                'questions': [(6, 0, question_list)],
                'participant_id': participant.id,
            }
            participant_paper = self.env['cbt.student.paper'].create(
                papers_data)
            participant_paper.question_sequence = question_list
            participant_paper.main_paper_id.slot_id.duration = paper_generator.criteria_id.duration
            paper.student_paper_gen = True
        self.state = 'done'
        return self.with_context(
            cbt_allocation_warning=warning_message,
        ).action_open_allocation_export_password_prompt()
