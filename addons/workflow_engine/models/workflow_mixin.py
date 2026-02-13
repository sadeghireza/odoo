from odoo import api, fields, models


class WorkflowMixin(models.AbstractModel):
    _name = "workflow.mixin"
    _description = "Workflow Mixin"

    workflow_instance_id = fields.Many2one("workflow.instance", string="Workflow Instance")

    def _workflow_process_code(self):
        return None

    def action_start_workflow(self):
        self.ensure_one()
        process_code = self._workflow_process_code()
        if not process_code:
            return False
        instance = self.env["workflow.engine"].start_for_record(self, process_code)
        self.workflow_instance_id = instance.id
        return instance
