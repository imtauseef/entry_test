# -*- coding: utf-8 -*-
from odoo import fields, models, _
from odoo.exceptions import ValidationError


class CBTMCQSSuspendWizard(models.TransientModel):
    _name = 'cbt.mcqs.suspend.wizard'
    _description = 'Suspend Question'

    question_id = fields.Many2one(
        'cbt.mcqs', string='Question', required=True, readonly=True)
    reason = fields.Text(string='Reason', required=True)
    suspended_from = fields.Datetime(
        string='Suspended From', required=True, default=fields.Datetime.now)
    suspended_until = fields.Datetime(
        string='Suspended Until', required=True)

    def action_suspend(self):
        self.ensure_one()
        if not (self.reason or '').strip():
            raise ValidationError(_("A suspension reason is required."))
        if self.suspended_until <= self.suspended_from:
            raise ValidationError(_(
                "The suspension end date must be after the start date."))
        self.question_id._cbt_suspend(
            self.reason, self.suspended_from, self.suspended_until)
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'cbt.mcqs',
            'res_id': self.question_id.id,
            'view_mode': 'form',
            'target': 'current',
        }
