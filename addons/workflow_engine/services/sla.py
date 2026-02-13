from datetime import timedelta

from odoo import api, fields, models


class WorkflowSlaService(models.AbstractModel):
    _name = "workflow.sla.service"
    _description = "Workflow SLA Service"

    """Manage SLA timers, escalation, and reassignment."""

    def create_timer(self, instance, state):
        rule = state.sla_rule_id
        if not rule or not rule.active:
            return False
        self.env["workflow.sla.timer"].search(
            [
                ("instance_id", "=", instance.id),
                ("state_id", "=", state.id),
                ("status", "=", "pending"),
            ]
        ).unlink()
        due_date = fields.Datetime.now() + timedelta(hours=rule.duration_hours)
        self.env["workflow.sla.timer"].create(
            {
                "instance_id": instance.id,
                "state_id": state.id,
                "rule_id": rule.id,
                "due_date": due_date,
            }
        )
        return True

    def close_timers(self, instance, state):
        timers = self.env["workflow.sla.timer"].search(
            [
                ("instance_id", "=", instance.id),
                ("state_id", "=", state.id),
                ("status", "=", "pending"),
            ]
        )
        if timers:
            timers.write({"status": "cleared"})
        return True

    def check_timers(self):
        now = fields.Datetime.now()
        timers = self.env["workflow.sla.timer"].search([("status", "=", "pending"), ("due_date", "<=", now)])
        for timer in timers:
            timer.status = "breached"
            self._escalate(timer)

    def _escalate(self, timer):
        rule = timer.rule_id
        instance = timer.instance_id
        if instance.status != "running":
            timer.status = "escalated"
            return False
        if rule.escalation_action == "notify":
            self.env["workflow.engine"].log_action(
                instance,
                action="sla_breach",
                from_state=instance.state_id,
                to_state=instance.state_id,
                comment="SLA breached",
                payload={"timer_id": timer.id},
            )
        if rule.escalation_action == "reassign":
            self._reassign_workitems(instance, rule)
        timer.mark_escalated()
        return True

    def _reassign_workitems(self, instance, rule):
        users = self.env["res.users"]
        if rule.escalation_user_id:
            users |= rule.escalation_user_id
        if rule.escalation_group_id:
            users |= rule.escalation_group_id.users
        if not users:
            return False
        pending = instance.workitem_ids.filtered(
            lambda w: w.state_id == instance.state_id and w.status in ("pending", "waiting")
        )
        for user in users:
            for item in pending:
                item.copy({"user_id": user.id, "status": "pending"})
        return True
