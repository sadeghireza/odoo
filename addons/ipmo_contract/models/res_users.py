from odoo import fields, models


class ResUsers(models.Model):
    _inherit = 'res.users'

    allowed_project_ids = fields.Many2many(
        'project.project',
        'ipmo_user_project_rel',
        'user_id',
        'project_id',
        string='Allowed Projects',
    )
