FROM node:24.15-bookworm-slim@sha256:4e6b70dd6cbfc88c8157ba19aa3d9f9cce6ba4703576d55459e45efcbc9c5f5d AS node
FROM oven/bun:1@sha256:9114c058aeae42162ee16dd5084b95fe9473970bb6bcb5b232ab1630f0546895 AS bun
FROM ghcr.io/astral-sh/uv:0.9.26@sha256:9a23023be68b2ed09750ae636228e903a54a05ea56ed03a934d00fe9fbeded4b AS uv

FROM python:3.14-slim-bookworm@sha256:c8137f4c460908c8763f281c8f22c431eb5c538514ba9553fc3a89c06b7cfb88
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules /usr/local/lib/node_modules
COPY --from=bun /usr/local/bin/bun /usr/local/bin/bun
COPY --from=uv /uv /uvx /usr/local/bin/
RUN ln -s ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm
RUN uv pip install --system pyyaml==6.0.3
COPY backend/app/services/preview_controller.py /controller/preview_controller.py
COPY backend/app/services/preview_compose.py /controller/app/services/preview_compose.py
COPY backend/app/services/preview_workspace_sync.py /controller/app/services/preview_workspace_sync.py
COPY backend/app/services/preview_registry_proxy.py /controller/preview_registry_proxy.py
COPY backend/app/services/preview_proxy_client.py /controller/preview_proxy_client.py
COPY backend/app/services/preview_workspace_sync.py /controller/preview_workspace_sync.py
CMD ["python", "/controller/preview_controller.py"]