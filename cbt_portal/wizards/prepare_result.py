# -*- coding: utf-8 -*-
from odoo import fields, models, _
from odoo.exceptions import UserError

from odoo.addons.cbt.models.allocation_xlsx import excel_password_prompt_action


class PrepareResultWizard(models.TransientModel):
    _name = 'prepare.result.wizard'
    _description = 'Export Offline Test Results'

    batch_id = fields.Many2one(
        'cbt.paper.export.batch', string='Finished Test Batch',
        required=True, domain=[('state', 'in', ('finished', 'result_collected'))])

    def prepare_result(self):
        self.ensure_one()
        if not self.env.user.has_group('cbt.group_cbt_admin'):
            raise UserError(_('Only CBT administrators may export test results.'))
        return excel_password_prompt_action(
            self.batch_id, '_action_export_results', 'export',
            _('Export Candidate Results Workbook'))
