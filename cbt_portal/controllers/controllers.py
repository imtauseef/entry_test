import json

from odoo import fields, http, _
from odoo.http import request

from . import main


class CBTHome(http.Controller):
    def _candidate_paper(
            self, user_id, states, paper_id=None, latest=False,
            started_only=False):
        domain = [
            ('user_id', '=', user_id),
            ('batch_id.state', 'in', states),
        ]
        if started_only:
            domain.append(('paper_started', '!=', False))
        if paper_id is not None:
            domain.append(('id', '=', paper_id))
        papers = request.env['cbt.paper.export'].sudo().search(
            domain, order='batch_id desc, id desc', limit=1 if latest else 2)
        if latest:
            return papers
        return papers if len(papers) == 1 else request.env[
            'cbt.paper.export'].sudo().browse([])

    def _json_error(self, message):
        return json.dumps({'message': message, 'error': message})

    @http.route(
        ['/cbt/home'], type='http', auth='user', website=True,
        methods=['GET', 'POST'])
    def cbt_portal_home(self, **kw):
        values, _success, user = main.prepare_portal_values(request)
        paper = self._candidate_paper(user.id, ['active'])
        if not paper:
            paper = self._candidate_paper(
                user.id, ['finished', 'result_collected'],
                latest=True, started_only=True)
        if paper:
            paper._cbt_expire_if_time_up()
        instructions = request.env['cbt.instruction.export'].sudo().search([])
        if paper:
            paper.write({'is_login': True})
        values.update({
            'paper': paper,
            'instructions': instructions,
            'end_paper': paper.end_paper if paper else False,
            'error_message': False if paper else _(
                'There is no active test batch assigned to your account.'),
        })
        return request.render('cbt_portal.cbt_instruction', values)

    @http.route(
        ['/cbt/paper'], type='http', auth='user', website=True,
        methods=['GET', 'POST'])
    def cbt_portal_paper(self, **kw):
        values, _success, user = main.prepare_portal_values(request)
        paper = self._candidate_paper(user.id, ['active'])
        if not paper:
            finished_paper = self._candidate_paper(
                user.id, ['finished', 'result_collected'],
                latest=True, started_only=True)
            if finished_paper:
                return request.redirect('/cbt/paper/finish/page')
            values.update({
                'paper': False,
                'error_message': _('There is no active test batch assigned to your account.'),
            })
            return request.render('cbt_portal.cbt_paper', values)
        paper._cbt_expire_if_time_up()
        if paper.end_paper:
            return request.redirect('/cbt/paper/finish/page')
        if not paper.paper_started:
            now = fields.Datetime.now()
            paper.write({'paper_started': now})
            request.env['cbt.paper.session'].sudo().create({
                'paper_id': paper.id,
                'name': paper.batch_id.name,
                'start_time': fields.Datetime.to_string(now),
            })
        values.update({
            'paper': paper,
            'instructions': request.env['cbt.instruction.export'].sudo().search(
                [], limit=1),
            'feedback_types': request.env[
                'cbt.paper.question.feedback.type'].sudo().search([
                    ('active', '=', True),
                ]),
            'paper_page': True,
            'error_message': False,
        })
        return request.render('cbt_portal.cbt_paper', values)

    @http.route(
        ['/cbt/rec/feedback'], type='http', auth='user', website=True,
        methods=['POST'])
    def cbt_portal_rec_feedback(self, **kw):
        _values, _success, user = main.prepare_portal_values(request)
        try:
            paper_id = int(kw.get('paper_id'))
            question_id = int(kw.get('question_id'))
        except (TypeError, ValueError):
            return self._json_error(_('Invalid paper or question identifier.'))

        paper = self._candidate_paper(user.id, ['active'], paper_id)
        if paper:
            paper._cbt_expire_if_time_up()
        if not paper or paper.end_paper or not paper.paper_started:
            return self._json_error(_('This paper is not active for your account.'))

        question = request.env['cbt.paper.line.export'].sudo().search([
            ('id', '=', question_id),
            ('paper_id', '=', paper.id),
        ], limit=1)
        if not question:
            return self._json_error(_('The question does not belong to your paper.'))

        feedback_text = (kw.get('feedback_text') or '').strip()
        if len(feedback_text) > 32767:
            return self._json_error(_(
                "Feedback must not exceed Excel's maximum cell length."))

        feedback_type = request.env[
            'cbt.paper.question.feedback.type'].sudo().browse()
        if kw.get('feedback_type_id'):
            try:
                feedback_type_id = int(kw['feedback_type_id'])
            except (TypeError, ValueError):
                return self._json_error(_('Select a valid feedback type.'))
            feedback_type = request.env[
                'cbt.paper.question.feedback.type'].sudo().search([
                    ('id', '=', feedback_type_id),
                    ('active', '=', True),
                ], limit=1)
            if not feedback_type:
                return self._json_error(_('Select a valid feedback type.'))

        if feedback_type.is_other and not feedback_text:
            return self._json_error(_(
                'Please describe the concern when selecting Other.'))

        Feedback = request.env['cbt.paper.question.feedback'].sudo()
        existing_feedback = Feedback.search([
            ('paper_id', '=', paper.id),
            ('question_id', '=', question.id),
        ], limit=1)
        if not feedback_type and not feedback_text:
            existing_feedback.unlink()
            return json.dumps({'message': _('Feedback cleared.')})

        feedback_values = {
            'paper_id': paper.id,
            'question_id': question.id,
            'feedback_type_id': feedback_type.id or False,
            'feedback_type_name': feedback_type.name or False,
            'feedback_text': feedback_text or False,
        }
        if existing_feedback:
            existing_feedback.write(feedback_values)
        else:
            Feedback.create(feedback_values)
        return json.dumps({'message': _('Feedback saved.')})

    @http.route(
        ['/cbt/rec/answer'], type='http', auth='user', website=True,
        csrf=False, methods=['GET', 'POST'])
    def cbt_portal_rec_answer(self, **kw):
        _values, _success, user = main.prepare_portal_values(request)
        try:
            paper_id = int(kw.get('paper_id'))
            question_id = int(kw.get('question_id'))
            subject_id = int(kw.get('subject_id'))
        except (TypeError, ValueError):
            return self._json_error(_('Invalid paper or question identifier.'))
        paper = self._candidate_paper(user.id, ['active'], paper_id)
        if paper:
            paper._cbt_expire_if_time_up()
        if not paper or paper.end_paper or not paper.paper_started:
            return self._json_error(_('This paper is not active for your account.'))
        question = request.env['cbt.paper.line.export'].sudo().search([
            ('id', '=', question_id),
            ('subject_id', '=', subject_id),
            ('paper_id', '=', paper.id),
        ], limit=1)
        if not question:
            return self._json_error(_('The question does not belong to your paper.'))

        page = None
        if kw.get('page'):
            try:
                page = int(kw['page'])
            except (TypeError, ValueError):
                return self._json_error(_('The question page number is invalid.'))
            if page < 1 or page > len(paper.line_ids):
                return self._json_error(_('The question page number is invalid.'))
        values = {'answer_recorded_time': fields.Datetime.now()}
        theory_answer = kw.get('theory_answer')
        if question.uses_paragraph:
            if theory_answer is None:
                theory_answer = ''
            if len(theory_answer) > 32767:
                return self._json_error(_(
                    "Theory answers must not exceed Excel's maximum cell length."
                ))
            values.update({
                'answer': 0,
                'answer_alphabet': False,
                'theory_answer': theory_answer,
            })
        else:
            try:
                option_id = int(kw.get('answer'))
                answer_number = int(kw.get('answer_no'))
            except (TypeError, ValueError):
                return self._json_error(_('Select a valid answer option.'))
            option = question.option_ids.filtered(
                lambda item: item.id == option_id)
            if (
                    not option
                    or answer_number < 1
                    or answer_number > len(question.option_ids)
                    or option.sequence != answer_number):
                return self._json_error(_('The selected option is invalid.'))
            values.update({
                'answer': option_id,
                'answer_alphabet': chr(64 + answer_number),
                'theory_answer': False,
            })
        question.write(values)
        if page:
            paper.write({'current_q': page})
        return json.dumps({
            'message': 'saved',
            'total_q': len(paper.line_ids),
            'answered': len(paper.line_ids.filtered(
                lambda line: line.is_answered)),
        })

    @http.route(
        ['/cbt/rec/mark_review'], type='http', auth='user', website=True,
        csrf=False, methods=['GET', 'POST'])
    def cbt_portal_mark_review(self, **kw):
        _values, _success, user = main.prepare_portal_values(request)
        try:
            paper_id = int(kw.get('paper_id'))
            question_id = int(kw.get('question_id'))
            subject_id = int(kw.get('subject_id'))
        except (TypeError, ValueError):
            return self._json_error(_('Invalid paper or question identifier.'))
        paper = self._candidate_paper(user.id, ['active'], paper_id)
        if paper:
            paper._cbt_expire_if_time_up()
        if not paper or paper.end_paper or not paper.paper_started:
            return self._json_error(_('This paper is not active for your account.'))
        question = request.env['cbt.paper.line.export'].sudo().search([
            ('id', '=', question_id),
            ('subject_id', '=', subject_id),
            ('paper_id', '=', paper.id),
        ], limit=1)
        if not question:
            return self._json_error(_('The question does not belong to your paper.'))
        question.write({'mark_review': kw.get('mark') == 'true'})
        return json.dumps({})

    @http.route(
        ['/cbt/rec/review/marked/questions'], type='http', auth='user',
        website=True, csrf=False, methods=['GET', 'POST'])
    def cbt_portal_review_marked_questions(self, **kw):
        _values, _success, user = main.prepare_portal_values(request)
        try:
            paper_id = int(kw.get('paper_id'))
        except (TypeError, ValueError):
            return self._json_error(_('Invalid paper identifier.'))
        paper = self._candidate_paper(user.id, ['active'], paper_id)
        if paper:
            paper._cbt_expire_if_time_up()
        if not paper or paper.end_paper or not paper.paper_started:
            return self._json_error(_('This paper is not active for your account.'))
        marked = paper.line_ids.filtered('mark_review')
        return json.dumps({
            'mark_review_list': [{
                'id': question.id,
                'question': question.name,
                'subject': question.subject_id.name,
                'options': [{
                    'id': option.id,
                    'option': option.name,
                } for option in question.option_ids],
                'is_theory': question.uses_paragraph,
                'theory_answer': question.theory_answer or '',
            } for question in marked],
        })

    @http.route(
        ['/cbt/paper/finish'], type='http', auth='user', csrf=False,
        website=True, methods=['GET', 'POST'])
    def cbt_portal_finish(self, **kw):
        _values, _success, user = main.prepare_portal_values(request)
        try:
            paper_id = int(kw.get('paper_id'))
        except (TypeError, ValueError):
            return self._json_error(_('Invalid paper identifier.'))
        paper = self._candidate_paper(user.id, ['active'], paper_id)
        if paper:
            paper._cbt_expire_if_time_up()
        if not paper or not paper.paper_started:
            return self._json_error(_('This paper is not active for your account.'))
        if not paper.end_paper:
            now = fields.Datetime.now()
            paper.write({
                'end_paper': True,
                'end_paper_time': now,
            })
            if paper.session_ids:
                paper.session_ids[-1].write({
                    'end_time': fields.Datetime.to_string(now),
                })
        return json.dumps({})

    @http.route(
        ['/cbt/paper/finish/page'], type='http', auth='user', csrf=False,
        website=True, methods=['GET', 'POST'])
    def cbt_portal_finish_page(self, **kw):
        values, _success, user = main.prepare_portal_values(request)
        paper = self._candidate_paper(user.id, ['active']) or (
            self._candidate_paper(
                user.id, ['finished', 'result_collected'],
                latest=True, started_only=True))
        if paper:
            paper._cbt_expire_if_time_up()
        values.update({
            'paper': paper,
            'end_paper': paper.end_paper if paper else False,
            'error_message': False if paper else _(
                'There is no completed test paper for your account.'),
        })
        response = request.render('cbt_portal.cbt_finish', values)
        release = request.env['ir.config_parameter'].sudo().get_param(
            'cbt.release_session_on_finish')
        if paper and paper.end_paper and str(release).lower() in (
                '1', 'true', 'yes'):
            request.env.user.sudo()._cbt_clear_session()
        return response

    @http.route(
        ['/cbt/time/remaining'], type='http', auth='user', website=True,
        csrf=False, methods=['GET', 'POST'])
    def cbt_portal_remaining(self, **kw):
        if not main.cbt_session_valid(request):
            return json.dumps({
                'session_ended': True,
                'error': 'Your session ended because this account was '
                         'logged in on another device.',
            })
        _values, _success, user = main.prepare_portal_values(request)
        paper = self._candidate_paper(user.id, ['active']) or (
            self._candidate_paper(
                user.id, ['finished', 'result_collected'],
                latest=True, started_only=True))
        if not paper:
            return self._json_error(_('There is no paper for your account.'))
        paper._cbt_expire_if_time_up()
        remaining_seconds = paper._cbt_remaining_seconds()
        remaining = '%s:%02d' % divmod(remaining_seconds, 60)
        if paper.batch_id.state == 'active' and not paper.end_paper:
            paper.write({'time_remaining': remaining})
        return json.dumps({
            'paper_state': paper.end_paper,
            'time_remaining': remaining,
        })

    @http.route(
        ['/cbt/paper/currentState'], type='http', auth='user', website=True,
        methods=['GET', 'POST'])
    def cbt_portal_current_state(self, **kw):
        if not main.cbt_session_valid(request):
            return json.dumps({
                'session_ended': True,
                'error': 'Your session ended because this account was '
                         'logged in on another device.',
            })
        _values, _success, user = main.prepare_portal_values(request)
        paper = self._candidate_paper(user.id, ['active']) or (
            self._candidate_paper(
                user.id, ['finished', 'result_collected'],
                latest=True, started_only=True))
        if not paper:
            return self._json_error(_('There is no paper for your account.'))
        paper._cbt_expire_if_time_up()
        remaining_seconds = paper._cbt_remaining_seconds()
        remaining = '%s:%02d' % divmod(remaining_seconds, 60)
        return json.dumps({
            'paper_state': paper.end_paper,
            'paper_started': bool(paper.paper_started),
            'current_q': paper.current_q,
            'time_remaining': remaining,
        })

    @http.route(
        ['/cbt/paper/review'], type='http', auth='user', website=True,
        methods=['GET', 'POST'])
    def cbt_portal_paper_review(self, **kw):
        values, _success, user = main.prepare_portal_values(request)
        paper = self._candidate_paper(user.id, ['active'])
        if not paper:
            finished_paper = self._candidate_paper(
                user.id, ['finished', 'result_collected'],
                latest=True, started_only=True)
            if finished_paper:
                return request.redirect('/cbt/paper/finish/page')
            values.update({
                'paper': False,
                'error_message': _('There is no active test batch assigned to your account.'),
            })
            return request.render('cbt_portal.cbt_paper_review', values)
        paper._cbt_expire_if_time_up()
        if paper.end_paper:
            return request.redirect('/cbt/paper/finish/page')
        if not paper.paper_started:
            now = fields.Datetime.now()
            paper.write({'paper_started': now})
            request.env['cbt.paper.session'].sudo().create({
                'paper_id': paper.id,
                'name': paper.batch_id.name,
                'start_time': fields.Datetime.to_string(now),
            })
        values.update({
            'paper': paper,
            'paper_page': True,
            'error_message': False,
        })
        return request.render('cbt_portal.cbt_paper_review', values)
