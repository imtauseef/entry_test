import re

from odoo import fields, models, _, api
import pdb
import math
from odoo.exceptions import UserError, ValidationError
import random


class CBTGeneratePaper(models.Model):
    _name = 'cbt.paper.criteria'
    _description = 'Paper Criteria'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    current_user = fields.Many2one('res.users', 'Created By', default=lambda self: self.env.user, readonly="True")
    name = fields.Char(string='Paper Criteria Name', tracking=True)
    duration = fields.Char(string='Duration (Minutes)', tracking=True)
    etest_id = fields.Many2one('cbt.test', 'Entry Test', tracking=True)
    type_id = fields.Many2one('cbt.test.type', 'Test Type', tracking=True)
    program_ids = fields.Many2many('cbt.program', string='Test Program')    
    total_questions = fields.Char(string='Total Questions', tracking=True)
    random_section = fields.Boolean('Random Section',default=False)
    total_questions_compute = fields.Char()
    papers_count = fields.Integer(
        string='Unique Papers Possible', compute='_compute_papers_count',
        help="Read-only. Maximum number of papers with mutually disjoint "
             "question sets that the current question bank can supply for the "
             "rules defined below. This is informational only: it does not "
             "decide how many papers are generated.")
    unique_questions = fields.Boolean(
        string='No repeat question across papers', default=False,
        help="When enabled, generated papers use mutually disjoint question "
             "sets (no question is reused across papers).")
    paper_ids = fields.One2many(
        'cbt.paper', 'criteria_id', string='Generated Papers')
    paper_count = fields.Integer(
        string='Generated Papers', compute='_compute_paper_count')
    rules_ids = fields.One2many('cbt.paper.criteria.rule', 'paper_id', string='Rules ID', required="True",
                                tracking=True)

    @api.model
    def create(self, vals):
        result = super().create(vals)
        if vals.get('total_questions') != vals.get('total_questions_compute'):
            raise UserError(_("Number of questions in subject should be equal to total number of questions"))
        else:
            return result

    @api.onchange('rules_ids')
    def change_total_question_lines(self):
        count = 0
        for each in self.rules_ids:
            count = count + int(each.no_questions)
        self.total_questions_compute = str(count)

    @api.depends('paper_ids')
    def _compute_paper_count(self):
        for rec in self:
            rec.paper_count = len(rec.paper_ids)

    @api.depends(
        'rules_ids', 'rules_ids.subjects', 'rules_ids.no_questions',
        'rules_ids.topic_rules', 'rules_ids.topic_rules.topic_id',
        'rules_ids.topic_rules.sub_topic_id',
        'rules_ids.topic_rules.difficulty_level_id',
        'rules_ids.topic_rules.no_questions',
        'rules_ids.type_rules', 'rules_ids.type_rules.type_id',
        'rules_ids.type_rules.no_questions',
        'rules_ids.difficulty_rules',
        'rules_ids.difficulty_rules.difficulty_level_id',
        'rules_ids.difficulty_rules.no_questions',
    )
    def _compute_papers_count(self):
        for rec in self:
            rec.papers_count = rec._get_max_unique_papers()

    @staticmethod
    def _int_or_zero(value):
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0

    def _iter_rule_buckets(self):
        """Return the rule buckets used by the generator/feasibility check.

        A bucket is a dict with:
            label     -> human readable bucket name
            domain    -> leaf domain (list of tuples) on ``cbt.mcqs``
            required  -> number of questions needed for ONE paper
            rule      -> originating ``cbt.paper.criteria.rule``

        The decomposition follows the real rule structure: topic rules take
        precedence, then question-type rules, then difficulty rules, then the
        whole subject.
        """
        self.ensure_one()
        buckets = []
        for rule in self.rules_ids:
            base = [('subject_id', '=', rule.subjects.id)] if rule.subjects else []
            if rule.topic_rules:
                for topic_rule in rule.topic_rules:
                    domain = list(base)
                    label = 'Topic %s' % (topic_rule.topic_id.name or '?')
                    if topic_rule.sub_topic_id:
                        domain.append(('stopic_id', '=', topic_rule.sub_topic_id.id))
                        label += ' / Sub Topic %s' % topic_rule.sub_topic_id.name
                    if topic_rule.difficulty_level_id:
                        domain.append(('difficulty_level_id', '=', topic_rule.difficulty_level_id.id))
                        label += ' / Difficulty %s' % topic_rule.difficulty_level_id.name
                    buckets.append({
                        'label': label,
                        'domain': domain,
                        'required': self._int_or_zero(topic_rule.no_questions),
                        'rule': rule,
                    })
            elif rule.type_rules:
                for type_rule in rule.type_rules:
                    domain = list(base) + [('type_id', '=', type_rule.type_id.id)]
                    label = 'Question Type %s' % (type_rule.type_id.name or '?')
                    buckets.append({
                        'label': label,
                        'domain': domain,
                        'required': self._int_or_zero(type_rule.no_questions),
                        'rule': rule,
                    })
            elif rule.difficulty_rules:
                for diff_rule in rule.difficulty_rules:
                    domain = list(base) + [('difficulty_level_id', '=', diff_rule.difficulty_level_id.id)]
                    label = 'Difficulty %s' % (diff_rule.difficulty_level_id.name or '?')
                    buckets.append({
                        'label': label,
                        'domain': domain,
                        'required': self._int_or_zero(diff_rule.no_questions),
                        'rule': rule,
                    })
            else:
                buckets.append({
                    'label': rule.subjects.name or 'Subject',
                    'domain': list(base),
                    'required': self._int_or_zero(rule.no_questions),
                    'rule': rule,
                })
        return buckets

    def _get_max_unique_papers(self):
        """Return the maximum number of papers with mutually disjoint question
        sets that the current question bank can supply for this criteria.

        It is the tightest bucket: for every rule bucket the bank must hold
        ``required * papers`` questions, so the bucket caps the number of
        papers at ``available // required``. The overall maximum is the minimum
        over all buckets (0 when no question requirement is defined).
        """
        self.ensure_one()
        pool = self.env['cbt.mcqs']
        limits = []
        for bucket in self._iter_rule_buckets():
            required = bucket['required']
            if required <= 0:
                continue
            available = len(pool._get_generation_pool(bucket['domain']))
            limits.append(available // required)
        return min(limits) if limits else 0

    def _get_availability(self):
        """Return the per-bucket capacity of the current question bank.

        Each item reports how many questions a single paper needs from the
        bucket (``required``), how many are currently available in the bank
        (``available``) and how many unique papers the bucket can therefore
        support (``max_papers``).
        """
        self.ensure_one()
        pool = self.env['cbt.mcqs']
        result = []
        for bucket in self._iter_rule_buckets():
            required = bucket['required']
            available = len(pool._get_generation_pool(bucket['domain']))
            result.append({
                'label': bucket['label'],
                'required': required,
                'available': available,
                'max_papers': (available // required) if required > 0 else 0,
            })
        return result

    def action_check_availability(self):
        self.ensure_one()
        availability = self._get_availability()
        if availability:
            summary = '\n'.join(
                "%s: need %s per paper, available %s -> up to %s paper(s)" % (
                    item['label'], item['required'], item['available'],
                    item['max_papers'])
                for item in availability)
            summary += '\n\n' + _("Maximum unique papers: %s") % (
                self._get_max_unique_papers())
        else:
            summary = _("No paper rules defined.")
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Availability Check'),
                'message': summary,
                'type': 'success',
                'sticky': False,
            },
        }

    def action_view_generated_papers(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id(
            'cbt.cbt_paper_action')
        action['domain'] = [('criteria_id', '=', self.id)]
        action['context'] = {'default_criteria_id': self.id}
        return action


class CBTPaperCriteriaRule(models.Model):
    _name = 'cbt.paper.criteria.rule'
    _description = 'Paper rules'

    subjects = fields.Many2one('cbt.subject', 'Subjects', required=True)
    topic_rules = fields.One2many('cbt.paper.criteria.rule.topic', 'criteria_rule_id', 'Topic Rules')
    difficulty_rules = fields.One2many('cbt.paper.criteria.rule.difficulty', 'criteria_rule_id', 'Paper Difficulty',
                                       required=True)
    type_rules = fields.One2many('cbt.paper.criteria.rule.type', 'criteria_rule_id', 'Type')
    # topics = fields.Many2one('cbt.subject.topic', 'Topics')
    # sub_topics = fields.Many2one('cbt.subject.subtopic', 'Sub Topics')
    # difficulty_level_id = fields.Many2one('cbt.question.difficulty.level', 'Difficulty Level')
    no_questions = fields.Char(string='Number of Questions', required=True)
    total_questions_difficulty_rule = fields.Char()
    total_questions_topic_rule = fields.Char()
    paper_id = fields.Many2one('cbt.paper.criteria', 'Paper ID')
    sequence = fields.Integer('Section Sequence', required=True, default=1)
    subjects = fields.Many2one('cbt.subject', 'Sections', required=True)


    @api.model
    def create(self, vals):
        result = super().create(vals)
        if not vals.get('difficulty_rules'):
            raise UserError(_("Please Define Paper Difficulty Criteria in Paper Rules"))
        elif vals.get('no_questions') != vals.get('total_questions_difficulty_rule'):
            raise ValidationError(_("Number of Questions in Subject and Difficult Level Criteria should be equal"))
        elif vals.get('topic_rules'):
            if vals.get('no_questions') != vals.get('total_questions_topic_rule'):
                raise ValidationError(_("Number of Questions in Subject and Topics/Subtopics Criteria should be equal"))

        return result

    @api.onchange('difficulty_rules')
    def change_total_question_lines(self):
        count = 0
        for difficulty_rule in self.difficulty_rules:
            count = count + int(difficulty_rule.no_questions)
        self.total_questions_difficulty_rule = str(count)

    @api.onchange('topic_rules')
    def change_total_questions_topics_lines(self):
        count = 0
        for topic_rule in self.topic_rules:
            count = count + int(topic_rule.no_questions)
        self.total_questions_topic_rule = str(count)

    def write(self, vals):
        result = super().write(vals)
        if not self.difficulty_rules:
            raise UserError(_("Please Define Paper Difficulty Criteria in Paper Rules"))
        elif self.no_questions != self.total_questions_difficulty_rule:
            raise ValidationError(_("Number of Questions in Subject and Difficult Level Criteria should be equal"))
        elif self.topic_rules:
            if self.no_questions != self.total_questions_topic_rule and int(self.total_questions_topic_rule) > 0:
                raise ValidationError(_("Number of Questions in Subject and Topics/Subtopics Criteria should be equal"))

        return result


class CBTPaperCriteriaRuleTopic(models.Model):
    _name = 'cbt.paper.criteria.rule.topic'
    _description = 'Paper Rule Topic'

    topic_id = fields.Many2one('cbt.subject.topic', 'Topic')
    sub_topic_id = fields.Many2one('cbt.subject.subtopic', 'Sub Topic')
    difficulty_level_id = fields.Many2one('cbt.question.difficulty.level', 'Difficulty Level')
    criteria_rule_id = fields.Many2one('cbt.paper.criteria.rule', 'Criteria Rule')
    no_questions = fields.Char(string='Number of Questions', required=True)
    subjects = fields.Many2one(related='criteria_rule_id.subjects')




class CBTPaperCriteriaRuleDifficulty(models.Model):
    _name = 'cbt.paper.criteria.rule.difficulty'
    _description = 'Paper Rule Difficulty'

    difficulty_level_id = fields.Many2one('cbt.question.difficulty.level', 'Difficulty Level', required=True)
    criteria_rule_id = fields.Many2one('cbt.paper.criteria.rule', 'Criteria Rule')
    no_questions = fields.Char(string='Number of Questions', required=True)


class CBTPaperCriteriaRuleType(models.Model):
    _name = 'cbt.paper.criteria.rule.type'
    _description = 'Paper Rule Type'

    type_id = fields.Many2one('cbt.question.type', 'Type')
    criteria_rule_id = fields.Many2one('cbt.paper.criteria.rule', 'Criteria Rule')
    no_questions = fields.Char(string='Number of Questions', required=True)
