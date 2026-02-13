import json
import urllib.request
import http.cookiejar

BASE_URL = "http://localhost:8070"
DB = "odoodb"
USERNAME = "admin"
PASSWORD = "admin"


class JsonRpcClient:
    def __init__(self, base_url):
        self.base_url = base_url.rstrip("/")
        self.cj = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.cj))

    def _post(self, path, payload):
        url = self.base_url + path
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        with self.opener.open(req) as res:
            return json.loads(res.read().decode("utf-8"))

    def authenticate(self, db, login, password):
        payload = {
            "jsonrpc": "2.0",
            "method": "call",
            "params": {"db": db, "login": login, "password": password},
            "id": 1,
        }
        result = self._post("/web/session/authenticate", payload)
        return result.get("result")

    def call_kw(self, model, method, args=None, kwargs=None):
        payload = {
            "jsonrpc": "2.0",
            "method": "call",
            "params": {
                "model": model,
                "method": method,
                "args": args or [],
                "kwargs": kwargs or {},
            },
            "id": 1,
        }
        result = self._post("/web/dataset/call_kw", payload)
        if "error" in result:
            raise RuntimeError(result["error"])
        return result.get("result")

    def api(self, path, params):
        payload = {"jsonrpc": "2.0", "method": "call", "params": params, "id": 1}
        result = self._post(path, payload)
        if "error" in result:
            raise RuntimeError(result["error"])
        return result.get("result")


def main():
    client = JsonRpcClient(BASE_URL)
    auth = client.authenticate(DB, USERNAME, PASSWORD)
    if not auth or not auth.get("uid"):
        raise RuntimeError("Authentication failed")

    contract_id = client.call_kw("workflow.contract.demo", "create", args=[{"name": "API Sanity"}])
    instance = client.api(
        "/api/workflow/instance/create",
        {"model": "workflow.contract.demo", "res_id": contract_id, "process_code": "contract_demo"},
    )
    instance_id = instance["instance_id"]

    state = client.api("/api/workflow/instance/state", {"instance_id": instance_id})
    workitems = client.api("/api/workflow/workitems", {"status": "pending", "limit": 20})
    if workitems:
        workitem_id = workitems[0]["id"]
        client.api(
            "/api/workflow/workitems/bulk",
            {"action": "approve", "workitem_ids": [workitem_id], "comment": "sanity"},
        )

    audit = client.api("/api/workflow/instance/audit", {"instance_id": instance_id})
    print("State:", state)
    print("Audit entries:", len(audit.get("audit", [])))


if __name__ == "__main__":
    main()
