from odoo import api, fields, models


class WorkflowAssignment(models.AbstractModel):
    _name = "workflow.assignment"
    _description = "Workflow Assignment Service"

    """Resolve assignees based on role rules and delegation."""

    def compute_assignees(self, state, record, instance, eval_context):
        users = self.env["res.users"]
        rules = self.env["workflow.role.rule"].search(
            [("state_id", "=", state.id)], order="sequence, id"
        )
        if not rules:
            rules = self.env["workflow.role.rule"].sudo().search(
                [("state_id", "=", state.id)], order="sequence, id"
            )
        for rule in rules:
            users |= rule.resolve_users(eval_context)
        users = users.filtered(lambda u: u.active)
        return self._apply_delegation(users)

    def _apply_delegation(self, users):
        delegated = self.env["res.users"]
        delegation_model = self.env["workflow.delegation"]
        for user in users:
            delegate = delegation_model.get_delegate(user)
            delegated |= delegate if delegate else user
        return delegated
