# -*- coding: utf-8 -*-
import base64

from odoo import fields, models, _
from odoo.addons.cbt.models.allocation_xlsx import (
    build_allocation_xlsx,
    encrypt_xlsx,
    excel_password_prompt_action,
    offline_result_payload_hash,
    verify_excel_admin_password,
)
from odoo.exceptions import UserError


class CBTPaperExportBatch(models.Model):
    _name = 'cbt.paper.export.batch'
    _description = 'Imported Paper Allocation Batch'
    _order = 'create_date desc, id desc'

    name = fields.Char(required=True)
    source_system_id = fields.Char(required=True, index=True, copy=False)
    source_export_id = fields.Char(required=True, index=True, copy=False)
    source_generator_id = fields.Char(required=True, index=True, copy=False)
    source_payload_hash = fields.Char(copy=False)
    paper_ids = fields.One2many(
        'cbt.paper.export', 'batch_id', string='Candidate Papers')
    state = fields.Selection([
        ('imported', 'Imported'),
        ('active', 'Active'),
        ('finished', 'Test Finished'),
        ('result_collected', 'Results Collected'),
    ], default='imported', required=True, index=True, copy=False)
    activated_at = fields.Datetime(readonly=True, copy=False)
    finished_at = fields.Datetime(readonly=True, copy=False)
    results_collected_at = fields.Datetime(readonly=True, copy=False)

    _sql_constraints = [
        (
            'source_export_uniq',
            'unique(source_system_id, source_export_id)',
            'This allocation workbook has already been imported.',
        ),
    ]

    def _check_cbt_admin(self):
        if not self.env.user.has_group('cbt.group_cbt_admin'):
            raise UserError(_('Only CBT administrators may manage test batches.'))

    def action_start_test(self):
        self.ensure_one()
        self._check_cbt_admin()
        if self.state != 'imported':
            raise UserError(_('Only an imported batch can be activated.'))
        if not self.paper_ids:
            raise UserError(_('This batch has no candidate papers.'))
        active_batch = self.search([
            ('state', '=', 'active'),
            ('id', '!=', self.id),
        ], limit=1)
        if active_batch:
            raise UserError(_(
                'Test batch %(batch)s is already active. Finish it before '
                'starting another batch.'
            ) % {'batch': active_batch.display_name})
        self.write({
            'state': 'active',
            'activated_at': fields.Datetime.now(),
        })
        return True

    def action_finish_test(self):
        self.ensure_one()
        self._check_cbt_admin()
        if self.state != 'active':
            raise UserError(_('Only an active batch can be finished.'))
        now = fields.Datetime.now()
        unfinished_papers = self.paper_ids.filtered(
            lambda paper: not paper.end_paper)
        unfinished_papers.write({
            'end_paper': True,
            'end_paper_time': now,
        })
        for paper in unfinished_papers:
            if paper.session_ids:
                paper.session_ids[-1].write({
                    'end_time': fields.Datetime.to_string(now),
                })
        self.write({
            'state': 'finished',
            'finished_at': now,
        })
        return True

    def action_open_results_export_password_prompt(self):
        return excel_password_prompt_action(
            self, '_action_export_results', 'export',
            _('Export Candidate Results Workbook'))

    def _action_export_results(
            self, odoo_password=None, workbook_password=None):
        self.ensure_one()
        verify_excel_admin_password(self.env, odoo_password)
        if self.state not in ('finished', 'result_collected'):
            raise UserError(_(
                'Finish the test batch before exporting candidate results.'
            ))
        if self.paper_ids.filtered(lambda paper: not paper.end_paper):
            raise UserError(_(
                'Every paper in the batch must be ended before results can be exported.'
            ))
        attended_papers = self.paper_ids.filtered('paper_started').sorted('id')
        if not attended_papers:
            raise UserError(_('No candidates started this test batch.'))

        paper_rows = [[
            'source_export_id',
            'source_student_id',
            'source_paper_id',
            'source_template_paper_id',
            'candidate_name',
            'paper_name',
            'login',
            'cid',
            'test_date',
            'test_started_at',
            'test_ended_at',
        ]]
        answer_rows = [[
            'source_student_id',
            'source_paper_id',
            'source_question_id',
            'question_order',
            'answer_alphabet',
            'source_option_id',
            'theory_answer',
            'answer_recorded_at',
            'mark_review',
            'feedback_type',
            'feedback_text',
        ]]
        source_prefix = '%s:' % self.source_system_id

        for paper in attended_papers:
            if (
                    not paper.source_export_id
                    or not paper.source_student_id
                    or not paper.source_paper_id
                    or not paper.source_template_paper_id):
                raise UserError(_(
                    'Candidate %s is missing required source identifiers.'
                ) % paper.display_name)
            if (
                    not paper.source_export_id.startswith(
                        '%scbt.student.paper:' % source_prefix)
                    or not paper.source_student_id.startswith(
                        '%scbt.participant:' % source_prefix)
                    or not paper.source_template_paper_id.startswith(
                        '%scbt.paper:' % source_prefix)):
                raise UserError(_(
                    'Candidate %s has source identifiers from another system '
                    'or model.'
                ) % paper.display_name)
            if paper.source_paper_id != paper.source_export_id:
                raise UserError(_(
                    'Candidate %s has inconsistent source paper identifiers.'
                ) % paper.display_name)
            if not paper.paper_started or not paper.end_paper_time:
                raise UserError(_(
                    'Candidate %s is missing a start or end timestamp.'
                ) % paper.display_name)
            if any(len(value or '') > 32767 for value in (
                    paper.login, paper.name, paper.paper_name)):
                raise UserError(_(
                    "Candidate data for %s exceeds Excel's maximum cell length."
                ) % paper.display_name)
            paper_rows.append([
                paper.source_export_id,
                paper.source_student_id,
                paper.source_paper_id,
                paper.source_template_paper_id or '',
                paper.name or '',
                paper.paper_name or '',
                paper.login,
                paper.cid or 0,
                fields.Date.to_string(paper.test_date) or '',
                fields.Datetime.to_string(paper.paper_started) or '',
                fields.Datetime.to_string(paper.end_paper_time) or '',
            ])
            questions = paper.line_ids.sorted('sequence')
            if not questions:
                raise UserError(_(
                    'Candidate %s has no questions to export.'
                ) % paper.display_name)
            if [question.sequence for question in questions] != list(
                    range(1, len(questions) + 1)):
                raise UserError(_(
                    'Candidate %s has invalid question ordering data.'
                ) % paper.display_name)
            for question in questions:
                if (
                        not question.source_question_id
                        or not question.source_question_id.startswith(
                            '%scbt.mcqs:' % source_prefix)
                        or question.source_student_id != paper.source_student_id
                        or question.source_paper_id != paper.source_paper_id):
                    raise UserError(_(
                        'Candidate %s has a question with invalid source identifiers.'
                    ) % paper.display_name)
                if len(question.theory_answer or '') > 32767:
                    raise UserError(_(
                        "A theory answer for %s exceeds Excel's maximum cell length."
                    ) % paper.display_name)
                feedback = question.feedback_ids[:1]
                if any(len(value or '') > 32767 for value in (
                        feedback.feedback_type_name,
                        feedback.feedback_text)):
                    raise UserError(_(
                        "Feedback for candidate %s exceeds Excel's maximum cell length."
                    ) % paper.display_name)
                selected_option = question.option_ids.filtered(
                    lambda option: option.id == question.answer)
                if question.uses_paragraph:
                    if question.answer or question.answer_alphabet or selected_option:
                        raise UserError(_(
                            'A theory answer for candidate %s contains an '
                            'unexpected multiple-choice selection.'
                        ) % paper.display_name)
                elif bool(question.answer_alphabet) != bool(selected_option):
                    raise UserError(_(
                        'A selected option for candidate %s is incomplete.'
                    ) % paper.display_name)
                elif selected_option and (
                        question.answer_alphabet != chr(
                            64 + selected_option.sequence)
                        or not selected_option.source_option_id.startswith(
                            '%s:option:' % question.source_question_id)
                        or selected_option.source_student_id
                        != paper.source_student_id
                        or selected_option.source_paper_id
                        != paper.source_paper_id
                        or selected_option.source_question_id
                        != question.source_question_id):
                    raise UserError(_(
                        'A selected option for candidate %s has invalid source identifiers.'
                    ) % paper.display_name)
                answer_rows.append([
                    question.source_student_id,
                    question.source_paper_id,
                    question.source_question_id,
                    question.sequence,
                    question.answer_alphabet or '',
                    selected_option.source_option_id if selected_option else '',
                    question.theory_answer or '',
                    fields.Datetime.to_string(
                        question.answer_recorded_time) or '',
                    question.mark_review,
                    feedback.feedback_type_name or '',
                    feedback.feedback_text or '',
                ])

        workbook = encrypt_xlsx(build_allocation_xlsx([
            ('Manifest', [
                ['schema_version', '1.2'],
                ['source_system_id', self.source_system_id],
                ['source_batch_export_id', self.source_export_id],
                ['source_generator_id', self.source_generator_id],
                ['paper_count', len(attended_papers)],
                ['answer_count', len(answer_rows) - 1],
                ['results_sha256', offline_result_payload_hash(
                    paper_rows[1:], answer_rows[1:])],
            ]),
            ('Papers', paper_rows),
            ('Answers', answer_rows),
        ]), workbook_password)
        attachment = self.env['ir.attachment'].sudo().create({
            'name': '%s_results.xlsx' % self.source_export_id.replace(':', '_'),
            'datas': base64.b64encode(workbook),
            'mimetype': (
                'application/vnd.openxmlformats-officedocument.'
                'spreadsheetml.sheet'
            ),
            'res_model': self._name,
            'res_id': self.id,
            'type': 'binary',
        })
        if self.state != 'result_collected':
            self.write({
                'state': 'result_collected',
                'results_collected_at': fields.Datetime.now(),
            })
        return {
            'type': 'ir.actions.act_url',
            'url': '/web/content/%s?download=1' % attachment.id,
            'target': 'new',
        }
