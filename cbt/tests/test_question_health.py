from datetime import datetime

from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestQuestionHealth(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        cls.subject = env['cbt.subject'].create({
            'name': 'Health Subject',
            'code': 'HEALTH',
        })
        cls.topic = env['cbt.subject.topic'].create({
            'name': 'Health Topic',
            'code': 'HEALTH-TOPIC',
            'subject_id': cls.subject.id,
        })
        cls.subtopic = env['cbt.subject.subtopic'].create({
            'name': 'Health Subtopic',
            'code': 'HEALTH-SUBTOPIC',
            'topic_id': cls.topic.id,
        })
        cls.question_type = env['cbt.question.type'].create({
            'name': 'Multiple Choice',
        })
        cls.skill = env['cbt.question.skill'].create({'name': 'Health Skill'})
        cls.difficulty = env['cbt.question.difficulty.level'].create({
            'name': 'Health Difficulty',
        })
        cls.question_time = env['cbt.question.time'].create({
            'name': 'One minute',
        })
        cls.question = env['cbt.mcqs'].create({
            'subject_id': cls.subject.id,
            'topic_id': cls.topic.id,
            'stopic_id': cls.subtopic.id,
            'type_id': cls.question_type.id,
            'skill_id': cls.skill.id,
            'difficulty_level_id': cls.difficulty.id,
            'time_id': cls.question_time.id,
            'question': '<p>Health question</p>',
            'option_quantity': '4',
            'ans1': '<p>Correct</p>',
            'ans1_correct': True,
            'ans2': '<p>Distractor B</p>',
            'ans3': '<p>Distractor C</p>',
            'ans4': '<p>Distractor D</p>',
        })

        program = env['cbt.program'].create({
            'name': 'Health Program',
            'code': 'HEALTH',
        })
        cls.slot = env['cbt.slot'].create({
            'name': 'Health Slot',
            'date': datetime.now().date(),
            'time': 9.0,
        })
        criteria = env['cbt.paper.criteria'].create({
            'name': 'Health Criteria',
            'duration': '60',
            'total_questions': '1',
            'total_questions_compute': '1',
            'program_ids': [(6, 0, [program.id])],
        })
        generator = env['cbt.paper.generator'].create({
            'name': 'Health Generator',
            'criteria_id': criteria.id,
            'slot_id': cls.slot.id,
            'configure_paper': True,
            'total_paper': 1,
        })
        cls.paper = env['cbt.paper'].create({
            'name': 'Health Paper',
            'generator_id': generator.id,
            'slot_id': cls.slot.id,
            'questions': [(6, 0, [cls.question.id])],
        })
        cls.participant = env['cbt.participant'].create({
            'name': 'Health Candidate',
            'login': 'health-candidate',
            'password': 'test-only',
            'program': program.id,
            'slot_id': cls.slot.id,
        })

    def _create_conduct(self, answer, question=None, allocation=None):
        if allocation is None:
            allocation = self.env['cbt.student.paper'].create({
                'main_paper_id': self.paper.id,
                'questions': [(6, 0, [self.question.id])],
                'participant_id': self.participant.id,
            })
        conduct = self.env['cbt.paper.conduct'].create({
            'paper_id': allocation.id,
            'date': datetime.now().date(),
        })
        self.env['cbt.paper.attempt'].create({
            'question_id': (question or self.question).id,
            'participant_answer': answer,
            'attempt_id': conduct.id,
        })
        return allocation, conduct

    def test_counts_imported_answers_once_per_generated_paper(self):
        self._create_conduct('A')
        allocation, _conduct = self._create_conduct('B')
        self._create_conduct('D', allocation=allocation)
        self._create_conduct(False)
        other_question = self.env['cbt.mcqs'].create({
            'subject_id': self.subject.id,
            'topic_id': self.topic.id,
            'stopic_id': self.subtopic.id,
            'type_id': self.question_type.id,
            'skill_id': self.skill.id,
            'difficulty_level_id': self.difficulty.id,
            'time_id': self.question_time.id,
            'question': '<p>Unallocated question</p>',
            'ans1': '<p>Option</p>',
            'ans1_correct': True,
        })
        self._create_conduct('C', question=other_question)

        counts = self.question._cbt_question_health_counts()
        self.assertEqual(dict(counts[self.question.id]), {1: 1, 4: 1})

    def test_refresh_recomputes_imported_result_statistics(self):
        self._create_conduct('A')
        question = self.question.sudo()
        health_before = str(question.question_health_html)
        self.assertIn('o_cbt_health_correct', health_before)

        self._create_conduct('A')
        question.action_refresh_question_health()
        health_after = str(question.question_health_html)

        self.assertIn('<td>2</td>', health_after)
