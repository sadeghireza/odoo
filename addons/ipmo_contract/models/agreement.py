from odoo import api, fields, models
from odoo.exceptions import ValidationError


class IpmoAgreement(models.Model):
    _name = 'ipmo.agreement'
    _description = 'Agreement'
    _order = 'agreement_no desc'

    agreement_no = fields.Char(required=True, index=True)
    agreement_type = fields.Selection(
        [('goods', 'Goods'), ('service', 'Service')],
        required=True,
        default='goods',
    )
    industry_term = fields.Selection(
        [('PO', 'PO'), ('Contract', 'Contract')],
        required=True,
        default='Contract',
    )
    vendor_id = fields.Many2one('ipmo.vendor', required=True, ondelete='restrict')
    project_id = fields.Many2one('project.project', required=True, ondelete='restrict')
    subject = fields.Char(required=True)
    start_date = fields.Date()
    end_date = fields.Date()
    currency_id = fields.Many2one(
        'res.currency',
        required=True,
        default=lambda self: self.env.company.currency_id,
    )
    base_amount = fields.Monetary(compute='_compute_amounts', store=True)
    tax_amount = fields.Monetary(compute='_compute_amounts', store=True)
    total_amount = fields.Monetary(compute='_compute_amounts', store=True)
    status = fields.Selection(
        [
            ('draft', 'Draft'),
            ('active', 'Active'),
            ('closed', 'Closed'),
            ('terminated', 'Terminated'),
        ],
        required=True,
        default='draft',
    )
    signed_date = fields.Date()

    line_ids = fields.One2many('ipmo.agreement.line', 'agreement_id', string='Lines')
    amendment_ids = fields.One2many('ipmo.agreement.amendment', 'agreement_id', string='Amendments')
    change_order_ids = fields.One2many('ipmo.change.order', 'agreement_id', string='Change Orders')
    payment_certificate_ids = fields.One2many('ipmo.payment.certificate', 'agreement_id', string='Payment Certificates')

    amendment_count = fields.Integer(compute='_compute_counts')
    change_order_count = fields.Integer(compute='_compute_counts')
    payment_certificate_count = fields.Integer(compute='_compute_counts')
    attachment_count = fields.Integer(compute='_compute_counts')

    _sql_constraints = [
        ('ipmo_agreement_no_uniq', 'unique(agreement_no)', 'Agreement number must be unique.'),
    ]

    def _get_tax_rate(self):
        param_value = self.env['ir.config_parameter'].sudo().get_param('ipmo_contract.tax_rate', '0')
        try:
            return float(param_value)
        except (TypeError, ValueError):
            return 0.0

    @api.depends('line_ids.line_amount')
    def _compute_amounts(self):
        for agreement in self:
            base_amount = sum(agreement.line_ids.mapped('line_amount'))
            tax_rate = agreement._get_tax_rate()
            tax_amount = base_amount * tax_rate / 100.0
            agreement.base_amount = base_amount
            agreement.tax_amount = tax_amount
            agreement.total_amount = base_amount + tax_amount

    @api.depends('amendment_ids', 'change_order_ids', 'payment_certificate_ids')
    def _compute_counts(self):
        for agreement in self:
            agreement.amendment_count = len(agreement.amendment_ids)
            agreement.change_order_count = len(agreement.change_order_ids)
            agreement.payment_certificate_count = len(agreement.payment_certificate_ids)
            agreement.attachment_count = self.env['ipmo.attachment'].search_count([
                ('res_model', '=', 'ipmo.agreement'),
                ('res_id', '=', agreement.id),
            ])

    @api.constrains('start_date', 'end_date')
    def _check_dates(self):
        for agreement in self:
            if agreement.start_date and agreement.end_date and agreement.end_date < agreement.start_date:
                raise ValidationError('End date must be on or after start date.')

    def _validate_status_transition(self, new_status):
        allowed_transitions = {
            'draft': ['active'],
            'active': ['closed', 'terminated'],
            'closed': [],
            'terminated': [],
        }
        for agreement in self:
            current_status = agreement.status
            if new_status == current_status:
                continue
            if new_status not in allowed_transitions.get(current_status, []):
                raise ValidationError('Invalid status transition for agreement.')

    def write(self, vals):
        if 'status' in vals:
            self._validate_status_transition(vals['status'])
            if vals['status'] == 'active' and not self.env.user.has_group('ipmo_contract.group_contract_approver'):
                raise ValidationError('Only Contract Approvers can activate agreements.')
        protected_fields = set(vals) - {'status'}
        for agreement in self:
            if agreement.status != 'draft' and protected_fields:
                raise ValidationError('Only draft agreements can be edited.')
        return super().write(vals)

    def action_activate(self):
        self.write({'status': 'active'})

    def action_close(self):
        self.write({'status': 'closed'})

    def action_terminate(self):
        self.write({'status': 'terminated'})

    def action_view_amendments(self):
        action = self.env.ref('ipmo_contract.action_ipmo_agreement_amendment').read()[0]
        action['domain'] = [('agreement_id', '=', self.id)]
        return action

    def action_view_change_orders(self):
        action = self.env.ref('ipmo_contract.action_ipmo_change_order').read()[0]
        action['domain'] = [('agreement_id', '=', self.id)]
        return action

    def action_view_payment_certificates(self):
        action = self.env.ref('ipmo_contract.action_ipmo_payment_certificate').read()[0]
        action['domain'] = [('agreement_id', '=', self.id)]
        return action

    def action_view_attachments(self):
        action = self.env.ref('ipmo_contract.action_ipmo_attachment').read()[0]
        action['domain'] = [
            ('res_model', '=', 'ipmo.agreement'),
            ('res_id', '=', self.id),
        ]
        return action
