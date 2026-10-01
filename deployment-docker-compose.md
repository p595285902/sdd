# FastAPI Project - Docker Compose Deployment

You can deploy the project to your own remote server with Docker Compose. The deployment configuration includes Traefik to handle HTTPS and route incoming traffic to the application.

## Preparation

* Have a remote server ready and available.
* Configure DNS records pointing to the server for the application domain and any supporting service subdomains you want to expose, such as `fastapi-project.example.com` and `adminer.fastapi-project.example.com`.
* Install and configure [Docker](https://docs.docker.com/engine/install/) on the remote server (Docker Engine, not Docker Desktop).

## Copy the Code

```bash
rsync -av --exclude=".git/" --filter=":- .gitignore" ./ root@your-server.example.com:/root/code/app/
```

The `--filter=":- .gitignore"` option tells `rsync` to use the same ignore rules as Git, excluding files such as the Python virtual environment.

## Configure the Application

### Environment Variables

Set the application domain, project name, and first superuser email:

```bash
export DOMAIN=fastapi-project.example.com
export PROJECT_NAME="Full Stack FastAPI Project"
export FIRST_SUPERUSER=admin@example.com
```

You can also configure these environment variables as needed:

* `SMTP_HOST`: The SMTP server host from your email provider.
* `SMTP_USER`: The SMTP server user.
* `EMAILS_FROM_EMAIL`: The email account used to send emails.
* `SENTRY_DSN`: The DSN for Sentry.
* `DEMO_GITHUB_REPO`: The tokenless HTTPS URL cloned into new Development Workspaces.

Develop may be disabled by leaving `DEMO_GITHUB_REPO`, `DEMO_GITHUB_TOKEN`, and `OPENAI_API_KEY` unset. A production deployment that sets any one of them must set all three or backend startup fails. The Compose deployment stores workspaces at `DEVELOP_WORKSPACE_ROOT=/develop-workspaces` on the `sdd-develop-workspaces` named volume.

### Secrets

Generate and set secure values for the database password, token signing key, and first superuser password:

```bash
export POSTGRES_PASSWORD="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
export SECRET_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
export FIRST_SUPERUSER_PASSWORD="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
```

To use an authenticated email provider, also set `SMTP_PASSWORD`.

To enable Develop, inject `DEMO_GITHUB_TOKEN` and `OPENAI_API_KEY` as runtime secrets. Do not add repository or provider credentials to the Dockerfile, image build arguments, or committed environment files.

## Deploy

```bash
cd /root/code/app/
docker compose -f compose.yml -f compose.deploy.yml build
docker compose -f compose.yml -f compose.deploy.yml run --rm backend bash scripts/prestart.sh
docker compose -f compose.yml -f compose.deploy.yml up -d
```

The `compose.deploy.yml` file adds HTTPS and automatic certificate handling to the shared `compose.yml` configuration. Explicitly listing both files excludes the local settings from `compose.override.yml`.

The backend Docker image builds the frontend, so the server does not need Bun or prebuilt frontend files.

### Develop CLI Versions

The backend image pins OpenCode `1.18.23` and OpenSpec `1.13.0`. This pair is verified against the Develop workflow, including `opencode init`, `openspec init --tools opencode`, and OpenSpec action commands. Update and verify both versions together before changing either Docker build argument.

### Develop Runtime Topology

The initial deployment runs exactly one FastAPI worker because Agent Turn admission, replay, reattachment, and stop coordination are process-local. Multiple workers or hosts require durable distributed admission, a shared event log, and shared workspace storage before they are safe to enable.

The `sdd-develop-workspaces` volume preserves repositories across backend container replacement. Back it up and monitor its growth. Do not use `docker compose down --volumes` during routine deployments because that deletes the workspace volume along with other named volumes.

Develop streams Agent Turn events using server-sent events with a 15-second heartbeat. Any proxy or load balancer in front of the backend must:

* disable response buffering and compression for event streams;
* flush chunks immediately and preserve `Cache-Control: no-cache`, `Connection: keep-alive`, and `X-Accel-Buffering: no` response headers;
* set idle and request timeouts above the configured heartbeat interval, with at least 60 seconds recommended.

The included Traefik service sets its response forwarding flush interval to `-1ms` for immediate streaming. Apply equivalent settings when replacing Traefik.

After building the image, run the deployment checks from `acceptance-tests/`:

```bash
npm run test:runtime
```

The check verifies normalized Compose storage and streaming configuration, exact executable versions, the single-worker image command, writable workspace storage, and persistence across container replacement.

## Deploy with GitHub Actions

The included `.github/workflows/deploy-docker-compose.yml` workflow runs the deployment commands on the server when manually triggered from GitHub Actions.

Use a self-hosted runner only for a repository whose contributors and workflow code you trust. GitHub recommends using self-hosted runners with private repositories because workflows execute directly on the runner machine.

### Configure Repository Variables and Secrets

In the repository, go to **Settings** > **Secrets and variables** > **Actions** and add these repository variables:

* `DOMAIN`
* `PROJECT_NAME`
* `FIRST_SUPERUSER`

To enable emails, add these optional repository variables:

* `SMTP_HOST`
* `SMTP_USER`
* `EMAILS_FROM_EMAIL`

To enable Sentry, add the optional `SENTRY_DSN` repository variable.

Add these repository secrets:

* `POSTGRES_PASSWORD`
* `SECRET_KEY`
* `FIRST_SUPERUSER_PASSWORD`

To use an authenticated email provider, add the optional `SMTP_PASSWORD` repository secret.

### Install a Self-Hosted Runner

On the server, create a dedicated user and grant it access to Docker:

```bash
sudo adduser github
sudo usermod -aG docker github
sudo su - github
```

In the GitHub repository, go to **Settings** > **Actions** > **Runners**, select **New self-hosted runner**, choose Linux, and follow the commands GitHub provides to download, configure, and register the runner. Install it in `/home/github/actions-runner`.

After registering the runner, exit the `github` user session and install the runner as a system service:

```bash
exit
cd /home/github/actions-runner
sudo ./svc.sh install github
sudo ./svc.sh start
sudo ./svc.sh status
```

See GitHub's guides for [adding a self-hosted runner](https://docs.github.com/en/actions/how-tos/manage-runners/self-hosted-runners/add-runners) and [configuring the runner as a service](https://docs.github.com/en/actions/how-tos/manage-runners/self-hosted-runners/configure-the-application?platform=linux).

### Run the Deployment

When the runner is online, open the repository's **Actions** tab, select **Deploy with Docker Compose**, and select **Run workflow**.

## URLs

Replace `fastapi-project.example.com` with your domain.

Application (frontend and API): `https://fastapi-project.example.com`

Interactive API docs: `https://fastapi-project.example.com/docs`

Adminer: `https://adminer.fastapi-project.example.com`
