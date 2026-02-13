from odoo import api, fields, models


class IpmoAttachment(models.Model):
    _name = 'ipmo.attachment'
    _description = 'Attachment'
    _order = 'uploaded_at desc'

    res_model = fields.Char(required=True, index=True)
    res_id = fields.Integer(required=True, index=True)
    file = fields.Binary(required=True, attachment=True)
    uploaded_by = fields.Many2one('res.users', default=lambda self: self.env.user, required=True)
    uploaded_at = fields.Datetime(default=fields.Datetime.now, required=True)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('uploaded_by'):
                vals['uploaded_by'] = self.env.user.id
            if not vals.get('uploaded_at'):
                vals['uploaded_at'] = fields.Datetime.now()
        return super().create(vals_list)
