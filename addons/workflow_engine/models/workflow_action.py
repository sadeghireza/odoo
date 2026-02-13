from odoo import api, fields, models
from odoo.exceptions import ValidationError


class WorkflowAction(models.Model):
    _name = "workflow.action"
    _description = "Workflow Action"
    _order = "sequence, id"

    state_id = fields.Many2one("workflow.state", required=True, ondelete="cascade")
    company_id = fields.Many2one(
        "res.company",
        related="state_id.company_id",
        store=True,
        readonly=True,
    )
    sequence = fields.Integer(default=10)
    action_type = fields.Selection(
        [
            ("set_field", "Set Field"),
            ("add_message", "Add Message"),
            ("change_status", "Change Status"),
        ],
        required=True,
        default="set_field",
    )
    field_name = fields.Char()
    field_value = fields.Char()
    message_body = fields.Text()
    status_value = fields.Char()

    @api.constrains("action_type", "field_name", "field_value", "message_body", "status_value")
    def _check_action_fields(self):
        for action in self:
            if action.action_type == "set_field":
                if not action.field_name:
                    raise ValidationError("Please set a field name for the action.")
                if action.field_value in (False, None, ""):
                    raise ValidationError("Please set a value for the field action.")
            if action.action_type == "add_message" and not action.message_body:
                raise ValidationError("Please provide a message body.")
            if action.action_type == "change_status" and not action.status_value:
                raise ValidationError("Please choose a status value.")
