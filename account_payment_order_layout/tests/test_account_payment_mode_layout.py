# Copyright 2026 Jarsa
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).

from odoo import Command, fields
from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged("-at_install", "post_install")
class TestAccountPaymentModeLayout(AccountTestInvoicingCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.company_data["company"]
        cls.env.user.company_id = cls.company.id
        cls.env.user.group_ids |= cls.env.ref(
            "account_payment_order.group_account_payment"
        )
        cls.partner = cls.env["res.partner"].create({"name": "Peñón Ñandú"})
        cls.layout = cls.env["account.payment.mode.layout"].create(
            {
                "name": "Test Layout",
                "code": "TEST",
                "print_file_name": "'TEST.txt'",
                "header_line_ids": [
                    cls._line_vals("header", 1, "Type", 1, "result = 'H'"),
                    cls._line_vals(
                        "header", 2, "Count", 3, "result = len(order.payment_ids)", "0"
                    ),
                ],
                "line_ids": [
                    cls._line_vals("line", 1, "Type", 1, "result = 'D'"),
                    cls._line_vals(
                        "line", 2, "Name", 12, "result = line.partner_id.name"
                    ),
                    cls._line_vals(
                        "line",
                        3,
                        "Amount",
                        6,
                        "result = int(round(line.amount * 100))",
                        "0",
                        strict_length=True,
                    ),
                ],
                "footer_line_ids": [
                    cls._line_vals("footer", 1, "Type", 1, "result = 'T'"),
                ],
            }
        )
        cls.mode = cls.env["account.payment.mode"].create(
            {
                "name": "Test Layout Mode",
                "company_id": cls.company.id,
                "bank_account_link": "variable",
                "payment_method_id": cls.env.ref(
                    "account.account_payment_method_manual_out"
                ).id,
                "layout_id": cls.layout.id,
            }
        )
        cls.expense_account = cls.env["account.account"].create(
            {
                "name": "Test expense account",
                "code": "TESTLAY",
                "account_type": "expense",
            }
        )
        cls.bank_journal = cls.company_data["default_journal_bank"]

    @classmethod
    def _line_vals(
        cls, usage, sequence, name, length, code, infill=False, strict_length=False
    ):
        return Command.create(
            {
                "usage": usage,
                "sequence": sequence,
                "name": name,
                "value_length": length,
                "code": code,
                "infill": infill,
                "alignment": "right" if infill else "left",
                "strict_length": strict_length,
            }
        )

    def _create_order(self, price_unit=100.0):
        invoice = self.env["account.move"].create(
            {
                "partner_id": self.partner.id,
                "move_type": "in_invoice",
                "ref": "LAY001",
                "payment_mode_id": self.mode.id,
                "invoice_date": fields.Date.today(),
                "invoice_line_ids": [
                    Command.create(
                        {
                            "name": "Service",
                            "quantity": 1.0,
                            "price_unit": price_unit,
                            "account_id": self.expense_account.id,
                            "tax_ids": [],
                        }
                    )
                ],
            }
        )
        invoice.action_post()
        invoice.create_account_payment_line()
        order = self.env["account.payment.order"].search(
            [("payment_mode_id", "=", self.mode.id), ("state", "=", "draft")]
        )
        order.journal_id = self.bank_journal
        order.draft2open()
        return order

    def _generate(self, order):
        action = order.open2generated()
        return self.env["ir.attachment"].browse(action["res_id"])

    def test_header_lines_and_footer(self):
        attachment = self._generate(self._create_order())
        self.assertEqual(attachment.name, "TEST.txt")
        self.assertEqual(
            attachment.raw.decode("ascii").split("\n"),
            ["H001", "DPenon Nandu 010000", "T"],
        )

    def test_separator_and_crlf(self):
        self.layout.write({"separator": "|", "line_ending": "crlf"})
        content = self._generate(self._create_order()).raw.decode("ascii")
        self.assertEqual(content, "H|001\r\nD|Penon Nandu |010000\r\nT")

    def test_non_ascii_without_equivalent_keeps_positions(self):
        self.partner.name = "Café €"
        content = self._generate(self._create_order()).raw.decode("ascii")
        self.assertEqual(content.split("\n")[1], "DCafe" + " " * 8 + "010000")

    def test_strict_length_raises(self):
        order = self._create_order(price_unit=10000.0)
        with self.assertRaisesRegex(UserError, "has more than 6 characters"):
            order.open2generated()

    def test_error_variable_raises(self):
        self.layout.footer_line_ids.code = "result = 'T'\nerror = 'Footer error'"
        order = self._create_order()
        with self.assertRaisesRegex(UserError, "Footer error"):
            order.open2generated()
