import re

from odoo import fields, models, _, api
import pdb


class CBTReviewQuestions(models.Model):
    _name = 'cbt.review.questions'
    _description = 'Review Question'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    current_user = fields.Many2one('res.users', 'Reviewed By', default=lambda self: self.env.user, readonly="True")
    questions = fields.Many2many('cbt.mcqs', string='Questions', tracking=True)
    remarks = fields.Char('Reviewer Remarks', tracking=True)
    search_ids = fields.Char(compute="_compute_search_ids",search='search_ids_search')

    def search_ids_search(self):
        subject_list = []
        employees = self.env['cbt.employee.role'].search(
            [('review_access', '=', True), ('employee_id', '=', self.current_user.id)])
        if employees:
            for each in employees:
                for sub_id in each.subject:
                    subject_list.append(sub_id.id)

        mcqs = self.env['cbt.mcqs'].search([('questions.subject_id','in',subject_list),('questions.current_user','!=',self.current_user)]).ids
        return [('id','in',mcqs)]










