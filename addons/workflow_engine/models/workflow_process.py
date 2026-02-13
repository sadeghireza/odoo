from odoo import api, fields, models


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
        related="process_id.company_id",
        store=True,
        readonly=True,
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

    def get_start_state(self):
        self.ensure_one()
        start_state = self.state_ids.filtered(lambda s: s.type == "start")
        if start_state:
            return start_state.sorted("sequence")[0]
        return self.state_ids.sorted("sequence")[:1]

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
