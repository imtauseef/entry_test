import re
from odoo import fields, models, _, api
import pdb


class CBTStudentPaper(models.Model):
    _name = 'cbt.student.paper'
    _description = 'Students Papers'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    main_paper_id = fields.Many2one('cbt.paper', 'Paper Generated From', tracking=True, required=True)
    slot_id = fields.Many2one('cbt.slot', 'Session', related='main_paper_id.slot_id',store=True)
    questions = fields.Many2many('cbt.mcqs', 'student_paper_questions_rel', 'student_paper_id', 'questions_id',
                                 string='Entry Test Questions', tracking=True)
    participant_id = fields.Many2one('cbt.participant', 'Participant', required=True, tracking=True)

    @api.depends('participant_id', 'main_paper_id')
    def _compute_display_name(self):
        for record in self:
            name = 'New'
            if record.participant_id and record.main_paper_id:
                name = record.participant_id.name + ' - ' + record.main_paper_id.name
            record.display_name = name

