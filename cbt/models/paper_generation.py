import re

from odoo import fields, models, _, api
from datetime import datetime, date
from dateutil.relativedelta import relativedelta
from odoo.tools.safe_eval import safe_eval
import pdb
import math
from odoo.exceptions import AccessError, UserError, RedirectWarning, ValidationError

from odoo.http import content_disposition, Controller, request, route
import random


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
                    count_subject_questions = len(self.env['cbt.mcqs'].search(
                        [('subject_id', '=', rules.subjects.id), ('state', '=', 'approved'), ('id', 'not in', tracked.ids)]))
                if self.enable_repeat_question:
                    count_subject_questions = len(self.env['cbt.mcqs'].search(
                        [('subject_id', '=', rules.subjects.id), ('state', '=', 'approved')]))

                if count_subject_questions < int(rules.no_questions):
                    raise ValidationError(_(
                        "%s has less then " + rules.no_questions + " questions in question bank defined in paper criteria") % (
                        rules.subjects.name))

                elif count_subject_questions >= int(rules.no_questions):
                    if self.env['cbt.mcqs'].search([('subject_id', '=', rules.subjects.id)]):
                        if not self.enable_repeat_question:
                            question_env_list = self.env['cbt.mcqs'].search(
                                [('subject_id', '=', rules.subjects.id), ('state', '=', 'approved'), ('id', 'not in', tracked.ids)])
                        if self.enable_repeat_question:
                            question_env_list = self.env['cbt.mcqs'].search(
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
                                        count_subject_questions = len(self.env['cbt.mcqs'].search([('subject_id', '=', rules.subjects.id), ('state', '=', 'approved'), ('id', 'not in', tracked.ids),
                                                                                                   ('difficulty_level_id', '=', rules_diff.difficulty_level_id.id)]))
                                    if self.enable_repeat_question:
                                        count_subject_questions = len(self.env['cbt.mcqs'].search([('subject_id', '=', rules.subjects.id), ('state', '=', 'approved'),
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
                                        count_subject_questions = len(self.env['cbt.mcqs'].search(
                                            [('subject_id', '=', rules.subjects.id), ('state', '=', 'approved'), ('id', 'not in', tracked.ids),
                                                ('topic_id', '=', rules_topic.topic_id.id)]))
                                    if self.enable_repeat_question:
                                        count_subject_questions = len(self.env['cbt.mcqs'].search(
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
                                                            count_topic_questions = self.env['cbt.mcqs'].search(
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
                                                            count_topic_questions = self.env['cbt.mcqs'].search(
                                                                [('subject_id', '=', rules.subjects.id),
                                                                 ('state', '=',
                                                                 'approved'),
                                                                 ('topic_id', '=',
                                                                 rules_topic.topic_id.id),
                                                                 ('difficulty_level_id', '=', diff_list[
                                                                     0])])

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

    def generate_multi_paper_student(self):
        '''
        allocate papers to students
        '''
        # active_id = self.env.context.get('active_id')

        paper_generator = self.env['cbt.paper.generator'].sudo().search(
            [('id', '=', self.id)])

        participants = self.env['cbt.participant'].search(
            [('program', 'in', paper_generator.program_ids.ids), ('slot_id', '=', paper_generator.slot_id.id)])

        papers = paper_generator.papers
        paper_id = [paper.id for paper in papers]
        unique_mode = paper_generator.criteria_id.unique_questions
        warning_message = ''
        if unique_mode:
            if not papers:
                raise UserError(_(
                    "No paper has been generated yet. Run 'Generate Papers' "
                    "before allocating them to students."))
            if len(participants) > len(papers):
                warning_message = _(
                    "There are %(participants)s participants but only "
                    "%(papers)s generated papers. Some candidates will share "
                    "the same paper.") % {
                    'participants': len(participants),
                    'papers': len(papers),
                }
        for index, participant in enumerate(participants):
            if unique_mode:
                paper = papers[index % len(papers)]
            else:
                random.shuffle(paper_id)
                paper = papers.filtered(
                    lambda x: x.id == paper_id[0])
                paper_id.pop(0)
            question_list = [ques.id for ques in paper.questions]
            random.shuffle(question_list)
            papers_data = {
                'main_paper_id': paper.id,
                'questions': [(6, 0, question_list)],
                'participant_id': participant.id,
            }
            participant_paper = self.env['cbt.student.paper'].create(
                papers_data)
            participant_paper.main_paper_id.slot_id.duration = paper_generator.criteria_id.duration
            participant_test_data = {
                'name': participant_paper.participant_id.name,
                'paper_name': participant_paper.main_paper_id.name,
                'program': participant.program.name,
                'test_time': participant.slot_id.time,
                'test_duration': participant_paper.main_paper_id.slot_id.duration,
                'test_date': participant.slot_id.date,
                'login': participant.login,
                'cid': participant.cid,
            }
            if paper_generator.criteria_id.random_section:
                participant_test_data.update({
                    'shuffle_section': True,
                })

            participant_test = self.env['cbt.paper.export'].create(
                participant_test_data)
            participant_test.server_id = participant_paper.id
            server_id = participant_paper.id

            participant_test_question = []
            for rec in participant_paper.questions:
                question = rec.question
                subject = rec.subject_id.name

                test_paper_subject = self.env['cbt.subject.export'].search(
                    [('name', '=ilike', subject)], limit=1)
                if not test_paper_subject:
                    test_paper_subject = self.env['cbt.subject.export'].create({
                        'name': subject,
                    })
                correct_answer = ''

                if rec.ans1_correct:
                    correct_answer = 'A'
                if rec.ans2_correct:
                    correct_answer = 'B'
                if rec.ans3_correct:
                    correct_answer = 'C'
                if rec.ans4_correct:
                    correct_answer = 'D'
                if rec.ans5_correct:
                    correct_answer = 'E'
                if rec.ans6_correct:
                    correct_answer = 'F'
                test_question = participant_test.line_ids.create({
                    'paper_id': participant_test.id,
                    'name': rec.question,
                    'server_id': rec.id,
                    'subject_id': test_paper_subject.id,
                    'correct_answer': correct_answer,

                })
                options = [rec.ans1, rec.ans2, rec.ans3,
                           rec.ans4, rec.ans5, rec.ans6]

                for opt in options:
                    participant_test.line_ids.option_ids.create({
                        'question_id': test_question.id,
                        'name': opt,
                        'server_id': test_question.id,
                    })
                # test_question.answer = correct_answer

            self.env.cr.commit()
            paper.student_paper_gen = True
        self.state = 'done'

        return {
            'warning': {
                'title': 'Warning!',
                'message': warning_message or 'The warning text'}

        }
