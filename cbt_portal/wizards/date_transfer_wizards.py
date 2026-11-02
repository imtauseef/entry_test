from odoo import fields, models, api
from odoo.exceptions import UserError
import json
import requests
from datetime import date

class TestDateTransfer(models.TransientModel):

    _name = 'test.date.transfer'
    _description = 'Test Date Transfer'

    program = fields.Char('Program', required=True)
    date = fields.Date('Old Date Of Paper', required=True, )
    new_date = fields.Date('New Date Of Paper', required=True)

    def transfer_date(self):
        paper = self.env['cbt.paper.export'].sudo().search(
            [('program', '=', self.program), ('test_date', '=', self.date)])
        if paper:
            for rec in paper:
                rec.test_date = self.new_date
