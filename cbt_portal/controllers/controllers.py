import json
from datetime import date, datetime, timedelta
from . import main
from odoo import http
from odoo.http import request
import socket
# But first get the computer name


class CBTHome(http.Controller):
    @http.route(['/cbt/home'], type='http', auth="user", website=True, methods=['GET', 'POST'])
    def cbt_portal_home(self, **kw):
        try:
            values, success, participant = main.prepare_portal_values(request)
            
            paper_id = http.request.env['cbt.paper.export'].sudo().search([('login','=',participant.login)], limit=1)
           
            data = {
                'is_login': True
            }
            paper_id.sudo().write(data)
            instructions = http.request.env['cbt.instruction.export'].sudo().search([])

            values.update({
                'paper': paper_id,
                'instructions': instructions,
                'end_paper': paper_id.end_paper
             })

            return http.request.render('cbt_portal.cbt_instruction', values)
        except Exception as e:
            values = {
                'error_message': e or False
            }
            return http.request.render('cbt_portal.cbt_instruction', values)

    @http.route(['/cbt/paper'], type='http', auth="user", website=True, methods=['GET', 'POST'])
    def cbt_portal_paper(self, **kw):
        try:
            values, success, participant = main.prepare_portal_values(request)
            paper_id = http.request.env['cbt.paper.export'].sudo().search([('login', '=', participant.login)], limit=1)
          
            start_time = paper_id
            if not paper_id.paper_started:
                data = {
                 'paper_started': datetime.now()
                }
                start_time.sudo().write(data)
            elif paper_id.paper_started:
                data = {
                    'start_time': datetime.now(),
                    'paper_id': start_time.id
                }
                start_time.session_ids.sudo().write(data)

            values.update({
                'paper': paper_id,
                'paper_page': True,
            })
            return http.request.render('cbt_portal.cbt_paper', values)
        except Exception as e:
            values = {
                'error_message': e or False
            }
            return http.request.render('cbt_portal.cbt_paper', values)

    @http.route(['/cbt/rec/answer'], type='http', auth="user", website=True, csrf=False, methods=['GET', 'POST'])
    def cbt_portal_rec_answer(self, **kw):
        try:
            values, success, participant = main.prepare_portal_values(request)
            question_id = int(kw.get('question_id'))
            subject_id = int(kw.get('subject_id'))
            paper_id = int(kw.get('paper_id'))
            answer = int(kw.get('answer'))
            answer_no = int(kw.get('answer_no'))

            if answer_no == 1:
                answer_no = "A"
            elif answer_no == 2:
                answer_no = "B"
            elif answer_no == 3:
                answer_no = "C"
            elif answer_no == 4:
                answer_no = "D"
            elif answer_no == 5:
                answer_no = "E"
            elif answer_no == 6:
                answer_no = "F"
            else:
                answer_no = "Too many options"
            answer_id = http.request.env['cbt.paper.line.export'].sudo().search(
                [('id', '=', question_id), ('subject_id', '=', subject_id), ('paper_id', '=', paper_id)])

            data = {
                'answer': answer,
                'answer_alphabet': answer_no
            }
            answer_id.sudo().write(data)
            current_question = http.request.env['cbt.paper.export'].sudo().search(
                [('id', '=', paper_id)])
            if kw.get('page'):
                data = {
                    'current_q': int(kw.get('page')),
                }
                current_question.sudo().write(data)
            paper_id = http.request.env['cbt.paper.export'].sudo().search([('login', '=', participant.login)], limit=1)
            data = {
                'message': 'saved',
                'total_q': len(paper_id.line_ids),
                'answered': len(paper_id.line_ids.filtered(lambda l: l.answer > 0))
            }
        except Exception as e:
            print(e)
            data={
             'message': e.args[0],
            }
        data = json.dumps(data)
        return data

    @http.route(['/cbt/rec/mark_review'], type='http', auth="user", website=True, csrf=False, methods=['GET', 'POST'])
    def cbt_portal_mark_review(self, **kw):
        try:
            values, success, participant = main.prepare_portal_values(request)
           
            question_id = int(kw.get('question_id'))
            subject_id = int(kw.get('subject_id'))
            paper_id = int(kw.get('paper_id'))
            mark_review_id = kw.get('mark')
            mark_review = http.request.env['cbt.paper.line.export'].sudo().search(
                [('id', '=', question_id), ('subject_id', '=', subject_id), ('paper_id', '=', paper_id)])

            data = {
                'mark_review': True if mark_review_id == 'true' else False,
            }

            mark_review.sudo().write(data)
            data = {

            }
        except Exception as e:
            print(e)
            data = {
                'message': e.args[0],
            }
        data = json.dumps(data)
        return data

    @http.route(['/cbt/rec/review/marked/questions'], type='http', auth="user", website=True, csrf=False, methods=['GET', 'POST'])
    def cbt_portal_review_marked_questions(self, **kw):
        try:
            values, success, participant = main.prepare_portal_values(request)
            
            paper_id = int(kw.get('paper_id'))
            mark_review = http.request.env['cbt.paper.line.export'].sudo().search(
                [('paper_id', '=', paper_id), ('mark_review', '=', True)])
            mark_review_list = []
            for question in mark_review:
                options = []
                for option in question.option_ids:
                    options.append({'id': option.id, 'option': option.name })
                mark_review_list.append({'id': question.id, 'question': question.name, 'subject': question.subject_id.name, 'options': options})

            data = {
                'mark_review_list': mark_review_list
            }
        except Exception as e:
            print(e)
            data = {
                'message': e.args[0],
            }
        data = json.dumps(data)
        return data

    @http.route(['/cbt/paper/finish'], type='http', auth="user", csrf=False, website=True, methods=['GET', 'POST'])
    def cbt_portal_finish(self, **kw):
        try:
            values, success, participant = main.prepare_portal_values(request)
            
            paper = int(kw.get('paper_id'))
            paper_id = http.request.env['cbt.paper.export'].sudo().browse(paper)
           
            data = {
                'end_paper': True,
                'end_paper_time': datetime.now()
            }
            paper_id.write(data)

            values.update({
                'paper': paper_id,
                'end_paper': paper_id.end_paper,
            })
            if paper:
                data = {

                }
                data = json.dumps(data)
                return  data
            return http.request.render('cbt_portal.cbt_finish', values)
        except Exception as e:
            values = {
                'error_message': e or False
            }
            return http.request.render('cbt_portal.cbt_finish', values)

    @http.route(['/cbt/paper/finish/page'], type='http', auth="user", csrf=False, website=True, methods=['GET', 'POST'])
    def cbt_portal_finish_page(self, **kw):
        try:
            values, success, participant = main.prepare_portal_values(request)
            paper_id = http.request.env['cbt.paper.export'].sudo().search([('login','=',participant.login)], limit=1)

            values.update({
                'paper': paper_id,
                'end_paper': paper_id.end_paper,
            })
            # request.session.logout()
            response = http.request.render('cbt_portal.cbt_finish', values)
        except Exception as e:
            values = {
                'error_message': e or False
            }
            response = http.request.render('cbt_portal.cbt_finish', values)

        release = request.env['ir.config_parameter'].sudo().get_param(
            'cbt.release_session_on_finish')
        if str(release).lower() in ('1', 'true', 'yes'):
            request.env.user.sudo()._cbt_clear_session()
        return response

    @http.route(['/cbt/time/remaining'], type='http', auth="user", website=True, csrf=False,methods=['GET', 'POST'])
    def cbt_portal_remaining(self, **kw):
        try:
            if not main.cbt_session_valid(request):
                return json.dumps({
                    'session_ended': True,
                    'error': 'Your session ended because this account was '
                             'logged in on another device.',
                })
            values, success, participant = main.prepare_portal_values(request)
            paper_id = http.request.env['cbt.paper.export'].sudo().search([('login','=',participant.login)], limit=1)

            time_remaining = kw.get('time')
            data = {
                'time_remaining': time_remaining
            }
            paper_id.write(data)
            values.update({
                'paper': paper_id.id,
                'time_remaining': paper_id.time_remaining
            })
            data = {
                'time_remaining': paper_id.time_remaining
            }
            data = json.dumps(data)
            return data
        except Exception as e:
            values = {
                'error_message': e or False
            }
            return values

    @http.route(['/cbt/paper/currentState'], type='http', auth="user", website=True, methods=['GET', 'POST'])
    def cbt_portal_currentState(self, **kw):
            try:
                if not main.cbt_session_valid(request):
                    return json.dumps({
                        'session_ended': True,
                        'error': 'Your session ended because this account was '
                                 'logged in on another device.',
                    })
                values, success, participant = main.prepare_portal_values(request)
                paper_id = http.request.env['cbt.paper.export'].sudo().search([('login', '=', participant.login)], limit=1)
                data = {
                    'paper_state': paper_id.end_paper,
                    'current_q': paper_id.current_q,
                    'time_remaining':paper_id.time_remaining
                }

                data = json.dumps(data)
                return data
            except Exception as e:
                values = {
                    'error_message': e or False
                }
                return http.request.render('cbt_portal.cbt_finish', values)

    @http.route(['/cbt/paper/review'], type='http', auth="user", website=True, methods=['GET', 'POST'])
    def cbt_portal_paper_review(self, **kw):
        try:
            values, success, participant = main.prepare_portal_values(request)
            paper_id = http.request.env['cbt.paper.export'].sudo().search([('login', '=', participant.login)], limit=1)
            
            start_time = paper_id
            if not paper_id.paper_started:
                data = {
                    'paper_started': datetime.now()
                }
                start_time.sudo().write(data)
            elif paper_id.paper_started:
                data = {
                    'start_time': datetime.now(),
                    'paper_id': start_time.id
                }
                start_time.session_ids.sudo().write(data)

            values.update({
                'paper': paper_id,
                'paper_page': True,
            })
            return http.request.render('cbt_portal.cbt_paper_review', values)
        except Exception as e:
            values = {
                'error_message': e or False
            }
            return http.request.render('cbt_portal.cbt_paper_review', values)