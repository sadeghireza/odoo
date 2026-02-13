import logging
from datetime import timedelta

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


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
        _logger.info(
            "workflow_sla_event=create_timer instance_id=%s state_id=%s rule_id=%s due_date=%s",
            instance.id,
            state.id,
            rule.id,
            due_date,
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
            _logger.info(
                "workflow_sla_event=close_timer instance_id=%s state_id=%s count=%s",
                instance.id,
                state.id,
                len(timers),
            )
        return True

    def check_timers(self):
        now = fields.Datetime.now()
        timers = self.env["workflow.sla.timer"].search(
            [("status", "=", "pending"), ("due_date", "<=", now)]
        )
        if timers:
            _logger.info("workflow_sla_event=check_timers due_count=%s", len(timers))
        for timer in timers:
            timer.status = "breached"
            self._escalate(timer)

    def _escalate(self, timer):
        rule = timer.rule_id
        instance = timer.instance_id
        if instance.status != "running":
            timer.status = "escalated"
            return False
        _logger.info(
            "workflow_sla_event=escalate instance_id=%s state_id=%s rule_id=%s action=%s",
            instance.id,
            instance.state_id.id,
            rule.id,
            rule.escalation_action,
        )
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
        _logger.info(
            "workflow_sla_event=reassign_workitems instance_id=%s state_id=%s users=%s pending=%s",
            instance.id,
            instance.state_id.id,
            len(users),
            len(pending),
        )
        vals_list = []
        for user in users:
            for item in pending:
                vals_list.append(
                    {
                        "instance_id": item.instance_id.id,
                        "state_id": item.state_id.id,
                        "user_id": user.id,
                        "status": "pending",
                        "sequence": item.sequence,
                        "assigned_date": item.assigned_date,
                    }
                )
        if vals_list:
            self.env["workflow.workitem"].create(vals_list)
        return True
