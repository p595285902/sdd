# The platform controller and project daemon are separate images/processes.
# Only this image is used for the private native-Compose outer sandbox.
FROM docker:28.5.1-dind-rootless@sha256:87d03cfe51f2bf87eec6dda1922dc572da4d37a1d21c5ca8e8b22c8a1fa107cc
USER root
RUN apk add --no-cache python3
COPY backend/app/services/preview_native_session.py /opt/preview/preview_native_session.py
COPY backend/app/services/preview_native_plan.py /opt/preview/preview_native_plan.py
COPY backend/app/services/preview_redaction.py /opt/preview/preview_redaction.py
USER rootless
