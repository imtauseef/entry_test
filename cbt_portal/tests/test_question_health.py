from datetime import datetime, timedelta

from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestQuestionHealth(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        cls.subject = env['cbt.subject'].sudo().create({
            'name': 'Health Subject',
            'code': 'HEALTH',
        })
        cls.topic = env['cbt.subject.topic'].sudo().create({
            'name': 'Health Topic',
            'code': 'HEALTH-TOPIC',
            'subject_id': cls.subject.id,
        })
        cls.subtopic = env['cbt.subject.subtopic'].sudo().create({
            'name': 'Health Subtopic',
            'code': 'HEALTH-SUBTOPIC',
            'topic_id': cls.topic.id,
        })
        cls.question_type = env['cbt.question.type'].sudo().create({
            'name': 'Multiple Choice',
        })
        cls.skill = env['cbt.question.skill'].sudo().create({
            'name': 'Health Skill',
        })
        cls.difficulty = env['cbt.question.difficulty.level'].sudo().create({
            'name': 'Health Difficulty',
        })
        question_time = env['cbt.question.time'].sudo().create({
            'name': 'One minute',
        })
        cls.question = env['cbt.mcqs'].sudo().create({
            'subject_id': cls.subject.id,
            'topic_id': cls.topic.id,
            'stopic_id': cls.subtopic.id,
            'type_id': cls.question_type.id,
            'skill_id': cls.skill.id,
            'difficulty_level_id': cls.difficulty.id,
            'time_id': question_time.id,
            'question': '<p>Health question</p>',
            'option_quantity': '4',
            'ans1': '<p>Correct</p>',
            'ans1_correct': True,
            'ans2': '<p>Distractor B</p>',
            'ans3': '<p>Distractor C</p>',
            'ans4': '<p>Distractor D</p>',
            'ans2_correct': False,
            'ans3_correct': False,
            'ans4_correct': False,
        })

        program = env['cbt.program'].sudo().create({
            'name': 'Health Program',
            'code': 'HEALTH',
        })
        cls.slot = env['cbt.slot'].sudo().create({
            'name': 'Health Slot',
            'date': datetime.now().date(),
            'time': 9.0,
        })
        criteria = env['cbt.paper.criteria'].sudo().create({
            'name': 'Health Criteria',
            'duration': '60',
            'total_questions': '1',
            'total_questions_compute': '1',
            'program_ids': [(6, 0, [program.id])],
        })
        cls.generator = env['cbt.paper.generator'].sudo().create({
            'name': 'Health Generator',
            'criteria_id': criteria.id,
            'slot_id': cls.slot.id,
            'configure_paper': True,
            'total_paper': 1,
        })
        cls.paper = env['cbt.paper'].sudo().create({
            'name': 'Health Paper',
            'generator_id': cls.generator.id,
            'slot_id': cls.slot.id,
            'questions': [(6, 0, [cls.question.id])],
        })
        cls.participant = env['cbt.participant'].sudo().create({
            'name': 'Health Candidate',
            'login': 'health-candidate',
            'password': 'test-only',
            'program': program.id,
            'slot_id': cls.slot.id,
        })

    def _create_attempt(self, answer_position=None, completed=True,
                        end_time=None, duplicate_export=False):
        attempt = self.env['cbt.student.paper'].sudo().create({
            'main_paper_id': self.paper.id,
            'questions': [(6, 0, [self.question.id])],
            'participant_id': self.participant.id,
        })
        end_time = end_time or datetime.now()
        portal_paper = self.env['cbt.paper.export'].sudo().create({
            'server_id': attempt.id,
            'login': self.participant.login,
            'test_date': self.slot.date,
            'end_paper': completed,
            'end_paper_time': end_time if completed else False,
        })
        self._create_export_line(portal_paper, answer_position)

        if duplicate_export:
            duplicate = self.env['cbt.paper.export'].sudo().create({
                'server_id': attempt.id,
                'login': self.participant.login,
                'test_date': self.slot.date,
                'end_paper': completed,
                'end_paper_time': end_time if completed else False,
            })
            self._create_export_line(duplicate, duplicate_export)
        return attempt

    def _create_export_line(self, portal_paper, answer_position):
        line = self.env['cbt.paper.line.export'].sudo().create({
            'paper_id': portal_paper.id,
            'server_id': self.question.id,
            'name': self.question.question,
            'correct_answer': 'A',
        })
        options = self.env['cbt.paper.line.option.export'].sudo()
        option_records = options.create([
            {'question_id': line.id, 'name': '<p>Correct</p>'},
            {'question_id': line.id, 'name': '<p>Distractor B</p>'},
            {'question_id': line.id, 'name': '<p>Distractor C</p>'},
            {'question_id': line.id, 'name': '<p>Distractor D</p>'},
        ])
        if answer_position:
            line.answer = option_records[answer_position - 1].id

    def test_counts_completed_question_selections_once_per_attempt(self):
        self._create_attempt(answer_position=1)
        self._create_attempt(
            answer_position=2, duplicate_export=3)
        self._create_attempt(answer_position=3, completed=False)
        self._create_attempt(
            answer_position=4,
            end_time=datetime.now() + timedelta(days=1))
        self._create_attempt()

        counts = self.question.sudo()._cbt_question_health_counts()
        self.assertEqual(dict(counts[self.question.id]), {1: 1, 3: 1})

    def test_health_html_is_read_only_summary_without_candidate_identity(self):
        self._create_attempt(answer_position=2)

        html = str(self.question.sudo().question_health_html)
        self.assertIn('Correct answer', html)
        self.assertIn('Distractor B', html)
        self.assertIn('Candidate selections', html)
        self.assertIn('o_cbt_health_warning', html)
        self.assertIn('o_cbt_health_distractor', html)
        self.assertNotIn(self.participant.login, html)

    def test_statistics_are_recomputed_after_a_response_changes(self):
        attempt = self._create_attempt(answer_position=1)
        counts = self.question.sudo()._cbt_question_health_counts()
        self.assertEqual(dict(counts[self.question.id]), {1: 1})

        portal_paper = self.env['cbt.paper.export'].sudo().search([
            ('server_id', '=', attempt.id),
        ], limit=1)
        line = portal_paper.line_ids.filtered(
            lambda row: row.server_id == self.question.id)
        line.answer = line.option_ids[1].id

        refreshed_counts = self.question.sudo()._cbt_question_health_counts()
        self.assertEqual(dict(refreshed_counts[self.question.id]), {2: 1})
