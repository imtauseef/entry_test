import re

from odoo import fields, models, _, api
import pdb
import random


class CBTPaperSubjectScore(models.Model):
    _name = 'cbt.paper.subject.score'
    _description = 'Paper Subject Score'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    conduct = fields.Many2one(
        'cbt.paper.conduct', string="Paper", tracking=True)
    subject_id = fields.Many2one('cbt.subject', 'Subject')
    score = fields.Integer('Score')
    total_score = fields.Integer('Total Score')


class CBTPaperConduct(models.Model):
    _name = 'cbt.paper.conduct'
    _description = 'Paper '
    _inherit = ['mail.thread', 'mail.activity.mixin']

    paper_id = fields.Many2one(
        'cbt.student.paper', string="Paper", tracking=True)
    slot_id = fields.Many2one('cbt.slot', 'Session',
                              related='paper_id.slot_id', store=True)
    participant_id = fields.Many2one(
        'cbt.participant', 'Participant', related='paper_id.participant_id', store=True)
    program = fields.Many2one(
        'cbt.program', 'program', related='participant_id.program', store=True)
    date = fields.Date('Paper Conduct Date', required=True, tracking=True)
    score = fields.Integer(
        'Test Score', compute='_compute_test_score', store=True)
    user_token = fields.Char('User Token', tracking=True, readonly="True")
    last_question_attempt_id = fields.Many2one(
        'cbt.mcqs', 'Last Question Attempt')
    question_attempt_id = fields.One2many(
        'cbt.paper.attempt', 'attempt_id', 'Questions Attempt', required=True)
    subject_score_id = fields.One2many(
        'cbt.paper.subject.score', 'conduct', 'Questions Attempt', required=True)

    @api.depends('question_attempt_id')
    def _compute_test_score(self):
        for rec in self:
            count = 0
            for each in rec.question_attempt_id:
                count = count+int(each.score)
            rec.score = count

    def user_token_reset(self):
        for rec in self:
            rec.user_token = ''

    def subject_wise_score(self):
        for rec in self:
            rec.subject_score_id.unlink()
            attempt = self.env['cbt.paper.attempt'].search(
                [('attempt_id', '=', rec.id)], order='question_id desc')
            if not attempt:
                continue
            subject_name = attempt[0].question_id.subject_id.name
            subject_id = 0
            ans = 0
            count = 1
            subject_count = 0
            for att in attempt:
                if subject_name == att.question_id.subject_id.name:
                    ans = int(ans) + att.score
                    subject_name = att.question_id.subject_id.name
                    subject_id = att.question_id.subject_id.id
                    subject_count = int(subject_count) + 1
                elif count != len(attempt):
                    data = {
                        'conduct': rec.id,
                        'subject_id': subject_id,
                        'score': ans,
                        'total_score': subject_count,

                    }
                    self.env['cbt.paper.subject.score'].create(data)
                    ans = att.score
                    subject_name = att.question_id.subject_id.name
                    subject_id = att.question_id.subject_id.id
                    subject_count = 1

                if count == len(attempt):
                    # subject_count = int(subject_count) + 1
                    data = {
                        'conduct': rec.id,
                        'subject_id': subject_id,
                        'score': ans,
                        'total_score': subject_count,
                    }
                    self.env['cbt.paper.subject.score'].create(data)

                count = int(count)+1
