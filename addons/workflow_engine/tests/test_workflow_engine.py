from datetime import timedelta

from odoo import fields
from odoo.tests.common import TransactionCase


class TestWorkflowEngine(TransactionCase):
    def setUp(self):
        super().setUp()
        self.process = self.env.ref("workflow_engine.workflow_process_contract_demo")
        self.version = self.env.ref("workflow_engine.workflow_version_contract_demo_v1")
        self.contract = self.env["workflow.contract.demo"].create({"name": "Test"})
        group_admin = self.env.ref("workflow_engine.group_workflow_admin")
        group_operator = self.env.ref("workflow_engine.group_workflow_operator")
        self.env.user.groups_id |= group_admin
        self.env.user.groups_id |= group_operator
        self.admin_user = self.env.ref("base.user_admin")
        self.root_user = self.env.ref("base.user_root")
        self.admin_user.groups_id |= group_admin
        self.admin_user.groups_id |= group_operator
        self.root_user.groups_id |= group_admin
        self.root_user.groups_id |= group_operator

    def test_basic_flow(self):
        instance = self.env["workflow.engine"].start_for_record(self.contract, "contract_demo")
        self.assertEqual(instance.state_id.code, "review")
        workitem = instance.workitem_ids.filtered(lambda w: w.status == "pending")
        workitem = workitem[:1]
        workitem.with_user(workitem.user_id).action_approve()
        self.assertEqual(instance.state_id.code, "done")
        self.assertEqual(instance.status, "done")

    def _build_parallel_process(self):
        process = self.env["workflow.process"].create({"name": "Parallel", "code": "parallel_demo"})
        version = self.env["workflow.process.version"].create(
            {"name": "Parallel v1", "process_id": process.id, "version": 1, "state": "active"}
        )
        start = self.env["workflow.state"].create(
            {"name": "Start", "code": "start", "version_id": version.id, "type": "start", "approval_mode": "none"}
        )
        review = self.env["workflow.state"].create(
            {
                "name": "Review",
                "code": "review",
                "version_id": version.id,
                "type": "task",
                "approval_mode": "parallel",
                "parallel_policy": "all",
            }
        )
        done = self.env["workflow.state"].create(
            {"name": "Done", "code": "done", "version_id": version.id, "type": "end", "approval_mode": "none"}
        )
        self.env["workflow.transition"].create(
            {
                "name": "to_review",
                "version_id": version.id,
                "source_state_id": start.id,
                "dest_state_id": review.id,
                "trigger": "auto",
            }
        )
        self.env["workflow.transition"].create(
            {
                "name": "to_done",
                "version_id": version.id,
                "source_state_id": review.id,
                "dest_state_id": done.id,
                "trigger": "auto",
            }
        )
        for index, user in enumerate([self.admin_user, self.root_user], start=1):
            self.env["workflow.role.rule"].create(
                {
                    "name": "Reviewer %s" % index,
                    "state_id": review.id,
                    "sequence": index,
                    "assignment_type": "user",
                    "user_id": user.id,
                }
            )
        return process

    def test_parallel_approvals(self):
        process = self._build_parallel_process()
        instance = self.env["workflow.engine"].start_for_record(self.contract, process.code)
        self.assertEqual(instance.state_id.code, "review")
        workitems = instance.workitem_ids.filtered(lambda w: w.status == "pending")
        for item in workitems:
            item.with_user(item.user_id).action_approve()
        self.assertEqual(instance.state_id.code, "done")

    def test_rejection_loop(self):
        process = self.env["workflow.process"].create({"name": "Reject", "code": "reject_demo"})
        version = self.env["workflow.process.version"].create(
            {"name": "Reject v1", "process_id": process.id, "version": 1, "state": "active"}
        )
        start = self.env["workflow.state"].create(
            {"name": "Start", "code": "start", "version_id": version.id, "type": "start", "approval_mode": "none"}
        )
        review = self.env["workflow.state"].create(
            {"name": "Review", "code": "review", "version_id": version.id, "type": "task", "approval_mode": "sequential"}
        )
        self.env["workflow.transition"].create(
            {
                "name": "to_review",
                "version_id": version.id,
                "source_state_id": start.id,
                "dest_state_id": review.id,
                "trigger": "manual",
            }
        )
        self.env["workflow.transition"].create(
            {
                "name": "reject",
                "version_id": version.id,
                "source_state_id": review.id,
                "dest_state_id": start.id,
                "transition_type": "reject",
                "trigger": "auto",
            }
        )
        self.env["workflow.role.rule"].create(
            {"name": "Reviewer", "state_id": review.id, "assignment_type": "user", "user_id": self.admin_user.id}
        )
        instance = self.env["workflow.engine"].start_for_record(self.contract, process.code)
        instance.action_trigger()
        workitem = instance.workitem_ids.filtered(lambda w: w.status == "pending")[:1]
        workitem.with_user(workitem.user_id).action_reject()
        self.assertEqual(instance.state_id.code, "start")

    def test_sla_escalation(self):
        process = self.env["workflow.process"].create({"name": "SLA", "code": "sla_demo"})
        version = self.env["workflow.process.version"].create(
            {"name": "SLA v1", "process_id": process.id, "version": 1, "state": "active"}
        )
        start = self.env["workflow.state"].create(
            {"name": "Start", "code": "start", "version_id": version.id, "type": "start", "approval_mode": "none"}
        )
        review = self.env["workflow.state"].create(
            {"name": "Review", "code": "review", "version_id": version.id, "type": "task", "approval_mode": "sequential"}
        )
        rule = self.env["workflow.sla.rule"].create(
            {"name": "Fast", "state_id": review.id, "duration_hours": 0.0, "escalation_action": "notify"}
        )
        review.sla_rule_id = rule.id
        self.env["workflow.transition"].create(
            {
                "name": "to_review",
                "version_id": version.id,
                "source_state_id": start.id,
                "dest_state_id": review.id,
                "trigger": "auto",
            }
        )
        self.env["workflow.role.rule"].create(
            {"name": "Reviewer", "state_id": review.id, "assignment_type": "user", "user_id": self.admin_user.id}
        )
        instance = self.env["workflow.engine"].start_for_record(self.contract, process.code)
        self.env["workflow.sla.service"].check_timers()
        timer = self.env["workflow.sla.timer"].search([("instance_id", "=", instance.id)], limit=1)
        self.assertEqual(timer.status, "escalated")

    def test_delegation_assignment(self):
        process = self.env["workflow.process"].create({"name": "Delegation", "code": "delegation_demo"})
        version = self.env["workflow.process.version"].create(
            {"name": "Delegation v1", "process_id": process.id, "version": 1, "state": "active"}
        )
        start = self.env["workflow.state"].create(
            {"name": "Start", "code": "start", "version_id": version.id, "type": "start", "approval_mode": "none"}
        )
        review = self.env["workflow.state"].create(
            {"name": "Review", "code": "review", "version_id": version.id, "type": "task", "approval_mode": "sequential"}
        )
        self.env["workflow.transition"].create(
            {
                "name": "to_review",
                "version_id": version.id,
                "source_state_id": start.id,
                "dest_state_id": review.id,
                "trigger": "auto",
            }
        )
        assignee = self.admin_user
        delegate = self.root_user
        self.env["workflow.role.rule"].create(
            {"name": "Reviewer", "state_id": review.id, "assignment_type": "user", "user_id": assignee.id}
        )
        now = fields.Datetime.now()
        self.env["workflow.delegation"].create(
            {
                "user_id": assignee.id,
                "delegate_id": delegate.id,
                "date_from": now - timedelta(days=1),
                "date_to": now + timedelta(days=1),
            }
        )
        instance = self.env["workflow.engine"].start_for_record(self.contract, process.code)
        workitem = instance.workitem_ids.filtered(lambda w: w.status == "pending")[:1]
        self.assertEqual(workitem.user_id.id, delegate.id)

    def test_dynamic_role_rule(self):
        process = self.env["workflow.process"].create({"name": "Dynamic", "code": "dynamic_demo"})
        version = self.env["workflow.process.version"].create(
            {"name": "Dynamic v1", "process_id": process.id, "version": 1, "state": "active"}
        )
        start = self.env["workflow.state"].create(
            {"name": "Start", "code": "start", "version_id": version.id, "type": "start", "approval_mode": "none"}
        )
        review = self.env["workflow.state"].create(
            {"name": "Review", "code": "review", "version_id": version.id, "type": "task", "approval_mode": "sequential"}
        )
        self.env["workflow.transition"].create(
            {
                "name": "to_review",
                "version_id": version.id,
                "source_state_id": start.id,
                "dest_state_id": review.id,
                "trigger": "auto",
            }
        )
        self.env["workflow.role.rule"].create(
            {
                "name": "Dynamic Reviewer",
                "state_id": review.id,
                "assignment_type": "dynamic",
                "expression": "[%s]" % self.admin_user.id,
            }
        )
        instance = self.env["workflow.engine"].start_for_record(self.contract, process.code)
        workitem = instance.workitem_ids.filtered(lambda w: w.status == "pending")[:1]
        self.assertEqual(workitem.user_id.id, self.admin_user.id)
