# Deployment

## Supported Deployment Target

The supported MVP deployment target is Docker Compose in a customer-controlled environment.

## Prerequisites

- Docker Engine with Docker Compose
- Customer-provided OpenAI-compatible model endpoint and API key
- At least 2 CPU cores, 4 GB RAM, and enough storage for uploaded documents

For a fresh VPS, the repository now includes:

- `bootstrap-vps.sh`, which clones or updates the repository from GitHub and then starts the project deployment flow
- `deploy-vps.sh`, which installs Docker on Ubuntu or Debian, prepares `.env`, starts the compose stack, and waits for the health checks

## VPS One-Click Deploy

### If the repository is already on the VPS

Run:

```bash
sudo bash ./deploy-vps.sh
```

### If you want a GitHub-to-VPS single-command deploy

Run:

```bash
curl -fsSL https://raw.githubusercontent.com/<owner>/<repo>/<branch>/bootstrap-vps.sh | \
  sudo env REPO_URL=https://github.com/<owner>/<repo>.git BRANCH=<branch> bash
```

If you already know the production domain, pass `APP_BASE_URL` at the same time:

```bash
curl -fsSL https://raw.githubusercontent.com/<owner>/<repo>/<branch>/bootstrap-vps.sh | \
  sudo env \
    REPO_URL=https://github.com/<owner>/<repo>.git \
    BRANCH=<branch> \
    APP_BASE_URL=https://translate.example.com \
    bash
```

`bootstrap-vps.sh` clones or updates the repository into `/opt/doc-translator` by default and then runs `deploy-vps.sh`.

### What `deploy-vps.sh` does

- install Docker Engine and the compose plugin if missing
- create `.env` from `.env.example` when needed
- prompt for the model endpoint, API key, admin email, and admin password unless already set
- switch `APP_ENV` to `production`
- start the stack with `docker-compose.yml` and `docker-compose.vps.yml`
- wait until `postgres`, `redis`, `api`, `worker`, and `web` report healthy status

You can also run it non-interactively by exporting the required variables before execution, for example `MODEL_API_KEY`, `MODEL_BASE_URL`, `MODEL_NAME`, `ADMIN_EMAIL`, `ADMIN_PASSWORD`, and optionally `APP_BASE_URL`.

## Domain Setup

1. Add an `A` record that points your domain, for example `translate.example.com`, to the VPS public IP.
2. Set `APP_BASE_URL=https://translate.example.com` before the first deployment, or update it later in `.env` and rerun the deploy script.
3. Put a reverse proxy with HTTPS in front of the `web` service.

Example Caddy site block:

```caddyfile
translate.example.com {
    reverse_proxy 127.0.0.1:3000
}
```

After the proxy is reloaded, open `https://translate.example.com`.

If the VPS is public, also restrict direct access to ports `3000` and `8000` with the VPS firewall or cloud security group so traffic enters only through `80/443`.

## Steps

1. Copy `.env.example` to `.env`.
2. Replace `APP_SECRET_KEY`, `ADMIN_PASSWORD`, and the model settings.
3. Review `LOCAL_STORAGE_PATH`, `FILE_RETENTION_DAYS`, and `MAX_CONCURRENT_JOBS`.
4. Start the stack:

```powershell
.\dev.ps1
```

5. The script will create `.env` from `.env.example` if needed, start Docker Desktop when possible, build the images, and wait for all service health checks.
6. Open [http://localhost:3000](http://localhost:3000).
7. Sign in with `ADMIN_EMAIL` and `ADMIN_PASSWORD`.
8. Open the admin settings panel and verify the configured model endpoint with the connection test.

Useful commands:

- `.\dev.ps1 logs`
- `.\dev.ps1 status`
- `.\dev.ps1 down`

## Volumes

- `postgres_data`: PostgreSQL data directory
- `redis_data`: Redis persistence
- `files_data`: original and translated document storage

## Reverse Proxy and HTTPS

This MVP expects HTTPS to be terminated by a customer-managed reverse proxy in front of the `web` service.

Recommended reverse proxy behavior:

- Terminate TLS at the proxy
- Forward traffic to `web:3000`
- Restrict direct access to the published API port if the VPS is exposed to the public internet
- Restrict network egress so only the chosen model endpoint is reachable if required by policy

## Network Boundary Reminder

The application stores files only on customer-managed infrastructure. If the configured model endpoint is external, translated text is sent to that endpoint during processing.
