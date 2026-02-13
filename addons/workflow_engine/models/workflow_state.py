from odoo import api, fields, models
from odoo.exceptions import ValidationError
from odoo.tools.safe_eval import safe_eval


class WorkflowState(models.Model):
    _name = "workflow.state"
    _description = "Workflow State"
    _order = "sequence, id"

    name = fields.Char(required=True)
    code = fields.Char(required=True, index=True)
    version_id = fields.Many2one("workflow.process.version", required=True, ondelete="cascade")
    sequence = fields.Integer(default=10)
    type = fields.Selection(
        [("start", "Start"), ("task", "Task"), ("condition", "Condition"), ("end", "End")],
        default="task",
        required=True,
    )
    approval_mode = fields.Selection(
        [("none", "None"), ("sequential", "Sequential"), ("parallel", "Parallel")],
        default="sequential",
        required=True,
    )
    parallel_policy = fields.Selection(
        [("all", "All"), ("any", "Any"), ("min", "Minimum")],
        default="all",
        required=True,
    )
    min_approvals = fields.Integer(default=1)
    role_rule_ids = fields.One2many("workflow.role.rule", "state_id", string="Role Rules")
    sla_rule_id = fields.Many2one("workflow.sla.rule", string="SLA Rule")
    allow_rework = fields.Boolean(default=True)
    ui_x = fields.Float(string="UI X")
    ui_y = fields.Float(string="UI Y")

    _sql_constraints = [
        (
            "workflow_state_code_uniq",
            "unique(version_id, code)",
            "State code must be unique per version.",
        ),
    ]


class WorkflowTransition(models.Model):
    _name = "workflow.transition"
    _description = "Workflow Transition"
    _order = "sequence, id"

    name = fields.Char(required=True)
    version_id = fields.Many2one("workflow.process.version", required=True, ondelete="cascade")
    source_state_id = fields.Many2one("workflow.state", required=True, ondelete="cascade")
    dest_state_id = fields.Many2one("workflow.state", required=True, ondelete="cascade")
    sequence = fields.Integer(default=10)
    transition_type = fields.Selection(
        [("normal", "Normal"), ("reject", "Reject"), ("rework", "Rework")],
        default="normal",
        required=True,
    )
    trigger = fields.Selection(
        [("manual", "Manual"), ("auto", "Auto")],
        default="manual",
        required=True,
    )
    branch_expression = fields.Text(help="Python expression for conditional branch evaluation")
    branch_is_else = fields.Boolean(default=False, help="Marks this branch as the ELSE path")

    @api.constrains("source_state_id", "branch_expression", "branch_is_else")
    def _check_branch_rules(self):
        for transition in self:
            state_type = transition.source_state_id.type
            if state_type == "condition":
                if transition.branch_is_else and transition.branch_expression:
                    raise ValidationError("ELSE branch cannot have an expression.")
                if not transition.branch_is_else and not transition.branch_expression:
                    raise ValidationError("Conditional branch must have an expression.")
                if transition.branch_is_else:
                    duplicate = self.search_count(
                        [
                            ("id", "!=", transition.id),
                            ("source_state_id", "=", transition.source_state_id.id),
                            ("branch_is_else", "=", True),
                        ]
                    )
                    if duplicate:
                        raise ValidationError("Only one ELSE branch is allowed per condition node.")
            else:
                if transition.branch_is_else or transition.branch_expression:
                    raise ValidationError("Branch expressions are only allowed from condition nodes.")


class WorkflowRoleRule(models.Model):
    _name = "workflow.role.rule"
    _description = "Workflow Role Rule"
    _order = "sequence, id"

    name = fields.Char(required=True)
    state_id = fields.Many2one("workflow.state", required=True, ondelete="cascade")
    sequence = fields.Integer(default=10)
    assignment_type = fields.Selection(
        [("user", "User"), ("group", "Group"), ("dynamic", "Dynamic")],
        required=True,
        default="user",
    )
    user_id = fields.Many2one("res.users")
    group_id = fields.Many2one("res.groups")
    expression = fields.Text(help="Python expression returning users or user ids")

    def resolve_users(self, eval_context):
        self.ensure_one()
        if self.assignment_type == "user" and self.user_id:
            return self.user_id
        if self.assignment_type == "group" and self.group_id:
            return self.group_id.users
        if self.assignment_type == "dynamic" and self.expression:
            result = safe_eval(self.expression, eval_context)
            if isinstance(result, models.BaseModel):
                return result
            if isinstance(result, (list, tuple, set)):
                return self.env["res.users"].browse(list(result))
        return self.env["res.users"]
