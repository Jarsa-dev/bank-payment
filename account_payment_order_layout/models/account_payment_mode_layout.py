# Copyright 2023 Jarsa
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).

import unicodedata

from odoo import api, fields, models, tools
from odoo.exceptions import UserError, ValidationError
from odoo.tools.safe_eval import safe_eval, test_python_expr, time


class AccountPaymentModeLayout(models.Model):
    _name = "account.payment.mode.layout"
    _description = "Account Payment Mode Layout"

    name = fields.Char(required=True)
    code = fields.Char(required=True)
    active = fields.Boolean(default=True)
    print_file_name = fields.Char(
        string="Printed File Name",
        translate=True,
        required=True,
        help="This is the filename of the file going to download. Keep empty to not"
        " change the filename. You can use a python expression with the 'order'"
        " and 'time' variables.",
        default="order.name + '.txt'",
    )
    company_id = fields.Many2one(
        comodel_name="res.company", default=lambda self: self.env.company
    )
    characters_to_remove = fields.Char(
        help="Characters that will be removed from all values"
    )
    separator = fields.Char(
        help="Character that will be used to separate the values, default is no "
        "separator"
    )
    line_ending = fields.Selection(
        selection=[
            ("lf", "LF (Unix)"),
            ("crlf", "CRLF (Windows)"),
        ],
        required=True,
        default="lf",
        help="Characters used to separate the records of the file",
    )
    header_line_ids = fields.One2many(
        comodel_name="account.payment.mode.layout.line",
        inverse_name="layout_id",
        string="Header Lines",
        help="Lines that will be added to the header of the file",
        domain=[("usage", "=", "header")],
    )
    line_ids = fields.One2many(
        comodel_name="account.payment.mode.layout.line",
        inverse_name="layout_id",
        string="Layout Lines",
        domain=[("usage", "=", "line")],
    )
    footer_line_ids = fields.One2many(
        comodel_name="account.payment.mode.layout.line",
        inverse_name="layout_id",
        string="Footer Lines",
        help="Lines that will be added to the footer of the file",
        domain=[("usage", "=", "footer")],
    )
    model_id = fields.Many2one(
        comodel_name="ir.model",
        domain=[("model", "in", ["account.payment.order", "account.payment"])],
        store=False,
    )
    model_field_id = fields.Many2one(comodel_name="ir.model.fields", store=False)
    submodel_id = fields.Many2one(comodel_name="ir.model", store=False)
    submodel_field_id = fields.Many2one(comodel_name="ir.model.fields", store=False)
    expression = fields.Char(store=False)

    @api.onchange("model_field_id", "submodel_id", "submodel_field_id")
    def _onchange_dynamic_placeholder(self):
        """
        Update the expression field based on the selected model and fields.

        This method is called whenever the model_field_id, submodel_id or
        submodel_field_id fields are changed.
        It updates the expression field based on the selected model and fields.

        :return: None
        """
        if self.model_field_id:
            if self.model_field_id.ttype in ["many2one", "one2many", "many2many"]:
                model = self.env["ir.model"]._get(self.model_field_id.relation)
                if model:
                    self.submodel_id = model.id
                    sub_field_name = self.submodel_field_id.name
                    self.expression = self._build_expression(
                        self.model_id, self.model_field_id.name, sub_field_name
                    )
            else:
                self.submodel_id = False
                self.submodel_field_id = False
                self.expression = self._build_expression(
                    self.model_id, self.model_field_id.name, False
                )
        else:
            self.submodel_id = False
            self.expression = False
            self.submodel_field_id = False

    @api.model
    def _build_expression(self, model, field_name, sub_field_name):
        """
        Build an expression string based on the given model, field name and subfield
        name.

        :param model: The model to build the expression for.
        :type model: ir.model
        :param field_name: The name of the field to include in the expression.
        :type field_name: str
        :param sub_field_name: The name of the subfield to include in the expression.
        :type sub_field_name: str

        :return: The expression string.
        :rtype: str
        """
        expression = "order." if model._name == "account.payment.order" else "line."
        if field_name:
            expression += field_name
            if sub_field_name:
                expression += "." + sub_field_name
        return expression

    def generate_payment_file(self, order):
        """
        Generate a payment file based on an order.

        The file has one record for the header, one record per payment and one
        record for the footer. Header and footer records are only added when the
        layout has lines for them. Non ASCII characters are transliterated
        (e.g. "Ñ" becomes "N") because bank files only accept ASCII.

        :param order: The order to generate the payment file for.
        :type order: account.payment.order

        :return: A tuple containing the payment file as bytes and the file name as a
        string.
        :rtype: tuple
        """
        self.ensure_one()
        errors = []
        records = []
        if self.header_line_ids:
            records.append(self._build_record(self.header_line_ids, order, errors))
        for payment in order.payment_ids:
            records.append(self._build_record(self.line_ids, order, errors, payment))
        if self.footer_line_ids:
            records.append(self._build_record(self.footer_line_ids, order, errors))
        if errors:
            raise UserError("\n".join(errors))
        line_ending = "\r\n" if self.line_ending == "crlf" else "\n"
        content = self._to_ascii(line_ending.join(records))
        file_name = safe_eval(self.print_file_name, {"order": order, "time": time})
        return (content.encode("ascii"), file_name)

    def _build_record(self, layout_lines, order, errors, line=False):
        """
        Build one record of the file joining the values of the given layout lines.

        :param layout_lines: The layout lines that form the record.
        :type layout_lines: account.payment.mode.layout.line
        :param order: The order to generate the payment file for.
        :type order: account.payment.order
        :param errors: List where the errors found are appended.
        :type errors: list
        :param line: The payment of the record, False for header and footer.
        :type line: account.payment

        :return: The record as a string.
        :rtype: str
        """
        values = []
        for layout_line in layout_lines:
            result = layout_line._process_line(order, line)
            values.append(result["result"])
            if result["error"] and result["error"] not in errors:
                errors.append(result["error"])
        return (self.separator or "").join(values)

    @api.model
    def _to_ascii(self, value):
        """
        Transliterate a string to ASCII removing accents and dropping the
        characters that have no ASCII equivalent.

        :param value: The string to transliterate.
        :type value: str

        :return: The ASCII string.
        :rtype: str
        """
        return (
            unicodedata.normalize("NFKD", value)
            .encode("ascii", "ignore")
            .decode("ascii")
        )

    @api.constrains("print_file_name")
    def _check_print_file_name(self):
        """
        Check the validity of the print_file_name field.

        :raises: ValidationError if the print_file_name field is invalid.
        """
        for rec in self.filtered("code"):
            msg = test_python_expr(expr=rec.print_file_name.strip(), mode="eval")
            if msg:
                raise ValidationError(msg)


