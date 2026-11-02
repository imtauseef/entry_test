# -*- coding: utf-8 -*-
from urllib.parse import urlencode

from odoo import fields, models, _
from odoo.exceptions import UserError


class CBTReportPrintWizard(models.TransientModel):
    """Ask the user whether to print a report as PDF or MS Word."""

    _name = 'cbt.report.print.wizard'
    _description = 'Print Report'

    print_format = fields.Selection(
        [('pdf', 'PDF'), ('word', 'MS Word')],
        string='Format', default='pdf', required=True)
    report_ref = fields.Char(required=True)
    res_model = fields.Char(required=True)
    res_id = fields.Integer(required=True)

    def action_print(self):
        self.ensure_one()
        report = self.env['ir.actions.report']._get_report(self.report_ref)
        if report.model != self.res_model:
            raise UserError(_(
                "The selected report does not match the document."))
        if report.groups_id and not (
                report.groups_id & self.env.user.groups_id):
            raise UserError(_("You are not allowed to print this report."))
        record = self.env[self.res_model].browse(self.res_id).exists()
        if not record:
            raise UserError(_("The selected document no longer exists."))
        record.check_access_rights('read')
        record.check_access_rule('read')
        ids = [self.res_id]
        if self.print_format == 'word':
            params = urlencode({
                'report_ref': self.report_ref,
                'res_model': self.res_model,
                'res_id': self.res_id,
            })
            return {
                'type': 'ir.actions.act_url',
                'url': '/cbt/report/word?%s' % params,
                'target': 'download',
            }
        return report.with_context(
            active_model=self.res_model, active_ids=ids,
        ).report_action(ids, config=False)
