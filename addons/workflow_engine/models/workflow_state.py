import ast
import re

from odoo import api, fields, models
from odoo.exceptions import ValidationError
from odoo.tools.safe_eval import safe_eval


class SafeRecordProxy:
    """Expose only direct field access for condition evaluation."""

    def __init__(self, record):
        self._record = record

    def __getattribute__(self, name):
        if name == "_record":
            return object.__getattribute__(self, name)
        if name.startswith("_"):
            raise AttributeError("Access to private attributes is not allowed.")
        return object.__getattribute__(self, name)

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError("Access to private attributes is not allowed.")
        record = object.__getattribute__(self, "_record")
        if name not in record._fields:
            raise AttributeError("Only direct record fields are allowed in condition expressions.")
        return record[name]


_ALLOWED_COMPARE_OPS = (ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE)
_ALLOWED_BOOL_OPS = (ast.And, ast.Or)
_ALLOWED_CONSTANTS = (bool,)


class _ConditionExpressionValidator(ast.NodeVisitor):
    def _fail(self, message):
        raise ValidationError(message)

    def visit(self, node):
        if not isinstance(
            node,
            (
                ast.Expression,
                ast.BoolOp,
                ast.UnaryOp,
                ast.Compare,
                ast.Name,
                ast.Attribute,
                ast.Constant,
            ),
        ):
            self._fail("Unsupported syntax in condition expression.")
        return super().visit(node)

    def visit_Expression(self, node):
        self.visit(node.body)

    def visit_BoolOp(self, node):
        if not isinstance(node.op, _ALLOWED_BOOL_OPS):
            self._fail("Only 'and'/'or' boolean operators are allowed.")
        for value in node.values:
            self.visit(value)

    def visit_UnaryOp(self, node):
        if not isinstance(node.op, ast.Not):
            self._fail("Only 'not' unary operator is allowed.")
        self.visit(node.operand)

    def visit_Compare(self, node):
        for op in node.ops:
            if not isinstance(op, _ALLOWED_COMPARE_OPS):
                self._fail("Only comparison operators ==, !=, <, <=, >, >= are allowed.")
        self.visit(node.left)
        for comparator in node.comparators:
            self.visit(comparator)

    def visit_Name(self, node):
        if node.id not in ("record", "user", "True", "False"):
            self._fail("Only 'record', 'user.id', and boolean literals are allowed.")

    def visit_Attribute(self, node):
        if isinstance(node.value, ast.Attribute):
            self._fail("Chained attribute access is not allowed in condition expressions.")
        if isinstance(node.value, ast.Name) and node.value.id == "record":
            if node.attr.startswith("_"):
                self._fail("Access to private attributes is not allowed.")
            return
        if (
            isinstance(node.value, ast.Name)
            and node.value.id == "user"
            and node.attr == "id"
        ):
            return
        self._fail("Only direct record fields and user.id are allowed in condition expressions.")

    def visit_Constant(self, node):
        if not isinstance(node.value, _ALLOWED_CONSTANTS):
            self._fail("Only boolean literals True/False are allowed.")

    def visit_Call(self, node):
        self._fail("Function calls are not allowed in condition expressions.")

    def visit_Subscript(self, node):
        self._fail("Subscript access is not allowed in condition expressions.")

    def visit_List(self, node):
        self._fail("List literals are not allowed in condition expressions.")

    def visit_Tuple(self, node):
        self._fail("Tuple literals are not allowed in condition expressions.")

    def visit_Set(self, node):
        self._fail("Set literals are not allowed in condition expressions.")

    def visit_Dict(self, node):
        self._fail("Dict literals are not allowed in condition expressions.")

    def visit_BinOp(self, node):
        self._fail("Binary operators are not allowed in condition expressions.")

    def visit_Lambda(self, node):
        self._fail("Lambda expressions are not allowed in condition expressions.")

    def visit_IfExp(self, node):
        self._fail("Conditional expressions are not allowed in condition expressions.")

    def visit_GeneratorExp(self, node):
        self._fail("Comprehensions are not allowed in condition expressions.")

    def visit_ListComp(self, node):
        self._fail("Comprehensions are not allowed in condition expressions.")

    def visit_SetComp(self, node):
        self._fail("Comprehensions are not allowed in condition expressions.")

    def visit_DictComp(self, node):
        self._fail("Comprehensions are not allowed in condition expressions.")


def validate_condition_expression(expression):
    if not expression:
        return
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError:
        raise ValidationError("Condition expression is invalid. Please correct the syntax.")
    _ConditionExpressionValidator().visit(tree)


