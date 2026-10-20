# -*- coding: utf-8 -*-
from odoo import fields
from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase


class TestPaperQuestionReplacement(TransactionCase):
    """Tests for the question-bank replacement feature.

    Replacement draws a random question from the *question bank* (approved,
    non-reserve) of the same discipline and moves the replaced question into
    the reserve pool.
    """

    def setUp(self):
        super().setUp()
        self.subject = self.env['cbt.subject'].create({'name': 'Physics'})
        self.other_subject = self.env['cbt.subject'].create({'name': 'Chemistry'})
        self.topic = self.env['cbt.subject.topic'].create({
            'name': 'Mechanics',
            'subject_id': self.subject.id,
        })
        self.topic2 = self.env['cbt.subject.topic'].create({
            'name': 'Optics',
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
    def _create_question(self, subject=None, topic=None, is_reserve=False,
                         state='approved', difficulty=None, qtype=None):
        return self.env['cbt.mcqs'].create({
            'subject_id': (subject or self.subject).id,
            'topic_id': (topic or self.topic).id,
            'stopic_id': self.stopic.id,
            'type_id': (qtype or self.qtype).id,
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

    def _create_criteria(self, unique=False):
        criteria = self.env['cbt.paper.criteria'].create({'name': 'Criteria'})
        if unique:
            criteria.write({'unique_questions': True})
        return criteria

    def _create_paper(self, questions, criteria=None, paper_gen_done=False):
        criteria = criteria or self._create_criteria()
        generator = self.env['cbt.paper.generator'].create({
            'name': 'Generator',
            'criteria_id': criteria.id,
            'slot_id': self.slot.id,
        })
        paper = self.env['cbt.paper'].create({
            'name': 'Paper',
            'generator_id': generator.id,
            'slot_id': self.slot.id,
            'questions': [(6, 0, [q.id for q in questions])],
        })
        if paper_gen_done:
            paper.student_paper_gen = True
        return paper

    # ------------------------------------------------------------------ tests
    def test_replacement_picks_only_bank_same_subject(self):
        old = self._create_question()
        bank = self._create_question()
        other_subject_bank = self._create_question(subject=self.other_subject)
        paper = self._create_paper([old])

        paper.action_replace_question(old.id)

        self.assertNotIn(old, paper.questions)
        self.assertIn(bank, paper.questions)
        self.assertNotIn(other_subject_bank, paper.questions)
        self.assertEqual(len(paper.questions), 1)

        log = self.env['cbt.paper.replacement.log'].search([
            ('paper_id', '=', paper.id)])
        self.assertEqual(len(log), 1)
        self.assertEqual(log.old_question_id, old)
        self.assertEqual(log.new_question_id, bank)
        self.assertEqual(log.user_id, self.env.user)
        self.assertEqual(log.match_level, 'exact')
        self.assertEqual(log.line_sequence, 1)

    def test_replacement_never_uses_reserve_question(self):
        old = self._create_question()
        reserve = self._create_question(is_reserve=True)
        bank = self._create_question()
        paper = self._create_paper([old])

        paper.action_replace_question(old.id)

        self.assertIn(bank, paper.questions)
        self.assertNotIn(reserve, paper.questions)

    def test_replaced_question_is_moved_to_reserve(self):
        old = self._create_question()
        self._create_question()
        paper = self._create_paper([old])

        self.assertFalse(old.is_reserve)
        paper.action_replace_question(old.id)
        self.assertTrue(old.is_reserve)

    def test_replacement_falls_back_to_subject_match(self):
        old = self._create_question(topic=self.topic)
        # Same subject/difficulty/type but a different topic -> subject match.
        bank = self._create_question(topic=self.topic2)
        paper = self._create_paper([old])

        paper.action_replace_question(old.id)

        self.assertIn(bank, paper.questions)
        log = self.env['cbt.paper.replacement.log'].search([
            ('paper_id', '=', paper.id)])
        self.assertEqual(log.match_level, 'subject')

    def test_replacement_never_duplicates_within_paper(self):
        old = self._create_question()
        already_present = self._create_question()
        spare = self._create_question()
        paper = self._create_paper([old, already_present])

        paper.action_replace_question(old.id)

        self.assertEqual(len(paper.questions), 2)
        self.assertIn(already_present, paper.questions)
        self.assertIn(spare, paper.questions)
        self.assertNotIn(old, paper.questions)

    def test_empty_pool_raises_user_error(self):
        old = self._create_question()
        paper = self._create_paper([old])

        with self.assertRaises(UserError) as error:
            paper.action_replace_question(old.id)
        self.assertIn('No question available in the question bank',
                      str(error.exception))
        self.assertIn(old, paper.questions)
        self.assertFalse(old.is_reserve)

    def test_blocked_when_paper_not_draft(self):
        old = self._create_question()
        self._create_question()
        paper = self._create_paper([old], paper_gen_done=True)

        with self.assertRaises(UserError):
            paper.action_replace_question(old.id)

    def test_unique_batch_excludes_sibling_paper_questions(self):
        criteria = self._create_criteria(unique=True)
        old = self._create_question()
        sibling_question = self._create_question()
        free_question = self._create_question()
        paper1 = self._create_paper([old], criteria=criteria)
        paper2 = self._create_paper([sibling_question], criteria=criteria)

        paper1.action_replace_question(old.id)

        self.assertIn(free_question, paper1.questions)
        self.assertNotIn(sibling_question, paper1.questions)
        self.assertIn(sibling_question, paper2.questions)

    def test_delegate_button_uses_context(self):
        old = self._create_question()
        bank = self._create_question()
        paper = self._create_paper([old])

        action = old.with_context(cbt_paper_id=paper.id).action_replace_question()

        self.assertEqual(action['tag'], 'reload')
        self.assertIn(bank, paper.questions)

    def test_delegate_without_context_raises(self):
        old = self._create_question()
        with self.assertRaises(UserError):
            old.action_replace_question()

    def test_replace_question_already_on_paper_raises(self):
        old = self._create_question()
        not_on_paper = self._create_question()
        paper = self._create_paper([old])
        with self.assertRaises(UserError):
            paper.action_replace_question(not_on_paper.id)

    def test_reserve_toggle_requires_review_on_approved(self):
        question = self._create_question(state='approved')
        user = self.env['res.users'].create({
            'name': 'Faculty User',
            'login': 'faculty_user',
            'groups_id': [(6, 0, [self.env.ref('cbt.group_cbt_faculty').id])],
        })
        with self.assertRaises(UserError):
            question.with_user(user).write({'is_reserve': True})
