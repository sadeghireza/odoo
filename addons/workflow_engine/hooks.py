import re

from odoo import api, SUPERUSER_ID


def _normalize_code(value):
    value = (value or "").strip().lower()
    value = re.sub(r"[^a-z0-9]+", "_", value)
    value = re.sub(r"_+", "_", value).strip("_")
    return value or "transition"


def post_init_hook(cr, registry):
    env = api.Environment(cr, SUPERUSER_ID, {})
    Transition = env["workflow.transition"]

    transitions = Transition.search(["|", ("code", "=", False), ("code", "=", "")])
    if not transitions:
        return

    for version in transitions.mapped("version_id"):
        version_transitions = Transition.search([("version_id", "=", version.id)])
        existing = {
            (t.code or "").strip().lower()
            for t in version_transitions
            if t.code
        }
        missing = version_transitions.filtered(lambda t: not t.code)
        for transition in missing:
            base = _normalize_code(transition.name)
            candidate = base
            counter = 2
            while candidate in existing:
                candidate = f"{base}_{counter}"
                counter += 1
            transition.write({"code": candidate})
            existing.add(candidate)