class WorkflowState(models.Model):
    _name = "workflow.state"
    _description = "Workflow State"
    _order = "sequence, id"

    name = fields.Char(required=True)
    code = fields.Char(index=True)
    version_id = fields.Many2one("workflow.process.version", required=True, ondelete="cascade")
    company_id = fields.Many2one(
        "res.company",
        required=True,
        default=lambda self: self.env.company,
    )
    sequence = fields.Integer(default=10)
    type = fields.Selection(
        [
            ("start", "Start"),
            ("task", "Approval"),
            ("approval", "Approval"),
            ("manual", "Manual Task"),
            ("action", "Action"),
            ("condition", "Gateway (XOR)"),
            ("end", "End"),
        ],
        default="task",
        required=True,
    )
    end_type = fields.Selection(
        [
            ("success", "Success"),
            ("rejected", "Rejected"),
            ("cancelled", "Cancelled"),
        ]
    )
    approval_mode = fields.Selection(
        [("none", "None"), ("sequential", "Sequential"), ("parallel", "Parallel")],
        default="sequential",
        required=True,
    )
    parallel_policy = fields.Selection(
        [("all", "All Required"), ("any", "Any"), ("min", "Minimum Required")],
        default="all",
        required=True,
    )
    min_approvals = fields.Integer(default=1)
    role_rule_ids = fields.One2many("workflow.role.rule", "state_id", string="Role Rules")
    action_ids = fields.One2many("workflow.action", "state_id", string="Actions")
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

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get("company_id") and vals.get("version_id"):
                version = self.env["workflow.process.version"].browse(vals["version_id"])
                if version.exists():
                    vals["company_id"] = version.company_id.id
            if not vals.get("company_id"):
                vals["company_id"] = self.env.company.id
        return super().create(vals_list)

    def write(self, vals):
        if "version_id" in vals and "company_id" not in vals:
            version = self.env["workflow.process.version"].browse(vals["version_id"])
            if version.exists():
                vals["company_id"] = version.company_id.id
        return super().write(vals)

    @api.constrains("company_id", "version_id")
    def _check_company_matches_version(self):
        for state in self:
            if state.version_id and state.company_id != state.version_id.company_id:
                raise ValidationError("State company must match the workflow version company.")

    @api.constrains("type", "end_type")
    def _check_end_type(self):
        for state in self:
            if state.type == "end" and not state.end_type:
                raise ValidationError("Please select an end type for END states.")
            if state.type != "end" and state.end_type:
                raise ValidationError("End type can only be set on END states.")


class WorkflowTransition(models.Model):
    _name = "workflow.transition"
    _description = "Workflow Transition"
    _order = "sequence, id"

    name = fields.Char(required=True)
    code = fields.Char(index=True)
    version_id = fields.Many2one("workflow.process.version", required=True, ondelete="cascade")
    company_id = fields.Many2one(
        "res.company",
        related="version_id.company_id",
        store=True,
        readonly=True,
    )
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

    _sql_constraints = [
        (
            "workflow_transition_code_uniq",
            "unique(version_id, code)",
            "Transition code must be unique per version.",
        ),
    ]

    @api.model
    def _normalize_code(self, value):
        value = (value or "").strip().lower()
        value = re.sub(r"[^a-z0-9]+", "_", value)
        value = re.sub(r"_+", "_", value).strip("_")
        return value or "transition"

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get("code") and vals.get("name"):
                vals["code"] = self._normalize_code(vals["name"])
        return super().create(vals_list)

    @api.constrains("code")
    def _check_code(self):
        for transition in self:
            if not transition.code:
                raise ValidationError("Please set a transition code.")

    @api.constrains("source_state_id", "branch_expression", "branch_is_else")
    def _check_branch_rules(self):
        for transition in self:
            state_type = transition.source_state_id.type
            if state_type == "condition":
                if transition.branch_is_else and transition.branch_expression:
                    raise ValidationError("DEFAULT branch cannot have a condition.")
                if not transition.branch_is_else and not transition.branch_expression:
                    raise ValidationError("A TRUE branch requires a condition.")
                validate_condition_expression(transition.branch_expression)
                if transition.branch_is_else:
                    duplicate = self.search_count(
                        [
                            ("id", "!=", transition.id),
                            ("source_state_id", "=", transition.source_state_id.id),
                            ("branch_is_else", "=", True),
                        ]
                    )
                    if duplicate:
                        raise ValidationError("Only one DEFAULT branch is allowed per condition state.")
            else:
                if transition.branch_is_else or transition.branch_expression:
                    raise ValidationError("Conditions can only be set on branches from a Condition state.")
                validate_condition_expression(transition.branch_expression)


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

    @api.constrains("expression")
    def _check_expression(self):
        for rule in self:
            if rule.expression and "__" in rule.expression:
                raise ValidationError("Role rule expressions cannot access private attributes.")

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
