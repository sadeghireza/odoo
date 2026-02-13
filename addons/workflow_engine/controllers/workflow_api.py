import logging
import threading
import time
from collections import deque

from odoo import http
from odoo.exceptions import AccessError, UserError
from odoo.http import request

_logger = logging.getLogger(__name__)
_RATE_LIMIT = {}
_RATE_LIMIT_LOCK = threading.Lock()


class WorkflowApiController(http.Controller):
    _GROUP_ADMIN = "workflow_engine.group_workflow_admin"
    _GROUP_OPERATOR = "workflow_engine.group_workflow_operator"
    _GROUP_AUDITOR = "workflow_engine.group_workflow_auditor"

    def _use_envelope(self):
        path = request.httprequest.path or ""
        return "/api/v1/" in path

    def _get_api_key_token(self):
        auth = request.httprequest.headers.get("Authorization", "")
        if auth.lower().startswith("bearer "):
            return auth.split(" ", 1)[1].strip()
        return request.httprequest.headers.get("X-API-Key")

    def _apply_api_key(self):
        token = self._get_api_key_token()
        if not token:
            return False
        user = request.env["workflow.api_key"].authenticate_token(token)
        if not user:
            _logger.warning("Invalid API key used for workflow API access")
            raise AccessError("Invalid API key.")
        request.update_env(user=user.id)
        return True

    def _check_rate_limit(self):
        params = request.env["ir.config_parameter"].sudo()
        window = params.get_param("workflow_engine.rate_limit_window_sec", "60")
        limit = params.get_param("workflow_engine.rate_limit_max", "120")
        try:
            window = int(window)
            limit = int(limit)
        except (TypeError, ValueError):
            window = 60
            limit = 120
        if window <= 0 or limit <= 0:
            return
        now = time.time()
        key = f"{request.env.user.id}:{request.httprequest.path}"
        with _RATE_LIMIT_LOCK:
            bucket = _RATE_LIMIT.get(key)
            if not bucket:
                bucket = deque()
                _RATE_LIMIT[key] = bucket
            while bucket and bucket[0] < now - window:
                bucket.popleft()
            if len(bucket) >= limit:
                _logger.warning(
                    "Workflow API rate limit hit. user_id=%s path=%s",
                    request.env.user.id,
                    request.httprequest.path,
                )
                raise UserError("Rate limit exceeded. Please retry later.")
            bucket.append(now)

    @http.route("/api/v1/workflow/health", type="json", auth="public", methods=["GET"])
    def health(self):
        try:
            params = request.env["ir.config_parameter"].sudo()
            allow_public = params.get_param("workflow_engine.health_allow_public", "0")
            if allow_public not in ("1", "true", "True"):
                if not self._apply_api_key():
                    raise AccessError("API key required.")
            request.env.cr.execute("SELECT 1")
            return self._wrap_ok({"status": "ok"})
        except Exception as exc:
            return self._wrap_error(exc)

    def _wrap_ok(self, data):
        if self._use_envelope():
            return {"ok": True, "data": data}
        return data

    def _wrap_error(self, exc):
        if not self._use_envelope():
            raise
        if isinstance(exc, AccessError):
            code = "access_denied"
        elif isinstance(exc, UserError):
            code = "user_error"
        else:
            code = "server_error"
        _logger.exception("Workflow API error: %s", code)
        return {"ok": False, "error": {"code": code, "message": str(exc)}}

    def _ensure_group(self, allowed_groups):
        self._apply_api_key()
        user = request.env.user
        if not any(user.has_group(group) for group in allowed_groups):
            _logger.warning(
                "Workflow API access denied. user_id=%s groups=%s",
                user.id,
                allowed_groups,
            )
            raise AccessError("User is not allowed to access workflow API.")

    def _get_int(self, value, label):
        try:
            return int(value)
        except (TypeError, ValueError):
            _logger.warning("Invalid %s: %s", label, value)
            raise UserError("Invalid %s." % label)

    def _clamp_paging(self, limit, offset, max_limit=200):
        limit_val = self._get_int(limit, "limit") if limit is not None else 50
        offset_val = self._get_int(offset, "offset") if offset is not None else 0
        if limit_val < 0 or offset_val < 0:
            raise UserError("Invalid paging parameters.")
        if limit_val > max_limit:
            limit_val = max_limit
        return limit_val, offset_val

    def _get_model(self, model):
        if not model or not isinstance(model, str):
            raise UserError("Invalid model.")
        try:
            return request.env[model]
        except KeyError:
            _logger.warning("Unknown model: %s", model)
            raise UserError("Unknown model.")

    def _get_record(self, model, res_id, access_mode="read"):
        model_env = self._get_model(model)
        res_id = self._get_int(res_id, "res_id")
        record = model_env.browse(res_id)
        if not record.exists():
            _logger.warning("Record not found: %s(%s)", model, res_id)
            raise UserError("Record not found.")
        record.check_access(access_mode)
        return record

    def _get_instance(self, instance_id):
        instance_id = self._get_int(instance_id, "workflow instance_id")
        instance = request.env["workflow.instance"].browse(instance_id)
        if not instance.exists():
            _logger.warning("Workflow instance not found: %s", instance_id)
            raise UserError("Workflow instance not found.")
        instance.check_access("read")
        return instance

    def _get_transition(self, transition_id):
        transition_id = self._get_int(transition_id, "transition_id")
        transition = request.env["workflow.transition"].browse(transition_id)
        if not transition.exists():
            _logger.warning("Workflow transition not found: %s", transition_id)
            raise UserError("Workflow transition not found.")
        transition.check_access("read")
        return transition

    @http.route("/api/v1/workflow/instance/create", type="json", auth="public", methods=["POST"])
    @http.route("/api/workflow/instance/create", type="json", auth="user", methods=["POST"])
    def create_instance(self, model, res_id, process_code):
        try:
            self._ensure_group([self._GROUP_ADMIN, self._GROUP_OPERATOR])
            self._check_rate_limit()
            record = self._get_record(model, res_id, access_mode="read")
            instance = request.env["workflow.engine"].start_for_record(record, process_code)
            return self._wrap_ok({"instance_id": instance.id, "state_id": instance.state_id.id})
        except Exception as exc:
            return self._wrap_error(exc)

    @http.route("/api/v1/workflow/instance/state", type="json", auth="public", methods=["GET", "POST"])
    @http.route("/api/workflow/instance/state", type="json", auth="user", methods=["GET", "POST"])
    def get_state(self, instance_id):
        try:
            self._ensure_group([self._GROUP_ADMIN, self._GROUP_OPERATOR])
            self._check_rate_limit()
            instance = self._get_instance(instance_id)
            return self._wrap_ok(
                {
                    "instance_id": instance.id,
                    "state_id": instance.state_id.id,
                    "state": instance.state_id.code,
                    "status": instance.status,
                }
            )
        except Exception as exc:
            return self._wrap_error(exc)

    @http.route("/api/v1/workflow/instance/trigger", type="json", auth="public", methods=["POST"])
    @http.route("/api/workflow/instance/trigger", type="json", auth="user", methods=["POST"])
    def trigger(self, instance_id, transition_id=None, comment=None):
        try:
            self._ensure_group([self._GROUP_ADMIN, self._GROUP_OPERATOR])
            self._check_rate_limit()
            instance = self._get_instance(instance_id)
            if transition_id:
                transition = self._get_transition(transition_id)
                instance.action_trigger(transition_id=transition.id, comment=comment)
            else:
                instance.action_trigger(comment=comment)
            return self._wrap_ok({"instance_id": instance.id, "state_id": instance.state_id.id})
        except Exception as exc:
            return self._wrap_error(exc)

    @http.route("/api/v1/workflow/instance/audit", type="json", auth="public", methods=["GET", "POST"])
    @http.route("/api/workflow/instance/audit", type="json", auth="user", methods=["GET", "POST"])
    def audit(self, instance_id):
        try:
            self._ensure_group([self._GROUP_ADMIN, self._GROUP_OPERATOR, self._GROUP_AUDITOR])
            self._check_rate_limit()
            instance = self._get_instance(instance_id)
            audits_recordset = instance.audit_ids
            audits_recordset.check_access("read")
            audits = audits_recordset.read(
                ["action", "user_id", "from_state_id", "to_state_id", "action_date", "comment", "payload"]
            )
            return self._wrap_ok({"instance_id": instance.id, "audit": audits})
        except AccessError as exc:
            _logger.warning(
                "Access denied to workflow audit. user_id=%s instance_id=%s",
                request.env.user.id,
                instance_id,
            )
            return self._wrap_error(exc)
        except Exception as exc:
            return self._wrap_error(exc)

    @http.route("/api/v1/workflow/instances", type="json", auth="public", methods=["GET", "POST"])
    @http.route("/api/workflow/instances", type="json", auth="user", methods=["GET", "POST"])
    def list_instances(self, status=None, model=None, limit=50, offset=0):
        try:
            self._ensure_group([self._GROUP_ADMIN, self._GROUP_OPERATOR])
            self._check_rate_limit()
            domain = []
            if status:
                domain.append(("status", "=", status))
            if model:
                domain.append(("res_model", "=", model))
            limit, offset = self._clamp_paging(limit, offset)
            instances = request.env["workflow.instance"].search(domain, limit=limit, offset=offset)
            data = instances.read(
                [
                    "name",
                    "process_id",
                    "version_id",
                    "res_model",
                    "res_id",
                    "state_id",
                    "status",
                    "start_date",
                    "end_date",
                ]
            )
            return self._wrap_ok(data)
        except Exception as exc:
            return self._wrap_error(exc)

    @http.route("/api/v1/workflow/workitems", type="json", auth="public", methods=["GET", "POST"])
    @http.route("/api/workflow/workitems", type="json", auth="user", methods=["GET", "POST"])
    def list_workitems(self, status=None, limit=50, offset=0):
        try:
            self._ensure_group([self._GROUP_ADMIN, self._GROUP_OPERATOR])
            self._check_rate_limit()
            domain = [("user_id", "=", request.env.user.id)]
            if status:
                domain.append(("status", "=", status))
            limit, offset = self._clamp_paging(limit, offset)
            items = request.env["workflow.workitem"].search(domain, limit=limit, offset=offset)
            data = items.read(
                [
                    "instance_id",
                    "state_id",
                    "user_id",
                    "status",
                    "assigned_date",
                    "action_date",
                    "comment",
                ]
            )
            return self._wrap_ok(data)
        except Exception as exc:
            return self._wrap_error(exc)

    @http.route("/api/v1/workflow/transition/by_code", type="json", auth="public", methods=["POST"])
    @http.route("/api/workflow/transition/by_code", type="json", auth="user", methods=["POST"])
    def trigger_by_code(self, instance_id, transition_code=None, comment=None):
        try:
            self._ensure_group([self._GROUP_ADMIN, self._GROUP_OPERATOR])
            self._check_rate_limit()
            instance = self._get_instance(instance_id)
            if not transition_code:
                raise UserError("transition_code is required.")
            transition = request.env["workflow.transition"].search(
                [
                    ("version_id", "=", instance.version_id.id),
                    ("source_state_id", "=", instance.state_id.id),
                    ("code", "=", transition_code),
                ],
                limit=1,
            )
            if not transition:
                transition = request.env["workflow.transition"].search(
                    [
                        ("version_id", "=", instance.version_id.id),
                        ("source_state_id", "=", instance.state_id.id),
                        ("name", "=", transition_code),
                    ],
                    limit=1,
                )
                if transition:
                    _logger.warning(
                        "Transition found by name fallback. Please set code. transition_id=%s",
                        transition.id,
                    )
            if not transition:
                raise UserError("Transition not found for the provided code.")
            instance.action_trigger(transition_id=transition.id, comment=comment)
            return self._wrap_ok({"instance_id": instance.id, "state_id": instance.state_id.id})
        except Exception as exc:
            return self._wrap_error(exc)

    @http.route("/api/v1/workflow/workitems/bulk", type="json", auth="public", methods=["POST"])
    @http.route("/api/workflow/workitems/bulk", type="json", auth="user", methods=["POST"])
    def bulk_workitem_action(self, action, workitem_ids, comment=None):
        try:
            self._ensure_group([self._GROUP_ADMIN, self._GROUP_OPERATOR])
            self._check_rate_limit()
            if action not in ("approve", "reject"):
                raise UserError("Invalid action.")
            if not isinstance(workitem_ids, (list, tuple)):
                raise UserError("workitem_ids must be a list.")
            ids = [self._get_int(item_id, "workitem_id") for item_id in workitem_ids]
            workitems = request.env["workflow.workitem"].browse(ids)
            if not workitems.exists():
                raise UserError("No work items found.")
            workitems.check_access("read")
            results = []
            for item in workitems:
                if action == "approve":
                    item.action_approve(comment=comment)
                elif action == "reject":
                    item.action_reject(comment=comment)
                results.append({"workitem_id": item.id, "status": item.status})
            return self._wrap_ok({"results": results})
        except Exception as exc:
            return self._wrap_error(exc)
