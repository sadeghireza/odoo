from odoo import fields, models


class IpmoPaymentType(models.Model):
    _name = 'ipmo.payment.type'
    _description = 'Payment Type'
    _order = 'code'

    code = fields.Char(required=True, index=True)
    name = fields.Char(required=True)
    description = fields.Text()

    _sql_constraints = [
        ('ipmo_payment_type_code_uniq', 'unique(code)', 'Payment type code must be unique.'),
    ]
