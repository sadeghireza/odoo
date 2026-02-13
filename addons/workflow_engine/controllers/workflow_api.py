from odoo import http
from odoo.http import request


class WorkflowApiController(http.Controller):
    @http.route("/api/workflow/instance/create", type="json", auth="user", methods=["POST"])
    def create_instance(self, model, res_id, process_code):
        record = request.env[model].browse(int(res_id))
        instance = request.env["workflow.engine"].start_for_record(record, process_code)
        return {"instance_id": instance.id, "state_id": instance.state_id.id}

    @http.route("/api/workflow/instance/state", type="json", auth="user", methods=["GET", "POST"])
    def get_state(self, instance_id):
        instance = request.env["workflow.instance"].browse(int(instance_id))
        return {
            "instance_id": instance.id,
            "state_id": instance.state_id.id,
            "state": instance.state_id.code,
            "status": instance.status,
        }

    @http.route("/api/workflow/instance/trigger", type="json", auth="user", methods=["POST"])
    def trigger(self, instance_id, transition_id=None, comment=None):
        instance = request.env["workflow.instance"].browse(int(instance_id))
        instance.action_trigger(transition_id=transition_id, comment=comment)
        return {"instance_id": instance.id, "state_id": instance.state_id.id}

    @http.route("/api/workflow/instance/audit", type="json", auth="user", methods=["GET", "POST"])
    def audit(self, instance_id):
        instance = request.env["workflow.instance"].browse(int(instance_id))
        audits = instance.audit_ids.sudo().read(
            ["action", "user_id", "from_state_id", "to_state_id", "action_date", "comment", "payload"]
        )
        return {"instance_id": instance.id, "audit": audits}

    @http.route("/api/workflow/instances", type="json", auth="user", methods=["GET", "POST"])
    def list_instances(self, status=None, model=None, limit=50, offset=0):
        domain = []
        if status:
            domain.append(("status", "=", status))
        if model:
            domain.append(("res_model", "=", model))
        instances = request.env["workflow.instance"].search(domain, limit=int(limit), offset=int(offset))
        return instances.read(["name", "process_id", "version_id", "res_model", "res_id", "state_id", "status", "start_date", "end_date"])

    @http.route("/api/workflow/workitems", type="json", auth="user", methods=["GET", "POST"])
    def list_workitems(self, status=None, limit=50, offset=0):
        domain = [("user_id", "=", request.env.user.id)]
        if status:
            domain.append(("status", "=", status))
        items = request.env["workflow.workitem"].search(domain, limit=int(limit), offset=int(offset))
        return items.read(["instance_id", "state_id", "user_id", "status", "assigned_date", "action_date", "comment"])

    @http.route("/api/workflow/transition/by_code", type="json", auth="user", methods=["POST"])
    def trigger_by_code(self, instance_id, transition_code=None, comment=None):
        instance = request.env["workflow.instance"].browse(int(instance_id))
        transition = False
        if transition_code:
            transition = request.env["workflow.transition"].search(
                [
                    ("version_id", "=", instance.version_id.id),
                    ("source_state_id", "=", instance.state_id.id),
                    ("name", "=", transition_code),
                ],
                limit=1,
            )
        instance.action_trigger(transition_id=transition.id if transition else None, comment=comment)
        return {"instance_id": instance.id, "state_id": instance.state_id.id}

    @http.route("/api/workflow/workitems/bulk", type="json", auth="user", methods=["POST"])
    def bulk_workitem_action(self, action, workitem_ids, comment=None):
        workitems = request.env["workflow.workitem"].browse([int(i) for i in workitem_ids])
        results = []
        for item in workitems:
            if action == "approve":
                item.action_approve(comment=comment)
            elif action == "reject":
                item.action_reject(comment=comment)
            results.append({"workitem_id": item.id, "status": item.status})
        return {"results": results}
