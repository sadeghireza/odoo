from odoo import fields, models


class IpmoVendor(models.Model):
    _name = 'ipmo.vendor'
    _description = 'Vendor'
    _order = 'name'

    name = fields.Char(required=True)
    code = fields.Char(required=True, index=True)
    vendor_type = fields.Selection(
        [
            ('supplier', 'Supplier'),
            ('contractor', 'Contractor'),
            ('consultant', 'Consultant'),
        ],
        required=True,
        default='supplier',
    )
    national_id = fields.Char()
    economic_code = fields.Char()
    bank_account = fields.Char()
    status = fields.Selection(
        [('active', 'Active'), ('inactive', 'Inactive')],
        required=True,
        default='active',
    )

    _sql_constraints = [
        ('ipmo_vendor_code_uniq', 'unique(code)', 'Vendor code must be unique.'),
    ]
