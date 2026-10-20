from odoo import models, fields, api, _
from odoo.exceptions import UserError


class ResConfigSettingInherit(models.TransientModel):
    _inherit = 'res.config.settings'

    admission_url = fields.Char('Admission Url' ,config_parameter='cbt.admission_url')
    admission_db = fields.Char('Admission Database Name',config_parameter='cbt.admission_db')
    admission_login = fields.Char('Admission Login',config_parameter='cbt.admission_login')
    admission_password = fields.Char('Admission Password',config_parameter='cbt.admission_password')