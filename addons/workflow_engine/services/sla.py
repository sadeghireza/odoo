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

    def check_timers(self, batch_limit=500):
        start = fields.Datetime.now()
        now = start
        timers = self.env["workflow.sla.timer"].search(
            [("status", "=", "pending"), ("due_date", "<=", now)],
            limit=batch_limit,
        )
        total = len(timers)
        breached = 0
        escalated = 0
        if timers:
            _logger.info("workflow_sla_event=check_timers due_count=%s", total)
        for timer in timers:
            timer.status = "breached"
            breached += 1
            if self._escalate(timer):
                escalated += 1
        duration_ms = int((fields.Datetime.now() - start).total_seconds() * 1000)
        _logger.info(
            "workflow_sla_event=check_timers_summary total=%s breached=%s escalated=%s duration_ms=%s",
            total,
            breached,
            escalated,
            duration_ms,
        )

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
        if rule.escalation_action in ("reassign", "escalate_to_role"):
            self._reassign_workitems(instance, rule)
        if rule.escalation_action == "auto_transition":
            self._auto_transition_instance(instance)
        timer.mark_escalated()
        return True

    def _auto_transition_instance(self, instance):
        record = self.env[instance.res_model].browse(instance.res_id)
        eval_context = self.env["workflow.engine"]._build_eval_context(instance, record)
        return self.env["workflow.engine"]._auto_transition(instance, eval_context)

    def _reassign_workitems(self, instance, rule):
        users = self.env["workflow.assignment"].compute_assignees(
            instance.state_id,
            self.env[instance.res_model].browse(instance.res_id),
            instance,
            self.env["workflow.engine"]._build_eval_context(
                instance, self.env[instance.res_model].browse(instance.res_id)
            ),
        )
        if not users:
            return False
        pending = instance.workitem_ids.filtered(
            lambda w: w.state_id == instance.state_id and w.status in ("pending", "waiting")
        )
        if not pending:
            return False
        existing = self.env["workflow.workitem"].search(
            [
                ("instance_id", "=", instance.id),
                ("state_id", "=", instance.state_id.id),
                ("user_id", "in", users.ids),
                ("status", "in", ("pending", "waiting")),
            ]
        )
        existing_pairs = {(item.user_id.id, item.state_id.id) for item in existing}
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
                key = (user.id, item.state_id.id)
                if key in existing_pairs:
                    continue
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
