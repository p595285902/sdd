import uuid
from pathlib import Path

import httpx
import pytest

from app.services.develop_preview_runtime import PreviewController


@pytest.mark.parametrize(('method', 'suffix', 'timeout'), [
    ('POST', '', 180),
    ('PUT', '', 180),
    ('DELETE', '', 180),
    ('GET', '', 10),
    ('POST', '/activity', 10),
    ('DELETE', '/unexpected', 10),
])
def test_lifecycle_requests_allow_cleanup_without_extending_observation_timeouts(
    monkeypatch, tmp_path: Path, method: str, suffix: str, timeout: int,
):
    chat_id = uuid.uuid4()
    seen = []
    real_client = httpx.Client

    def handle(request):
        seen.append(request)
        return httpx.Response(200, json={'state': 'stopped'})

    def client(**kwargs):
        return real_client(**kwargs, transport=httpx.MockTransport(handle))

    monkeypatch.setattr(httpx, 'Client', client)
    controller = PreviewController(root=tmp_path, url='http://preview-controller:8090')
    if method == 'DELETE' and not suffix:
        result = controller.stop(chat_id)
    else:
        result = controller._request(method, f'/workloads/{chat_id}{suffix}')
    assert result == {'state': 'stopped'}
    assert len(seen) == 1
    assert seen[0].method == method
    assert seen[0].url.path == f'/workloads/{chat_id}{suffix}'
    assert seen[0].extensions['timeout'] == dict.fromkeys(('connect', 'read', 'write', 'pool'), timeout)
