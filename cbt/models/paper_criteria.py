import re

from odoo import fields, models, _, api
import pdb
import math
from odoo.exceptions import ValidationError
import random


class CBTGeneratePaper(models.Model):
    _name = 'cbt.paper.criteria'
    _description = 'Paper Criteria'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    current_user = fields.Many2one(
        'res.users', 'Created By', default=lambda self: self.env.user,
        readonly=True)
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
    rules_ids = fields.One2many('cbt.paper.criteria.rule', 'paper_id', string='Rules ID', required=True,
                                tracking=True)

    @staticmethod
    def _question_count(value, label, required=True):
        if value in (None, False, ''):
            if required:
                raise ValidationError(_('%s is required.') % label)
            return None
        try:
            count = int(value)
        except (TypeError, ValueError, OverflowError):
            raise ValidationError(_('%s must be a whole number.') % label)
        if count < 0:
            raise ValidationError(_('%s cannot be negative.') % label)
        return count

    @api.model
    def create(self, vals):
        result = super(
            CBTGeneratePaper,
            self.with_context(cbt_defer_question_count_validation=True),
        ).create(vals)
        result._validate_question_counts()
        return result

    def write(self, vals):
        result = super(
            CBTGeneratePaper,
            self.with_context(cbt_defer_question_count_validation=True),
        ).write(vals)
        self._validate_question_counts()
        return result

    def _validate_question_counts(self):
        for criteria in self:
            rules = criteria.rules_ids
            for rule in rules:
                rule._validate_question_counts()

            total = criteria._question_count(
                criteria.total_questions, _('Total Questions'), required=False)
            if total is None:
                continue
            section_total = sum(
                criteria._question_count(
                    rule.no_questions, _('Section question count'))
                for rule in rules)
            if total != section_total:
                raise ValidationError(_(
                    'The total number of questions (%(total)s) must equal '
                    'the sum of section question counts (%(sections)s).'
                ) % {'total': total, 'sections': section_total})

    @api.onchange('rules_ids')
    def change_total_question_lines(self):
        count = 0
        for each in self.rules_ids:
            count += self._question_count(
                each.no_questions, _('Section question count'))
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
    _inherit = ['cbt.line.access']

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
        model = self.sudo() if self._cbt_can_elevate() else self
        result = super(
            CBTPaperCriteriaRule,
            model.with_context(cbt_defer_question_count_validation=True),
        ).create(vals)
        if not self.env.context.get('cbt_defer_question_count_validation'):
            result._validate_question_counts()
            result.mapped('paper_id')._validate_question_counts()
        return result

    def write(self, vals):
        model = self.sudo() if self._cbt_can_elevate() else self
        previous_criteria = model.mapped('paper_id')
        result = super(
            CBTPaperCriteriaRule,
            model.with_context(cbt_defer_question_count_validation=True),
        ).write(vals)
        if not model.env.context.get('cbt_defer_question_count_validation'):
            model._validate_question_counts()
            (previous_criteria | model.mapped('paper_id'))._validate_question_counts()
        return result

    def unlink(self):
        criteria = self.mapped('paper_id')
        result = super().unlink()
        if not self.env.context.get('cbt_defer_question_count_validation'):
            criteria._validate_question_counts()
        return result

    def _validate_question_counts(self):
        for rule in self:
            if not rule.difficulty_rules:
                raise ValidationError(
                    _("Please Define Paper Difficulty Criteria in Paper Rules"))
            section_count = self.env[
                'cbt.paper.criteria']._question_count(
                    rule.no_questions, _('Section question count'))
            for field_name, label in (
                    ('difficulty_rules', _('Paper Difficulty')),
                    ('topic_rules', _('Paper Topic Rules'))):
                lines = rule[field_name]
                if not lines:
                    continue
                line_total = sum(
                    self.env['cbt.paper.criteria']._question_count(
                        line.no_questions, _('%s question count') % label)
                    for line in lines)
                if line_total > section_count:
                    raise ValidationError(_(
                        '%(rule)s question counts (%(count)s) cannot exceed '
                        'the section question count (%(section)s).'
                    ) % {
                        'rule': label,
                        'count': line_total,
                        'section': section_count,
                    })

    @api.onchange('difficulty_rules')
    def change_total_question_lines(self):
        count = 0
        for difficulty_rule in self.difficulty_rules:
            count += self.env['cbt.paper.criteria']._question_count(
                difficulty_rule.no_questions,
                _('Paper Difficulty question count'))
        self.total_questions_difficulty_rule = str(count)

    @api.onchange('topic_rules')
    def change_total_questions_topics_lines(self):
        count = 0
        for topic_rule in self.topic_rules:
            count += self.env['cbt.paper.criteria']._question_count(
                topic_rule.no_questions,
                _('Paper Topic Rules question count'))
        self.total_questions_topic_rule = str(count)


