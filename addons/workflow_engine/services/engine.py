import logging

from odoo import api, fields, models
from odoo.exceptions import UserError
from odoo.tools.safe_eval import safe_eval

_logger = logging.getLogger(__name__)


class WorkflowEngine(models.AbstractModel):
    _name = "workflow.engine"
    _description = "Workflow Engine Service"

    """Core workflow execution service.

    This service orchestrates state transitions, work item completion,
    audit logging, and SLA integration.
    """

    def _build_eval_context(self, instance, record):
        return {
            "record": record,
            "instance": instance,
            "user": self.env.user,
            "time": fields.Datetime,
        }

    def _log_event(self, event, instance, **payload):
        _logger.info(
            "workflow_event=%s instance_id=%s process_id=%s version_id=%s state_id=%s payload=%s",
            event,
            instance.id,
            instance.process_id.id,
            instance.version_id.id,
            instance.state_id.id if instance.state_id else None,
            payload,
        )

    def start_for_record(self, record, process_code):
        if not record or not record.exists():
            raise UserError("Target record not found.")
        record.check_access("read")
        process = self.env["workflow.process"].search([("code", "=", process_code)], limit=1)
        version = process.active_version_id
        if process and not version:
            version = self.env["workflow.process.version"].search(
                [("process_id", "=", process.id), ("state", "=", "active")],
                order="version desc",
                limit=1,
            )
        if not process or not version:
            raise UserError("No active workflow version for process.")
        if process.target_model_id and process.target_model_id.model != record._name:
            raise UserError("Record model does not match workflow target model.")
        start_state = version.get_start_state()
        if not start_state:
            raise UserError("Workflow version has no start state.")
        instance = self.env["workflow.instance"].create(
            {
                "name": f"{process.name} - {record._name}({record.id})",
                "process_id": process.id,
                "version_id": version.id,
                "res_model": record._name,
                "res_id": record.id,
                "state_id": start_state.id,
            }
        )
        self._log_event("start", instance, res_model=record._name, res_id=record.id)
        self.log_action(
            instance,
            action="start",
            from_state=False,
            to_state=start_state,
            comment=None,
        )
        self._enter_state(instance, start_state)
        return instance

    def trigger_transition(self, instance, transition_id=None, comment=None):
        instance.ensure_one()
        if instance.status != "running":
            raise UserError("Workflow is not running.")
        if instance.state_id.type == "condition":
            record = self.env[instance.res_model].browse(instance.res_id)
            eval_context = self._build_eval_context(instance, record)
            return self._evaluate_condition_node(instance, instance.state_id, eval_context)
        transitions = instance.version_id.transition_ids.filtered(
            lambda t: t.source_state_id == instance.state_id and t.trigger == "manual"
        )
        if transition_id:
            transitions = transitions.filtered(lambda t: t.id == transition_id)
        if not transitions:
            raise UserError("No manual transition available.")
        for transition in transitions.sorted("sequence"):
            return self._move_to_state(instance, transition, comment=comment)
        raise UserError("No transition conditions matched.")

    def complete_workitem(self, workitem, approved=True, comment=None):
        workitem.ensure_one()
        if workitem.status not in ("pending", "waiting"):
            raise UserError("Work item already completed.")
        workitem.write(
            {
                "status": "approved" if approved else "rejected",
                "action_date": fields.Datetime.now(),
                "comment": comment,
            }
        )
        instance = workitem.instance_id
        self._log_event(
            "workitem_complete",
            instance,
            workitem_id=workitem.id,
            approved=approved,
        )
        action = "approve" if approved else "reject"
        self.log_action(
            instance,
            action=action,
            from_state=instance.state_id,
            to_state=instance.state_id,
            comment=comment,
            payload={"workitem_id": workitem.id},
        )
        if not approved:
            return self._handle_rejection(instance, comment=comment)
        return self._check_state_completion(instance)

    def _evaluate_condition_node(self, instance, state, eval_context):
        transitions = instance.version_id.transition_ids.filtered(
            lambda t: t.source_state_id == state
        ).sorted("sequence")
        else_transition = transitions.filtered(lambda t: t.branch_is_else)
        if not else_transition:
            raise UserError("Condition node must define an ELSE branch.")
        for transition in transitions.filtered(lambda t: not t.branch_is_else):
            if transition.branch_expression:
                try:
                    if safe_eval(transition.branch_expression, eval_context):
                        return self._move_to_state(instance, transition)
                except Exception:
                    _logger.exception(
                        "Condition evaluation failed. instance_id=%s transition_id=%s",
                        instance.id,
                        transition.id,
                    )
                    raise UserError("Condition evaluation failed.")
        return self._move_to_state(instance, else_transition[0])

    def _move_to_state(self, instance, transition, comment=None):
        from_state = instance.state_id
        to_state = transition.dest_state_id
        self.env["workflow.sla.service"].close_timers(instance, from_state)
        instance.state_id = to_state.id
        self._log_event(
            "transition",
            instance,
            transition_id=transition.id,
            from_state_id=from_state.id if from_state else None,
            to_state_id=to_state.id if to_state else None,
        )
        self.log_action(
            instance,
            action="transition",
            from_state=from_state,
            to_state=to_state,
            comment=comment,
            payload={"transition_id": transition.id},
        )
        self._enter_state(instance, to_state)
        return True

    def _enter_state(self, instance, state):
        record = self.env[instance.res_model].browse(instance.res_id)
        eval_context = self._build_eval_context(instance, record)
        if state.type == "condition":
            return self._evaluate_condition_node(instance, state, eval_context)
        assignment = self.env["workflow.assignment"].compute_assignees(
            state, record, instance, eval_context
        )
        if state.type == "end":
            instance.status = "done"
            instance.end_date = fields.Datetime.now()
            self._log_event("complete", instance)
            self.log_action(
                instance,
                action="complete",
                from_state=state,
                to_state=False,
                comment=None,
            )
            return True
        if state.approval_mode != "none":
            if not assignment:
                raise UserError("No assignees resolved for approval state.")
            self._create_workitems(instance, state, assignment)
        else:
            self._auto_transition(instance, eval_context)
        self.env["workflow.sla.service"].create_timer(instance, state)
        return True

    def _auto_transition(self, instance, eval_context):
        if instance.state_id.type == "condition":
            return self._evaluate_condition_node(instance, instance.state_id, eval_context)
        transitions = instance.version_id.transition_ids.filtered(
            lambda t: t.source_state_id == instance.state_id and t.trigger == "auto"
        ).sorted("sequence")
        for transition in transitions:
            return self._move_to_state(instance, transition)
        return False

    def _create_workitems(self, instance, state, assignees):
        vals_list = []
        if state.approval_mode == "sequential":
            for index, user in enumerate(assignees, start=1):
                vals_list.append(
                    {
                        "instance_id": instance.id,
                        "state_id": state.id,
                        "user_id": user.id,
                        "status": "pending" if index == 1 else "waiting",
                        "sequence": index,
                    }
                )
        else:
            for index, user in enumerate(assignees, start=1):
                vals_list.append(
                    {
                        "instance_id": instance.id,
                        "state_id": state.id,
                        "user_id": user.id,
                        "status": "pending",
                        "sequence": index,
                    }
                )
        self.env["workflow.workitem"].create(vals_list)

    def _check_state_completion(self, instance):
        state = instance.state_id
        if state.approval_mode == "parallel":
            return self._evaluate_parallel_completion(instance)
        if state.approval_mode == "sequential":
            return self._activate_next_sequential(instance)
        record = self.env[instance.res_model].browse(instance.res_id)
        return self._auto_transition(instance, self._build_eval_context(instance, record))

    def _evaluate_parallel_completion(self, instance):
        state = instance.state_id
        WorkItem = self.env["workflow.workitem"]
        base_domain = [("instance_id", "=", instance.id), ("state_id", "=", state.id)]
        rejected_count = WorkItem.search_count(base_domain + [("status", "=", "rejected")])
        if rejected_count:
            return self._handle_rejection(instance)
        approved_count = WorkItem.search_count(base_domain + [("status", "=", "approved")])
        if state.parallel_policy == "any" and approved_count:
            record = self.env[instance.res_model].browse(instance.res_id)
            return self._auto_transition(instance, self._build_eval_context(instance, record))
        if state.parallel_policy == "min" and approved_count >= state.min_approvals:
            record = self.env[instance.res_model].browse(instance.res_id)
            return self._auto_transition(instance, self._build_eval_context(instance, record))
        if state.parallel_policy == "all":
            total_count = WorkItem.search_count(base_domain)
            if approved_count and approved_count == total_count:
                record = self.env[instance.res_model].browse(instance.res_id)
                return self._auto_transition(instance, self._build_eval_context(instance, record))
        pending_count = WorkItem.search_count(base_domain + [("status", "in", ("pending", "waiting"))])
        if pending_count:
            return False
        return False

    def _activate_next_sequential(self, instance):
        state = instance.state_id
        WorkItem = self.env["workflow.workitem"]
        base_domain = [("instance_id", "=", instance.id), ("state_id", "=", state.id)]
        pending_count = WorkItem.search_count(base_domain + [("status", "=", "pending")])
        if pending_count:
            return False
        waiting = WorkItem.search(base_domain + [("status", "=", "waiting")], order="sequence", limit=1)
        if waiting:
            waiting.status = "pending"
            return False
        record = self.env[instance.res_model].browse(instance.res_id)
        return self._auto_transition(instance, self._build_eval_context(instance, record))

    def _handle_rejection(self, instance, comment=None):
        Transition = self.env["workflow.transition"]
        transitions = Transition.search(
            [
                ("version_id", "=", instance.version_id.id),
                ("source_state_id", "=", instance.state_id.id),
                ("transition_type", "=", "reject"),
            ],
            order="sequence",
            limit=1,
        )
        if not transitions:
            raise UserError("No rejection transition configured.")
        return self._move_to_state(instance, transitions, comment=comment)

    def log_action(self, instance, action, from_state, to_state, comment=None, payload=None):
        self.env["workflow.audit"].sudo().create(
            {
                "instance_id": instance.id,
                "action": action,
                "user_id": self.env.user.id,
                "from_state_id": from_state.id if from_state else False,
                "to_state_id": to_state.id if to_state else False,
                "comment": comment,
                "payload": payload or {},
            }
        )
