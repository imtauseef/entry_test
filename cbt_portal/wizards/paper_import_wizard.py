# -*- coding: utf-8 -*-
import base64
import hashlib
import json
import math
import re
from collections import defaultdict

from odoo import fields, models, _
from odoo.addons.cbt.models.allocation_xlsx import (
    decrypt_xlsx,
    excel_password_prompt_action,
    load_allocation_xlsx,
    normalize_inline_image_sources,
    offline_image_key,
    offline_image_placeholder,
    transform_html_image_sources,
    verify_excel_admin_password,
)
from odoo.exceptions import UserError
from odoo.tools import html_sanitize


class CBTPaperImportWizard(models.TransientModel):
    _name = 'cbt.paper.import.wizard'
    _description = 'Import Paper Allocation Workbook'

    xlsx_file = fields.Binary(string='XLSX Workbook', required=True)
    name = fields.Char(string='File Name')

    _SHEETS = {
        'Participants': (
            'source_student_id', 'login', 'name', 'password',
        ),
        'Papers': (
            'source_export_id', 'source_generator_id', 'source_student_id',
            'login', 'name', 'cid', 'source_paper_id',
            'source_template_paper_id', 'paper_name', 'program',
            'test_center', 'test_date', 'test_time', 'test_duration',
            'shuffle_section', 'source_schedule_id', 'payload_sha256',
        ),
        'Questions': (
            'source_student_id', 'source_paper_id', 'source_question_id',
            'subject_name', 'name', 'question_order', 'is_theory',
            'correct_answer',
        ),
        'Answer Options': (
            'source_student_id', 'source_paper_id', 'source_question_id',
            'source_option_id', 'sequence', 'option_label', 'name',
        ),
        'Images': (
            'image_key', 'mimetype', 'chunk_index', 'chunk_count',
            'data_base64',
        ),
    }

    def action_open_import_password_prompt(self):
        return excel_password_prompt_action(
            self, '_import_workbook', 'import',
            _('Import Paper Allocation Workbook'))

    def _import_workbook(
            self, odoo_password=None, workbook_password=None):
        self.ensure_one()
        verify_excel_admin_password(self.env, odoo_password)
        if not self.xlsx_file:
            raise UserError(_('Please select a workbook to import.'))
        if self.name and not self.name.lower().endswith('.xlsx'):
            raise UserError(_('Please upload an .xlsx workbook.'))

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
        if missing_sheets:
            raise UserError(_(
                'The workbook is missing required sheets: %s'
            ) % ', '.join(sorted(missing_sheets)))
        unexpected_sheets = set(workbook.sheetnames).difference(required_sheets)
        if unexpected_sheets:
            raise UserError(_(
                'The workbook contains unsupported sheets: %s'
            ) % ', '.join(sorted(unexpected_sheets)))

        manifest = self._read_manifest(workbook['Manifest'])
        if manifest.get('schema_version') != '4.0':
            raise UserError(_('Unsupported allocation workbook schema version.'))
        source_system_id = manifest.get('source_system_id')
        export_id = manifest.get('export_id')
        source_generator_id = manifest.get('source_generator_id')
        source_generator_name = manifest.get('source_generator_name', '')
        if not source_system_id or not export_id or not source_generator_id:
            raise UserError(_(
                'The workbook manifest must contain source_system_id, '
                'source_generator_id, and export_id.'
            ))
        if not source_generator_id.startswith(
                '%s:cbt.paper.generator:' % source_system_id):
            raise UserError(_('The Manifest source_generator_id is invalid.'))
        self._source_record_id(
            source_generator_id, 'Manifest', {'_row_number': 1})

        rows = {
            sheet: self._read_rows(workbook[sheet], expected_columns)
            for sheet, expected_columns in self._SHEETS.items()
        }
        image_payloads = self._read_image_payloads(
            rows['Images'], manifest.get('image_count'))
        participants = rows['Participants']
        allocations = rows['Papers']
        if not participants:
            raise UserError(_('No participant credentials were found in the workbook.'))
        if not allocations:
            raise UserError(_('No paper export rows were found in the workbook.'))
        if manifest.get('paper_export_model') != 'cbt.paper.export':
            raise UserError(_('The Manifest paper_export_model is invalid.'))
        if self._as_integer(
                manifest.get('paper_export_count'),
                'Manifest paper_export_count') != len(allocations):
            raise UserError(_('The paper export count does not match the Manifest.'))
        if self._as_integer(
                manifest.get('participant_count'),
                'Manifest participant_count') != len(participants):
            raise UserError(_('The participant count does not match the Manifest.'))

        participants_by_source_id = {}
        participants_by_login = {}
        source_prefix = '%s:' % source_system_id
        for row in participants:
            self._require_text_fields(row, (
                'source_student_id', 'login', 'name', 'password',
            ))
            if not row['source_student_id'].startswith(
                    '%scbt.participant:' % source_prefix):
                self._row_error(
                    'Participants', row,
                    'source_student_id is not a valid source-scoped identifier.')
            self._source_record_id(
                row['source_student_id'], 'Participants', row)
            if not row['login'] or row['login'] != row['login'].strip():
                self._row_error(
                    'Participants', row,
                    'login is required and must not have surrounding whitespace.')
            if not row['name']:
                self._row_error('Participants', row, 'name is required.')
            if not row['password'].strip():
                self._row_error('Participants', row, 'password is required.')
            if row['source_student_id'] in participants_by_source_id:
                self._row_error(
                    'Participants', row, 'source_student_id is duplicated.')
            if row['login'] in participants_by_login:
                self._row_error('Participants', row, 'login is duplicated.')
            participants_by_source_id[row['source_student_id']] = row
            participants_by_login[row['login']] = row

        allocations_by_id = {}
        allocations_by_key = {}
        allocations_by_student = {}
        questions_by_allocation = defaultdict(list)
        questions_by_key = {}
        options_by_question = defaultdict(list)
        for row in allocations:
            self._require_text_fields(row, (
                'source_export_id', 'source_generator_id',
                'source_student_id', 'login', 'name',
                'source_paper_id', 'source_template_paper_id', 'paper_name',
                'program', 'test_center', 'test_date', 'source_schedule_id',
                'payload_sha256',
            ))
            key = row['source_export_id']
            if not key or key in allocations_by_id:
                self._row_error('Papers', row, 'source_export_id is empty or duplicated.')
            if not row['source_student_id'] or not row['source_paper_id']:
                self._row_error(
                    'Papers', row,
                    'source_student_id and source_paper_id are required.')
            if key != row['source_paper_id']:
                self._row_error(
                    'Papers', row,
                    'source_export_id must identify its cbt.student.paper allocation.')
            if not row['login']:
                self._row_error('Papers', row, 'login is required for portal mapping.')
            participant_data = participants_by_source_id.get(
                row['source_student_id'])
            if not participant_data:
                self._row_error(
                    'Papers', row,
                    'source_student_id is missing from the Participants sheet.')
            if (
                    participant_data['login'] != row['login']
                    or participant_data['name'] != row['name']):
                self._row_error(
                    'Papers', row,
                    'login and name must match the Participants sheet.')
            if not row['payload_sha256']:
                self._row_error('Papers', row, 'payload_sha256 is required.')
            for column, model_name in (
                    ('source_export_id', 'cbt.student.paper'),
                    ('source_generator_id', 'cbt.paper.generator'),
                    ('source_student_id', 'cbt.participant'),
                    ('source_paper_id', 'cbt.student.paper'),
                    ('source_template_paper_id', 'cbt.paper')):
                if not row[column].startswith(
                        '%s%s:' % (source_prefix, model_name)):
                    self._row_error(
                        'Papers', row,
                        '%s is not a valid source-scoped identifier.' % column)
                self._source_record_id(row[column], 'Papers', row)
            row['_server_id'] = self._source_record_id(
                row['source_paper_id'], 'Papers', row)
            if row['source_generator_id'] != source_generator_id:
                self._row_error(
                    'Papers', row,
                    'source_generator_id does not match the Manifest.')
            if (row['source_schedule_id']
                    and not row['source_schedule_id'].startswith(
                        '%scbt.slot:' % source_prefix)):
                self._row_error(
                    'Papers', row,
                    'source_schedule_id is not a valid source-scoped identifier.')
            if row['source_schedule_id']:
                self._source_record_id(row['source_schedule_id'], 'Papers', row)
            row['_date'] = self._parse_date(row['test_date'], row)
            row['_time'] = self._as_float(row['test_time'], row, 'test_time')
            row['_duration'] = self._as_integer(row['test_duration'], row)
            row['_cid'] = self._as_integer(row['cid'], row)
            row['_shuffle'] = self._as_boolean(row['shuffle_section'], row)
            if not row['_date']:
                self._row_error('Papers', row, 'test_date is required.')
            if row['_duration'] <= 0:
                self._row_error('Papers', row, 'test_duration must be greater than zero.')
            if not 0 <= row['_time'] < 24:
                self._row_error('Papers', row, 'test_time must be between 0 and 24 hours.')
            allocations_by_id[key] = row
            allocation_key = (row['source_student_id'], row['source_paper_id'])
            if allocation_key in allocations_by_key:
                self._row_error(
                    'Papers', row,
                    'source_student_id and source_paper_id are duplicated.')
            if row['source_student_id'] in allocations_by_student:
                self._row_error(
                    'Papers', row,
                    'a candidate can have only one paper in each test batch.')
            allocations_by_key[allocation_key] = row
            allocations_by_student[row['source_student_id']] = row

        allocation_student_ids = {
            row['source_student_id'] for row in allocations
        }
        unused_participants = (
            set(participants_by_source_id) - allocation_student_ids)
        if unused_participants:
            row = participants_by_source_id[sorted(unused_participants)[0]]
            self._row_error(
                'Participants', row,
                'participant is not referenced by any Papers row.')

        for row in rows['Questions']:
            self._require_text_fields(row, (
                'source_student_id', 'source_paper_id',
                'source_question_id', 'subject_name', 'name',
                'correct_answer',
            ))
            key = (row['source_student_id'], row['source_paper_id'])
            if key not in allocations_by_key:
                self._row_error('Questions', row, 'question references an unknown allocation.')
            if not row['source_question_id']:
                self._row_error('Questions', row, 'source_question_id is required.')
            if not row['source_question_id'].startswith(
                    '%scbt.mcqs:' % source_prefix):
                self._row_error(
                    'Questions', row,
                    'source_question_id is not a valid source-scoped identifier.')
            row['_server_id'] = self._source_record_id(
                row['source_question_id'], 'Questions', row)
            row['_order'] = self._as_integer(row['question_order'], row, 'question_order')
            row['_theory'] = self._as_boolean(row['is_theory'], row)
            answer_key = row['correct_answer']
            if answer_key and answer_key not in ('A', 'B', 'C', 'D', 'E', 'F'):
                self._row_error('Questions', row, 'correct_answer must be empty or A-F.')
            if row['_theory'] and answer_key:
                self._row_error('Questions', row, 'Theory questions cannot have a multiple-choice answer key.')
            self._validate_image_markers(
                row['name'], image_payloads, 'Questions', row)
            allocation_key = (row['source_student_id'], row['source_paper_id'])
            question_key = (allocation_key, row['source_question_id'])
            if question_key in questions_by_key:
                self._row_error('Questions', row, 'source_question_id is duplicated in this allocation.')
            questions_by_key[question_key] = row
            questions_by_allocation[allocation_key].append(row)

        for row in rows['Answer Options']:
            self._require_text_fields(row, (
                'source_student_id', 'source_paper_id',
                'source_question_id', 'source_option_id',
                'option_label', 'name',
            ))
            allocation_key = (row['source_student_id'], row['source_paper_id'])
            question_key = (allocation_key, row['source_question_id'])
            if question_key not in questions_by_key:
                self._row_error('Answer Options', row, 'option references an unknown question.')
            if not row['source_option_id']:
                self._row_error('Answer Options', row, 'source_option_id is required.')
            self._validate_image_markers(
                row['name'], image_payloads, 'Answer Options', row)
            if not row['source_option_id'].startswith(
                    '%scbt.mcqs:' % source_prefix):
                self._row_error(
                    'Answer Options', row,
                    'source_option_id is not a valid source-scoped identifier.')
            option_prefix = '%s:option:' % row['source_question_id']
            if not row['source_option_id'].startswith(option_prefix):
                self._row_error(
                    'Answer Options', row,
                    'source_option_id does not match its source question.')
            try:
                source_option_position = int(
                    row['source_option_id'][len(option_prefix):])
            except ValueError:
                source_option_position = 0
            if source_option_position not in range(1, 7):
                self._row_error(
                    'Answer Options', row,
                    'source_option_id must identify an option position from 1 to 6.')
            row['_order'] = self._as_integer(row['sequence'], row, 'sequence')
            if any(
                    existing['source_option_id'] == row['source_option_id']
                    for existing in options_by_question[question_key]):
                self._row_error('Answer Options', row, 'source_option_id is duplicated for this question.')
            options_by_question[question_key].append(row)

        for allocation_key, allocation in allocations_by_key.items():
            allocation_questions = questions_by_allocation[allocation_key]
            if not allocation_questions:
                self._row_error(
                    'Papers', allocation,
                    'each allocation must contain at least one question.')
            allocation_questions.sort(key=lambda question: question['_order'])
            if [question['_order'] for question in allocation_questions] != list(
                    range(1, len(allocation_questions) + 1)):
                raise UserError(_(
                    'Question order values must be unique and contiguous within each allocation.'
                ))
            for question in allocation_questions:
                question_key = (
                    allocation_key, question['source_question_id'])
                question_options = options_by_question[question_key]
                question_options.sort(key=lambda option: option['_order'])
                option_orders = [option['_order'] for option in question_options]
                if question['_theory']:
                    if question_options:
                        self._row_error(
                            'Questions', question,
                            'theory questions cannot include multiple-choice options.')
                    continue
                if not question_options:
                    self._row_error(
                        'Questions', question,
                        'multiple-choice questions must include at least one option.')
                if option_orders != list(range(1, len(question_options) + 1)):
                    self._row_error(
                        'Answer Options', question_options[0],
                        'option sequence values must start at 1 and be contiguous.')
                if any(
                        option['option_label'] != chr(64 + option['_order'])
                        for option in question_options):
                    self._row_error(
                        'Answer Options', question_options[0],
                        'option_label does not match the option sequence.')
                if question['correct_answer'] and (
                        ord(question['correct_answer']) - 64 > len(question_options)):
                    self._row_error(
                        'Questions', question,
                        'correct_answer does not refer to an exported option.')

        self._validate_hashes(allocations, questions_by_allocation, options_by_question)

        created = 0
        sections_created = 0
        questions_created = 0
        options_created = 0
        skipped = 0
        created_users = 0
        repaired = 0
        with self.env.cr.savepoint():
            batch_hash = hashlib.sha256(content).hexdigest()
            Batch = self.env['cbt.paper.export.batch'].sudo()
            batch = Batch.search([
                ('source_system_id', '=', source_system_id),
                ('source_export_id', '=', export_id),
            ], limit=1)
            if batch:
                if batch.source_payload_hash != batch_hash:
                    raise UserError(_(
                        'This workbook identifier has already been imported '
                        'with different content.'
                    ))
                if batch.state != 'imported':
                    raise UserError(_(
                        'This batch has already been started or completed and '
                        'cannot be re-imported.'
                    ))
                if source_generator_name and batch.name != source_generator_name:
                    batch.write({'name': source_generator_name})
            else:
                batch = Batch.create({
                    'name': source_generator_name or (
                        _('Generator %s') % source_generator_id),
                    'source_system_id': source_system_id,
                    'source_export_id': export_id,
                    'source_generator_id': source_generator_id,
                    'source_payload_hash': batch_hash,
                })

            users_by_student_id, created_users = self._resolve_portal_users(
                participants)
            portal_users = {
                allocation['source_export_id']: users_by_student_id[
                    allocation['source_student_id']]
                for allocation in allocations
            }
            existing, image_repairs, center_repairs = (
                self._validate_existing_allocations(
                    allocations, questions_by_allocation, options_by_question,
                    portal_users, image_payloads))
            for allocation in allocations:
                if allocation['source_export_id'] in existing:
                    export_id = allocation['source_export_id']
                    paper = existing[export_id]
                    if paper.batch_id and paper.batch_id != batch:
                        self._row_error(
                            'Papers', allocation,
                            'this allocation is already assigned to another test batch.')
                    if not paper.batch_id:
                        if not self._paper_is_unstarted(paper):
                            self._row_error(
                                'Papers', allocation,
                                'an existing started allocation cannot be moved into a test batch.')
                    if (
                            paper.source_template_paper_id
                            and paper.source_template_paper_id
                            != allocation['source_template_paper_id']):
                        self._row_error(
                            'Papers', allocation,
                            'the existing allocation has a conflicting template paper identifier.')
                    paper.write({
                        'batch_id': batch.id,
                        'source_template_paper_id': allocation[
                            'source_template_paper_id'],
                    })
                    if export_id in image_repairs:
                        allocation_key = (
                            allocation['source_student_id'],
                            allocation['source_paper_id'])
                        for question in questions_by_allocation[allocation_key]:
                            line = paper.line_ids.filtered(
                                lambda item: item.source_question_id
                                == question['source_question_id'])
                            line.write({
                                'name': self._restore_image_markers(
                                    question['name'], image_payloads),
                            })
                            question_key = (
                                allocation_key, question['source_question_id'])
                            options_by_source_id = {
                                option['source_option_id']: option
                                for option in options_by_question.get(
                                    question_key, [])
                            }
                            for option in line.option_ids:
                                source_option_id = option.source_option_id
                                if source_option_id in options_by_source_id:
                                    option.write({
                                        'name': self._restore_image_markers(
                                            options_by_source_id[
                                                source_option_id]['name'],
                                            image_payloads),
                                    })
                    if export_id in center_repairs:
                        paper.write({
                            'test_center': allocation['test_center'],
                        })
                    if export_id in image_repairs or export_id in center_repairs:
                        paper.write({
                            'source_payload_hash': allocation['payload_sha256'],
                        })
                        repaired += 1
                    else:
                        skipped += 1
                    continue
                portal_user = portal_users[allocation['source_export_id']]
                paper = self.env['cbt.paper.export'].create({
                    'batch_id': batch.id,
                    'source_export_id': allocation['source_export_id'],
                    'source_student_id': allocation['source_student_id'],
                    'source_paper_id': allocation['source_paper_id'],
                    'source_template_paper_id': allocation[
                        'source_template_paper_id'],
                    'source_payload_hash': allocation['payload_sha256'],
                    'participant_id': False,
                    'server_id': allocation['_server_id'],
                    'user_id': portal_user.id,
                    'login': portal_user.login,
                    'name': allocation['name'] or portal_user.name,
                    'paper_name': allocation['paper_name'],
                    'program': allocation['program'],
                    'test_center': allocation['test_center'],
                    'test_date': allocation['_date'],
                    'test_time': allocation['_time'],
                    'test_duration': allocation['_duration'],
                    'shuffle_section': allocation['_shuffle'],
                    'cid': allocation['_cid'],
                })

                subject_by_name = {}
                for question in questions_by_allocation[
                        (allocation['source_student_id'], allocation['source_paper_id'])]:
                    subject_name = question['subject_name'] or _('General')
                    if subject_name not in subject_by_name:
                        section = self.env['cbt.subject.export'].create({
                            'paper_id': paper.id,
                            'sequence_no': len(subject_by_name) + 1,
                            'name': subject_name,
                        })
                        subject_by_name[subject_name] = section
                        sections_created += 1

                    line = self.env['cbt.paper.line.export'].create({
                        'paper_id': paper.id,
                        'subject_id': subject_by_name[subject_name].id,
                        'name': self._restore_image_markers(
                            question['name'], image_payloads),
                        'source_question_id': question['source_question_id'],
                        'source_paper_id': allocation['source_paper_id'],
                        'source_student_id': allocation['source_student_id'],
                        'server_id': question['_server_id'],
                        'sequence': question['_order'],
                        'is_theory': question['_theory'],
                        'correct_answer': question['correct_answer'],
                    })
                    questions_created += 1
                    question_key = (
                        (allocation['source_student_id'], allocation['source_paper_id']),
                        question['source_question_id'],
                    )
                    for option in sorted(
                            options_by_question.get(question_key, []),
                            key=lambda item: item['_order']):
                        self.env['cbt.paper.line.option.export'].create({
                            'question_id': line.id,
                            'name': self._restore_image_markers(
                                option['name'], image_payloads),
                            'source_option_id': option['source_option_id'],
                            'source_question_id': question['source_question_id'],
                            'source_paper_id': allocation['source_paper_id'],
                            'source_student_id': allocation['source_student_id'],
                            'sequence': option['_order'],
                        })
                        options_created += 1
                created += 1

        summary = _(
            'Created %(papers)s paper allocation(s), %(sections)s section(s), '
            '%(questions)s question(s), and %(options)s answer option(s). '
            'Added them to test batch "%(batch)s". '
            'Provisioned %(users)s new portal user(s). Repaired %(repaired)s '
            'unstarted allocation(s). '
            'Skipped %(skipped)s identical allocation(s).'
        ) % {
            'papers': created,
            'batch': batch.name,
            'sections': sections_created,
            'questions': questions_created,
            'options': options_created,
            'users': created_users,
            'repaired': repaired,
            'skipped': skipped,
        }
        allocation_warning = manifest.get('allocation_warning')
        if allocation_warning:
            summary = '%s\n%s' % (
                summary,
                _('Allocation warning from the source server: %s') % allocation_warning)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Paper Allocation Import'),
                'message': summary,
                'type': 'warning' if allocation_warning else 'success',
                'sticky': False,
            },
        }

    def _read_manifest(self, worksheet):
        manifest = {}
        for row_number, row in enumerate(
                worksheet.iter_rows(values_only=True), start=1):
            if not row or row[0] in (None, ''):
                continue
            key = str(row[0]).strip()
            value = row[1] if len(row) > 1 else None
            if value in (None, '') and key != 'allocation_warning':
                raise UserError(_(
                    'Manifest row %s must contain a key and value.'
                ) % row_number)
            if key in manifest:
                raise UserError(_('Manifest key %s is duplicated.') % key)
            manifest[key] = str(value).strip() if value not in (None, '') else ''
        return manifest

    def _read_rows(self, worksheet, required_columns):
        iterator = worksheet.iter_rows(values_only=True)
        header = next(iterator, None)
        if not header:
            raise UserError(_('Worksheet %s is empty.') % worksheet.title)
        columns = [str(value or '').strip() for value in header]
        if len(columns) != len(set(columns)):
            raise UserError(_('Worksheet %s contains duplicate column names.') % worksheet.title)
        missing = set(required_columns).difference(columns)
        unexpected = set(columns).difference(required_columns)
        if missing or unexpected:
            raise UserError(_(
                'Worksheet %(sheet)s has an invalid schema. Missing: %(missing)s. '
                'Unexpected: %(unexpected)s.'
            ) % {
                'sheet': worksheet.title,
                'missing': ', '.join(sorted(missing)) or _('none'),
                'unexpected': ', '.join(sorted(unexpected)) or _('none'),
            })
        result = []
        for row_number, values in enumerate(iterator, start=2):
            if not values or not any(value not in (None, '') for value in values):
                continue
            record = {
                key: self._cell_text(values[index]) if index < len(values) else ''
                for index, key in enumerate(columns)
            }
            record['_row_number'] = row_number
            record['_sheet'] = worksheet.title
            result.append(record)
        return result

    def _read_image_payloads(self, rows, expected_count):
        image_chunks = {}
        for row in rows:
            self._require_text_fields(
                row, ('image_key', 'mimetype', 'data_base64'))
            image_key = row['image_key']
            mimetype = row['mimetype'].lower()
            if (
                    len(image_key) != 64
                    or any(char not in '0123456789abcdef' for char in image_key)):
                self._row_error('Images', row, 'image_key must be a SHA-256 digest.')
            if not re.fullmatch(r'image/[a-z0-9.+-]+', mimetype):
                self._row_error('Images', row, 'mimetype must identify an image.')
            chunk_index = self._as_integer(row.get('chunk_index'), row, 'chunk_index')
            chunk_count = self._as_integer(row.get('chunk_count'), row, 'chunk_count')
            if chunk_count <= 0 or chunk_index < 1 or chunk_index > chunk_count:
                self._row_error(
                    'Images', row, 'chunk_index and chunk_count are invalid.')
            image = image_chunks.setdefault(image_key, {
                'mimetype': mimetype,
                'chunk_count': chunk_count,
                'chunks': {},
            })
            if (
                    image['mimetype'] != mimetype
                    or image['chunk_count'] != chunk_count):
                self._row_error(
                    'Images', row,
                    'image metadata does not match the other chunks.')
            if chunk_index in image['chunks']:
                self._row_error('Images', row, 'chunk_index is duplicated.')
            image['chunks'][chunk_index] = row['data_base64']

        if self._as_integer(expected_count, {}, 'Manifest image_count') != len(
                image_chunks):
            raise UserError(_('The image count does not match the Manifest.'))

        images = {}
        for image_key, image in image_chunks.items():
            if set(image['chunks']) != set(
                    range(1, image['chunk_count'] + 1)):
                raise UserError(_(
                    'Image %(image)s is missing one or more data chunks.'
                ) % {'image': image_key})
            encoded = ''.join(
                image['chunks'][index]
                for index in range(1, image['chunk_count'] + 1))
            try:
                image_data = base64.b64decode(encoded, validate=True)
            except (ValueError, TypeError) as exc:
                raise UserError(_(
                    'Image %(image)s contains invalid base64 data.'
                ) % {'image': image_key}) from exc
            if not image_data:
                self._row_error('Images', row, 'image data must not be empty.')
            if offline_image_key(image['mimetype'], image_data) != image_key:
                raise UserError(_(
                    'Image %(image)s failed its integrity check.'
                ) % {'image': image_key})
            images[image_key] = 'data:%s;base64,%s' % (
                image['mimetype'], encoded)
        return images

    def _validate_image_markers(self, value, images, sheet, row):
        def validate_marker(source):
            if not source.startswith('cbt-offline-image:'):
                return source
            image_key = source.split(':', 1)[1]
            if image_key not in images:
                self._row_error(
                    sheet, row,
                    'image reference does not exist in the Images sheet.')
            return source

        transform_html_image_sources(value, validate_marker)

    def _restore_image_markers(self, value, images):
        def restore_marker(source):
            if not source.startswith('cbt-offline-image:'):
                return source
            image_key = source.split(':', 1)[1]
            return images[image_key]

        return transform_html_image_sources(value, restore_marker)

    def _html_matches_except_image_sources(self, current, expected):
        def remove_sources(value):
            return html_sanitize(transform_html_image_sources(
                value, lambda _source: ''))

        return remove_sources(current or '') == remove_sources(expected or '')

    @staticmethod
    def _cell_text(value):
        if value is None:
            return ''
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            if isinstance(value, float) and value.is_integer():
                return str(int(value))
            return value
        if hasattr(value, 'isoformat'):
            return value.isoformat()
        return str(value)

    def _row_error(self, sheet, row, message):
        raise UserError(_(
            '%(sheet)s row %(row)s: %(message)s'
        ) % {
            'sheet': sheet,
            'row': row.get('_row_number', '?'),
            'message': message,
        })

    def _source_record_id(self, source_id, sheet, row):
        try:
            record_id = int(source_id.rsplit(':', 1)[1])
            if record_id <= 0:
                raise ValueError
            return record_id
        except (AttributeError, IndexError, TypeError, ValueError):
            self._row_error(
                sheet, row,
                'source identifier must end with a positive source record ID.')

    def _require_text_fields(self, row, names):
        for name in names:
            if not isinstance(row.get(name), str):
                self._row_error(
                    row.get('_sheet', 'Papers'), row,
                    '%s must be text.' % name)

    def _as_integer(self, value, row, field_name='value'):
        try:
            number = int(value)
            if str(value).strip() not in (str(number), '%s.0' % number):
                raise ValueError
            return number
        except (TypeError, ValueError):
            error_row = row if isinstance(row, dict) else {}
            self._row_error(error_row.get('_sheet', 'Manifest'), error_row,
                            '%s must be an integer.' % field_name)

    def _as_float(self, value, row, field_name):
        try:
            number = float(value)
            if not math.isfinite(number):
                raise ValueError
            return number
        except (TypeError, ValueError):
            self._row_error(row.get('_sheet', 'Papers'), row,
                            '%s must be numeric.' % field_name)

    def _as_boolean(self, value, row):
        if value is True or value == 1 or str(value).strip().lower() in ('true', '1'):
            return True
        if value is False or value == 0 or str(value).strip().lower() in ('false', '0', ''):
            return False
        self._row_error(row.get('_sheet', 'Papers'), row,
                        'Boolean values must be true or false.')

    def _parse_date(self, value, row):
        if not value:
            return False
        try:
            return fields.Date.to_string(fields.Date.to_date(value))
        except (TypeError, ValueError):
            self._row_error('Papers', row, 'test_date must be an ISO date.')

    def _validate_hashes(self, allocations, questions_by_allocation, options_by_question):
        for allocation in allocations:
            allocation_key = (
                allocation['source_student_id'], allocation['source_paper_id'])
            allocation_questions = questions_by_allocation.get(allocation_key, [])
            allocation_options = []
            for question in allocation_questions:
                question_key = (allocation_key, question['source_question_id'])
                for option in sorted(
                        options_by_question.get(question_key, []),
                        key=lambda item: item['_order']):
                    allocation_options.append([
                        allocation['source_student_id'],
                        allocation['source_paper_id'],
                        question['source_question_id'],
                        option['source_option_id'],
                        option['_order'],
                        option['option_label'],
                        option['name'],
                    ])
            allocation_values = [
                allocation['source_export_id'],
                allocation['source_generator_id'],
                allocation['source_student_id'],
                allocation['login'],
                allocation['name'],
                allocation['_cid'],
                allocation['source_paper_id'],
                allocation['source_template_paper_id'],
                allocation['paper_name'],
                allocation['program'],
                allocation['test_center'],
                allocation['test_date'],
                allocation['_time'],
                allocation['_duration'],
                allocation['_shuffle'],
                allocation['source_schedule_id'],
            ]
            question_values = [
                [
                    question['source_student_id'],
                    question['source_paper_id'],
                    question['source_question_id'],
                    question['subject_name'],
                    question['name'],
                    question['_order'],
                    question['_theory'],
                    question['correct_answer'],
                ]
                for question in allocation_questions
            ]
            expected_hash = hashlib.sha256(json.dumps({
                'paper_export': allocation_values,
                'questions': question_values,
                'options': allocation_options,
            }, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')).hexdigest()
            if expected_hash != allocation['payload_sha256']:
                self._row_error(
                    'Papers', allocation,
                    'payload_sha256 does not match the allocation data.')

    def _resolve_portal_users(self, participants):
        Users = self.env['res.users'].sudo().with_context(
            active_test=False, no_reset_password=True)
        logins = [row['login'] for row in participants]
        user_by_login = {
            user.login: user
            for user in Users.search([
                ('login', 'in', logins),
            ])
        }
        participant_users = {}
        missing_users = []
        for participant in participants:
            login = participant['login']
            user = user_by_login.get(login)
            if not user:
                missing_users.append(participant)
                continue
            if not user.active:
                self._row_error(
                    'Participants', participant,
                    'portal user %s is archived.' % login)
            if not user._cbt_is_portal_only():
                self._row_error(
                    'Participants', participant,
                    'login %s belongs to a non-portal user.' % login)
            participant_users[participant['source_student_id']] = user

        portal_group = self.env.ref('base.group_portal')
        company = self.env.company
        for participant in missing_users:
            login = participant['login']
            name = participant['name'] or login
            partner = self.env['res.partner'].sudo().create({
                'name': name,
                'email': login,
            })
            user = Users.create({
                'name': name,
                'login': login,
                'password': participant['password'],
                'partner_id': partner.id,
                'email': login,
                'groups_id': [(6, 0, [portal_group.id])],
                'company_id': company.id,
                'company_ids': [(6, 0, [company.id])],
                'active': True,
            })
            participant_users[participant['source_student_id']] = user
            user_by_login[login] = user

        return participant_users, len(missing_users)

    def _validate_existing_allocations(
            self, allocations, questions_by_allocation, options_by_question,
            portal_users, image_payloads):
        Paper = self.env['cbt.paper.export'].sudo()
        existing = {}
        image_repairs = set()
        center_repairs = set()
        export_ids = [row['source_export_id'] for row in allocations]
        student_ids = list({row['source_student_id'] for row in allocations})
        paper_ids = list({row['source_paper_id'] for row in allocations})
        existing_papers = Paper.search([
            '|',
            ('source_export_id', 'in', export_ids),
            '&',
            ('source_student_id', 'in', student_ids),
            ('source_paper_id', 'in', paper_ids),
        ])
        existing_by_export = {
            paper.source_export_id: paper for paper in existing_papers
            if paper.source_export_id
        }
        existing_by_pair = defaultdict(list)
        for paper in existing_papers:
            if paper.source_student_id and paper.source_paper_id:
                existing_by_pair[
                    (paper.source_student_id, paper.source_paper_id)
                ].append(paper)

        for allocation in allocations:
            allocation_key = (
                allocation['source_student_id'], allocation['source_paper_id'])
            paper = existing_by_export.get(allocation['source_export_id'])
            papers_for_pair = existing_by_pair.get(allocation_key, [])
            if not paper and papers_for_pair:
                self._row_error(
                    'Papers', allocation,
                    'the same source student/paper already exists under a different allocation identifier.')
            if paper and any(existing_paper != paper for existing_paper in papers_for_pair):
                self._row_error(
                    'Papers', allocation,
                    'the source allocation identifier and student/paper mapping refer to different records.')
            if not paper:
                continue
            image_repair = False
            center_repair = False
            if paper.source_payload_hash != allocation['payload_sha256']:
                center_repair = (
                    (paper.test_center or '') != allocation['test_center']
                    and self._paper_is_unstarted(paper))
                image_repair = self._can_repair_image_sources(
                    paper, allocation,
                    questions_by_allocation[allocation_key],
                    options_by_question, image_payloads)
                if not image_repair and not center_repair:
                    self._row_error(
                        'Papers', allocation,
                        'this source allocation already exists with different data; '
                        'it will not be overwritten.')
            portal_user = portal_users[allocation['source_export_id']]
            if paper.user_id != portal_user.id:
                self._row_error(
                    'Papers', allocation,
                    'the existing source allocation is linked to a different portal user.')
            if (
                    paper.source_student_id != allocation['source_student_id']
                    or paper.source_paper_id != allocation['source_paper_id']
                    or (
                        paper.source_template_paper_id
                        and paper.source_template_paper_id
                        != allocation['source_template_paper_id'])):
                self._row_error(
                    'Papers', allocation,
                    'the existing source allocation has conflicting source identifiers.')
            expected_values = {
                'server_id': allocation['_server_id'],
                'user_id': portal_user.id,
                'login': portal_user.login,
                'name': allocation['name'] or portal_user.name,
                'paper_name': allocation['paper_name'],
                'program': allocation['program'],
                'test_center': allocation['test_center'],
                'test_duration': allocation['_duration'],
                'shuffle_section': allocation['_shuffle'],
                'cid': allocation['_cid'],
            }
            for field_name, expected_value in expected_values.items():
                if field_name == 'test_center' and center_repair:
                    continue
                actual_value = getattr(paper, field_name)
                if field_name in ('login', 'name', 'paper_name', 'program', 'test_center'):
                    actual_value = actual_value or ''
                    expected_value = expected_value or ''
                if actual_value != expected_value:
                    self._row_error(
                        'Papers', allocation,
                        'an existing allocation has conflicting %s data.' % field_name)
            if fields.Date.to_string(paper.test_date) != allocation['_date']:
                self._row_error(
                    'Papers', allocation,
                    'an existing allocation has conflicting test_date data.')
            if not math.isclose(
                    paper.test_time, allocation['_time'], rel_tol=0, abs_tol=1e-9):
                self._row_error(
                    'Papers', allocation,
                    'an existing allocation has conflicting test_time data.')
            expected_questions = questions_by_allocation[allocation_key]
            existing_questions = {
                line.source_question_id: line for line in paper.line_ids
            }
            if (len(existing_questions) != len(paper.line_ids)
                    or set(existing_questions) != {
                    question['source_question_id']
                    for question in expected_questions}):
                self._row_error(
                    'Papers', allocation,
                    'an existing allocation has an incomplete or conflicting question graph.')
            for question in expected_questions:
                question_key = (
                    allocation_key, question['source_question_id'])
                line = existing_questions[question['source_question_id']]
                expected_options = {
                    option['source_option_id']: option
                    for option in options_by_question.get(question_key, [])
                }
                expected_question_html = html_sanitize(
                    self._restore_image_markers(
                        question['name'], image_payloads))
                question_html_matches = (
                    normalize_inline_image_sources(line.name or '')
                    == normalize_inline_image_sources(expected_question_html))
                if (
                        not question_html_matches
                        and not (
                            image_repair
                            and self._html_matches_except_image_sources(
                                line.name, expected_question_html))):
                    self._row_error(
                        'Papers', allocation,
                        'an existing allocation has conflicting question data.')
                if (
                        line.server_id != question['_server_id']
                        or line.sequence != question['_order']
                        or (line.subject_id.name or '') != question['subject_name']
                        or line.is_theory != question['_theory']
                        or (line.correct_answer or '') != question['correct_answer']
                        or line.source_student_id != allocation['source_student_id']
                        or line.source_paper_id != allocation['source_paper_id']):
                    self._row_error(
                        'Papers', allocation,
                        'an existing allocation has conflicting question data.')
                existing_options = {
                    option.source_option_id: option for option in line.option_ids
                }
                if (
                        len(existing_options) != len(line.option_ids)
                        or set(existing_options) != set(expected_options)):
                    self._row_error(
                        'Papers', allocation,
                        'an existing allocation has an incomplete or conflicting option graph.')
                for source_option_id, expected_option in expected_options.items():
                    existing_option = existing_options[source_option_id]
                    expected_option_html = html_sanitize(
                        self._restore_image_markers(
                            expected_option['name'], image_payloads))
                    option_html_matches = (
                        normalize_inline_image_sources(
                            existing_option.name or '')
                        == normalize_inline_image_sources(expected_option_html))
                    if (
                            not option_html_matches
                            and not (
                                image_repair
                                and self._html_matches_except_image_sources(
                                    existing_option.name, expected_option_html))):
                        self._row_error(
                            'Papers', allocation,
                            'an existing allocation has conflicting answer option data.')
                    if (
                            existing_option.sequence != expected_option['_order']):
                        self._row_error(
                            'Papers', allocation,
                            'an existing allocation has conflicting answer option data.')
            existing[allocation['source_export_id']] = paper
            if image_repair:
                image_repairs.add(allocation['source_export_id'])
            if center_repair:
                center_repairs.add(allocation['source_export_id'])
        return existing, image_repairs, center_repairs

    def _paper_is_unstarted(self, paper):
        return not (
            paper.paper_started or paper.end_paper or paper.is_login
            or paper.last_session_id or paper.last_session_token
            or paper.session_ids
            or paper.line_ids.filtered(lambda line: (
                line.answer or (line.theory_answer or '').strip()
                or line.mark_review or line.answer_alphabet)))

    def _can_repair_image_sources(
            self, paper, allocation, expected_questions, options_by_question,
            image_payloads):
        if not self._paper_is_unstarted(paper):
            return False

        allocation_key = (
            allocation['source_student_id'], allocation['source_paper_id'])
        existing_questions = {
            line.source_question_id: line for line in paper.line_ids
        }
        if (
                len(existing_questions) != len(paper.line_ids)
                or set(existing_questions) != {
                    question['source_question_id']
                    for question in expected_questions}):
            return False

        has_new_image = False
        has_changed_image_source = False
        for question in expected_questions:
            question_key = (
                allocation_key, question['source_question_id'])
            line = existing_questions[question['source_question_id']]
            expected_question_html = html_sanitize(
                self._restore_image_markers(question['name'], image_payloads))
            if 'cbt-offline-image:' in question['name']:
                has_new_image = True
            if (
                    line.server_id != question['_server_id']
                    or line.sequence != question['_order']
                    or (line.subject_id.name or '') != question['subject_name']
                    or line.is_theory != question['_theory']
                    or (line.correct_answer or '') != question['correct_answer']
                    or line.source_student_id != allocation['source_student_id']
                    or line.source_paper_id != allocation['source_paper_id']):
                return False
            if (line.name or '') != expected_question_html:
                if not self._html_matches_except_image_sources(
                        line.name, expected_question_html):
                    return False
                has_changed_image_source = True

            expected_options = {
                option['source_option_id']: option
                for option in options_by_question.get(question_key, [])
            }
            existing_options = {
                option.source_option_id: option for option in line.option_ids
            }
            if (
                    len(existing_options) != len(line.option_ids)
                    or set(existing_options) != set(expected_options)):
                return False
            for source_option_id, expected_option in expected_options.items():
                existing_option = existing_options[source_option_id]
                expected_option_html = html_sanitize(
                    self._restore_image_markers(
                        expected_option['name'], image_payloads))
                if 'cbt-offline-image:' in expected_option['name']:
                    has_new_image = True
                if existing_option.sequence != expected_option['_order']:
                    return False
                if (existing_option.name or '') != expected_option_html:
                    if not self._html_matches_except_image_sources(
                            existing_option.name, expected_option_html):
                        return False
                    has_changed_image_source = True

        return has_new_image and has_changed_image_source
