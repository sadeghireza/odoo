from odoo import api, fields, models
from odoo.exceptions import ValidationError


class IpmoAgreementAmendment(models.Model):
    _name = 'ipmo.agreement.amendment'
    _description = 'Agreement Amendment'
    _order = 'amendment_no desc'

    agreement_id = fields.Many2one('ipmo.agreement', required=True, ondelete='cascade')
    amendment_no = fields.Char(required=True)
    amendment_date = fields.Date(required=True)
    reason = fields.Text()
    delta_amount = fields.Monetary(required=True)
    delta_duration = fields.Integer(help='Duration change in days')
    status = fields.Selection(
        [('draft', 'Draft'), ('submitted', 'Submitted'), ('approved', 'Approved')],
        required=True,
        default='draft',
    )
    currency_id = fields.Many2one(related='agreement_id.currency_id', store=True, readonly=True)
    attachment_count = fields.Integer(compute='_compute_attachment_count')

    _sql_constraints = [
        ('ipmo_amendment_no_uniq', 'unique(agreement_id, amendment_no)', 'Amendment number must be unique per agreement.'),
    ]

    def _validate_status_transition(self, new_status):
        allowed_transitions = {
            'draft': ['submitted'],
            'submitted': ['approved'],
            'approved': [],
        }
        for amendment in self:
            current_status = amendment.status
            if new_status == current_status:
                continue
            if new_status not in allowed_transitions.get(current_status, []):
                raise ValidationError('Invalid status transition for amendment.')

    @api.depends()
    def _compute_attachment_count(self):
        for amendment in self:
            amendment.attachment_count = self.env['ipmo.attachment'].search_count([
                ('res_model', '=', 'ipmo.agreement.amendment'),
                ('res_id', '=', amendment.id),
            ])

    def write(self, vals):
        if 'status' in vals:
            self._validate_status_transition(vals['status'])
        protected_fields = set(vals) - {'status'}
        for amendment in self:
            if amendment.status != 'draft' and protected_fields:
                raise ValidationError('Only draft amendments can be edited.')
        return super().write(vals)

    def action_submit(self):
        self.write({'status': 'submitted'})

    def action_approve(self):
        self.write({'status': 'approved'})

    def action_view_attachments(self):
        action = self.env.ref('ipmo_contract.action_ipmo_attachment').read()[0]
        action['domain'] = [
            ('res_model', '=', 'ipmo.agreement.amendment'),
            ('res_id', '=', self.id),
        ]
        return action
