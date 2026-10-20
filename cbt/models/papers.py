import re
from odoo import fields, models, _, api
import pdb
import math
from odoo.exceptions import UserError, ValidationError
import random


class CBTPaper(models.Model):
    _name = 'cbt.paper'
    _description = 'Paper'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    current_user = fields.Many2one('res.users', 'Created By', default=lambda self: self.env.user, readonly="True")
    name = fields.Char(string='Paper Name', tracking=True, required=True)
    generator_id = fields.Many2one('cbt.paper.generator', 'Paper Generation', tracking=True, required=True)
    criteria_id = fields.Many2one(
        'cbt.paper.criteria', 'Paper Criteria',
        related='generator_id.criteria_id', store=True, index=True)
    questions = fields.Many2many('cbt.mcqs', 'paper_questions_rel', 'paper_id', 'questions_id',
                                 string='Entry Test', tracking=True)
    slot_id = fields.Many2one('cbt.slot', 'Session', required=True, tracking=True)
    # program_id = fields.Many2one('cbt.program', 'Test program', tracking=True)
    program_ids = fields.Many2many('cbt.program', string='Programs')
    number_of_questions = fields.Integer('Total Questions', compute='_count_total_questions', store=True)
    student_paper_gen = fields.Boolean('Student Paper Generated', default=False)
    state = fields.Selection(
        [('draft', 'Draft'), ('done', 'Done')], string='Status',
        compute='_compute_state', store=False)
    replacement_log_ids = fields.One2many(
        'cbt.paper.replacement.log', 'paper_id', string='Replacements')

    @api.depends('generator_id')
    def _count_total_questions(self):
        count = 0
        for rec in self:
            for count_ques in rec.questions:
                count = count + 1
        self.number_of_questions = count

    @api.depends('student_paper_gen')
    def _compute_state(self):
        for rec in self:
            rec.state = 'done' if rec.student_paper_gen else 'draft'

    # ------------------------------------------------------------------
    # Question replacement (draft papers only)
    # ------------------------------------------------------------------
    def _question_correct_answer(self, question):
        if question.ans1_correct:
            return 'A'
        if question.ans2_correct:
            return 'B'
        if question.ans3_correct:
            return 'C'
        if question.ans4_correct:
            return 'D'
        if question.ans5_correct:
            return 'E'
        if question.ans6_correct:
            return 'F'
        return ''

    def _get_replacement_pool(self, old_question):
        """Return ``(recordset, match_level)`` of question-bank questions usable
        to replace ``old_question`` on this paper.

        The pool is the normal question bank (approved, non-reserve) of the
        same discipline (subject), never already present on this paper, and
        (when the criteria batch is unique) never used by a sibling paper.
        Reserve questions are *not* a replacement source any more: they are the
        destination of the question being replaced. The preferred level
        additionally matches topic, difficulty and question type; otherwise it
        falls back to subject-only matching.
        """
        self.ensure_one()
        domain = [
            ('subject_id', '=', old_question.subject_id.id),
            ('id', 'not in', self.questions.ids),
        ]
        criteria = self.criteria_id
        if criteria and criteria.unique_questions:
            sibling_papers = self.env['cbt.paper'].search([
                ('criteria_id', '=', criteria.id),
                ('id', '!=', self.id),
            ])
            domain.append(('id', 'not in', sibling_papers.mapped('questions').ids))

        # ``_get_generation_pool`` is the single source of truth for what
        # belongs to the question bank (approved + non-reserve).
        pool = self.env['cbt.mcqs']._get_generation_pool(domain)
        exact = pool.filtered(
            lambda q: q.topic_id.id == old_question.topic_id.id
            and q.difficulty_level_id.id == old_question.difficulty_level_id.id
            and q.type_id.id == old_question.type_id.id)
        if exact:
            return exact, 'exact'
        return pool, 'subject'

    def _move_question_to_reserve(self, question):
        """Move a replaced question out of the question bank into the reserve
        pool so it is no longer used by generation or replacements.

        The move is a system side effect of the replace action, so it is done
        with ``sudo`` and therefore bypasses the manual reserve-toggle access
        rules (``cbt.mcqs._check_reserve_toggle_access``).
        """
        if not question.is_reserve:
            question.sudo().write({'is_reserve': True})

    def _sync_replacement_to_export(self, old_question, new_question):
        """Guarded best-effort sync of a replacement into the cbt_portal
        mirror (``cbt.paper.export`` and its lines/options).

        Does nothing when cbt_portal is not installed or no mirror exists for
        this paper. Returns True when a mirror line was updated.
        """
        PaperExport = self.env.get('cbt.paper.export')
        if PaperExport is None:
            return False
        export = PaperExport.search([('server_id', '=', self.id)], limit=1)
        if not export:
            return False
        line = export.line_ids.filtered(
            lambda l: l.server_id == old_question.id)[:1]
        if not line:
            return False

        line.name = new_question.question
        line.server_id = new_question.id
        line.correct_answer = self._question_correct_answer(new_question)

        SubjectExport = self.env.get('cbt.subject.export')
        if SubjectExport is not None and new_question.subject_id:
            subject = SubjectExport.search(
                [('name', '=ilike', new_question.subject_id.name)], limit=1)
            if not subject:
                subject = SubjectExport.create({
                    'name': new_question.subject_id.name,
                })
            line.subject_id = subject.id

        OptionExport = self.env.get('cbt.paper.line.option.export')
        if OptionExport is not None:
            line.option_ids.unlink()
            options = [new_question.ans1, new_question.ans2, new_question.ans3,
                       new_question.ans4, new_question.ans5, new_question.ans6]
            for option in options:
                if option:
                    OptionExport.create({
                        'question_id': line.id,
                        'name': option,
                        'server_id': new_question.id,
                    })
        return True

    def action_replace_question(self, old_question_id):
        """Replace ``old_question_id`` with a random question taken from the
        question bank (approved, non-reserve) of the same discipline.

        The question being replaced is moved to the reserve pool so it is no
        longer used by generation. Only allowed while the paper is still in
        draft state and before a candidate mirror (``cbt.paper.export``) has
        been created.
        """
        self.ensure_one()
        if self.state != 'draft':
            raise UserError(_(
                "Questions can only be replaced while the paper is in draft "
                "state."))

        # PaperExport = self.env.get('cbt.paper.export')
        # if PaperExport is not None and PaperExport.search(
        #         [('server_id', '=', self.id)], limit=1):
        #     raise UserError(_(
        #         "This paper has already been published to candidates and can "
        #         "no longer be changed."))

        old_question = self.env['cbt.mcqs'].browse(old_question_id)
        if old_question not in self.questions:
            raise UserError(_(
                "The question you are trying to replace is not part of this "
                "paper."))

        pool, match_level = self._get_replacement_pool(old_question)
        if not pool:
            raise UserError(_(
                "No question available in the question bank for %s") % (
                old_question.subject_id.name or _("this subject")))

        new_question = self.env['cbt.mcqs'].browse(random.choice(pool.ids))

        # Swap the question keeping its position on the paper.
        question_ids = list(self.questions.ids)
        position = question_ids.index(old_question.id)
        question_ids[position] = new_question.id
        self.write({'questions': [(6, 0, question_ids)]})

        # The replaced question is retired into the reserve pool.
        self._move_question_to_reserve(old_question)

        # Track the fresh question the same way the generator does.
        self.env['cbt.question.repeat.track'].create({
            'question_id': new_question.id,
            'paper_id': self.id,
        })

        self.env['cbt.paper.replacement.log'].create({
            'paper_id': self.id,
            'line_sequence': position + 1,
            'old_question_id': old_question.id,
            'new_question_id': new_question.id,
            'user_id': self.env.user.id,
            'match_level': match_level,
        })

        # Optional: keep the portal mirror in sync when it exists (no-op when
        # cbt_portal is not installed).
        self._sync_replacement_to_export(old_question, new_question)

        self.message_post(body=_(
            "Question replaced from the question bank (line %(line)s, "
            "match: %(level)s): %(old)s -> %(new)s. The replaced question was "
            "moved to reserve.",
            line=position + 1,
            level=match_level,
            old=old_question.display_name,
            new=new_question.display_name))

        return {'type': 'ir.actions.client', 'tag': 'reload'}

    def generate_student_paper(self):
        question_list = []
        for ques in self.questions:
            question_list.append(ques.id)
        participants = self.env['cbt.participant'].search(
            [('program','in',self.program_ids.ids),('slot_id','=',self.slot_id.id)])
        
        for participant in participants:
            random.shuffle(question_list)
            papers_data = {
                'main_paper_id': self.id,
                'questions': [(6, 0, question_list)],
                'participant_id': participant.id,
            }
            self.env['cbt.student.paper'].create(papers_data)
            self.env.cr.commit()
            self.student_paper_gen = True


class CBTPaperReplacementLog(models.Model):
    _name = 'cbt.paper.replacement.log'
    _description = 'Paper Question Replacement Log'
    _order = 'replace_datetime desc, id desc'

    paper_id = fields.Many2one(
        'cbt.paper', 'Paper', required=True, ondelete='cascade', index=True)
    line_sequence = fields.Integer('Line')
    old_question_id = fields.Many2one(
        'cbt.mcqs', 'Replaced Question', required=True, ondelete='restrict')
    new_question_id = fields.Many2one(
        'cbt.mcqs', 'Replacement Question', required=True, ondelete='restrict')
    user_id = fields.Many2one(
        'res.users', 'Replaced By', default=lambda self: self.env.user)
    replace_datetime = fields.Datetime(
        'Replaced On', default=fields.Datetime.now)
    match_level = fields.Selection([
        ('exact', 'Topic + Difficulty + Type'),
        ('subject', 'Subject only'),
    ], string='Match Level')
