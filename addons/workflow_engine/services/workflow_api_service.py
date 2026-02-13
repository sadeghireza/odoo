import logging
import threading
import time
from collections import deque

from odoo.exceptions import AccessError, UserError

from .workflow_api_auth import WorkflowApiAuth

_logger = logging.getLogger(__name__)

_RATE_LIMIT = {}
_RATE_LIMIT_LOCK = threading.Lock()


class WorkflowApiService:
    def __init__(self, request):
        self.request = request
        self.auth_service = WorkflowApiAuth(request)

    def _use_envelope(self):
        path = self.request.httprequest.path or ""
        return "/api/v1/" in path

    def handle_request(self, handler, groups=None, rate_limit=True, allow_public=False):
        try:
            if groups or allow_public:
                self.auth(groups=groups, allow_public=allow_public)
            else:
                self.auth_service.authenticate_if_present()
            if rate_limit:
                self.apply_rate_limit()
            data = handler()
            return self.format_response(data=data)
        except Exception as exc:
            return self.format_response(error=exc)

    def auth(self, groups=None, allow_public=False):
        if allow_public:
            params = self.request.env["ir.config_parameter"].sudo()
            allow_public_flag = params.get_param("workflow_engine.health_allow_public", "0")
            if allow_public_flag in ("1", "true", "True"):
                self.auth_service.authenticate_if_present()
                return True
        self.auth_service.authenticate_if_present()
        if groups:
            user = self.request.env.user
            if not any(user.has_group(group) for group in groups):
                _logger.warning(
                    "Workflow API access denied. user_id=%s groups=%s",
                    user.id,
                    groups,
                )
                raise AccessError(
                    "You do not have access to this workflow API. Please contact your administrator."
                )
        return True

    def validate_payload(self, action=None, workitem_ids=None):
        if action is not None and action not in ("approve", "reject"):
            raise UserError("Action must be 'approve' or 'reject'.")
        if workitem_ids is not None and not isinstance(workitem_ids, (list, tuple)):
            raise UserError("Please provide workitem_ids as a list of IDs.")

    def apply_rate_limit(self):
        params = self.request.env["ir.config_parameter"].sudo()
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
        key = f"{self.request.env.user.id}:{self.request.httprequest.path}"
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
                    self.request.env.user.id,
                    self.request.httprequest.path,
                )
                raise UserError("Too many requests. Please try again in a minute.")
            bucket.append(now)

    def format_response(self, data=None, error=None):
        if error is None:
            if self._use_envelope():
                return {"ok": True, "data": data}
            return data
        if not self._use_envelope():
            raise error
        if isinstance(error, AccessError):
            code = "access_denied"
        elif isinstance(error, UserError):
            code = "user_error"
        else:
            code = "server_error"
        _logger.exception("Workflow API error: %s", code)
        return {"ok": False, "error": {"code": code, "message": str(error)}}

    def health(self):
        self.request.env.cr.execute("SELECT 1")
        return {"status": "ok"}

    def create_instance(self, model, res_id, process_code):
        record = self._get_record(model, res_id, access_mode="read")
        instance = self.request.env["workflow.engine"].start_for_record(record, process_code)
        return {"instance_id": instance.id, "state_id": instance.state_id.id}

    def get_state(self, instance_id):
        instance = self._get_instance(instance_id)
        return {
            "instance_id": instance.id,
            "state_id": instance.state_id.id,
            "state": instance.state_id.code,
            "status": instance.status,
        }

    def trigger(self, instance_id, transition_id=None, comment=None):
        instance = self._get_instance(instance_id)
        if transition_id:
            transition = self._get_transition(transition_id)
            instance.action_trigger(transition_id=transition.id, comment=comment)
        else:
            instance.action_trigger(comment=comment)
        return {"instance_id": instance.id, "state_id": instance.state_id.id}

    def audit(self, instance_id):
        instance = self._get_instance(instance_id)
        audits_recordset = instance.audit_ids
        audits_recordset.check_access("read")
        audits = audits_recordset.read(
            ["action", "user_id", "from_state_id", "to_state_id", "action_date", "comment", "payload"]
        )
        return {"instance_id": instance.id, "audit": audits}

    def list_instances(self, status=None, model=None, limit=50, offset=0):
        domain = []
        if status:
            domain.append(("status", "=", status))
        if model:
            domain.append(("res_model", "=", model))
        limit, offset = self._clamp_paging(limit, offset)
        instances = self.request.env["workflow.instance"].search(domain, limit=limit, offset=offset)
        return instances.read(
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

    def list_workitems(self, status=None, limit=50, offset=0):
        domain = [("user_id", "=", self.request.env.user.id)]
        if status:
            domain.append(("status", "=", status))
        limit, offset = self._clamp_paging(limit, offset)
        items = self.request.env["workflow.workitem"].search(domain, limit=limit, offset=offset)
        return items.read(
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

    def trigger_by_code(self, instance_id, transition_code=None, comment=None):
        instance = self._get_instance(instance_id)
        if not transition_code:
            raise UserError("Please provide a transition code.")
        transition = self.request.env["workflow.transition"].search(
            [
                ("version_id", "=", instance.version_id.id),
                ("source_state_id", "=", instance.state_id.id),
                ("code", "=", transition_code),
            ],
            limit=1,
        )
        if not transition:
            transition = self.request.env["workflow.transition"].search(
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
            raise UserError("No matching transition was found for this state.")
        instance.action_trigger(transition_id=transition.id, comment=comment)
        return {"instance_id": instance.id, "state_id": instance.state_id.id}

    def bulk_workitem_action(self, action, workitem_ids, comment=None):
        self.validate_payload(action=action, workitem_ids=workitem_ids)
        ids = [self._get_int(item_id, "workitem_id") for item_id in workitem_ids]
        workitems = self.request.env["workflow.workitem"].browse(ids)
        if not workitems.exists():
            raise UserError("No work items were found for the selected IDs.")
        workitems.check_access("read")
        results = []
        for item in workitems:
            if action == "approve":
                item.action_approve(comment=comment)
            elif action == "reject":
                item.action_reject(comment=comment)
            results.append({"workitem_id": item.id, "status": item.status})
        return {"results": results}

    def _get_int(self, value, label):
        try:
            return int(value)
        except (TypeError, ValueError):
            _logger.warning("Invalid %s: %s", label, value)
            raise UserError("Please provide a valid %s." % label)

    def _clamp_paging(self, limit, offset, max_limit=200):
        limit_val = self._get_int(limit, "limit") if limit is not None else 50
        offset_val = self._get_int(offset, "offset") if offset is not None else 0
        if limit_val < 0 or offset_val < 0:
            raise UserError("Paging values must be zero or greater.")
        if limit_val > max_limit:
            limit_val = max_limit
        return limit_val, offset_val

    def _get_model(self, model):
        if not model or not isinstance(model, str):
            raise UserError("Please provide a valid model name.")
        try:
            return self.request.env[model]
        except KeyError:
            _logger.warning("Unknown model: %s", model)
            raise UserError("The requested model is not available.")

    def _get_record(self, model, res_id, access_mode="read"):
        model_env = self._get_model(model)
        res_id = self._get_int(res_id, "res_id")
        record = model_env.browse(res_id)
        if not record.exists():
            _logger.warning("Record not found: %s(%s)", model, res_id)
            raise UserError("The record was not found. Please check the ID.")
        record.check_access(access_mode)
        return record

    def _get_instance(self, instance_id):
        instance_id = self._get_int(instance_id, "workflow instance_id")
        instance = self.request.env["workflow.instance"].browse(instance_id)
        if not instance.exists():
            _logger.warning("Workflow instance not found: %s", instance_id)
            raise UserError("The workflow instance was not found. Please check the ID.")
        instance.check_access("read")
        return instance

    def _get_transition(self, transition_id):
        transition_id = self._get_int(transition_id, "transition_id")
        transition = self.request.env["workflow.transition"].browse(transition_id)
        if not transition.exists():
            _logger.warning("Workflow transition not found: %s", transition_id)
            raise UserError("The workflow transition was not found. Please check the ID.")
        transition.check_access("read")
        return transition
