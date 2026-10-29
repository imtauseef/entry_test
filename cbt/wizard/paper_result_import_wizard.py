# -*- coding: utf-8 -*-
import base64

from odoo import fields, models, _
from odoo.addons.cbt.models.allocation_xlsx import (
    decrypt_xlsx,
    excel_password_prompt_action,
    load_allocation_xlsx,
    offline_result_payload_hash,
    verify_excel_admin_password,
)
from odoo.exceptions import UserError


class CBTPaperResultImportWizard(models.TransientModel):
    _name = 'cbt.paper.result.import.wizard'
    _description = 'Import Offline Paper Results'

    xlsx_file = fields.Binary(string='Results Workbook', required=True)
    name = fields.Char(string='File Name')

    _SHEETS = {
        'Papers': (
            'source_export_id', 'source_student_id', 'source_paper_id',
            'source_template_paper_id', 'candidate_name', 'paper_name',
            'login', 'cid', 'test_date', 'test_started_at', 'test_ended_at',
        ),
        'Answers': (
            'source_student_id', 'source_paper_id', 'source_question_id',
            'question_order', 'answer_alphabet', 'source_option_id',
            'theory_answer', 'answer_recorded_at', 'mark_review',
            'feedback_type', 'feedback_text',
        ),
    }
    _V11_SHEETS = {
        'Papers': _SHEETS['Papers'],
        'Answers': (
            'source_student_id', 'source_paper_id', 'source_question_id',
            'question_order', 'answer_alphabet', 'source_option_id',
            'theory_answer', 'answer_recorded_at', 'mark_review',
        ),
    }
    _LEGACY_SHEETS = {
        'Papers': (
            'source_export_id', 'source_student_id', 'source_paper_id',
            'source_template_paper_id', 'login', 'cid', 'test_date',
            'test_started_at', 'test_ended_at',
        ),
        'Answers': _V11_SHEETS['Answers'],
    }

    def action_open_import_password_prompt(self):
        return excel_password_prompt_action(
            self, '_import_workbook', 'import',
            _('Import Offline Test Results'))

    def _import_workbook(
            self, odoo_password=None, workbook_password=None):
        self.ensure_one()
        verify_excel_admin_password(self.env, odoo_password)
        if not self.xlsx_file:
            raise UserError(_('Please select a results workbook.'))
        if self.name and not self.name.lower().endswith('.xlsx'):
            raise UserError(_('Please upload an .xlsx results workbook.'))
        try:
            content = base64.b64decode(self.xlsx_file, validate=True)
            content = decrypt_xlsx(content, workbook_password)
            workbook = load_allocation_xlsx(content)
        except UserError:
            raise
        except Exception as exc:
            raise UserError(_('The uploaded file is not a valid XLSX workbook.')) from exc

        required_sheets = {'Manifest', *self._SHEETS}
        missing_sheets = required_sheets.difference(workbook.sheetnames)
        unexpected_sheets = set(workbook.sheetnames).difference(required_sheets)
        if missing_sheets or unexpected_sheets:
            raise UserError(_(
                'The results workbook must contain exactly these worksheets: '
                'Manifest, Papers, and Answers.'
            ))
        manifest = self._read_manifest(workbook['Manifest'])
        schema_version = manifest.get('schema_version')
        if schema_version not in ('1.0', '1.1', '1.2'):
            raise UserError(_('Unsupported results workbook schema version.'))
        sheets_schema = (
            self._LEGACY_SHEETS if schema_version == '1.0'
            else self._V11_SHEETS if schema_version == '1.1'
            else self._SHEETS)
        source_system_id = manifest.get('source_system_id')
        batch_export_id = manifest.get('source_batch_export_id')
        source_generator_id = manifest.get('source_generator_id')
        if not source_system_id or not batch_export_id or not source_generator_id:
            raise UserError(_(
                'The Manifest must contain source_system_id, '
                'source_batch_export_id, and source_generator_id.'
            ))
        configured_source_id = self.env['ir.config_parameter'].sudo().get_param(
            'cbt.offline_source_system_id')
        if not configured_source_id or source_system_id != configured_source_id:
            raise UserError(_(
                'The workbook was not exported by this CBT source instance.'
            ))
        generator_id = self._source_record_id(
            source_generator_id, 'cbt.paper.generator', source_system_id,
            'Manifest', {'_row_number': 1})
        rows = {
            sheet: self._read_rows(workbook[sheet], columns)
            for sheet, columns in sheets_schema.items()
        }
        paper_rows = rows['Papers']
        answer_rows = rows['Answers']
        if not paper_rows:
            raise UserError(_('The workbook contains no attended candidates.'))
        if self._as_integer(
                manifest.get('paper_count'), 'Manifest', 'paper_count') != len(
                    paper_rows):
            raise UserError(_('The candidate count does not match the Manifest.'))
        if self._as_integer(
                manifest.get('answer_count'), 'Manifest', 'answer_count') != len(
                    answer_rows):
            raise UserError(_('The answer count does not match the Manifest.'))

        payload_hash = offline_result_payload_hash(
            [
                [row[column] for column in sheets_schema['Papers']]
                for row in paper_rows
            ],
            [
                [row[column] for column in sheets_schema['Answers']]
                for row in answer_rows
            ],
        )
        if manifest.get('results_sha256') != payload_hash:
            raise UserError(_('The results workbook failed its integrity check.'))
        imported_batch = self.env['cbt.paper.result.batch'].search([
            ('source_system_id', '=', source_system_id),
            ('source_batch_export_id', '=', batch_export_id),
        ], limit=1)
        if imported_batch:
            if imported_batch.result_payload_sha256 != payload_hash:
                raise UserError(_(
                    'This portal batch was already imported with different results.'
                ))
            return self._notification(_(
                'This results workbook has already been imported; no records were changed.'
            ))

        generator = self.env['cbt.paper.generator'].browse(generator_id).exists()
        if not generator:
            raise UserError(_('The source paper generator no longer exists.'))
        expected_generator_id = '%s:cbt.paper.generator:%s' % (
            source_system_id, generator.id)
        if source_generator_id != expected_generator_id:
            raise UserError(_('The Manifest paper generator identifier is invalid.'))

        papers_by_source_id = {}
        papers_by_student_id = {}
        for row in paper_rows:
            self._require_text_fields(row, (
                'source_export_id', 'source_student_id', 'source_paper_id',
                'source_template_paper_id', 'login', 'test_date',
                'test_started_at', 'test_ended_at',
            ))
            source_allocation_id = self._source_record_id(
                row['source_export_id'], 'cbt.student.paper',
                source_system_id, 'Papers', row)
            student_id = self._source_record_id(
                row['source_student_id'], 'cbt.participant',
                source_system_id, 'Papers', row)
            allocation = self.env['cbt.student.paper'].browse(
                source_allocation_id).exists()
            if not allocation:
                self._row_error('Papers', row, 'the source allocation does not exist.')
            if source_allocation_id in papers_by_source_id:
                self._row_error('Papers', row, 'source_export_id is duplicated.')
            if student_id in papers_by_student_id:
                self._row_error('Papers', row, 'a candidate has multiple papers in this batch.')
            participant = allocation.participant_id
            if (
                    participant.id != student_id
                    or row['source_student_id'] != '%s:cbt.participant:%s' % (
                        source_system_id, participant.id)):
                self._row_error(
                    'Papers', row,
                    'the source student does not match the allocation.')
            template_id = self._source_record_id(
                row['source_template_paper_id'], 'cbt.paper',
                source_system_id, 'Papers', row)
            if (
                    allocation.main_paper_id.id != template_id
                    or allocation.main_paper_id.generator_id.id != generator.id):
                self._row_error(
                    'Papers', row,
                    'the allocation does not belong to the Manifest generator.')
            if row['source_paper_id'] != row['source_export_id']:
                self._row_error(
                    'Papers', row,
                    'source_paper_id must match source_export_id.')
            try:
                card_id = int(row['cid'])
            except (TypeError, ValueError):
                self._row_error('Papers', row, 'cid must be an integer.')
            if (
                    row['login'] != participant.login
                    or card_id != (participant.cid or 0)):
                self._row_error(
                    'Papers', row,
                    'the candidate login or card ID does not match the source allocation.')
            expected_date = fields.Date.to_string(
                allocation.slot_id.date) if allocation.slot_id.date else ''
            if row['test_date'] != expected_date:
                self._row_error(
                    'Papers', row,
                    'test_date does not match the source allocation.')
            started_at = self._parse_datetime(
                row['test_started_at'], 'Papers', row, required=True)
            ended_at = self._parse_datetime(
                row['test_ended_at'], 'Papers', row, required=True)
            if started_at > ended_at:
                self._row_error(
                    'Papers', row,
                    'test_ended_at must be after test_started_at.')
            row['_allocation'] = allocation
            row['_participant'] = participant
            row['_started_at'] = started_at
            row['_ended_at'] = ended_at
            papers_by_source_id[row['source_export_id']] = row
            papers_by_student_id[student_id] = row

        answers_by_paper = {source_id: {} for source_id in papers_by_source_id}
        question_orders_by_paper = {
            source_id: set() for source_id in papers_by_source_id
        }
        for row in answer_rows:
            self._require_text_fields(row, (
                'source_student_id', 'source_paper_id',
                'source_question_id', 'answer_alphabet',
                'source_option_id', 'theory_answer',
                'answer_recorded_at',
            ))
            paper_row = papers_by_source_id.get(row['source_paper_id'])
            if (
                    not paper_row
                    or row['source_student_id'] != paper_row['source_student_id']):
                self._row_error(
                    'Answers', row,
                    'the answer references an unknown or mismatched candidate paper.')
            allocation = paper_row['_allocation']
            question_id = self._source_record_id(
                row['source_question_id'], 'cbt.mcqs', source_system_id,
                'Answers', row)
            question = self.env['cbt.mcqs'].browse(question_id).exists()
            if not question or question not in allocation.questions:
                self._row_error(
                    'Answers', row,
                    'the source question is not part of the allocated paper.')
            try:
                question_order = int(row['question_order'])
            except (TypeError, ValueError):
                self._row_error(
                    'Answers', row, 'question_order must be an integer.')
            if question_order <= 0:
                self._row_error(
                    'Answers', row, 'question_order must be greater than zero.')
            if question_order in question_orders_by_paper[
                    row['source_paper_id']]:
                self._row_error(
                    'Answers', row, 'question_order is duplicated for this paper.')
            if question.id in answers_by_paper[row['source_paper_id']]:
                self._row_error(
                    'Answers', row, 'a question has duplicate answer rows.')
            question_orders_by_paper[
                row['source_paper_id']].add(question_order)
            answer_alphabet = row['answer_alphabet']
            source_option_id = row['source_option_id']
            theory_answer = row['theory_answer']
            if question.is_theory:
                if answer_alphabet or source_option_id:
                    self._row_error(
                        'Answers', row,
                        'theory answers cannot contain a multiple-choice option.')
            elif theory_answer:
                self._row_error(
                    'Answers', row,
                    'multiple-choice answers cannot contain theory text.')
            original_answer = ''
            if answer_alphabet or source_option_id:
                if question.is_theory or answer_alphabet not in (
                        'A', 'B', 'C', 'D', 'E', 'F') or not source_option_id:
                    self._row_error(
                        'Answers', row,
                        'the selected answer option is invalid.')
                option_prefix = '%s:option:' % row['source_question_id']
                if not source_option_id.startswith(option_prefix):
                    self._row_error(
                        'Answers', row,
                        'source_option_id does not match the source question.')
                try:
                    source_option_position = int(
                        source_option_id[len(option_prefix):])
                except ValueError:
                    source_option_position = 0
                option_values = [
                    question.ans1, question.ans2, question.ans3,
                    question.ans4, question.ans5, question.ans6,
                ]
                visible_positions = [
                    position for position, value in enumerate(option_values, 1)
                    if value
                ]
                if source_option_position not in visible_positions:
                    self._row_error(
                        'Answers', row,
                        'source_option_id does not identify an exported option.')
                visible_answer = chr(
                    64 + visible_positions.index(source_option_position) + 1)
                if answer_alphabet != visible_answer:
                    self._row_error(
                        'Answers', row,
                        'answer_alphabet does not match source_option_id.')
                original_answer = chr(64 + source_option_position)
            answer_time = self._parse_datetime(
                row['answer_recorded_at'], 'Answers', row)
            mark_review = self._as_boolean(
                row['mark_review'], 'Answers', row)
            feedback_type = (row.get('feedback_type') or '').strip()
            feedback_text = (row.get('feedback_text') or '').strip()
            if len(feedback_type) > 32767 or len(feedback_text) > 32767:
                self._row_error(
                    'Answers', row,
                    "feedback fields must not exceed Excel's maximum cell length.")
            row['_question'] = question
            row['_answer'] = original_answer
            row['_answer_time'] = answer_time
            row['_mark_review'] = mark_review
            row['_feedback_type'] = feedback_type
            row['_feedback_text'] = feedback_text
            answers_by_paper[row['source_paper_id']][question.id] = row

        for paper_row in paper_rows:
            allocation = paper_row['_allocation']
            expected_question_ids = set(allocation.questions.ids)
            actual_question_ids = set(answers_by_paper[
                paper_row['source_export_id']])
            if actual_question_ids != expected_question_ids:
                self._row_error(
                    'Papers', paper_row,
                    'the result workbook must contain one answer row for every allocated question.')
            question_orders = question_orders_by_paper[
                paper_row['source_export_id']]
            if question_orders != set(range(1, len(expected_question_ids) + 1)):
                self._row_error(
                    'Papers', paper_row,
                    'answer question_order values must be contiguous from 1.')
            existing_conduct = self.env['cbt.paper.conduct'].search([
                ('paper_id', '=', allocation.id),
            ], limit=1)
            if existing_conduct:
                self._row_error(
                    'Papers', paper_row,
                    'a conduct result already exists for this allocation.')

        with self.env.cr.savepoint():
            result_batch = self.env['cbt.paper.result.batch'].create({
                'name': _('Results %s') % batch_export_id,
                'source_system_id': source_system_id,
                'source_batch_export_id': batch_export_id,
                'source_generator_id': source_generator_id,
                'paper_generate_id': generator.id,
                'result_payload_sha256': payload_hash,
            })
            for paper_row in paper_rows:
                allocation = paper_row['_allocation']
                conduct = self.env['cbt.paper.conduct'].create({
                    'paper_id': allocation.id,
                    'date': paper_row['_started_at'].date(),
                    'result_batch_id': result_batch.id,
                    'portal_started_at': paper_row['_started_at'],
                    'portal_ended_at': paper_row['_ended_at'],
                })
                question_attempts = []
                question_feedback = []
                for answer_row in answers_by_paper[
                        paper_row['source_export_id']].values():
                    question_attempts.append({
                        'question_id': answer_row['_question'].id,
                        'participant_answer': answer_row['_answer'],
                        'theory_answer': answer_row['theory_answer'] or False,
                        'answer_recorded_at': answer_row['_answer_time'],
                        'mark_review': answer_row['_mark_review'],
                        'attempt_id': conduct.id,
                    })
                    if (
                            answer_row['_feedback_type']
                            or answer_row['_feedback_text']):
                        question_feedback.append({
                            'question_id': answer_row['_question'].id,
                            'candidate_id': paper_row['_participant'].id,
                            'candidate_source_id':
                                paper_row['source_student_id'],
                            'candidate_name':
                                paper_row.get('candidate_name')
                                or paper_row['_participant'].name
                                or paper_row['login'],
                            'feedback_type':
                                answer_row['_feedback_type'] or False,
                            'feedback_text':
                                answer_row['_feedback_text'] or False,
                            'conduct_id': conduct.id,
                            'result_batch_id': result_batch.id,
                        })
                self.env['cbt.paper.attempt'].create(question_attempts)
                if question_feedback:
                    self.env['cbt.mcqs.feedback'].create(question_feedback)
                conduct.subject_wise_score()

        return self._notification(_(
            'Imported results for %s candidate(s).'
        ) % len(paper_rows))

    def _read_manifest(self, worksheet):
        manifest = {}
        for row_number, row in enumerate(
                worksheet.iter_rows(values_only=True), start=1):
            if not row or row[0] in (None, ''):
                continue
            key = self._cell_text(row[0]).strip()
            value = row[1] if len(row) > 1 else None
            if not key or value in (None, ''):
                raise UserError(_(
                    'Manifest row %s must contain a key and value.'
                ) % row_number)
            if key in manifest:
                raise UserError(_('Manifest key %s is duplicated.') % key)
            manifest[key] = str(self._cell_text(value)).strip()
        return manifest

    def _read_rows(self, worksheet, required_columns):
        iterator = worksheet.iter_rows(values_only=True)
        header = next(iterator, None)
        if not header:
            raise UserError(_('Worksheet %s is empty.') % worksheet.title)
        columns = [self._cell_text(value).strip() for value in header]
        if len(columns) != len(set(columns)):
            raise UserError(_('Worksheet %s contains duplicate columns.') % worksheet.title)
        if set(columns) != set(required_columns):
            raise UserError(_(
                'Worksheet %s has an invalid schema.'
            ) % worksheet.title)
        rows = []
        for row_number, values in enumerate(iterator, start=2):
            if not values or not any(value not in (None, '') for value in values):
                continue
            row = {
                column: self._cell_text(
                    values[index] if index < len(values) else None)
                for index, column in enumerate(columns)
            }
            row['_row_number'] = row_number
            rows.append(row)
        return rows

    def _source_record_id(
            self, source_id, model_name, source_system_id, sheet, row):
        prefix = '%s:%s:' % (source_system_id, model_name)
        if not source_id.startswith(prefix):
            self._row_error(
                sheet, row,
                'source identifier is not scoped to the expected source model.')
        try:
            record_id = int(source_id[len(prefix):])
            if record_id <= 0:
                raise ValueError
            return record_id
        except (TypeError, ValueError):
            self._row_error(
                sheet, row,
                'source identifier must end with a positive record ID.')

    def _require_text_fields(self, row, names):
        for name in names:
            if not isinstance(row.get(name), str):
                self._row_error(
                    row.get('_sheet', 'Papers'), row,
                    '%s must contain text.' % name)

    def _as_integer(self, value, sheet, field_name):
        try:
            number = int(value)
            if str(value).strip() not in (str(number), '%s.0' % number):
                raise ValueError
            return number
        except (TypeError, ValueError):
            raise UserError(_('%s must be an integer.') % field_name)

    def _as_boolean(self, value, sheet, row):
        if value is True or str(value).strip().lower() in ('true', '1'):
            return True
        if value is False or str(value).strip().lower() in ('false', '0', ''):
            return False
        self._row_error(sheet, row, 'mark_review must be true or false.')

    def _parse_datetime(self, value, sheet, row, required=False):
        if not value:
            if required:
                self._row_error(sheet, row, 'timestamp is required.')
            return False
        try:
            return fields.Datetime.to_datetime(value)
        except (TypeError, ValueError):
            self._row_error(sheet, row, 'timestamp must be an ISO datetime.')

    def _cell_text(self, value):
        if value is None:
            return ''
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            if isinstance(value, float) and value.is_integer():
                return str(int(value))
            return value
        if hasattr(value, 'isoformat'):
            return value.isoformat(sep=' ') if hasattr(value, 'hour') else value.isoformat()
        return str(value)

    def _row_error(self, sheet, row, message):
        raise UserError(_('%(sheet)s row %(row)s: %(message)s') % {
            'sheet': sheet,
            'row': row.get('_row_number', '?'),
            'message': message,
        })

    def _notification(self, message):
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Offline Results'),
                'message': message,
                'type': 'success',
                'sticky': False,
            },
        }
