import secrets
from datetime import timedelta

from werkzeug.security import check_password_hash, generate_password_hash

from odoo import api, fields, models


class WorkflowApiKey(models.Model):
    _name = "workflow.api_key"
    _description = "Workflow API Key"
    _order = "create_date desc"

    name = fields.Char(required=True)
    user_id = fields.Many2one("res.users", required=True, ondelete="cascade")
    company_id = fields.Many2one(
        "res.company",
        related="user_id.company_id",
        store=True,
        readonly=True,
    )
    key_hash = fields.Char(required=True, readonly=True)
    key_prefix = fields.Char(readonly=True, index=True)
    scopes = fields.Char(help="Optional comma-separated scopes")
    active = fields.Boolean(default=True)
    expires_at = fields.Datetime()
    last_used_at = fields.Datetime()

    def _generate_token(self):
        return f"wfe_{secrets.token_urlsafe(32)}"

    def _set_token(self, token):
        self.ensure_one()
        prefix = token[:8]
        self.write(
            {
                "key_hash": generate_password_hash(token),
                "key_prefix": prefix,
                "last_used_at": False,
            }
        )
        return token

    def generate_new_key(self):
        token = self._generate_token()
        return self._set_token(token)

    def action_generate_key(self):
        self.ensure_one()
        token = self.generate_new_key()
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": "API Key Generated",
                "message": f"New key: {token}",
                "sticky": True,
            },
        }

    @api.model
    def create_with_token(self, vals):
        token = self._generate_token()
        vals = dict(vals or {})
        vals.update(
            {
                "key_hash": generate_password_hash(token),
                "key_prefix": token[:8],
            }
        )
        record = self.create(vals)
        return record, token

    @api.model
    def authenticate_token(self, token):
        if not token:
            return False
        token = token.strip()
        if not token:
            return False
        prefix = token[:8]
        now = fields.Datetime.now()
        candidates = self.sudo().search(
            [("key_prefix", "=", prefix), ("active", "=", True)]
        )
        for key in candidates:
            if key.expires_at and key.expires_at < now:
                continue
            if check_password_hash(key.key_hash, token):
                key.sudo().write({"last_used_at": now})
                return key.user_id
        return False
