# -*- coding: utf-8 -*-
import json

from odoo import http, _
from odoo.exceptions import UserError
from odoo.http import request


class CBTExcelPasswordController(http.Controller):
    _ALLOWED_OPERATIONS = {
        'cbt.paper.generator': {'_export_allocation_workbook'},
        'cbt.paper.export.batch': {'_action_export_results'},
        'cbt.paper.result.batch': {'_action_export_final_result_list'},
        'cbt.paper.import.wizard': {'_import_workbook'},
        'cbt.paper.result.import.wizard': {'_import_workbook'},
    }

    # Each allowlisted method rejects the request without the caller's password.
    @http.route(
        '/cbt/excel/execute', type='http', auth='user',
        methods=['POST'], csrf=False)
    def execute_excel_operation(self):
        try:
            payload = request.httprequest.get_json(silent=True)
            if not isinstance(payload, dict):
                raise UserError(_('The Excel operation request is invalid.'))

            model_name = payload.get('model')
            method_name = payload.get('method')
            if not isinstance(model_name, str) or not isinstance(
                    method_name, str):
                raise UserError(_('This Excel operation is not allowed.'))
            if method_name not in self._ALLOWED_OPERATIONS.get(model_name, set()):
                raise UserError(_('This Excel operation is not allowed.'))
            try:
                record_id = int(payload.get('res_id'))
            except (TypeError, ValueError):
                raise UserError(_('The Excel operation record is invalid.'))

            context = {}
            action_context = payload.get('context')
            if isinstance(action_context, dict):
                allocation_warning = action_context.get(
                    'cbt_allocation_warning')
                if isinstance(allocation_warning, str):
                    context['cbt_allocation_warning'] = allocation_warning

            record = request.env[model_name].with_context(**context).browse(
                record_id).exists()
            if not record:
                raise UserError(_('The Excel operation record no longer exists.'))
            record.check_access_rights('read')
            record.check_access_rule('read')
            result = getattr(record, method_name)(
                odoo_password=payload.get('odoo_password'),
                workbook_password=payload.get('workbook_password'),
            )
            response_body = {'result': result}
            status = 200
        except UserError as exc:
            response_body = {'error': str(exc)}
            status = 400

        return request.make_response(
            json.dumps(response_body),
            headers=[
                ('Content-Type', 'application/json'),
                ('Cache-Control', 'no-store'),
                ('Pragma', 'no-cache'),
            ],
            status=status,
        )
