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
              body: bytes | None = None, content_type: str = "") -> dict:
        if len(path) + len(query) > 2000 or not path.startswith("/") or path.startswith("//"):
            raise ValueError("Invalid preview path")
        with httpx.Client(base_url=self.url, timeout=20) as client:
            destination = f"/workloads/{chat_id}/browser?path={quote(path + ('?' + query if query else ''), safe='')}"
            if port is not None:
                destination += f"&port={quote(port, safe='')}"
            if body is None:
                response = client.get(destination)
            else:
                response = client.post(destination, json={"body": base64.b64encode(body).decode(),
                                                          "content_type": content_type})
            response.raise_for_status()
            result = response.json()
            return {"status": result["status"], "location": result.get("location", ""),
                    "content_type": result["content_type"],
                    "body": base64.b64decode(result["body"], validate=True)}

    def launch(self, chat_id: uuid.UUID, plan: dict) -> dict[str, str]:
        workspace_path(root=self.root, chat_id=chat_id)
        with httpx.Client(base_url=self.url, timeout=180) as client:
            response = client.post(f"/workloads/{chat_id}/launch", json=plan)
            response.raise_for_status()
            return response.json()

    def _request(self, method: str, path: str) -> dict[str, str]:
        timeout = 180 if method in ("POST", "PUT") and path.count("/") == 2 else 10
        with httpx.Client(base_url=self.url, timeout=timeout) as client:
            response = client.request(method, path)
            response.raise_for_status()
            return response.json()
