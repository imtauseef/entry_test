# -*- coding: utf-8 -*-
from datetime import datetime, timedelta

from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestFacultyAccess(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        faculty_group = env.ref('cbt.group_cbt_faculty')
        admin_group = env.ref('cbt.group_cbt_admin')
        internal_group = env.ref('base.group_user')

        cls.faculty = env['res.users'].create({
            'name': 'Faculty A',
            'login': 'faculty-a',
            'groups_id': [(6, 0, [internal_group.id, faculty_group.id])],
        })
        cls.creator = env['res.users'].create({
            'name': 'Creator A',
            'login': 'creator-a',
            'groups_id': [(6, 0, [internal_group.id, faculty_group.id])],
        })
        cls.admin = env['res.users'].create({
            'name': 'CBT Admin',
            'login': 'cbt-admin',
            'groups_id': [(6, 0, [internal_group.id, admin_group.id])],
        })

        cls.faculty_employee = env['hr.employee'].create({
            'name': 'Faculty A',
            'user_id': cls.faculty.id,
        })
        cls.creator_employee = env['hr.employee'].create({
            'name': 'Creator A',
            'user_id': cls.creator.id,
        })

        cls.subject_a = env['cbt.subject'].create({
            'name': 'Subject A', 'code': 'SUB-A'})
        cls.subject_b = env['cbt.subject'].create({
            'name': 'Subject B', 'code': 'SUB-B'})
        cls.topic_a = env['cbt.subject.topic'].create({
            'name': 'Topic A', 'code': 'TOP-A',
            'subject_id': cls.subject_a.id})
        cls.topic_b = env['cbt.subject.topic'].create({
            'name': 'Topic B', 'code': 'TOP-B',
            'subject_id': cls.subject_b.id})
        cls.subtopic_a = env['cbt.subject.subtopic'].create({
            'name': 'Sub Topic A', 'code': 'SUB-TOP-A',
            'topic_id': cls.topic_a.id})
        cls.subtopic_b = env['cbt.subject.subtopic'].create({
            'name': 'Sub Topic B', 'code': 'SUB-TOP-B',
            'topic_id': cls.topic_b.id})

        cls.faculty_role = env['cbt.employee.role'].create({
            'employee_id': cls.faculty_employee.id,
            'subject_id': cls.subject_a.id,
            'create_access': True,
            'review_access': True,
        })
        cls.creator_role = env['cbt.employee.role'].create({
            'employee_id': cls.creator_employee.id,
            'subject_id': cls.subject_a.id,
            'create_access': True,
            'review_access': False,
        })

        cls.question_type = env['cbt.question.type'].create({
            'name': 'Multiple Choice'})
        cls.question_skill = env['cbt.question.skill'].create({
            'name': 'Knowledge'})
        cls.difficulty = env['cbt.question.difficulty.level'].create({
            'name': 'Easy'})
        cls.question_time = env['cbt.question.time'].create({
            'name': 'One minute'})

        cls.own_draft = cls._question(
            cls.subject_a, cls.topic_a, cls.subtopic_a,
            state='draft', current_user=cls.faculty)
        cls.other_draft = cls._question(
            cls.subject_a, cls.topic_a, cls.subtopic_a,
            state='draft', current_user=cls.creator)
        cls.submitted_a = cls._question(
            cls.subject_a, cls.topic_a, cls.subtopic_a,
            state='submitted', current_user=cls.creator)
        cls.approved_a = cls._question(
            cls.subject_a, cls.topic_a, cls.subtopic_a,
            state='approved', current_user=cls.creator)
        cls.approved_b = cls._question(
            cls.subject_b, cls.topic_b, cls.subtopic_b,
            state='approved', current_user=cls.creator)
        cls.submitted_b = cls._question(
            cls.subject_b, cls.topic_b, cls.subtopic_b,
            state='submitted', current_user=cls.creator)

    @classmethod
    def _question(cls, subject, topic, subtopic, state, current_user):
        values = {
            'subject_id': subject.id,
            'topic_id': topic.id,
            'stopic_id': subtopic.id,
            'type_id': cls.question_type.id,
            'skill_id': cls.question_skill.id,
            'difficulty_level_id': cls.difficulty.id,
            'time_id': cls.question_time.id,
            'question': '<p>Question</p>',
            'ans1': '<p>A</p>',
            'ans2': '<p>B</p>',
            'ans3': '<p>C</p>',
            'ans4': '<p>D</p>',
            'ans1_correct': True,
            'state': state,
            'current_user': current_user.id,
        }
        return cls.env['cbt.mcqs'].create(values)

    def test_subject_master_scope(self):
        faculty_env = self.env(user=self.faculty)
        subjects = faculty_env['cbt.subject'].search([])
        self.assertIn(self.subject_a, subjects)
        self.assertNotIn(self.subject_b, subjects)

        topics = faculty_env['cbt.subject.topic'].search([])
        self.assertIn(self.topic_a, topics)
        self.assertNotIn(self.topic_b, topics)

        subtopics = faculty_env['cbt.subject.subtopic'].search([])
        self.assertIn(self.subtopic_a, subtopics)
        self.assertNotIn(self.subtopic_b, subtopics)

        roles = faculty_env['cbt.employee.role'].search([])
        self.assertIn(self.faculty_role, roles)
        self.assertNotIn(self.creator_role, roles)

    def test_question_read_scope_and_visibility(self):
        questions = self.env['cbt.mcqs'].with_user(self.faculty).search([])
        self.assertIn(self.own_draft, questions)
        self.assertIn(self.submitted_a, questions)
        self.assertIn(self.approved_a, questions)
        self.assertNotIn(self.other_draft, questions)
        self.assertNotIn(self.approved_b, questions)
        self.assertNotIn(self.submitted_b, questions)

    def test_question_write_is_subject_scoped(self):
        self.own_draft.with_user(self.faculty).write({
            'question': '<p>Updated</p>'})
        with self.assertRaises(AccessError):
            self.approved_b.with_user(self.faculty).write({
                'question': '<p>Not allowed</p>'})

    def test_question_create_outside_scope_rejected(self):
        values = {
            'subject_id': self.subject_b.id,
            'topic_id': self.topic_b.id,
            'stopic_id': self.subtopic_b.id,
            'type_id': self.question_type.id,
            'skill_id': self.question_skill.id,
            'difficulty_level_id': self.difficulty.id,
            'time_id': self.question_time.id,
            'question': '<p>Outside</p>',
            'ans1': '<p>A</p>',
            'ans2': '<p>B</p>',
            'ans3': '<p>C</p>',
            'ans4': '<p>D</p>',
        }
        with self.assertRaises(UserError):
            self.env['cbt.mcqs'].with_user(self.faculty).create(values)

    def test_question_create_topic_must_belong_to_subject(self):
        values = {
            'subject_id': self.subject_a.id,
            'topic_id': self.topic_b.id,
            'stopic_id': self.subtopic_b.id,
            'type_id': self.question_type.id,
            'skill_id': self.question_skill.id,
            'difficulty_level_id': self.difficulty.id,
            'time_id': self.question_time.id,
            'question': '<p>Mismatch</p>',
            'ans1': '<p>A</p>',
            'ans2': '<p>B</p>',
            'ans3': '<p>C</p>',
            'ans4': '<p>D</p>',
        }
        with self.assertRaises(UserError):
            self.env['cbt.mcqs'].with_user(self.faculty).create(values)

    def test_question_create_within_scope_allowed(self):
        question = self.env['cbt.mcqs'].with_user(self.faculty).create({
            'subject_id': self.subject_a.id,
            'topic_id': self.topic_a.id,
            'stopic_id': self.subtopic_a.id,
            'type_id': self.question_type.id,
            'skill_id': self.question_skill.id,
            'difficulty_level_id': self.difficulty.id,
            'time_id': self.question_time.id,
            'question': '<p>Allowed</p>',
            'ans1': '<p>A</p>',
            'ans2': '<p>B</p>',
            'ans3': '<p>C</p>',
            'ans4': '<p>D</p>',
        })
        self.assertEqual(question.current_user, self.faculty)
        self.assertEqual(question.state, 'draft')

    def test_question_hierarchy_constraint_applies_to_admin_writes(self):
        with self.assertRaises(ValidationError):
            self.own_draft.sudo().write({
                'subject_id': self.subject_b.id,
            })

        with self.assertRaises(ValidationError):
            self.own_draft.sudo().write({
                'stopic_id': self.subtopic_b.id,
            })

    def test_question_onchanges_clear_invalid_children(self):
        question = self.env['cbt.mcqs'].new({
            'subject_id': self.subject_b.id,
            'topic_id': self.topic_a.id,
            'stopic_id': self.subtopic_a.id,
        })
        question._get_topic()
        self.assertFalse(question.topic_id)
        self.assertFalse(question.stopic_id)

        question.topic_id = self.topic_b
        question.stopic_id = self.subtopic_a
        question._get_subtopic()
        self.assertFalse(question.stopic_id)

    def test_legacy_ids_are_optional_and_assignable(self):
        program = self.env['cbt.program'].create({
            'name': 'Legacy Program',
            'code': 'LEGACY',
        })
        records = (
            program,
            self.subject_a,
            self.topic_a,
            self.subtopic_a,
            self.question_type,
            self.question_skill,
            self.difficulty,
            self.own_draft,
        )
        for index, record in enumerate(records, start=1):
            self.assertIn('old_id', record._fields)
            self.assertFalse(record.old_id)
            record.write({'old_id': 1000 + index})
            self.assertEqual(record.old_id, 1000 + index)

    def test_question_health_highlight_scenarios(self):
        get_classes = (
            self.env['cbt.mcqs']._cbt_question_health_option_classes)

        correct_high = get_classes({1: 30, 2: 15, 3: 10, 4: 5}, 1)
        self.assertEqual(correct_high[1], 'o_cbt_health_correct')
        self.assertTrue(all(not correct_high[i] for i in (2, 3, 4)))

        wrong_high = get_classes({1: 12, 2: 25, 3: 10, 4: 7}, 1)
        self.assertEqual(wrong_high[1], 'o_cbt_health_warning')
        self.assertEqual(wrong_high[2], 'o_cbt_health_distractor')
        self.assertFalse(wrong_high[3])
        self.assertFalse(wrong_high[4])

        tied_wrong = get_classes({1: 12, 2: 25, 3: 25, 4: 7}, 1)
        self.assertEqual(tied_wrong[2], 'o_cbt_health_distractor')
        self.assertEqual(tied_wrong[3], 'o_cbt_health_distractor')

        tied_correct = get_classes({1: 20, 2: 20, 3: 10, 4: 5}, 1)
        self.assertTrue(all(not value for value in tied_correct.values()))

        no_responses = get_classes({1: 0, 2: 0, 3: 0, 4: 0}, 1)
        self.assertTrue(all(not value for value in no_responses.values()))

        correct_unselected = get_classes({1: 0, 2: 8, 3: 3, 4: 1}, 1)
        self.assertEqual(correct_unselected[1], 'o_cbt_health_warning')
        self.assertEqual(correct_unselected[2], 'o_cbt_health_distractor')
        self.assertFalse(correct_unselected[3])
        self.assertFalse(correct_unselected[4])

        incomplete_answer_key = get_classes({1: 0, 2: 8}, None)
        self.assertTrue(all(not value
                            for value in incomplete_answer_key.values()))

    def test_question_health_refresh_requires_subject_review_access(self):
        with self.assertRaises(AccessError):
            self.own_draft.with_user(
                self.creator).action_refresh_question_health()

        action = self.own_draft.with_user(
            self.faculty).action_refresh_question_health()
        self.assertEqual(action['tag'], 'reload')

    def test_role_scope_must_match_hierarchy(self):
        with self.assertRaises(ValidationError):
            self.env['cbt.employee.role'].create({
                'employee_id': self.creator_employee.id,
                'subject_id': self.subject_a.id,
                'topic_id': self.topic_b.id,
            })

    def test_creator_cannot_see_own_submitted_until_approved(self):
        self.own_draft.with_user(self.faculty).action_submit()
        self.assertEqual(self.own_draft.state, 'submitted')

        faculty_questions = self.env['cbt.mcqs'].with_user(
            self.faculty).search([])
        self.assertNotIn(self.own_draft, faculty_questions)
        with self.assertRaises(AccessError):
            self.own_draft.with_user(self.faculty).read(['question'])
        with self.assertRaises(AccessError):
            self.own_draft.with_user(self.faculty).write({
                'state': 'approved'})

        self.own_draft.sudo().write({'state': 'approved'})
        self.own_draft.invalidate_recordset()

        faculty_questions = self.env['cbt.mcqs'].with_user(
            self.faculty).search([])
        self.assertIn(self.own_draft, faculty_questions)
        self.own_draft.with_user(self.faculty).read(['question'])

    def test_review_workflow_respects_scope(self):
        self.own_draft.with_user(self.faculty).action_submit()
        self.assertEqual(self.own_draft.state, 'submitted')

        self.submitted_a.with_user(self.faculty).approve_question()
        self.assertEqual(self.submitted_a.state, 'approved')

    def test_admin_sees_everything(self):
        questions = self.env['cbt.mcqs'].with_user(self.admin).search([])
        self.assertIn(self.approved_b, questions)
        self.assertIn(self.submitted_b, questions)
        subjects = self.env['cbt.subject'].with_user(self.admin).search([])
        self.assertIn(self.subject_a, subjects)
        self.assertIn(self.subject_b, subjects)

    def test_question_changes_are_audited(self):
        question = self._question(
            self.subject_a, self.topic_a, self.subtopic_a,
            state='draft', current_user=self.faculty)
        Audit = self.env['cbt.mcqs.audit.log']
        logs = Audit.search([('question_ref', '=', question.id)])
        self.assertTrue(logs.filtered(lambda log: log.action == 'create'))

        question.write({'question': '<p>Updated question</p>'})
        logs = Audit.search([('question_ref', '=', question.id)])
        update_logs = logs.filtered(lambda log: log.action == 'update')
        self.assertTrue(update_logs)
        self.assertTrue(any(
            'Question' in (log.change_summary or '')
            for log in update_logs))

        question_name = question.display_name
        question.unlink()
        logs = Audit.search([('question_ref', '=', question.id)])
        delete_logs = logs.filtered(lambda log: log.action == 'delete')
        self.assertEqual(len(delete_logs), 1)
        self.assertFalse(delete_logs.question_id)
        self.assertEqual(delete_logs.question_name, question_name)

    def test_question_option_quantity_controls_options(self):
        question = self._question(
            self.subject_a, self.topic_a, self.subtopic_a,
            state='draft', current_user=self.faculty)
        self.assertEqual(question.option_quantity, '4')

        question.write({
            'option_quantity': '6',
            'ans5': '<p>E</p>',
            'ans6': '<p>F</p>',
        })
        self.assertTrue(question.ans5)
        self.assertTrue(question.ans6)

        question.write({'option_quantity': '2'})
        self.assertFalse(question.ans3)
        self.assertFalse(question.ans4)
        self.assertFalse(question.ans5)
        self.assertFalse(question.ans6)

        with self.assertRaises(ValidationError):
            question.write({'ans1_correct': False})

    def test_theory_question_has_no_answer_options(self):
        theory_type = self.env['cbt.question.type'].create({
            'name': 'Theory', 'code': 'THEORY'})
        self.assertTrue(
            self.env['cbt.mcqs']._cbt_is_theory_type(theory_type.id))

        theory_question = self.env['cbt.mcqs'].create({
            'subject_id': self.subject_a.id,
            'topic_id': self.topic_a.id,
            'stopic_id': self.subtopic_a.id,
            'type_id': theory_type.id,
            'skill_id': self.question_skill.id,
            'difficulty_level_id': self.difficulty.id,
            'time_id': self.question_time.id,
            'question': '<p>Explain the theory.</p>',
            'state': 'draft',
            'current_user': self.faculty.id,
        })
        self.assertTrue(theory_question.is_theory)
        self.assertFalse(theory_question.ans1)
        self.assertFalse(theory_question.ans2)

        theory_question.write({
            'ans1': '<p>Ignored</p>',
            'ans1_correct': True,
        })
        self.assertFalse(theory_question.ans1)
        self.assertFalse(theory_question.ans1_correct)

        descriptive_type = self.env['cbt.question.type'].create({
            'name': 'Long Answer', 'is_theory': True})
        self.assertTrue(
            self.env['cbt.mcqs']._cbt_is_theory_type(descriptive_type.id))

        with self.assertRaises(ValidationError):
            self.env['cbt.mcqs'].create({
                'subject_id': self.subject_a.id,
                'topic_id': self.topic_a.id,
                'stopic_id': self.subtopic_a.id,
                'type_id': self.question_type.id,
                'skill_id': self.question_skill.id,
                'difficulty_level_id': self.difficulty.id,
                'time_id': self.question_time.id,
                'question': '<p>No options.</p>',
                'state': 'draft',
                'current_user': self.faculty.id,
            })

    def _active_paper_for(self, question):
        criteria = self.env['cbt.paper.criteria'].create({
            'name': 'Criteria'})
        slot = self.env['cbt.slot'].create({
            'name': 'Slot',
            'date': datetime.now().date(),
            'time': 9.0,
        })
        generator = self.env['cbt.paper.generator'].create({
            'name': 'Generator',
            'criteria_id': criteria.id,
            'slot_id': slot.id,
        })
        paper = self.env['cbt.paper'].create({
            'name': 'Paper',
            'generator_id': generator.id,
            'slot_id': slot.id,
            'questions': [(6, 0, [question.id])],
        })
        paper.write({'student_paper_gen': True})
        return paper

    def test_faculty_can_suspend_approved_question(self):
        now = datetime.now()
        self.approved_a.with_user(self.creator)._cbt_suspend(
            'Content review', now, now + timedelta(days=1))
        self.assertTrue(
            self.approved_a.with_user(self.creator).is_suspended)

    def test_suspend_question_with_reason_and_cron_resume(self):
        now = datetime.now()
        question = self._question(
            self.subject_a, self.topic_a, self.subtopic_a,
            state='approved', current_user=self.faculty)
        question._cbt_suspend(
            'Syllabus change', now, now + timedelta(days=2))
        question.invalidate_recordset()
        self.assertTrue(question.is_suspended)
        self.assertFalse(question.can_suspend)
        self.assertNotIn(
            question,
            self.env['cbt.mcqs']._get_generation_pool(
                [('id', '=', question.id)]))

        with self.assertRaises(ValidationError):
            question._cbt_suspend(
                '', now, now + timedelta(days=1))

        expired = self._question(
            self.subject_a, self.topic_a, self.subtopic_a,
            state='approved', current_user=self.faculty)
        expired._cbt_suspend(
            'Temporary outage',
            now - timedelta(days=2), now - timedelta(days=1))
        self.env['cbt.mcqs']._cron_resume_suspended_questions()

        expired.invalidate_recordset()
        question.invalidate_recordset()
        self.assertFalse(expired.is_suspended)
        self.assertFalse(expired.suspension_reason)
        self.assertTrue(question.is_suspended)

    def test_suspend_hidden_for_question_in_active_paper(self):
        question = self._question(
            self.subject_a, self.topic_a, self.subtopic_a,
            state='approved', current_user=self.faculty)
        self._active_paper_for(question)
        question.invalidate_recordset()

        self.assertFalse(question.can_suspend)
        with self.assertRaises(UserError):
            question.action_suspend()
