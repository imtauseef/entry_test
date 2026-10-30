# -*- coding: utf-8 -*-
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

    def test_role_scope_must_match_hierarchy(self):
        with self.assertRaises(ValidationError):
            self.env['cbt.employee.role'].create({
                'employee_id': self.creator_employee.id,
                'subject_id': self.subject_a.id,
                'topic_id': self.topic_b.id,
            })

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
