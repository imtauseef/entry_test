

import os
import time
import subprocess
from odoo import fields, models, _, api, http
import pdb
from odoo.exceptions import UserError, ValidationError


class CBTExportInhert(models.Model):
    _inherit = 'cbt.export'




    def dump_database(self):
        DB_NAME = 'cbt_export'
        DB_USER = 'odoo14'
        DB_HOST = "localhost"
        DB_PASSWORD = '12345'
        dump_success = 1
        date_latest=str(fields.datetime.now())
        print('Backing up %s database ' % (DB_NAME))
        command_for_dumping = f'pg_dump --username "odoo14" --no-password --format custom --blobs --verbose --file "odoo-custom-addons/cbt/static/backups/{DB_NAME}_{date_latest}.dump" {DB_NAME}'
        cbt_export_id = self.env['cbt.export'].search([('id', '=', self.id)])
        path_export = '/cbt/static/backups/' + DB_NAME + '_' + date_latest + '.dump'
        try:
            proc = subprocess.Popen(command_for_dumping, shell=True, env={
                'PGPASSWORD': DB_PASSWORD
            })
            out, err = proc.communicate()

        except Exception as e:
            dump_success = 0
            raise ValidationError(_("Exception happened during dump %s") % (e))

        if dump_success:
            # print('db dump Successfull')
            return {
                "type": "ir.actions.act_url",
                "url": str(path_export),
                "target": "new",
            }
            raise ValidationError(_("DB dump Successfull"))




