# -*- coding: utf-8 -*-
import base64

from odoo import fields, models, _
from odoo.exceptions import UserError

from .allocation_xlsx import (
    build_allocation_xlsx,
    encrypt_xlsx,
    excel_password_prompt_action,
    verify_excel_admin_password,
)


class CBTPaperResultBatch(models.Model):
    _name = 'cbt.paper.result.batch'
    _description = 'Imported Offline Paper Results'
    _order = 'imported_at desc, id desc'

    name = fields.Char(string='Result Batch', required=True)
    source_system_id = fields.Char(
        string='Source System ID', required=True, index=True, copy=False)
    source_batch_export_id = fields.Char(
        string='Portal Test Batch ID', required=True, index=True, copy=False)
    source_generator_id = fields.Char(
        string='Source Generator ID', required=True, index=True, copy=False)
    paper_generate_id = fields.Many2one(
        'cbt.paper.generator', string='Paper Generator', required=True,
        index=True, readonly=True, copy=False, ondelete='restrict')
    result_payload_sha256 = fields.Char(
        string='Result Payload SHA-256', required=True, copy=False)
    imported_at = fields.Datetime(
        required=True, default=fields.Datetime.now, readonly=True, copy=False)
    conduct_ids = fields.One2many(
        'cbt.paper.conduct', 'result_batch_id', string='Candidate Results')

    def action_open_final_result_list_password_prompt(self):
        return excel_password_prompt_action(
            self, '_action_export_final_result_list', 'export',
            _('Export Final Result List'))

    def _action_export_final_result_list(
            self, odoo_password=None, workbook_password=None):
        self.ensure_one()
        verify_excel_admin_password(self.env, odoo_password)
        if not self.conduct_ids:
            raise UserError(_(
                'There are no candidate results in this result batch to export.'))

        subjects = self.env['cbt.paper.subject.score'].search([
            ('conduct', 'in', self.conduct_ids.ids),
            ('subject_id', '!=', False),
        ]).mapped('subject_id')
        subjects = subjects.sorted(
            key=lambda subject: (
                subject.sequence, subject.name or '', subject.id))
        headers = [
            'Student Login ID',
            'Student Name',
            'Paper Name',
        ]
        for subject in subjects:
            headers.extend([
                '%s - Obtained Marks' % subject.name,
                '%s - Total Marks' % subject.name,
            ])
        headers.extend(['Total Marks', 'Obtained Marks'])

        rows = [headers]
        conducts = self.conduct_ids.sorted(
            key=lambda conduct: (
                conduct.participant_id.login or '',
                conduct.participant_id.name or '',
                conduct.id))
        for conduct in conducts:
            participant = conduct.participant_id
            paper = conduct.paper_id
            if not participant or not participant.login or not paper:
                raise UserError(_(
                    'Candidate result %s is missing its student login or paper.'
                ) % conduct.display_name)
            paper_name = paper.main_paper_id.name
            if not paper_name:
                raise UserError(_(
                    'Candidate result %s is missing its paper name.'
                ) % conduct.display_name)

            subject_scores = {
                score.subject_id.id: score
                for score in conduct.subject_score_id
                if score.subject_id
            }
            total_marks = 0
            row = [participant.login, participant.name or '', paper_name]
            for subject in subjects:
                score = subject_scores.get(subject.id)
                obtained = score.score if score else 0
                available = score.total_score if score else 0
                total_marks += available
                row.extend([obtained, available])
            row.extend([total_marks, conduct.score])
            rows.append(row)

        workbook = encrypt_xlsx(
            build_allocation_xlsx([('Final Results', rows)]),
            workbook_password)
        attachment = self.env['ir.attachment'].sudo().create({
            'name': 'final_result_list_%s.xlsx' % self.id,
            'datas': base64.b64encode(workbook),
            'mimetype': (
                'application/vnd.openxmlformats-officedocument.'
                'spreadsheetml.sheet'),
            'res_model': self._name,
            'res_id': self.id,
            'type': 'binary',
        })
        return {
            'type': 'ir.actions.act_url',
            'url': '/web/content/%s?download=1' % attachment.id,
            'target': 'new',
        }

    _sql_constraints = [
        (
            'source_result_batch_uniq',
            'unique(source_system_id, source_batch_export_id)',
            'Results from this portal test batch have already been imported.',
        ),
    ]
