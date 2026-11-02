from odoo import fields, models


class CBTQuestionFeedback(models.Model):
    _name = 'cbt.mcqs.feedback'
    _description = 'Candidate Feedback on Question'
    _order = 'create_date desc, id desc'

    question_id = fields.Many2one(
        'cbt.mcqs', required=True, index=True, ondelete='cascade')
    candidate_id = fields.Many2one(
        'cbt.participant', string='Candidate', required=True, index=True,
        ondelete='restrict')
    candidate_source_id = fields.Char(
        string='Source Candidate ID', required=True, index=True,
        readonly=True)
    candidate_name = fields.Char(required=True, readonly=True)
    feedback_type = fields.Char(readonly=True)
    feedback_text = fields.Text(string='Additional Details', readonly=True)
    conduct_id = fields.Many2one(
        'cbt.paper.conduct', required=True, index=True, ondelete='cascade')
    result_batch_id = fields.Many2one(
        'cbt.paper.result.batch', required=True, index=True,
        ondelete='restrict')

    _sql_constraints = [
        (
            'conduct_question_uniq',
            'unique(conduct_id, question_id)',
            'A candidate can submit only one feedback entry per question.',
        ),
    ]
