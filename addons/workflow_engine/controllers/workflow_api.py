from odoo import http
from odoo.http import request

from odoo.addons.workflow_engine.services.workflow_api_service import WorkflowApiService


class WorkflowApiController(http.Controller):
    _GROUP_ADMIN = "workflow_engine.group_workflow_admin"
    _GROUP_OPERATOR = "workflow_engine.group_workflow_operator"
    _GROUP_AUDITOR = "workflow_engine.group_workflow_auditor"

    def _service(self):
        return WorkflowApiService(request)

    @http.route("/api/v1/workflow/health", type="json", auth="public", methods=["GET"])
    def health(self):
        service = self._service()
        return service.handle_request(service.health, allow_public=True, rate_limit=False)

    @http.route("/api/v1/workflow/instance/create", type="json", auth="public", methods=["POST"])
    @http.route("/api/workflow/instance/create", type="json", auth="user", methods=["POST"])
    def create_instance(self, model, res_id, process_code):
        service = self._service()
        return service.handle_request(
            lambda: service.create_instance(model, res_id, process_code),
            groups=[self._GROUP_ADMIN, self._GROUP_OPERATOR],
        )

    @http.route("/api/v1/workflow/instance/state", type="json", auth="public", methods=["GET", "POST"])
    @http.route("/api/workflow/instance/state", type="json", auth="user", methods=["GET", "POST"])
    def get_state(self, instance_id):
        service = self._service()
        return service.handle_request(
            lambda: service.get_state(instance_id),
            groups=[self._GROUP_ADMIN, self._GROUP_OPERATOR],
        )

    @http.route("/api/v1/workflow/instance/trigger", type="json", auth="public", methods=["POST"])
    @http.route("/api/workflow/instance/trigger", type="json", auth="user", methods=["POST"])
    def trigger(self, instance_id, transition_id=None, comment=None):
        service = self._service()
        return service.handle_request(
            lambda: service.trigger(instance_id, transition_id=transition_id, comment=comment),
            groups=[self._GROUP_ADMIN, self._GROUP_OPERATOR],
        )

    @http.route("/api/v1/workflow/instance/audit", type="json", auth="public", methods=["GET", "POST"])
    @http.route("/api/workflow/instance/audit", type="json", auth="user", methods=["GET", "POST"])
    def audit(self, instance_id):
        service = self._service()
        return service.handle_request(
            lambda: service.audit(instance_id),
            groups=[self._GROUP_ADMIN, self._GROUP_OPERATOR, self._GROUP_AUDITOR],
        )

    @http.route("/api/v1/workflow/instances", type="json", auth="public", methods=["GET", "POST"])
    @http.route("/api/workflow/instances", type="json", auth="user", methods=["GET", "POST"])
    def list_instances(self, status=None, model=None, limit=50, offset=0):
        service = self._service()
        return service.handle_request(
            lambda: service.list_instances(status=status, model=model, limit=limit, offset=offset),
            groups=[self._GROUP_ADMIN, self._GROUP_OPERATOR],
        )

    @http.route("/api/v1/workflow/workitems", type="json", auth="public", methods=["GET", "POST"])
    @http.route("/api/workflow/workitems", type="json", auth="user", methods=["GET", "POST"])
    def list_workitems(self, status=None, limit=50, offset=0):
        service = self._service()
        return service.handle_request(
            lambda: service.list_workitems(status=status, limit=limit, offset=offset),
            groups=[self._GROUP_ADMIN, self._GROUP_OPERATOR],
        )

    @http.route("/api/v1/workflow/transition/by_code", type="json", auth="public", methods=["POST"])
    @http.route("/api/workflow/transition/by_code", type="json", auth="user", methods=["POST"])
    def trigger_by_code(self, instance_id, transition_code=None, comment=None):
        service = self._service()
        return service.handle_request(
            lambda: service.trigger_by_code(
                instance_id, transition_code=transition_code, comment=comment
            ),
            groups=[self._GROUP_ADMIN, self._GROUP_OPERATOR],
        )

    @http.route("/api/v1/workflow/workitems/bulk", type="json", auth="public", methods=["POST"])
    @http.route("/api/workflow/workitems/bulk", type="json", auth="user", methods=["POST"])
    def bulk_workitem_action(self, action, workitem_ids, comment=None):
        service = self._service()
        return service.handle_request(
            lambda: service.bulk_workitem_action(action, workitem_ids, comment=comment),
            groups=[self._GROUP_ADMIN, self._GROUP_OPERATOR],
        )
