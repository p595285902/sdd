import uuid
from pathlib import Path

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

    def launch(self, chat_id: uuid.UUID, plan: dict) -> dict[str, str]:
        workspace_path(root=self.root, chat_id=chat_id)
        with httpx.Client(base_url=self.url, timeout=180) as client:
            response = client.post(f"/workloads/{chat_id}/launch", json=plan)
            response.raise_for_status()
            return response.json()

    def _request(self, method: str, path: str) -> dict[str, str]:
        with httpx.Client(base_url=self.url, timeout=10) as client:
            response = client.request(method, path)
            response.raise_for_status()
            return response.json()
