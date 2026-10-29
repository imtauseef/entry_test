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
    result_batch_id = fields.Many2one(
        'cbt.paper.result.batch', string='Offline Result Batch',
        index=True, ondelete='restrict', copy=False)
    portal_started_at = fields.Datetime(
        string='Portal Start Time', readonly=True, copy=False)
    portal_ended_at = fields.Datetime(
        string='Portal End Time', readonly=True, copy=False)
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
            attempts = self.env['cbt.paper.attempt'].search([
                ('attempt_id', '=', rec.id),
            ])
            subject_totals = {}
            for attempt in attempts:
                subject = attempt.question_id.subject_id
                if not subject:
                    continue
                totals = subject_totals.setdefault(subject.id, {
                    'score': 0,
                    'total_score': 0,
                })
                totals['score'] += attempt.score
                totals['total_score'] += 1
            self.env['cbt.paper.subject.score'].create([
                {
                    'conduct': rec.id,
                    'subject_id': subject_id,
                    **totals,
                }
                for subject_id, totals in subject_totals.items()
            ])
