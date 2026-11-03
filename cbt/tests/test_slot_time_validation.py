from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase


class TestSlotTimeValidation(TransactionCase):

    def setUp(self):
        super().setUp()
        self.center_model = self.env['cbt.center']
        self.slot_model = self.env['cbt.slot']

    def _slot_values(self, **overrides):
        values = {
            'date': '2026-11-02',
            'time': 9.0,
            'time_to': 10.0,
        }
        values.update(overrides)
        return values

    def test_center_rejects_midnight_as_slot_end(self):
        with self.assertRaises(ValidationError):
            self.center_model.create({
                'name': 'Validation Center',
                'code': 'SLOT-VALIDATION',
                'slot_ids': [(0, 0, self._slot_values(time_to=0.0))],
            })

    def test_slot_end_must_be_valid_and_different_from_start(self):
        for invalid_end in (0.0, 24.0, 9.0):
            with self.subTest(time_to=invalid_end):
                with self.assertRaises(ValidationError):
                    self.slot_model.create(self._slot_values(
                        time_to=invalid_end))

    def test_valid_regular_and_overnight_slot_times_are_allowed(self):
        regular_slot = self.slot_model.create(self._slot_values())
        overnight_slot = self.slot_model.create(self._slot_values(
            time=23.0, time_to=1.0))

        self.assertEqual(regular_slot.time_to, 10.0)
        self.assertEqual(overnight_slot.time_to, 1.0)

    def test_slot_end_cannot_be_changed_to_midnight(self):
        slot = self.slot_model.create(self._slot_values())

        with self.assertRaises(ValidationError):
            slot.write({'time_to': 0.0})
