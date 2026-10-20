from odoo import fields, models, api
from odoo.exceptions import UserError
import json
import requests


class PrepareResultWizard(models.TransientModel):

    _name = 'prepare.result.wizard'
    _description = 'Result Export'

    paper_id = fields.Many2one(
        'cbt.paper.generator', 'Generated Paper', required=True)

    def prepare_result(self):
        try:
            db = self.env['ir.config_parameter'].get_param('cbt.admission_db')
            url = self.env['ir.config_parameter'].get_param(
                'cbt.admission_url')
            login = self.env['ir.config_parameter'].get_param(
                'cbt.admission_login')
            password = self.env['ir.config_parameter'].get_param(
                'cbt.admission_password')

            if not db or not login or not password or not url:
                raise UserError('Please Fill All Fields In Configuration')
            if not self.paper_id:
                raise UserError('Please Select Test')

            # Remove previous demo data
            papers = self.env['cbt.paper.attempt.demo'].search([])
            papers.unlink()

            questions = self.env['cbt.question.attempt.demo'].search([])
            questions.unlink()

            paper_ids = self.env['cbt.paper.export'].search_read(
                [], ['server_id', 'test_date'])

            for paper_id in paper_ids:
                if paper_id['id'] and paper_id['server_id']:
                    data = {
                        'paper_id_portal': int(paper_id['id']),
                        'date': paper_id['test_date'],
                        'paper_server_id': int(paper_id['server_id'])
                    }
                    self.env['cbt.paper.attempt.demo'].create(data)

            paper_line_ids = self.env['cbt.paper.line.export'].search_read(
                [], ['server_id', 'answer_alphabet', 'paper_id'])
            for ques in paper_line_ids:
                if ques['paper_id'] and ques['server_id']:
                    data = {
                        'paper_id_portal': int(ques['paper_id'][0]),
                        'question_server_id': int(ques['server_id']),
                        'answer': ques['answer_alphabet']
                    }
                    self.env['cbt.question.attempt.demo'].create(data)

            for paper in self.env['cbt.paper.attempt.demo'].search([]):
                conduct = self.env['cbt.paper.conduct'].search(
                    [('paper_id', '=', paper.paper_server_id)], limit=1)
                if not conduct:
                    conduct = self.env['cbt.paper.conduct'].create({
                        'paper_id': paper.paper_server_id,
                        'date': paper.date,
                    })
                existing_questions = conduct.question_attempt_id.mapped('question_id').ids
                for question in self.env['cbt.question.attempt.demo'].search([('paper_id_portal', '=', paper.paper_id_portal)]):
                    if question.question_server_id in existing_questions:
                        continue
                    self.env['cbt.paper.attempt'].create({
                        'question_id': question.question_server_id,
                        'participant_answer': question.answer,
                        'attempt_id': conduct.id
                    })
            student_result = self.env['cbt.paper.conduct'].search([])
            for result in student_result:
                result.subject_wise_score()
            user = requests.post(url + '/web/session/authenticate',
                                 json={
                                     "jsonrpc": "2.0",
                                     "params": {
                                         "db": db,
                                         "login": login,
                                         "password": password,
                                     }
                                 }, headers={"Content-Type": "application/json"})

            result_export = url + '/result/import'

            subjects = self.env['cbt.paper.subject.score'].search([
                ('conduct.paper_id.main_paper_id.generator_id', '=', self.paper_id.id)])

            results_all = []
            for subject in subjects:
                result_stu = {
                    subject.conduct.paper_id.participant_id.login: {
                        subject.subject_id.name: {
                            'subject_score': subject.score,
                            'subject_total_score': subject.total_score,
                        },

                    }, 'cid': subject.conduct.paper_id.participant_id.cid,
                }
                results_all.append(result_stu)
            
            request_student_data = requests.post(result_export, json={"jsonrpc": "2.0", "params": {
                "result_all": json.dumps(results_all),
            }}, headers={
                "Content-Type": "application/json", "Cookie": f"session_id={user.cookies.get_dict().get('session_id')}",
                "X-Openerp": user.cookies.get_dict().get('session_id')
            })

            response = json.loads(request_student_data.content)['result']
            response_status = json.loads(response)
            if response_status['status'] == 'no':
                raise UserError(response_status.get('error', 'Result export failed'))
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Result',
                    'message': 'Data Exported Successfully!',
                    'type': 'success',
                    'sticky': False,
                },
            }
        except UserError:
            raise
        except Exception as e:
            raise UserError(f"{e}")
