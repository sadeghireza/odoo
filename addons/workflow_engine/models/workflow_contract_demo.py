from odoo import api, fields, models


class WorkflowContractDemo(models.Model):
    _name = "workflow.contract.demo"
    _description = "Workflow Contract Demo"
    _inherit = "workflow.mixin"

    name = fields.Char(required=True)
    amount = fields.Float()
    partner_id = fields.Many2one("res.partner")

    def _workflow_process_code(self):
        return "contract_demo"
