from odoo import api, fields, models
from odoo.exceptions import ValidationError


class IpmoPaymentCertificate(models.Model):
    _name = 'ipmo.payment.certificate'
    _description = 'Payment Certificate'
    _order = 'pc_no desc'

    agreement_id = fields.Many2one('ipmo.agreement', required=True, ondelete='cascade')
    pc_no = fields.Char(required=True)
    period_from = fields.Date(required=True)
    period_to = fields.Date(required=True)
    pc_date = fields.Date(required=True)
    gross_amount = fields.Monetary(compute='_compute_amounts', store=True)
    deduction_amount = fields.Monetary()
    net_amount = fields.Monetary(compute='_compute_amounts', store=True)
    status = fields.Selection(
        [('draft', 'Draft'), ('submitted', 'Submitted'), ('approved', 'Approved')],
        required=True,
        default='draft',
    )
    currency_id = fields.Many2one(related='agreement_id.currency_id', store=True, readonly=True)
    line_ids = fields.One2many('ipmo.payment.certificate.line', 'payment_certificate_id', string='Lines')
    attachment_count = fields.Integer(compute='_compute_attachment_count')

    _sql_constraints = [
        ('ipmo_payment_certificate_no_uniq', 'unique(agreement_id, pc_no)', 'Payment certificate number must be unique per agreement.'),
    ]

    @api.depends('line_ids.payable_amount', 'deduction_amount')
    def _compute_amounts(self):
        for certificate in self:
            gross = sum(certificate.line_ids.mapped('payable_amount'))
            certificate.gross_amount = gross
            certificate.net_amount = gross - (certificate.deduction_amount or 0.0)

    @api.constrains('period_from', 'period_to')
    def _check_period_dates(self):
        for certificate in self:
            if certificate.period_to < certificate.period_from:
                raise ValidationError('Payment certificate period end must be on or after start.')

    def _validate_status_transition(self, new_status):
        allowed_transitions = {
            'draft': ['submitted'],
            'submitted': ['approved'],
            'approved': [],
        }
        for certificate in self:
            current_status = certificate.status
            if new_status == current_status:
                continue
            if new_status not in allowed_transitions.get(current_status, []):
                raise ValidationError('Invalid status transition for payment certificate.')

    @api.depends()
    def _compute_attachment_count(self):
        for certificate in self:
            certificate.attachment_count = self.env['ipmo.attachment'].search_count([
                ('res_model', '=', 'ipmo.payment.certificate'),
                ('res_id', '=', certificate.id),
            ])

    def write(self, vals):
        if 'status' in vals:
            self._validate_status_transition(vals['status'])
        protected_fields = set(vals) - {'status'}
        for certificate in self:
            if certificate.status != 'draft' and protected_fields:
                raise ValidationError('Only draft payment certificates can be edited.')
        return super().write(vals)

    def action_submit(self):
        self.write({'status': 'submitted'})

    def action_approve(self):
        self.write({'status': 'approved'})

    def action_view_attachments(self):
        action = self.env.ref('ipmo_contract.action_ipmo_attachment').read()[0]
        action['domain'] = [
            ('res_model', '=', 'ipmo.payment.certificate'),
            ('res_id', '=', self.id),
        ]
        return action


class IpmoPaymentCertificateLine(models.Model):
    _name = 'ipmo.payment.certificate.line'
    _description = 'Payment Certificate Line'
    _order = 'id'

    payment_certificate_id = fields.Many2one('ipmo.payment.certificate', required=True, ondelete='cascade')
    agreement_line_id = fields.Many2one('ipmo.agreement.line', required=True, ondelete='restrict')
    executed_quantity = fields.Float()
    executed_percent = fields.Float()
    actual_cost = fields.Monetary()
    payable_amount = fields.Monetary(compute='_compute_payable_amount', store=True)
    currency_id = fields.Many2one(related='agreement_line_id.currency_id', store=True, readonly=True)

    @api.depends(
        'agreement_line_id.payment_type_id.code',
        'agreement_line_id.lump_sum_amount',
        'agreement_line_id.unit_price',
        'agreement_line_id.ceiling_amount',
        'executed_quantity',
        'executed_percent',
        'actual_cost',
    )
    def _compute_payable_amount(self):
        for line in self:
            code = line.agreement_line_id.payment_type_id.code
            if code == 'LS':
                percent = line.executed_percent or 0.0
                line.payable_amount = (line.agreement_line_id.lump_sum_amount or 0.0) * percent / 100.0
            elif code == 'UR':
                line.payable_amount = (line.executed_quantity or 0.0) * (line.agreement_line_id.unit_price or 0.0)
            elif code in ('CR', 'TM', 'TC'):
                amount = line.actual_cost or 0.0
                ceiling = line.agreement_line_id.ceiling_amount or 0.0
                line.payable_amount = min(amount, ceiling) if ceiling else amount
            else:
                line.payable_amount = 0.0

    @api.constrains('executed_percent', 'executed_quantity', 'actual_cost', 'agreement_line_id')
    def _check_execution_fields(self):
        for line in self:
            code = line.agreement_line_id.payment_type_id.code
            if code == 'LS':
                if line.executed_percent is None or line.executed_percent <= 0.0:
                    raise ValidationError('Lump Sum payment certificates require executed percent.')
                if line.executed_percent > 100.0:
                    raise ValidationError('Executed percent cannot exceed 100%.')
            elif code == 'UR':
                if not line.executed_quantity:
                    raise ValidationError('Unit Rate payment certificates require executed quantity.')
            elif code in ('CR', 'TM', 'TC'):
                if not line.actual_cost:
                    raise ValidationError('Cost Reimbursable or T&M payment certificates require actual cost.')
            else:
                raise ValidationError('Unsupported payment type on payment certificate line.')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('payment_certificate_id'):
                certificate = self.env['ipmo.payment.certificate'].browse(vals['payment_certificate_id'])
                if certificate.status != 'draft':
                    raise ValidationError('Payment certificate lines can only be added in draft certificates.')
        return super().create(vals_list)

    def write(self, vals):
        for line in self:
            if line.payment_certificate_id.status != 'draft':
                raise ValidationError('Payment certificate lines can only be edited in draft certificates.')
        return super().write(vals)

    def unlink(self):
        for line in self:
            if line.payment_certificate_id.status != 'draft':
                raise ValidationError('Payment certificate lines can only be removed in draft certificates.')
        return super().unlink()
