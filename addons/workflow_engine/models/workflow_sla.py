from odoo import api, fields, models


class WorkflowSlaRule(models.Model):
    _name = "workflow.sla.rule"
    _description = "Workflow SLA Rule"

    name = fields.Char(required=True)
    state_id = fields.Many2one("workflow.state", required=True, ondelete="cascade")
    duration_hours = fields.Float(required=True, default=24.0)
    escalation_action = fields.Selection(
        [("notify", "Notify"), ("reassign", "Reassign")],
        default="notify",
        required=True,
    )
    escalation_user_id = fields.Many2one("res.users")
    escalation_group_id = fields.Many2one("res.groups")
    active = fields.Boolean(default=True)


class WorkflowSlaTimer(models.Model):
    _name = "workflow.sla.timer"
    _description = "Workflow SLA Timer"
    _order = "due_date asc"

    instance_id = fields.Many2one("workflow.instance", required=True, ondelete="cascade", index=True)
    state_id = fields.Many2one("workflow.state", required=True, ondelete="restrict", index=True)
    rule_id = fields.Many2one("workflow.sla.rule", required=True, ondelete="restrict")
    due_date = fields.Datetime(required=True, index=True)
    status = fields.Selection(
        [
            ("pending", "Pending"),
            ("breached", "Breached"),
            ("escalated", "Escalated"),
            ("cleared", "Cleared"),
        ],
        default="pending",
        index=True,
    )
    last_escalation_date = fields.Datetime()

    def mark_escalated(self):
        self.write({"status": "escalated", "last_escalation_date": fields.Datetime.now()})
