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
- `.env.vps.example`, which is the editable production env template used to create `.env` on the VPS, including `CERTBOT_EMAIL`

## VPS One-Click Deploy

### If the repository is already on the VPS

Run:

```bash
sudo bash ./deploy-vps.sh
```

### If you want a GitHub-to-VPS single-command deploy

Run:

```bash
curl -fsSL https://raw.githubusercontent.com/i2Echo/doc-translator/main/bootstrap-vps.sh | \
  sudo bash
```

If you want to pin a different branch, pass `BRANCH`. If you already know the production domain, pass `APP_BASE_URL` at the same time:

```bash
curl -fsSL https://raw.githubusercontent.com/i2Echo/doc-translator/main/bootstrap-vps.sh | \
  sudo env \
    BRANCH=main \
    APP_BASE_URL=https://translate.example.com \
    bash
```

`bootstrap-vps.sh` clones or updates the repository into `/opt/doc-translator` by default and then runs `deploy-vps.sh`.

### What `deploy-vps.sh` does

- install Docker Engine and the compose plugin if missing
- create `.env` from `.env.vps.example` when needed
- prompt for the model endpoint, API key, admin email, and admin password unless already set
- switch `APP_ENV` to `production`
- start the stack with `docker-compose.yml` and `docker-compose.vps.yml`
- wait until `postgres`, `redis`, `api`, `worker`, and `web` report healthy status
- install and configure a host-level Nginx reverse proxy to `127.0.0.1:3000`
- automatically obtain a Let's Encrypt certificate and enable `certbot.timer` when `APP_BASE_URL` uses `https://`

You can also run it non-interactively by exporting the required variables before execution, for example `MODEL_API_KEY`, `MODEL_BASE_URL`, `MODEL_NAME`, `ADMIN_EMAIL`, `ADMIN_PASSWORD`, optionally `CERTBOT_EMAIL`, and `APP_BASE_URL`.

## Domain Setup

1. Add an `A` record that points your domain, for example `translate.example.com`, to the VPS public IP.
2. Set `APP_BASE_URL=https://translate.example.com` before the first deployment if DNS is already live and ports `80/443` are open.
3. `deploy-vps.sh` will install Nginx on the VPS, reverse proxy requests to `127.0.0.1:3000`, and automatically request a Let's Encrypt certificate.
4. If DNS is not ready yet, deploy once with `http://`, then switch `APP_BASE_URL` to `https://...` later and rerun `deploy-vps.sh`.

On the VPS, the editable production env file is:

```text
/opt/doc-translator/.env
```

It is created automatically from:

```text
/opt/doc-translator/.env.vps.example
```

The generated Nginx site file is:

```text
/etc/nginx/sites-available/doc-translator
```

After deployment, open the URL you set in `APP_BASE_URL`.

If HTTPS is enabled, `deploy-vps.sh` uses Certbot and enables automatic renewal through `certbot.timer`. You can verify it with:

```bash
sudo systemctl status certbot.timer
sudo certbot renew --dry-run
```

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

This MVP expects reverse proxy traffic to terminate on the VPS host and then forward to the `web` service over loopback.

Recommended reverse proxy behavior:

- Forward traffic to `127.0.0.1:3000`
- Set `client_max_body_size` to at least the configured `MAX_UPLOAD_MB`
- Keep ports `80/443` open so Certbot can validate and renew domain certificates
- Restrict direct access to the published API port if the VPS is exposed to the public internet
- Restrict network egress so only the chosen model endpoint is reachable if required by policy

## Network Boundary Reminder

The application stores files only on customer-managed infrastructure. If the configured model endpoint is external, translated text is sent to that endpoint during processing.
