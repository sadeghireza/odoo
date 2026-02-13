from odoo import api, fields, models
from odoo.exceptions import ValidationError


class IpmoAgreementLine(models.Model):
    _name = 'ipmo.agreement.line'
    _description = 'Agreement Line'
    _order = 'line_no'

    agreement_id = fields.Many2one('ipmo.agreement', required=True, ondelete='cascade')
    line_no = fields.Integer(required=True, default=1)
    description = fields.Char(required=True)
    payment_type_id = fields.Many2one('ipmo.payment.type', required=True, ondelete='restrict')
    unit = fields.Char()
    quantity = fields.Float()
    unit_price = fields.Monetary()
    lump_sum_amount = fields.Monetary()
    ceiling_amount = fields.Monetary()
    line_amount = fields.Monetary(compute='_compute_line_amount', store=True)
    currency_id = fields.Many2one(related='agreement_id.currency_id', store=True, readonly=True)

    _sql_constraints = [
        ('ipmo_agreement_line_no_uniq', 'unique(agreement_id, line_no)', 'Line number must be unique per agreement.'),
    ]

    @api.depends('payment_type_id.code', 'quantity', 'unit_price', 'lump_sum_amount', 'ceiling_amount')
    def _compute_line_amount(self):
        for line in self:
            code = line.payment_type_id.code
            if code == 'LS':
                line.line_amount = line.lump_sum_amount
            elif code == 'UR':
                line.line_amount = line.quantity * line.unit_price
            elif code in ('CR', 'TM', 'TC'):
                line.line_amount = line.ceiling_amount
            else:
                line.line_amount = 0.0

    @api.constrains('payment_type_id', 'quantity', 'unit_price', 'lump_sum_amount', 'ceiling_amount')
    def _check_payment_fields(self):
        for line in self:
            code = line.payment_type_id.code
            if code == 'LS':
                if not line.lump_sum_amount:
                    raise ValidationError('Lump Sum lines require a lump sum amount.')
                if line.quantity or line.unit_price or line.ceiling_amount:
                    raise ValidationError('Lump Sum lines only allow a lump sum amount.')
            elif code == 'UR':
                if not line.quantity or not line.unit_price:
                    raise ValidationError('Unit Rate lines require quantity and unit price.')
                if line.lump_sum_amount or line.ceiling_amount:
                    raise ValidationError('Unit Rate lines do not allow lump sum or ceiling amounts.')
            elif code in ('CR', 'TM', 'TC'):
                if not line.ceiling_amount:
                    raise ValidationError('Cost Reimbursable or T&M lines require a ceiling amount.')
                if line.lump_sum_amount:
                    raise ValidationError('Cost Reimbursable or T&M lines do not allow lump sum amounts.')
            else:
                raise ValidationError('Unsupported payment type on agreement line.')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('agreement_id'):
                agreement = self.env['ipmo.agreement'].browse(vals['agreement_id'])
                if agreement.status != 'draft':
                    raise ValidationError('Agreement lines can only be added in draft agreements.')
                if not vals.get('line_no'):
                    existing = self.search([('agreement_id', '=', agreement.id)], order='line_no desc', limit=1)
                    vals['line_no'] = (existing.line_no or 0) + 1
        return super().create(vals_list)

    def write(self, vals):
        for line in self:
            if line.agreement_id.status != 'draft':
                raise ValidationError('Agreement lines can only be edited in draft agreements.')
        return super().write(vals)

    def unlink(self):
        for line in self:
            if line.agreement_id.status != 'draft':
                raise ValidationError('Agreement lines can only be removed in draft agreements.')
        return super().unlink()
