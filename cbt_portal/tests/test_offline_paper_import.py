# -*- coding: utf-8 -*-
import base64
import hashlib
import io
import json
import zipfile
from datetime import datetime
from unittest import mock

from odoo import fields
from odoo.addons.cbt.models.allocation_xlsx import (
    build_allocation_xlsx,
    decrypt_xlsx,
    encrypt_xlsx,
    load_allocation_xlsx,
)
from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase


class TestOfflinePaperImport(TransactionCase):

    def setUp(self):
        super().setUp()
        self.odoo_password = 'offline-test-admin-password'
        self.workbook_password = 'offline-transfer-password-2026'
        self.env.user.sudo().write({'password': self.odoo_password})
        self.participant = self.env['cbt.participant'].create({
            'name': 'Offline Import Candidate',
            'login': 'offline-import-candidate',
            'password': 'test-password',
            'cid': 9876,
        })
        user_sync = self.participant._sync_portal_user()
        self.portal_user = self.env['res.users'].sudo().browse(
            user_sync['user_id'])
        self.source_system_id = 'source-system-test'
        self.source_export_id = (
            '%s:cbt.student.paper:20' % self.source_system_id)
        self.source_student_id = (
            '%s:cbt.participant:10' % self.source_system_id)
        self.source_question_id = (
            '%s:cbt.mcqs:30' % self.source_system_id)
        self.allocation = [
            self.source_export_id,
            '%s:cbt.paper.generator:5' % self.source_system_id,
            self.source_student_id,
            self.participant.login,
            self.participant.name,
            9876,
            self.source_export_id,
            '%s:cbt.paper:15' % self.source_system_id,
            'Offline Test Paper',
            '',
            '',
            '2026-10-26',
            9.5,
            90,
            False,
            '%s:cbt.slot:8' % self.source_system_id,
        ]
        self.questions = [[
            self.source_student_id,
            self.source_export_id,
            self.source_question_id,
            'Mathematics',
            '<p>Unicode: سوالات</p>\n<p>Question body</p>',
            1,
            False,
            'B',
        ], [
            self.source_student_id,
            self.source_export_id,
            '%s:cbt.mcqs:31' % self.source_system_id,
            'Mathematics',
            '<p>Question two</p>',
            2,
            False,
            'A',
        ]]
        self.options = [
            [
                self.source_student_id,
                self.source_export_id,
                self.source_question_id,
                '%s:option:1' % self.source_question_id,
                1,
                'A',
                '<p>First</p>',
            ],
            [
                self.source_student_id,
                self.source_export_id,
                self.source_question_id,
                '%s:option:2' % self.source_question_id,
                2,
                'B',
                '<p>Second</p>',
            ],
            [
                self.source_student_id,
                self.source_export_id,
                '%s:cbt.mcqs:31' % self.source_system_id,
                '%s:cbt.mcqs:31:option:1' % self.source_system_id,
                1,
                'A',
                '<p>Third</p>',
            ],
            [
                self.source_student_id,
                self.source_export_id,
                '%s:cbt.mcqs:31' % self.source_system_id,
                '%s:cbt.mcqs:31:option:2' % self.source_system_id,
                2,
                'B',
                '<p>Fourth</p>',
            ],
        ]

    def _workbook(self, question_text=None):
        questions = [row[:] for row in self.questions]
        if question_text is not None:
            questions[0][4] = question_text
        payload = {
            'paper_export': self.allocation,
            'questions': self.questions,
            'options': self.options,
        }
        payload_hash = hashlib.sha256(json.dumps(
            payload, ensure_ascii=False, sort_keys=True,
            separators=(',', ':'),
        ).encode('utf-8')).hexdigest()

        return base64.b64encode(build_allocation_xlsx([
            ('Manifest', [
                ['schema_version', '4.0'],
                ['source_system_id', self.source_system_id],
                ['source_generator_id', self.allocation[1]],
                ['source_generator_name', 'Offline Test Generator'],
                ['export_id', 'offline-test-export'],
                ['paper_export_count', 1],
                ['participant_count', 1],
                ['image_count', 0],
                ['paper_export_model', 'cbt.paper.export'],
                ['allocation_warning', ''],
            ]),
            ('Participants', [[
                'source_student_id', 'login', 'name', 'password',
            ], [
                self.source_student_id,
                self.participant.login,
                self.participant.name,
                self.participant.password,
            ]]),
            ('Papers', [[
                'source_export_id', 'source_generator_id', 'source_student_id',
                'login', 'name', 'cid', 'source_paper_id',
                'source_template_paper_id', 'paper_name', 'program',
                'test_center', 'test_date', 'test_time', 'test_duration',
                'shuffle_section', 'source_schedule_id', 'payload_sha256',
            ], self.allocation + [payload_hash]]),
            ('Questions', [[
                'source_student_id', 'source_paper_id', 'source_question_id',
                'subject_name', 'name', 'question_order', 'is_theory',
                'correct_answer',
            ]] + questions),
            ('Answer Options', [[
                'source_student_id', 'source_paper_id', 'source_question_id',
                'source_option_id', 'sequence', 'option_label', 'name',
            ]] + self.options),
            ('Images', [[
                'image_key', 'mimetype', 'chunk_index', 'chunk_count',
                'data_base64',
            ]]),
        ]))

    def _create_wizard(self, workbook):
        return self.env['cbt.paper.import.wizard'].create({
            'xlsx_file': workbook,
            'name': 'offline-allocation.xlsx',
        })

    def _import_allocation(self, wizard, workbook_password=''):
        return wizard._import_workbook(
            odoo_password=self.odoo_password,
            workbook_password=workbook_password)

    def test_import_requires_admin_and_workbook_passwords(self):
        wizard = self._create_wizard(b'not-an-xlsx-file')
        with self.assertRaisesRegex(UserError, 'Odoo login password is incorrect'):
            wizard._import_workbook(
                odoo_password='incorrect-admin-password',
                workbook_password='irrelevant')

        encrypted = encrypt_xlsx(
            base64.b64decode(self._workbook()),
            self.workbook_password)
        protected_wizard = self._create_wizard(
            base64.b64encode(encrypted))
        with self.assertRaisesRegex(UserError, 'workbook is password-protected'):
            self._import_allocation(protected_wizard)
        with self.assertRaisesRegex(UserError, 'workbook password is incorrect'):
            self._import_allocation(protected_wizard, 'incorrect-workbook-password')
        self.assertFalse(self.env['cbt.paper.export'].search_count([
            ('source_export_id', '=', self.source_export_id),
        ]))

    def test_import_recreates_candidate_paper_and_reimport_is_idempotent(self):
        self.portal_user.sudo().write({'password': 'portal-current-secret'})
        password_hash = self.portal_user.sudo().password
        wizard = self._create_wizard(self._workbook())
        result = self._import_allocation(wizard)
        self.assertEqual(result['tag'], 'display_notification')
        self.assertEqual(result['params']['type'], 'success')
        self.assertIn('Created 1 paper allocation(s)', result['params']['message'])
        self.assertIn('1 section(s)', result['params']['message'])
        self.assertIn('2 question(s)', result['params']['message'])
        self.assertIn('4 answer option(s)', result['params']['message'])
        self.assertIn('Skipped 0 identical allocation(s)', result['params']['message'])

        paper = self.env['cbt.paper.export'].search([
            ('source_export_id', '=', self.source_export_id),
        ])
        self.assertEqual(len(paper), 1)
        self.assertFalse(paper.participant_id)
        self.assertEqual(paper.user_id, self.portal_user.id)
        self.assertEqual(paper.login, self.portal_user.login)
        self.assertEqual(self.portal_user.sudo().password, password_hash)
        self.assertEqual(paper.server_id, 20)
        self.assertEqual(paper.test_duration, 90)
        self.assertEqual(paper.test_time, 9.5)
        self.assertEqual(paper.current_q, 1)
        self.assertFalse(paper.paper_started)
        self.assertFalse(paper.end_paper)
        self.assertFalse(paper.last_session_token)
        self.assertEqual(len(paper.line_ids), 2)
        ordered_lines = paper.line_ids.sorted('sequence')
        self.assertEqual(ordered_lines.mapped('server_id'), [30, 31])
        self.assertEqual(
            ordered_lines.mapped('name'),
            [self.questions[0][4], self.questions[1][4]])
        line = ordered_lines[0]
        self.assertEqual(line.sequence, 1)
        self.assertEqual(line.server_id, 30)
        self.assertEqual(line.correct_answer, 'B')
        self.assertEqual(line.name, self.questions[0][4])
        self.assertEqual(
            line.option_ids.sorted('sequence').mapped('name'),
            ['<p>First</p>', '<p>Second</p>'],
        )
        self.assertEqual(line.option_ids.sorted('sequence').mapped('sequence'), [1, 2])
        self.assertEqual(
            ordered_lines[1].option_ids.sorted('sequence').mapped('name'),
            ['<p>Third</p>', '<p>Fourth</p>'])

        line.answer = line.option_ids.sorted('sequence')[1].id
        paper.paper_started = '2026-10-26 09:00:00'
        self._import_allocation(wizard)
        self.assertEqual(
            self.env['cbt.paper.export'].search_count([
                ('source_export_id', '=', self.source_export_id),
            ]),
            1,
        )
        self.assertEqual(line.answer, line.option_ids.sorted('sequence')[1].id)
        self.assertTrue(paper.paper_started)

    def test_import_provisions_missing_portal_user_from_participant_sheet(self):
        self.portal_user.write({'login': 'different-existing-portal-user'})
        wizard = self._create_wizard(self._workbook())

        result = self._import_allocation(wizard)

        self.assertIn('Provisioned 1 new portal user(s)', result['params']['message'])
        provisioned_user = self.env['res.users'].sudo().search([
            ('login', '=', self.participant.login),
        ], limit=1)
        self.assertTrue(provisioned_user)
        self.assertTrue(provisioned_user.active)
        self.assertTrue(provisioned_user._cbt_is_portal_only())
        self.assertIn(
            self.env.ref('base.group_portal'),
            provisioned_user.groups_id)
        self.assertNotEqual(provisioned_user.password, self.participant.password)
        paper = self.env['cbt.paper.export'].search([
            ('source_export_id', '=', self.source_export_id),
        ])
        self.assertEqual(paper.user_id, provisioned_user.id)

    def test_invalid_payload_is_rejected_without_creating_paper(self):
        loaded = self._create_wizard(self._workbook(
            question_text='<p>Tampered</p>'))
        with self.assertRaises(UserError):
            self._import_allocation(loaded)
        self.assertFalse(self.env['cbt.paper.export'].search([
            ('source_export_id', '=', self.source_export_id),
        ]))

    def test_unsupported_file_extension_is_rejected(self):
        wizard = self._create_wizard(self._workbook())
        wizard.name = 'allocation.xls'
        with self.assertRaises(UserError):
            self._import_allocation(wizard)
        self.assertFalse(self.env['cbt.paper.export'].search([
            ('source_export_id', '=', self.source_export_id),
        ]))

    def test_candidate_paper_expires_at_server_side_duration_deadline(self):
        paper = self.env['cbt.paper.export'].create({
            'test_duration': 60,
            'paper_started': '2026-10-28 10:00:00',
        })
        session = self.env['cbt.paper.session'].create({
            'paper_id': paper.id,
            'start_time': '2026-10-28 10:00:00',
        })
        before_deadline = datetime(2026, 10, 28, 10, 59, 59)
        deadline = datetime(2026, 10, 28, 11, 0, 0)

        self.assertEqual(paper._cbt_remaining_seconds(before_deadline), 1)
        self.assertFalse(paper._cbt_expire_if_time_up(before_deadline))
        self.assertFalse(paper.end_paper)
        self.assertTrue(paper._cbt_expire_if_time_up(deadline))
        self.assertTrue(paper.end_paper)
        self.assertEqual(
            fields.Datetime.to_string(paper.end_paper_time),
            '2026-10-28 11:00:00')
        self.assertEqual(session.end_time, '2026-10-28 11:00:00')
        self.assertEqual(paper._cbt_remaining_seconds(deadline), 0)

    def test_generator_export_is_importable_as_candidate_paper(self):
        self.env.user.write({
            'groups_id': [(4, self.env.ref('cbt.group_cbt_admin').id)],
        })
        program = self.env['cbt.program'].create({
            'name': 'Offline Test Program',
            'code': 'OFFLINE-IMPORT',
        })
        center = self.env['cbt.center'].create({
            'name': 'Offline Exam Center',
            'code': 'OFFLINE-CENTER',
        })
        slot = self.env['cbt.slot'].create({
            'name': 'Offline Test Slot',
            'date': fields.Date.from_string('2026-10-26'),
            'time': 9.5,
            'duration': 90,
            'center_id': center.id,
        })
        self.participant.write({
            'program': program.id,
            'slot_id': slot.id,
        })
        subject = self.env['cbt.subject'].create({'name': 'Mathematics'})
        topic = self.env['cbt.subject.topic'].create({
            'name': 'Algebra',
            'subject_id': subject.id,
        })
        subtopic = self.env['cbt.subject.subtopic'].create({
            'name': 'Equations',
            'topic_id': topic.id,
        })
        question_type = self.env['cbt.question.type'].create({'name': 'MCQ'})
        difficulty = self.env['cbt.question.difficulty.level'].create({
            'name': 'Easy',
        })
        skill = self.env['cbt.question.skill'].create({'name': 'Basic'})
        question_time = self.env['cbt.question.time'].create({'name': '60'})
        image_data = base64.b64decode(
            'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8z8BQDwAEhQ'
            'GAhKmMIQAAAABJRU5ErkJggg==')
        image_attachment = self.env['ir.attachment'].create({
            'name': 'offline-question.png',
            'type': 'binary',
            'datas': base64.b64encode(image_data),
            'mimetype': 'image/png',
        })
        question = self.env['cbt.mcqs'].create({
            'subject_id': subject.id,
            'topic_id': topic.id,
            'stopic_id': subtopic.id,
            'type_id': question_type.id,
            'difficulty_level_id': difficulty.id,
            'skill_id': skill.id,
            'time_id': question_time.id,
            'question': (
                '<p>What is 2 + 2?</p>'
                '<img src="/web/image/%s-offlinehash/offline-question.png"/>' %
                image_attachment.id),
            'ans1': False,
            'ans2': '<p>4</p>',
            'ans3': '<p>5</p>',
            'ans1_correct': False,
            'ans2_correct': False,
            'ans3_correct': True,
            'state': 'approved',
        })
        theory_type = self.env['cbt.question.type'].create({
            'name': 'Theory',
            'is_theory': True,
        })
        theory_question = self.env['cbt.mcqs'].create({
            'subject_id': subject.id,
            'topic_id': topic.id,
            'stopic_id': subtopic.id,
            'type_id': theory_type.id,
            'difficulty_level_id': difficulty.id,
            'skill_id': skill.id,
            'time_id': question_time.id,
            'question': '<p>Explain the solution.</p>',
            'state': 'approved',
        })
        criteria = self.env['cbt.paper.criteria'].create({
            'name': 'Offline Import Criteria',
            'duration': '90',
            'program_ids': [(6, 0, [program.id])],
            'random_section': True,
        })
        generator = self.env['cbt.paper.generator'].create({
            'name': 'Offline Import Generator',
            'criteria_id': criteria.id,
            'slot_id': slot.id,
            'configure_paper': True,
        })
        generated_paper = self.env['cbt.paper'].create({
            'name': 'Generated Offline Paper',
            'generator_id': generator.id,
            'slot_id': slot.id,
            'questions': [(6, 0, [question.id, theory_question.id])],
        })
        allocation = self.env['cbt.student.paper'].create({
            'main_paper_id': generated_paper.id,
            'participant_id': self.participant.id,
            'questions': [(6, 0, [question.id, theory_question.id])],
            'question_sequence': [question.id, theory_question.id],
        })

        with mock.patch(
                'odoo.fields.Datetime.now',
                return_value=datetime(2026, 10, 26, 10, 0)):
            generator.with_context(tz='UTC')._export_allocation_workbook(
                odoo_password=self.odoo_password,
                workbook_password=self.workbook_password)
        attachment = self.env['ir.attachment'].search([
            ('res_model', '=', 'cbt.paper.generator'),
            ('res_id', '=', generator.id),
        ], order='id desc', limit=1)
        self.assertTrue(attachment)
        self.assertFalse(zipfile.is_zipfile(io.BytesIO(
            base64.b64decode(attachment.datas))))
        workbook = load_allocation_xlsx(decrypt_xlsx(
            base64.b64decode(attachment.datas), self.workbook_password))
        paper_rows = list(workbook['Papers'].iter_rows(values_only=True))
        question_rows = list(workbook['Questions'].iter_rows(values_only=True))
        image_rows = list(workbook['Images'].iter_rows(values_only=True))
        self.assertEqual(len(paper_rows), 2)
        self.assertEqual(paper_rows[1][10], center.name)
        self.assertIn('cbt-offline-image:', question_rows[1][4])
        self.assertEqual(len(image_rows), 2)
        self.assertEqual(image_rows[1][1], 'image/png')
        self.assertEqual(paper_rows[1][0], (
            '%s:cbt.student.paper:%s' % (
                self.env['ir.config_parameter'].sudo().get_param(
                    'cbt.offline_source_system_id'),
                allocation.id,
            )))
        self.assertEqual(paper_rows[1][6], paper_rows[1][0])

        self.participant.write({'login': 'admin-instance-only'})
        import_result = self._import_allocation(
            self._create_wizard(attachment.datas), self.workbook_password)
        self.assertEqual(import_result['params']['type'], 'success')
        self.assertIn('Created 1 paper allocation(s)', import_result['params']['message'])
        imported = self.env['cbt.paper.export'].search([
            ('source_export_id', '=', paper_rows[1][0]),
        ])
        self.assertEqual(len(imported), 1)
        self.assertFalse(imported.participant_id)
        self.assertEqual(imported.user_id, self.portal_user.id)
        self.assertEqual(imported.batch_id.name, generator.name)
        self.assertEqual(imported.paper_name, generated_paper.name)
        self.assertEqual(imported.test_center, center.name)
        self.assertEqual(imported.test_date, slot.date)
        self.assertEqual(imported.test_time, slot.time)
        self.assertEqual(imported.test_duration, 90)
        self.assertEqual(imported.server_id, allocation.id)
        self.assertEqual(imported.program, program.name)
        self.assertEqual(imported.cid, 9876)
        self.assertTrue(imported.shuffle_section)
        self.assertEqual(imported.current_q, 1)
        self.assertFalse(imported.paper_started)
        self.assertFalse(imported.end_paper)
        self.assertFalse(imported.is_login)
        self.assertFalse(imported.session_ids)
        self.assertEqual(imported.batch_id.state, 'imported')
        self.assertEqual(imported.batch_id.name, 'Offline Test Generator')
        self.assertEqual(len(imported.line_ids), 2)
        imported_question = imported.line_ids.filtered(
            lambda line: line.server_id == question.id)
        imported_theory_question = imported.line_ids.filtered(
            lambda line: line.server_id == theory_question.id)
        self.assertEqual(imported_question.server_id, question.id)
        self.assertEqual(imported_question.sequence, 1)
        self.assertIn('data:image/png;base64,', imported_question.name)
        self.assertEqual(imported_question.source_student_id, (
            '%s:cbt.participant:%s' % (
                self.env['ir.config_parameter'].sudo().get_param(
                    'cbt.offline_source_system_id'),
                self.participant.id,
            )))
        self.assertEqual(imported_question.correct_answer, 'B')
        self.assertTrue(imported_theory_question.is_theory)
        self.assertFalse(imported_theory_question.option_ids)
        self.assertEqual(
            imported_question.option_ids.sorted('sequence').mapped('name'),
            ['<p>4</p>', '<p>5</p>'])
        self.assertEqual(
            imported_question.option_ids.sorted('sequence').mapped(
                'source_option_id'),
            [
                '%s:cbt.mcqs:%s:option:2' % (
                    self.env['ir.config_parameter'].sudo().get_param(
                        'cbt.offline_source_system_id'),
                    question.id,
                ),
                '%s:cbt.mcqs:%s:option:3' % (
                    self.env['ir.config_parameter'].sudo().get_param(
                        'cbt.offline_source_system_id'),
                    question.id,
                ),
            ])
        imported_question.write({
            'name': '<p>What is 2 + 2?</p>'
                    '<img src="/web/image/ir.attachment/999/datas"/>',
        })
        imported.write({
            'test_center': False,
            'source_payload_hash': 'legacy-offline-payload',
        })
        repeated_import = self._import_allocation(
            self._create_wizard(attachment.datas), self.workbook_password)
        self.assertIn(
            'Repaired 1 unstarted allocation(s)',
            repeated_import['params']['message'])
        self.assertIn('data:image/png;base64,', imported_question.name)
        self.assertEqual(imported.test_center, center.name)
        self.assertEqual(imported.source_payload_hash, paper_rows[1][-1])

        self.participant.write({'login': 'offline-import-candidate'})
        batch = imported.batch_id
        batch.action_start_test()
        imported.paper_started = '2026-10-26 09:00:00'
        imported_question.answer = imported_question.option_ids.sorted(
            'sequence')[1].id
        imported_question.answer_alphabet = 'B'
        imported_question.answer_recorded_time = '2026-10-26 09:15:00'
        feedback_type = self.env[
            'cbt.paper.question.feedback.type'].create({
                'name': 'Question wording concern',
            })
        self.env['cbt.paper.question.feedback'].create({
            'paper_id': imported.id,
            'question_id': imported_question.id,
            'feedback_type_id': feedback_type.id,
            'feedback_text': 'The wording is unclear.',
        })
        imported_theory_question.theory_answer = 'Show each algebraic step.'
        self.env['cbt.paper.question.feedback'].create({
            'paper_id': imported.id,
            'question_id': imported_theory_question.id,
            'feedback_text': 'Please check the question data.',
        })
        imported_theory_question.answer_recorded_time = '2026-10-26 09:16:00'
        imported_theory_question.mark_review = True
        with mock.patch(
                'odoo.fields.Datetime.now',
                return_value=datetime(2026, 10, 26, 10, 0)):
            batch.action_finish_test()
        result_action = batch._action_export_results(
            odoo_password=self.odoo_password,
            workbook_password=self.workbook_password)
        self.assertEqual(batch.state, 'result_collected')
        self.assertEqual(result_action['type'], 'ir.actions.act_url')

        result_attachment = self.env['ir.attachment'].search([
            ('res_model', '=', 'cbt.paper.export.batch'),
            ('res_id', '=', batch.id),
        ], order='id desc', limit=1)
        self.assertFalse(zipfile.is_zipfile(io.BytesIO(
            base64.b64decode(result_attachment.datas))))
        result_workbook = load_allocation_xlsx(decrypt_xlsx(
            base64.b64decode(result_attachment.datas),
            self.workbook_password))
        result_answer_rows = list(
            result_workbook['Answers'].iter_rows(values_only=True))
        result_paper_rows = list(
            result_workbook['Papers'].iter_rows(values_only=True))
        result_manifest_rows = list(
            result_workbook['Manifest'].iter_rows(values_only=True))
        self.assertEqual(result_manifest_rows[0], ('schema_version', '1.2'))
        self.assertIn('candidate_name', result_paper_rows[0])
        self.assertIn('paper_name', result_paper_rows[0])
        self.assertEqual(result_paper_rows[1][4], imported.name)
        self.assertEqual(result_paper_rows[1][5], imported.paper_name)
        self.assertNotIn('correct_answer', result_answer_rows[0])
        self.assertEqual(result_answer_rows[1][4], 'B')
        self.assertEqual(result_answer_rows[1][5], (
            '%s:cbt.mcqs:%s:option:3' % (
                self.env['ir.config_parameter'].sudo().get_param(
                    'cbt.offline_source_system_id'),
                question.id,
            )))
        self.assertEqual(result_answer_rows[2][6], 'Show each algebraic step.')
        self.assertTrue(result_answer_rows[2][8])
        self.assertIn('feedback_type', result_answer_rows[0])
        self.assertEqual(result_answer_rows[1][9], 'Question wording concern')
        self.assertEqual(result_answer_rows[1][10], 'The wording is unclear.')
        self.assertFalse(result_answer_rows[2][9])
        self.assertEqual(
            result_answer_rows[2][10], 'Please check the question data.')

        result_import = self.env['cbt.paper.result.import.wizard'].create({
            'xlsx_file': result_attachment.datas,
            'name': 'offline-results.xlsx',
        })
        allocation.question_sequence = list(reversed(
            allocation.question_sequence))
        result_import._import_workbook(
            odoo_password=self.odoo_password,
            workbook_password=self.workbook_password)
        conduct = self.env['cbt.paper.conduct'].search([
            ('paper_id', '=', allocation.id),
        ])
        self.assertEqual(len(conduct), 1)
        self.assertEqual(conduct.result_batch_id.source_batch_export_id,
                         batch.source_export_id)
        self.assertEqual(
            conduct.result_batch_id.paper_generate_id,
            allocation.main_paper_id.generator_id)
        self.assertEqual(conduct.score, 1)
        imported_attempt = conduct.question_attempt_id
        mcq_attempt = imported_attempt.filtered(
            lambda attempt: attempt.question_id == question)
        theory_attempt = imported_attempt.filtered(
            lambda attempt: attempt.question_id == theory_question)
        self.assertEqual(mcq_attempt.participant_answer, 'C')
        self.assertEqual(mcq_attempt.score, 1)
        self.assertEqual(theory_attempt.theory_answer, 'Show each algebraic step.')
        self.assertTrue(theory_attempt.mark_review)
        imported_feedback = self.env['cbt.mcqs.feedback'].search([
            ('conduct_id', '=', conduct.id),
            ('question_id', '=', question.id),
        ])
        self.assertEqual(len(imported_feedback), 1)
        self.assertEqual(
            imported_feedback.candidate_id, self.participant)
        self.assertEqual(imported_feedback.candidate_name, self.participant.name)
        self.assertEqual(
            imported_feedback.feedback_type, 'Question wording concern')
        self.assertEqual(
            imported_feedback.feedback_text, 'The wording is unclear.')
        imported_text_feedback = self.env['cbt.mcqs.feedback'].search([
            ('conduct_id', '=', conduct.id),
            ('question_id', '=', theory_question.id),
        ])
        self.assertEqual(
            imported_text_feedback.feedback_text,
            'Please check the question data.')
        self.assertEqual(conduct.subject_score_id.score, 1)
        self.assertEqual(
            fields.Datetime.to_string(mcq_attempt.answer_recorded_at),
            '2026-10-26 09:15:00')
        final_result_batch = conduct.result_batch_id
        final_result_action = (
            final_result_batch._action_export_final_result_list(
                odoo_password=self.odoo_password,
                workbook_password=self.workbook_password))
        self.assertEqual(final_result_action['type'], 'ir.actions.act_url')
        final_result_attachment = self.env['ir.attachment'].search([
            ('res_model', '=', 'cbt.paper.result.batch'),
            ('res_id', '=', final_result_batch.id),
            ('name', '=', 'final_result_list_%s.xlsx' % final_result_batch.id),
        ], limit=1)
        self.assertFalse(zipfile.is_zipfile(io.BytesIO(
            base64.b64decode(final_result_attachment.datas))))
        final_result_workbook = load_allocation_xlsx(decrypt_xlsx(
            base64.b64decode(final_result_attachment.datas),
            self.workbook_password))
        final_result_rows = list(
            final_result_workbook['Final Results'].iter_rows(
                values_only=True))
        subject_scores = conduct.subject_score_id
        self.assertEqual(final_result_rows[0][:3], (
            'Student Login ID', 'Student Name', 'Paper Name'))
        self.assertEqual(final_result_rows[1][:3], (
            self.participant.login,
            self.participant.name,
            allocation.main_paper_id.name,
        ))
        self.assertEqual(
            final_result_rows[0][-2:],
            ('Total Marks', 'Obtained Marks'))
        self.assertEqual(final_result_rows[1][-2:], (
            sum(subject_scores.mapped('total_score')),
            conduct.score,
        ))
        ordered_subject_scores = subject_scores.sorted(
            key=lambda score: (
                score.subject_id.sequence,
                score.subject_id.name or '',
                score.subject_id.id))
        for index, subject_score in enumerate(ordered_subject_scores):
            column = 3 + index * 2
            self.assertEqual(final_result_rows[0][column:column + 2], (
                '%s - Obtained Marks' % subject_score.subject_id.name,
                '%s - Total Marks' % subject_score.subject_id.name,
            ))
            self.assertEqual(final_result_rows[1][column:column + 2], (
                subject_score.score,
                subject_score.total_score,
            ))
        duplicate_result = self.env['cbt.paper.result.import.wizard'].create({
            'xlsx_file': result_attachment.datas,
            'name': 'offline-results.xlsx',
        })._import_workbook(
            odoo_password=self.odoo_password,
            workbook_password=self.workbook_password)
        self.assertIn('already been imported', duplicate_result['params']['message'])
