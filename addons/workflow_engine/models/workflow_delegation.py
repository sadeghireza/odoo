from odoo import api, fields, models


class WorkflowDelegation(models.Model):
    _name = "workflow.delegation"
    _description = "Workflow Delegation"
    _order = "date_from desc"

    user_id = fields.Many2one("res.users", required=True, ondelete="cascade", index=True)
    delegate_id = fields.Many2one("res.users", required=True, ondelete="cascade")
    date_from = fields.Datetime(required=True)
    date_to = fields.Datetime(required=True)
    active = fields.Boolean(default=True)
    reason = fields.Char()

    def get_delegate(self, user, date=None):
        date = date or fields.Datetime.now()
        delegation = self.search(
            [
                ("user_id", "=", user.id),
                ("active", "=", True),
                ("date_from", "<=", date),
                ("date_to", ">=", date),
            ],
            limit=1,
        )
        return delegation.delegate_id if delegation else self.env["res.users"]