class CBTPaperCriteriaRuleTopic(models.Model):
    _name = 'cbt.paper.criteria.rule.topic'
    _description = 'Paper Rule Topic'
    _inherit = ['cbt.line.access']

    topic_id = fields.Many2one('cbt.subject.topic', 'Topic')
    sub_topic_id = fields.Many2one('cbt.subject.subtopic', 'Sub Topic')
    difficulty_level_id = fields.Many2one('cbt.question.difficulty.level', 'Difficulty Level')
    criteria_rule_id = fields.Many2one('cbt.paper.criteria.rule', 'Criteria Rule')
    no_questions = fields.Char(string='Number of Questions', required=True)
    subjects = fields.Many2one(related='criteria_rule_id.subjects')

    @api.model_create_multi
    def create(self, vals_list):
        records = super(
            CBTPaperCriteriaRuleTopic,
            self.with_context(cbt_defer_question_count_validation=True),
        ).create(vals_list)
        _validate_rule_question_count_changes(self, records.mapped('criteria_rule_id'))
        return records

    def write(self, vals):
        rules = self.mapped('criteria_rule_id')
        result = super(
            CBTPaperCriteriaRuleTopic,
            self.with_context(cbt_defer_question_count_validation=True),
        ).write(vals)
        rules |= self.mapped('criteria_rule_id')
        _validate_rule_question_count_changes(self, rules)
        return result

    def unlink(self):
        rules = self.mapped('criteria_rule_id')
        result = super().unlink()
        _validate_rule_question_count_changes(self, rules)
        return result


class CBTPaperCriteriaRuleDifficulty(models.Model):
    _name = 'cbt.paper.criteria.rule.difficulty'
    _description = 'Paper Rule Difficulty'
    _inherit = ['cbt.line.access']

    difficulty_level_id = fields.Many2one('cbt.question.difficulty.level', 'Difficulty Level', required=True)
    criteria_rule_id = fields.Many2one('cbt.paper.criteria.rule', 'Criteria Rule')
    no_questions = fields.Char(string='Number of Questions', required=True)

    @api.model_create_multi
    def create(self, vals_list):
        records = super(
            CBTPaperCriteriaRuleDifficulty,
            self.with_context(cbt_defer_question_count_validation=True),
        ).create(vals_list)
        _validate_rule_question_count_changes(self, records.mapped('criteria_rule_id'))
        return records

    def write(self, vals):
        rules = self.mapped('criteria_rule_id')
        result = super(
            CBTPaperCriteriaRuleDifficulty,
            self.with_context(cbt_defer_question_count_validation=True),
        ).write(vals)
        rules |= self.mapped('criteria_rule_id')
        _validate_rule_question_count_changes(self, rules)
        return result

    def unlink(self):
        rules = self.mapped('criteria_rule_id')
        result = super().unlink()
        _validate_rule_question_count_changes(self, rules)
        return result


class CBTPaperCriteriaRuleType(models.Model):
    _name = 'cbt.paper.criteria.rule.type'
    _description = 'Paper Rule Type'
    _inherit = ['cbt.line.access']

    type_id = fields.Many2one('cbt.question.type', 'Type')
    criteria_rule_id = fields.Many2one('cbt.paper.criteria.rule', 'Criteria Rule')
    no_questions = fields.Char(string='Number of Questions', required=True)


def _validate_rule_question_count_changes(env_model, rules):
    if env_model.env.context.get('cbt_defer_question_count_validation'):
        return
    rules._validate_question_counts()
    rules.mapped('paper_id')._validate_question_counts()
