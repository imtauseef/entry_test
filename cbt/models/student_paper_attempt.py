import re

from odoo import fields, models, _, api
import pdb


class CBTPaperAttempt(models.Model):
    _name = 'cbt.paper.attempt'
    _description = 'Paper Attempt'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    question_id = fields.Many2one('cbt.mcqs', 'Questions', tracking=True, required=True)
    participant_answer = fields.Char(string='Participant Answer')
    score = fields.Integer('Question Score', compute='_compute_question_score', store=True)
    attempt_id = fields.Many2one('cbt.paper.conduct', 'Conduct Paper', required=True, tracking=True)

    @api.depends('question_id', 'participant_answer')
    def _compute_question_score(self):
        for each in self:
            each.score = 0
            if each.question_id.ans1_correct == True:
                if each.participant_answer == 'A':
                    each.score = 1
                else:
                    each.score = 0
            elif each.question_id.ans2_correct == True:
                if each.participant_answer == 'B':
                    each.score = 1
                else:
                    each.score = 0
            elif each.question_id.ans3_correct == True:
                if each.participant_answer == 'C':
                    each.score = 1
                else:
                    each.score = 0
            elif each.question_id.ans4_correct == True:
                if each.participant_answer == 'D': 
                    each.score = 1
                else:
                    each.score = 0
            elif each.question_id.ans5_correct == True:
                if each.participant_answer == 'E':
                    each.score = 1
                else:
                    each.score = 0
            elif each.question_id.ans6_correct == True:
                if each.participant_answer == 'F':
                    each.score = 1
                else:
                    each.score = 0