class AccountPaymentModeLayoutLine(models.Model):
    _name = "account.payment.mode.layout.line"
    _description = "Account Payment Mode Layout Line"
    _order = "sequence"

    layout_id = fields.Many2one(
        comodel_name="account.payment.mode.layout", required=True, ondelete="cascade"
    )
    sequence = fields.Integer(required=True, default=10)
    name = fields.Char(required=True)
    value_length = fields.Integer(string="Length", required=True)
    description = fields.Text()
    code = fields.Text(
        string="Python Code",
        default="result = ''",
        help="Write Python code that the action will execute. Some variables "
        "are available for use.",
    )
    characters_to_remove = fields.Char(
        help="Characters that will be removed from the value",
    )
    infill = fields.Char(
        help="Character that will be used to fill the value to the length, default is "
        "space",
    )
    strict_length = fields.Boolean(
        help="Raise an error when the value is longer than the length instead of "
        "truncating it. Use it on fields where a truncated value is a wrong value, "
        "like accounts or amounts.",
    )
    alignment = fields.Selection(
        selection=[
            ("left", "Left"),
            ("right", "Right"),
        ],
        required=True,
        default="right",
    )
    usage = fields.Selection(
        selection=[
            ("header", "Header"),
            ("line", "Line"),
            ("footer", "Footer"),
        ],
        required=True,
    )

    def _get_eval_context(self, order, line):
        """
        Prepare the context used when evaluating python code, like the python formulas
        or code server actions.

        :param order: The order to generate the payment file for.
        :type order: account.payment.order
        :param line: The line to process.
        :type line: account.payment.mode.layout.line

        :return: A dictionary containing the evaluation context.
        :rtype: dict
        """
        self.ensure_one()

        def log(message, level="info"):
            with self.pool.cursor() as cr:
                cr.execute(
                    """
                    INSERT INTO ir_logging(
                    create_date, create_uid, type, dbname, name, level,
                    message, path, line, func)
                    VALUES (
                    NOW() at time zone 'UTC',
                    %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                    (
                        self.env.uid,
                        "server",
                        self.env.cr.dbname,
                        __name__,
                        level,
                        message,
                        "account_payment_mode_layout",
                        self.id,
                        self.name,
                    ),
                )

        return {
            "line": line,
            "order": order,
            "datetime": tools.safe_eval.datetime,
            "dateutil": tools.safe_eval.dateutil,
            "time": tools.safe_eval.time,
            "UserError": UserError,
            "log": log,
        }

    def _process_line(self, order, line=False):
        """
        Process a line in the payment file layout by evaluating the Python code in the
        `code` field.

        :param order: The order to generate the payment file for.
        :type order: account.payment.order
        :param line: The line to process.
        :type line: account.payment.mode.layout.line

        :return: A dictionary containing the processed result and any error messages.
        :rtype: dict
        """
        self.ensure_one()
        eval_context = self._get_eval_context(order, line)
        safe_eval(self.code.strip(), eval_context, mode="exec")
        result = str(eval_context.get("result", ""))
        error = str(eval_context.get("error", ""))
        value = self._clean_result(result)
        if not error and self.strict_length and len(value) > self.value_length:
            error = self.env._(
                "The value '%(value)s' of the field '%(field)s' has more than "
                "%(length)s characters (%(record)s).",
                value=value,
                field=self.name,
                length=self.value_length,
                record=line.partner_id.display_name if line else order.name,
            )
        return {
            "result": self._format_result(result),
            "error": error,
        }

    def _clean_result(self, result):
        """
        Transliterate the value to ASCII and remove the characters configured in
        the line and in the layout. It is done per value, before padding, so a
        character without ASCII equivalent never shifts the fixed positions.

        :param result: The value to clean.
        :type result: str

        :return: The cleaned value.
        :rtype: str
        """
        self.ensure_one()
        result = self.layout_id._to_ascii(result)
        for char in self.characters_to_remove or "":
            result = result.replace(char, "")
        for char in self.layout_id.characters_to_remove or "":
            result = result.replace(char, "")
        return result

    def _format_result(self, result):
        """
        Format the result of processing a line in the payment file layout.

        :param result: The result to format.
        :type result: str

        :return: The formatted result.
        :rtype: str
        """
        self.ensure_one()
        result = self._clean_result(result)
        if self.alignment == "left":
            result = result.ljust(self.value_length, self.infill or " ")
        else:
            result = result.rjust(self.value_length, self.infill or " ")
        return result[: self.value_length]

    @api.constrains("code")
    def _check_python_code(self):
        """
        Check the validity of the code field.

        :raises: ValidationError if the code field is invalid.
        """
        for rec in self.filtered("code"):
            msg = test_python_expr(expr=rec.code.strip(), mode="exec")
            if msg:
                raise ValidationError(msg)
