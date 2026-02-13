from odoo import api, fields, models
from odoo.exceptions import ValidationError


class IpmoChangeOrder(models.Model):
    _name = 'ipmo.change.order'
    _description = 'Change Order'
    _order = 'co_no desc'

    agreement_id = fields.Many2one('ipmo.agreement', required=True, ondelete='cascade')
    co_no = fields.Char(required=True)
    co_date = fields.Date(required=True)
    reason = fields.Text()
    status = fields.Selection(
        [('draft', 'Draft'), ('submitted', 'Submitted'), ('approved', 'Approved')],
        required=True,
        default='draft',
    )
    line_ids = fields.One2many('ipmo.change.order.line', 'change_order_id', string='Lines')
    attachment_count = fields.Integer(compute='_compute_attachment_count')

    _sql_constraints = [
        ('ipmo_change_order_no_uniq', 'unique(agreement_id, co_no)', 'Change order number must be unique per agreement.'),
    ]

    def _validate_status_transition(self, new_status):
        allowed_transitions = {
            'draft': ['submitted'],
            'submitted': ['approved'],
            'approved': [],
        }
        for change_order in self:
            current_status = change_order.status
            if new_status == current_status:
                continue
            if new_status not in allowed_transitions.get(current_status, []):
                raise ValidationError('Invalid status transition for change order.')

    @api.depends()
    def _compute_attachment_count(self):
        for change_order in self:
            change_order.attachment_count = self.env['ipmo.attachment'].search_count([
                ('res_model', '=', 'ipmo.change.order'),
                ('res_id', '=', change_order.id),
            ])

    def write(self, vals):
        if 'status' in vals:
            self._validate_status_transition(vals['status'])
        protected_fields = set(vals) - {'status'}
        for change_order in self:
            if change_order.status != 'draft' and protected_fields:
                raise ValidationError('Only draft change orders can be edited.')
        return super().write(vals)

    def action_submit(self):
        self.write({'status': 'submitted'})

    def action_approve(self):
        self.write({'status': 'approved'})

    def action_view_attachments(self):
        action = self.env.ref('ipmo_contract.action_ipmo_attachment').read()[0]
        action['domain'] = [
            ('res_model', '=', 'ipmo.change.order'),
            ('res_id', '=', self.id),
        ]
        return action


class IpmoChangeOrderLine(models.Model):
    _name = 'ipmo.change.order.line'
    _description = 'Change Order Line'
    _order = 'id'

    change_order_id = fields.Many2one('ipmo.change.order', required=True, ondelete='cascade')
    agreement_line_id = fields.Many2one('ipmo.agreement.line', required=True, ondelete='restrict')
    delta_quantity = fields.Float()
    delta_unit_price = fields.Monetary()
    delta_lump_sum = fields.Monetary()
    delta_ceiling_amount = fields.Monetary()
    currency_id = fields.Many2one(related='agreement_line_id.currency_id', store=True, readonly=True)

    @api.constrains('delta_quantity', 'delta_unit_price', 'delta_lump_sum', 'delta_ceiling_amount')
    def _check_delta_values(self):
        for line in self:
            if not any([
                line.delta_quantity,
                line.delta_unit_price,
                line.delta_lump_sum,
                line.delta_ceiling_amount,
            ]):
                raise ValidationError('Change order lines require at least one delta value.')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('change_order_id'):
                change_order = self.env['ipmo.change.order'].browse(vals['change_order_id'])
                if change_order.status != 'draft':
                    raise ValidationError('Change order lines can only be added in draft change orders.')
        return super().create(vals_list)

    def write(self, vals):
        for line in self:
            if line.change_order_id.status != 'draft':
                raise ValidationError('Change order lines can only be edited in draft change orders.')
        return super().write(vals)

    def unlink(self):
        for line in self:
            if line.change_order_id.status != 'draft':
                raise ValidationError('Change order lines can only be removed in draft change orders.')
        return super().unlink()
