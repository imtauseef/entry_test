from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class CBTPaperQuestionFeedbackType(models.Model):
    _name = 'cbt.paper.question.feedback.type'
    _description = 'Candidate Question Feedback Type'
    _order = 'sequence, name, id'

    name = fields.Char(required=True, translate=True)
    sequence = fields.Integer(default=10)
    is_other = fields.Boolean(string='Other')
    active = fields.Boolean(default=True)

    _sql_constraints = [
        ('name_uniq', 'unique(name)', 'Feedback type names must be unique.'),
    ]

    @api.constrains('is_other', 'active')
    def _check_single_active_other(self):
        for record in self.filtered(lambda item: item.is_other and item.active):
            other_count = self.search_count([
                ('is_other', '=', True),
                ('active', '=', True),
                ('id', '!=', record.id),
            ])
            if other_count:
                raise ValidationError(_(
                    'Only one active feedback type can be marked as Other.'))


class CBTPaperQuestionFeedback(models.Model):
    _name = 'cbt.paper.question.feedback'
    _description = 'Candidate Question Feedback'
    _order = 'create_date desc, id desc'

    paper_id = fields.Many2one(
        'cbt.paper.export', required=True, index=True, ondelete='cascade')
    question_id = fields.Many2one(
        'cbt.paper.line.export', required=True, index=True, ondelete='cascade')
    candidate_id = fields.Char(
        string='Candidate ID', related='paper_id.source_student_id',
        store=True, readonly=True, index=True)
    candidate_name = fields.Char(
        related='paper_id.name', store=True, readonly=True)
    source_question_id = fields.Char(
        related='question_id.source_question_id', store=True, readonly=True,
        index=True)
    feedback_type_id = fields.Many2one(
        'cbt.paper.question.feedback.type', ondelete='restrict')
    feedback_type_name = fields.Char(readonly=True)
    feedback_text = fields.Text(string='Additional Details')

    _sql_constraints = [
        (
            'paper_question_uniq',
            'unique(paper_id, question_id)',
            'A candidate can submit only one feedback entry per question.',
        ),
    ]

    @api.model_create_multi
    def create(self, vals_list):
        for values in vals_list:
            feedback_type_id = values.get('feedback_type_id')
            if feedback_type_id and not values.get('feedback_type_name'):
                feedback_type = self.env[
                    'cbt.paper.question.feedback.type'].browse(
                        feedback_type_id)
                values['feedback_type_name'] = feedback_type.name
        return super().create(vals_list)

    @api.constrains('paper_id', 'question_id')
    def _check_question_paper(self):
        for record in self:
            if record.question_id.paper_id != record.paper_id:
                raise ValidationError(_(
                    'Feedback must reference a question from the candidate paper.'))

    @api.constrains('feedback_text')
    def _check_feedback_text_length(self):
        for record in self:
            if len(record.feedback_text or '') > 32767:
                raise ValidationError(_(
                    "Feedback must not exceed Excel's maximum cell length."))
