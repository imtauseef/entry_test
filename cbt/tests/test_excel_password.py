# -*- coding: utf-8 -*-
import zipfile

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase

from odoo.addons.cbt.models.allocation_xlsx import (
    build_allocation_xlsx,
    decrypt_xlsx,
    encrypt_xlsx,
    load_allocation_xlsx,
    verify_excel_admin_password,
)


class TestExcelPassword(TransactionCase):

    def setUp(self):
        super().setUp()
        self.odoo_password = 'excel-test-admin-password'
        self.workbook_password = 'excel-test-workbook-password-2026'
        self.env.user.sudo().write({'password': self.odoo_password})
        self.env.user.sudo().write({
            'groups_id': [(4, self.env.ref('cbt.group_cbt_admin').id)],
        })

    def test_password_verification_accepts_only_current_user_password(self):
        verify_excel_admin_password(self.env, self.odoo_password)
        with self.assertRaisesRegex(UserError, 'Odoo login password is incorrect'):
            verify_excel_admin_password(self.env, 'incorrect-password')

    def test_xlsx_encryption_rejects_missing_or_incorrect_password(self):
        workbook = build_allocation_xlsx([
            ('Results', [['Student Login ID'], ['candidate-1']]),
        ])
        self.assertTrue(zipfile.is_zipfile(workbook))

        encrypted = encrypt_xlsx(workbook, self.workbook_password)
        self.assertFalse(zipfile.is_zipfile(encrypted))
        with self.assertRaisesRegex(UserError, 'workbook is password-protected'):
            decrypt_xlsx(encrypted)
        with self.assertRaisesRegex(UserError, 'workbook password is incorrect'):
            decrypt_xlsx(encrypted, 'incorrect-workbook-password')

        decrypted = decrypt_xlsx(encrypted, self.workbook_password)
        self.assertTrue(zipfile.is_zipfile(decrypted))
        loaded = load_allocation_xlsx(decrypted)
        self.assertEqual(
            list(loaded['Results'].iter_rows(values_only=True)),
            [('Student Login ID',), ('candidate-1',)],
        )

    def test_short_workbook_password_is_rejected(self):
        with self.assertRaisesRegex(UserError, 'at least 12 characters'):
            encrypt_xlsx(b'not-used', 'short')
