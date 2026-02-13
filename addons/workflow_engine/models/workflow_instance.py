from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError


class WorkflowInstance(models.Model):
    _name = "workflow.instance"
    _description = "Workflow Instance"
    _order = "create_date desc"

    name = fields.Char(required=True)
    process_id = fields.Many2one("workflow.process", required=True, ondelete="restrict")
    version_id = fields.Many2one("workflow.process.version", required=True, ondelete="restrict")
    res_model = fields.Char(required=True, index=True)
    res_id = fields.Integer(required=True, index=True)
    state_id = fields.Many2one("workflow.state", required=True, ondelete="restrict", index=True)
    status = fields.Selection(
        [("running", "Running"), ("done", "Done"), ("cancelled", "Cancelled")],
        default="running",
        index=True,
    )
    start_date = fields.Datetime(default=fields.Datetime.now, index=True)
    end_date = fields.Datetime(index=True)
    started_by = fields.Many2one("res.users", default=lambda self: self.env.user)

    workitem_ids = fields.One2many("workflow.workitem", "instance_id", string="Work Items")
    audit_ids = fields.One2many("workflow.audit", "instance_id", string="Audit Log")

    @api.constrains("res_model", "res_id", "status")
    def _check_single_running_instance(self):
        for instance in self.filtered(lambda i: i.status == "running"):
            duplicate = self.search_count(
                [
                    ("id", "!=", instance.id),
                    ("res_model", "=", instance.res_model),
                    ("res_id", "=", instance.res_id),
                    ("status", "=", "running"),
                ]
            )
            if duplicate:
                raise UserError("Only one running instance is allowed per record.")

    def action_trigger(self, transition_id=None, comment=None):
        self.ensure_one()
        return self.env["workflow.engine"].trigger_transition(
            self, transition_id=transition_id, comment=comment
        )

    def action_cancel(self, comment=None):
        self.ensure_one()
        if self.status != "running":
            return False
        self.status = "cancelled"
        self.end_date = fields.Datetime.now()
        self.env["workflow.engine"].log_action(
            self,
            action="cancel",
            from_state=self.state_id,
            to_state=False,
            comment=comment,
        )
        return True


class WorkflowWorkItem(models.Model):
    _name = "workflow.workitem"
    _description = "Workflow Work Item"
    _order = "sequence, id"

    instance_id = fields.Many2one("workflow.instance", required=True, ondelete="cascade", index=True)
    state_id = fields.Many2one("workflow.state", required=True, ondelete="restrict", index=True)
    user_id = fields.Many2one("res.users", required=True, ondelete="restrict", index=True)
    status = fields.Selection(
        [
            ("waiting", "Waiting"),
            ("pending", "Pending"),
            ("approved", "Approved"),
            ("rejected", "Rejected"),
            ("delegated", "Delegated"),
        ],
        default="pending",
        index=True,
    )
    sequence = fields.Integer(default=10)
    assigned_date = fields.Datetime(default=fields.Datetime.now)
    action_date = fields.Datetime()
    comment = fields.Text()

    def _ensure_user(self):
        if self.user_id != self.env.user:
            raise AccessError("Only the assigned user can act on this work item.")

    def action_approve(self, comment=None):
        self.ensure_one()
        self._ensure_user()
        return self.env["workflow.engine"].complete_workitem(
            self, approved=True, comment=comment
        )

    def action_reject(self, comment=None):
        self.ensure_one()
        self._ensure_user()
        return self.env["workflow.engine"].complete_workitem(
            self, approved=False, comment=comment
        )


class WorkflowAudit(models.Model):
    _name = "workflow.audit"
    _description = "Workflow Audit Trail"
    _order = "create_date desc"

    instance_id = fields.Many2one("workflow.instance", required=True, ondelete="cascade", index=True)
    action = fields.Char(required=True, index=True)
    user_id = fields.Many2one("res.users", required=True, ondelete="restrict", index=True)
    from_state_id = fields.Many2one("workflow.state", ondelete="restrict")
    to_state_id = fields.Many2one("workflow.state", ondelete="restrict")
    comment = fields.Text()
    payload = fields.Json()
    action_date = fields.Datetime(default=fields.Datetime.now, index=True)

    def write(self, vals):
        raise UserError("Audit log is immutable.")

    def unlink(self):
        raise UserError("Audit log is immutable.")
