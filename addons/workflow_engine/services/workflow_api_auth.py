import logging

from odoo.exceptions import AccessError

_logger = logging.getLogger(__name__)


class WorkflowApiAuth:
    def __init__(self, request):
        self.request = request

    def _get_api_key_token(self):
        auth = self.request.httprequest.headers.get("Authorization", "")
        if auth.lower().startswith("bearer "):
            return auth.split(" ", 1)[1].strip()
        return self.request.httprequest.headers.get("X-API-Key")

    def authenticate_if_present(self):
        token = self._get_api_key_token()
        if not token:
            return False
        user = self.request.env["workflow.api_key"].authenticate_token(token)
        if not user:
            _logger.warning("Invalid API key used for workflow API access")
            raise AccessError("API key is invalid. Please provide a valid key.")
        self.request.update_env(user=user.id)
        return True

    def require_api_key(self):
        if not self.authenticate_if_present():
            raise AccessError("API key is required to access this endpoint.")
