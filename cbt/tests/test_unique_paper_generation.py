# -*- coding: utf-8 -*-
from unittest import mock

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase


class TestUniquePaperGeneration(TransactionCase):
    """Tests for the 'no repeat question across papers' feature."""

    def setUp(self):
        super().setUp()
        self.subject = self.env['cbt.subject'].create({'name': 'Physics'})
        self.topic = self.env['cbt.subject.topic'].create({
            'name': 'Mechanics',
            'subject_id': self.subject.id,
        })
        self.stopic = self.env['cbt.subject.subtopic'].create({
            'name': 'Kinematics',
            'topic_id': self.topic.id,
        })
        self.difficulty = self.env['cbt.question.difficulty.level'].create({
            'name': 'Easy',
        })
        self.qtype = self.env['cbt.question.type'].create({'name': 'MCQ'})
        self.skill = self.env['cbt.question.skill'].create({'name': 'Basic'})
        self.qtime = self.env['cbt.question.time'].create({'name': '60'})
        self.slot = self.env['cbt.slot'].create({
            'name': 'Morning',
            'date': fields.Date.today(),
            'time': 9.0,
        })

    # ------------------------------------------------------------------ utils
    def _create_question(self, state='approved', is_reserve=False,
                         difficulty=None):
        return self.env['cbt.mcqs'].create({
            'subject_id': self.subject.id,
            'topic_id': self.topic.id,
            'stopic_id': self.stopic.id,
            'type_id': self.qtype.id,
            'skill_id': self.skill.id,
            'difficulty_level_id': (difficulty or self.difficulty).id,
            'time_id': self.qtime.id,
            'question': '<p>Q</p>',
            'ans1': '<p>A</p>',
            'ans2': '<p>B</p>',
            'ans3': '<p>C</p>',
            'ans4': '<p>D</p>',
            'ans1_correct': True,
            'state': state,
            'is_reserve': is_reserve,
        })

    def _create_criteria(self, unique=False, per_paper=2):
        criteria = self.env['cbt.paper.criteria'].create({'name': 'Criteria'})
        self.env['cbt.paper.criteria.rule'].create({
            'subjects': self.subject.id,
            'paper_id': criteria.id,
            'no_questions': str(per_paper),
            'total_questions_difficulty_rule': str(per_paper),
            'difficulty_rules': [(0, 0, {
                'difficulty_level_id': self.difficulty.id,
                'no_questions': str(per_paper),
            })],
        })
        if unique:
            criteria.write({'unique_questions': True})
        criteria.invalidate_recordset()
        return criteria

    def _create_generator(self, criteria, enable_repeat=False,
                          configure_paper=False, total_paper=0):
        generator = self.env['cbt.paper.generator'].create({
            'name': 'Generator',
            'criteria_id': criteria.id,
            'slot_id': self.slot.id,
            'enable_repeat_question': enable_repeat,
            'configure_paper': configure_paper,
        })
        if total_paper:
            generator.total_paper = total_paper
        return generator

    # ------------------------------------------------------------------ tests
    def test_generation_pool_excludes_reserve_and_unapproved(self):
        approved = self._create_question()
        self._create_question(state='draft')
        self._create_question(is_reserve=True)
        pool = self.env['cbt.mcqs']._get_generation_pool(
            [('subject_id', '=', self.subject.id)])
        self.assertEqual(pool, approved)

    def test_papers_count_reflects_question_bank(self):
        for _ in range(5):
            self._create_question()
        criteria = self._create_criteria(unique=True, per_paper=2)
        # 5 approved questions, 2 per paper -> 2 whole papers.
        self.assertEqual(criteria.papers_count, 2)

        self._create_question()  # now 6 questions
        criteria.invalidate_recordset(['papers_count'])
        self.assertEqual(criteria.papers_count, 3)

    def test_papers_count_is_minimum_across_buckets(self):
        hard = self.env['cbt.question.difficulty.level'].create({'name': 'Hard'})
        for _ in range(6):
            self._create_question(difficulty=self.difficulty)  # easy
        for _ in range(3):
            self._create_question(difficulty=hard)  # hard
        criteria = self.env['cbt.paper.criteria'].create({'name': 'Criteria'})
        self.env['cbt.paper.criteria.rule'].create({
            'subjects': self.subject.id,
            'paper_id': criteria.id,
            'no_questions': '4',
            'total_questions_difficulty_rule': '4',
            'difficulty_rules': [
                (0, 0, {
                    'difficulty_level_id': self.difficulty.id,  # easy: 6 -> 3
                    'no_questions': '2',
                }),
                (0, 0, {
                    'difficulty_level_id': hard.id,  # hard: 3 -> 1
                    'no_questions': '2',
                }),
            ],
        })
        self.assertEqual(criteria.papers_count, 1)

    def test_papers_count_is_readonly_and_not_required(self):
        criteria = self._create_criteria(unique=True, per_paper=2)
        self.assertTrue(criteria._fields['papers_count'].compute)
        self.assertFalse(criteria._fields['papers_count'].store)

    def test_generation_requires_a_positive_paper_count(self):
        self._create_question()
        self._create_question()
        criteria = self._create_criteria(unique=True, per_paper=2)
        generator = self._create_generator(criteria)  # total_paper stays 0
        with self.assertRaises(UserError) as error:
            generator.papers_generation()
        self.assertIn("No paper to generate", str(error.exception))

    def test_generation_fails_when_more_than_capacity(self):
        # 2 approved questions but 2 unique papers x 2 questions need 4.
        self._create_question()
        self._create_question()
        criteria = self._create_criteria(unique=True, per_paper=2)
        self.assertEqual(criteria.papers_count, 1)
        generator = self._create_generator(criteria, total_paper=2)
        with self.assertRaises(UserError) as error:
            generator.papers_generation()
        self.assertIn('At most 1 unique papers', str(error.exception))

    def test_check_availability_button_lists_capacity(self):
        self._create_question()
        self._create_question()
        self._create_question()
        self._create_question()
        criteria = self._create_criteria(unique=True, per_paper=2)
        action = criteria.action_check_availability()
        self.assertEqual(action['tag'], 'display_notification')
        self.assertIn('available 4', action['params']['message'])
        self.assertIn('up to 2 paper(s)', action['params']['message'])
        self.assertIn('Maximum unique papers: 2', action['params']['message'])

    def test_unique_batch_is_disjoint(self):
        for _ in range(6):
            self._create_question()
        criteria = self._create_criteria(unique=True, per_paper=2)
        self.assertEqual(criteria.papers_count, 3)
        generator = self._create_generator(criteria, total_paper=2)
        generator.papers_generation()

        papers = self.env['cbt.paper'].search([
            ('generator_id', '=', generator.id)])
        self.assertEqual(len(papers), 2)
        self.assertEqual(generator.state, 'assign')
        for paper in papers:
            self.assertEqual(len(paper.questions), 2)

        first = set(papers[0].questions.ids)
        second = set(papers[1].questions.ids)
        self.assertFalse(first & second, "Papers share questions!")

        # Every used question is tracked exactly once per paper.
        tracks = self.env['cbt.question.repeat.track'].search([
            ('paper_id', 'in', papers.ids)])
        self.assertEqual(len(tracks), 4)

    def test_no_partial_batch_when_pool_shrinks(self):
        questions = [self._create_question() for _ in range(4)]
        criteria = self._create_criteria(unique=True, per_paper=2)
        generator = self._create_generator(criteria, total_paper=2)

        # Remove one question from the approved pool after the feasibility
        # check, so generation must fail.
        questions[0].state = 'draft'
        with self.assertRaises(UserError):
            generator.papers_generation()

        papers = self.env['cbt.paper'].search([
            ('generator_id', '=', generator.id)])
        self.assertEqual(len(papers), 0, "No paper should be persisted.")

    def test_unique_false_keeps_existing_behaviour(self):
        # Only 2 questions available but 2 papers of 2 questions requested.
        # With repeat allowed and uniqueness disabled the legacy algorithm
        # must still generate both papers (questions are reused).
        self._create_question()
        self._create_question()
        criteria = self._create_criteria(unique=False, per_paper=2)
        generator = self._create_generator(
            criteria, enable_repeat=True, configure_paper=True, total_paper=2)
        # The legacy algorithm commits mid-way; neutralise it so the test
        # transaction stays isolated.
        with mock.patch('odoo.sql_db.Cursor.commit', return_value=None):
            generator.papers_generation()

        papers = self.env['cbt.paper'].search([
            ('generator_id', '=', generator.id)])
        self.assertEqual(len(papers), 2)
        self.assertEqual(generator.state, 'assign')

    def test_round_robin_assignment_warns_when_more_participants(self):
        for _ in range(4):
            self._create_question()
        criteria = self._create_criteria(unique=True, per_paper=2)
        program = self.env['cbt.program'].create({
            'name': 'BE-%s' % id(self),
            'code': 'BE%s' % abs(hash(self)),
        })
        criteria.program_ids = [(4, program.id)]
        generator = self._create_generator(criteria, total_paper=2)
        generator.papers_generation()

        for index in range(3):
            self.env['cbt.participant'].create({
                'name': 'Student %s' % index,
                'login': 'student%s' % index,
                'cid': index,
                'program': program.id,
                'slot_id': self.slot.id,
            })
        # generate_multi_paper_student also commits mid-way.
        with mock.patch('odoo.sql_db.Cursor.commit', return_value=None):
            result = generator.generate_multi_paper_student()
        self.assertIn('share', result['warning']['message'])