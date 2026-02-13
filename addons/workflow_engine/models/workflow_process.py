from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools.safe_eval import safe_eval

from odoo.addons.workflow_engine.models.workflow_state import (
    SafeRecordProxy,
    validate_condition_expression,
)


class WorkflowProcess(models.Model):
    _name = "workflow.process"
    _description = "Workflow Process"

    name = fields.Char(required=True)
    code = fields.Char(required=True, index=True)
    company_id = fields.Many2one(
        "res.company",
        required=True,
        default=lambda self: self.env.company,
    )
    target_model_id = fields.Many2one(
        "ir.model",
        string="Target Model",
        ondelete="set null",
        help="Model that this process is designed for.",
    )
    active = fields.Boolean(default=True)
    version_ids = fields.One2many("workflow.process.version", "process_id", string="Versions")
    active_version_id = fields.Many2one(
        "workflow.process.version",
        string="Active Version",
        domain="[('process_id', '=', id), ('state', '=', 'active')]",
    )

    _sql_constraints = [
        ("workflow_process_code_uniq", "unique(code)", "Process code must be unique."),
    ]


class WorkflowProcessVersion(models.Model):
    _name = "workflow.process.version"
    _description = "Workflow Process Version"
    _order = "process_id, version desc"

    name = fields.Char(required=True)
    process_id = fields.Many2one("workflow.process", required=True, ondelete="cascade")
    company_id = fields.Many2one(
        "res.company",
        required=True,
        default=lambda self: self.env.company,
    )
    version = fields.Integer(required=True, default=1)
    state = fields.Selection(
        [("draft", "Draft"), ("active", "Active"), ("retired", "Retired")],
        default="draft",
        required=True,
        index=True,
    )
    state_ids = fields.One2many("workflow.state", "version_id", string="States")
    transition_ids = fields.One2many("workflow.transition", "version_id", string="Transitions")

    _sql_constraints = [
        (
            "workflow_process_version_uniq",
            "unique(process_id, version)",
            "Version number must be unique per process.",
        ),
    ]

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get("company_id") and vals.get("process_id"):
                process = self.env["workflow.process"].browse(vals["process_id"])
                if process.exists():
                    vals["company_id"] = process.company_id.id
            if not vals.get("company_id"):
                vals["company_id"] = self.env.company.id
        return super().create(vals_list)

    def write(self, vals):
        if vals.get("state") == "active":
            for version in self:
                version.validate_before_activation()
        if "process_id" in vals and "company_id" not in vals:
            process = self.env["workflow.process"].browse(vals["process_id"])
            if process.exists():
                vals["company_id"] = process.company_id.id
        return super().write(vals)

    @api.constrains("company_id", "process_id")
    def _check_company_matches_process(self):
        for version in self:
            if version.process_id and version.company_id != version.process_id.company_id:
                raise ValidationError("Version company must match the process company.")

    def get_start_state(self):
        self.ensure_one()
        start_state = self.state_ids.filtered(lambda s: s.type == "start")
        if start_state:
            return start_state.sorted("sequence")[0]
        return self.state_ids.sorted("sequence")[:1]

    def validate_before_activation(self):
        self.ensure_one()
        states = self.state_ids
        transitions = self.transition_ids
        start_states = states.filtered(lambda s: s.type == "start")
        end_states = states.filtered(lambda s: s.type == "end")

        if not start_states:
            raise ValidationError("Please add a START state before activation.")
        if len(start_states) != 1:
            raise ValidationError("Please keep exactly one START state in this version.")
        if not end_states:
            raise ValidationError("Please add at least one END state before activation.")
        missing_end_type = end_states.filtered(lambda s: not s.end_type)
        if missing_end_type:
            names = ", ".join(missing_end_type.mapped("name"))
            raise ValidationError(
                "Please set an end type for END states: %s." % names
            )

        outgoing = {}
        for transition in transitions:
            outgoing.setdefault(transition.source_state_id.id, []).append(transition)

        for state in states.filtered(lambda s: s.type != "end"):
            if not outgoing.get(state.id):
                raise ValidationError(
                    "State '%s' needs at least one outgoing transition." % state.name
                )

        for state in states.filtered(lambda s: s.type == "condition"):
            branches = outgoing.get(state.id, [])
            true_branches = [t for t in branches if not t.branch_is_else]
            default_branches = [t for t in branches if t.branch_is_else]
            if not true_branches:
                raise ValidationError(
                    "Condition state '%s' needs at least one TRUE branch." % state.name
                )
            if len(default_branches) != 1:
                raise ValidationError(
                    "Condition state '%s' must have exactly one DEFAULT branch." % state.name
                )

        reachable = set()
        stack = [state.id for state in start_states]
        while stack:
            current = stack.pop()
            if current in reachable:
                continue
            reachable.add(current)
            for transition in outgoing.get(current, []):
                dest_id = transition.dest_state_id.id
                if dest_id not in reachable:
                    stack.append(dest_id)

        unreachable_states = states.filtered(lambda s: s.id not in reachable)
        if unreachable_states:
            names = ", ".join(unreachable_states.mapped("name"))
            raise ValidationError("These states are not reachable from START: %s." % names)

        reverse_edges = {}
        for transition in transitions:
            reverse_edges.setdefault(transition.dest_state_id.id, []).append(
                transition.source_state_id.id
            )

        can_reach_end = set()
        stack = [state.id for state in end_states]
        while stack:
            current = stack.pop()
            if current in can_reach_end:
                continue
            can_reach_end.add(current)
            for source_id in reverse_edges.get(current, []):
                if source_id not in can_reach_end:
                    stack.append(source_id)

        dead_end_states = states.filtered(
            lambda s: s.id in reachable and s.id not in can_reach_end
        )
        if dead_end_states:
            names = ", ".join(dead_end_states.mapped("name"))
            raise ValidationError(
                "These states do not lead to an END state: %s." % names
            )
        return True

    def create_revision(self):
        self.ensure_one()
        process = self.process_id
        latest = self.search(
            [("process_id", "=", process.id)],
            order="version desc",
            limit=1,
        )
        next_version = (latest.version or 0) + 1
        new_version = self.create(
            {
                "name": f"{process.name} v{next_version}",
                "process_id": process.id,
                "version": next_version,
                "state": "draft",
            }
        )

        state_map = {}
        for state in self.state_ids.sorted("sequence"):
            new_state = state.copy(
                {
                    "version_id": new_version.id,
                }
            )
            state_map[state.id] = new_state.id
            if state.action_ids:
                for action in state.action_ids.sorted("sequence"):
                    action.copy({"state_id": new_state.id})

        for transition in self.transition_ids.sorted("sequence"):
            self.env["workflow.transition"].create(
                {
                    "name": transition.name,
                    "code": transition.code,
                    "version_id": new_version.id,
                    "source_state_id": state_map.get(transition.source_state_id.id),
                    "dest_state_id": state_map.get(transition.dest_state_id.id),
                    "sequence": transition.sequence,
                    "transition_type": transition.transition_type,
                    "trigger": transition.trigger,
                    "branch_expression": transition.branch_expression,
                    "branch_is_else": transition.branch_is_else,
                }
            )

        return new_version.id

    def activate_version(self):
        self.ensure_one()
        self.validate_before_activation()
        process = self.process_id
        if not process:
            return False
        other_versions = self.search([
            ("process_id", "=", process.id),
            ("id", "!=", self.id),
            ("state", "=", "active"),
        ])
        if other_versions:
            other_versions.write({"state": "retired"})
        self.write({"state": "active"})
        process.active_version_id = self.id
        return True

    def simulate(self, record_id):
        self.ensure_one()
        target_model = self.process_id.target_model_id
        if not target_model:
            raise UserError("Please set a Target Model on the process before simulation.")
        record = self.env[target_model.model].browse(record_id)
        if not record.exists():
            raise UserError("The selected record was not found.")
        record.check_access("read")
        return self._simulate_on_record(record)

    def _simulate_on_record(self, record, max_steps=200):
        self.ensure_one()
        transitions = self.transition_ids.sorted("sequence")
        outgoing = {}
        for transition in transitions:
            outgoing.setdefault(transition.source_state_id.id, []).append(transition)

        start_states = self.state_ids.filtered(lambda s: s.type == "start")
        start_state = start_states[:1]
        if not start_state:
            raise UserError("Simulation requires a START state.")

        visited = []
        evaluated = []
        current = start_state
        steps = 0
        while current and steps < max_steps:
            steps += 1
            visited.append({"state_id": current.id, "state": current.name, "type": current.type})
            if current.type == "end":
                return {
                    "visited": visited,
                    "evaluated": evaluated,
                    "final_state": {
                        "state_id": current.id,
                        "state": current.name,
                        "end_type": current.end_type,
                    },
                    "stopped": False,
                }

            if current.type == "condition":
                branches = outgoing.get(current.id, [])
                else_branch = [t for t in branches if t.branch_is_else]
                match = None
                for transition in branches:
                    if transition.branch_is_else:
                        continue
                    expr = transition.branch_expression
                    if not expr:
                        continue
                    validate_condition_expression(expr)
                    result = safe_eval(
                        expr,
                        {
                            "record": SafeRecordProxy(record),
                            "user": {"id": self.env.user.id},
                            "True": True,
                            "False": False,
                        },
                    )
                    evaluated.append(
                        {
                            "transition_id": transition.id,
                            "expression": expr,
                            "result": bool(result),
                        }
                    )
                    if result:
                        match = transition
                        break
                current = match.dest_state_id if match else (else_branch[0].dest_state_id if else_branch else None)
                continue

            next_transitions = outgoing.get(current.id, [])
            if not next_transitions:
                return {
                    "visited": visited,
                    "evaluated": evaluated,
                    "final_state": None,
                    "stopped": True,
                    "reason": "No outgoing transition available.",
                }

            auto = [t for t in next_transitions if t.trigger == "auto"]
            chosen = auto[0] if auto else next_transitions[0]
            current = chosen.dest_state_id

        return {
            "visited": visited,
            "evaluated": evaluated,
            "final_state": None,
            "stopped": True,
            "reason": "Simulation reached the maximum step limit.",
        }
