import base64
import uuid
from pathlib import Path
from urllib.parse import quote

import httpx

from app.services.develop_workspace import workspace_path


class PreviewController:
    def __init__(self, *, root: Path, url: str) -> None:
        self.root = root
        self.url = url

    def start(self, chat_id: uuid.UUID) -> dict[str, str]:
        checkout = workspace_path(root=self.root, chat_id=chat_id)
        if not checkout.is_dir():
            raise FileNotFoundError("Development Chat checkout is not ready")
        return self._request("POST", f"/workloads/{chat_id}")

    def status(self, chat_id: uuid.UUID) -> dict[str, str]:
        workspace_path(root=self.root, chat_id=chat_id)
        return self._request("GET", f"/workloads/{chat_id}")

    def stop(self, chat_id: uuid.UUID) -> dict[str, str]:
        return self._request("DELETE", f"/workloads/{chat_id}")

    def restart(self, chat_id: uuid.UUID) -> dict[str, str]:
        checkout = workspace_path(root=self.root, chat_id=chat_id)
        if not checkout.is_dir():
            raise FileNotFoundError("Development Chat checkout is not ready")
        return self._request("PUT", f"/workloads/{chat_id}")

    def activity(self, chat_id: uuid.UUID) -> dict[str, str]:
        return self._request("POST", f"/workloads/{chat_id}/activity")

    def fetch(self, chat_id: uuid.UUID, path: str, query: str, port: str | None = None,
              body: bytes | None = None, content_type: str = "", cookie: str = "") -> dict:
        if len(path) + len(query) > 2000 or not path.startswith("/") or path.startswith("//"):
            raise ValueError("Invalid preview path")
        if len(cookie) > 8192:
            raise ValueError("Invalid preview cookie")
        with httpx.Client(base_url=self.url, timeout=20) as client:
            destination = f"/workloads/{chat_id}/browser?path={quote(path + ('?' + query if query else ''), safe='')}"
            if port is not None:
                destination += f"&port={quote(port, safe='')}"
            if body is None:
                response = client.get(destination, headers={"Cookie": cookie} if cookie else {})
            else:
                response = client.post(destination, json={"body": base64.b64encode(body).decode(),
                                                          "content_type": content_type, "cookie": cookie})
            response.raise_for_status()
            result = response.json()
            return {"status": result["status"], "location": result.get("location", ""),
                    "content_type": result["content_type"], "cookies": result.get("cookies", []),
                    "body": base64.b64decode(result["body"], validate=True)}

    def launch(self, chat_id: uuid.UUID, plan: dict) -> dict[str, str]:
        workspace_path(root=self.root, chat_id=chat_id)
        with httpx.Client(base_url=self.url, timeout=180) as client:
            response = client.post(f"/workloads/{chat_id}/launch", json=plan)
            response.raise_for_status()
            return response.json()

    def acceptance_state(self, *, timeout_seconds: float) -> dict:
        return self._acceptance_request("GET", "/testing/acceptance/state", timeout_seconds=timeout_seconds)

    def acceptance_control(self, action: str, *, run_id: str, reset_id: str, expected_generation: int, timeout_seconds: float, **extra: object) -> dict:
        if action not in {"quiesce", "reset", "resume"}:
            raise ValueError("Invalid acceptance controller operation")
        return self._acceptance_request("POST", f"/testing/acceptance/{action}", timeout_seconds=timeout_seconds, body={
            "run_id": run_id, "reset_id": reset_id, "expected_generation": expected_generation,
            "timeout_seconds": min(timeout_seconds, 300), **extra,
        })

    def _acceptance_request(self, method: str, path: str, *, timeout_seconds: float, body: dict | None = None) -> dict:
        from app.core.config import settings

        if not (settings.DEVELOP_ACCEPTANCE_MODE and settings.DEVELOP_ACCEPTANCE_RESET_ENABLED and settings.ACCEPTANCE_RESET_TOKEN):
            raise RuntimeError("Acceptance controller controls are disabled")
        if timeout_seconds <= 0:
            raise TimeoutError("Acceptance controller deadline exceeded")
        headers = {"Authorization": "Bearer " + settings.ACCEPTANCE_RESET_TOKEN.get_secret_value(),
                   "X-Acceptance-Run": settings.ACCEPTANCE_RUN_ID}
        with httpx.Client(base_url=self.url, timeout=timeout_seconds) as client:
            response = client.request(method, path, headers=headers, json=body)
            response.raise_for_status()
            result = response.json()
            if not isinstance(result, dict):
                raise RuntimeError("Invalid acceptance controller response")
            return result

    def _request(self, method: str, path: str) -> dict[str, str]:
        timeout = 180 if method in ("POST", "PUT") and path.count("/") == 2 else 10
        with httpx.Client(base_url=self.url, timeout=timeout) as client:
            response = client.request(method, path)
            response.raise_for_status()
            return response.json()
