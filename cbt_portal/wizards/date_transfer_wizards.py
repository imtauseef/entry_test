from odoo import fields, models, api
from odoo.exceptions import UserError
import json
import requests
from datetime import date

class TestDateTransfer(models.TransientModel):

    _name = 'test.date.transfer'
    _description = 'Test Date Transfer'

    program_id = fields.Many2one('cbt.program', 'Cbt Program', required=True)
    # slot_id = fields.Many2one('cbt.slot', string='Slot',required=True, )
    date = fields.Date('Old Date Of Paper', required=True, )
    new_date = fields.Date('New Date Of Paper', required=True)

    def transfer_date(self):
        print(type(fields.date.today()))
        paper = self.env['cbt.paper.export'].sudo().search(
            [('program', '=', self.program_id.name), ('test_date', '=', self.date)])
        if paper:
            for rec in paper:
                rec.test_date = self.new_date
