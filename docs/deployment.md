# Deployment

## Supported Deployment Target

The supported MVP deployment target is Docker Compose in a customer-controlled environment.

## Prerequisites

- Docker Engine with Docker Compose
- Customer-provided OpenAI-compatible model endpoint and API key
- At least 2 CPU cores, 4 GB RAM, and enough storage for uploaded documents

## Steps

1. Copy `.env.example` to `.env`.
2. Replace `APP_SECRET_KEY`, `ADMIN_PASSWORD`, and the model settings.
3. Review `LOCAL_STORAGE_PATH`, `FILE_RETENTION_DAYS`, and `MAX_CONCURRENT_JOBS`.
4. Start the stack:

```bash
docker compose up --build -d
```

5. Open [http://localhost:3000](http://localhost:3000).
6. Sign in with `ADMIN_EMAIL` and `ADMIN_PASSWORD`.
7. Open the admin settings panel and verify the configured model endpoint with the connection test.

## Volumes

- `postgres_data`: PostgreSQL data directory
- `redis_data`: Redis persistence
- `files_data`: original and translated document storage

## Reverse Proxy and HTTPS

This MVP expects HTTPS to be terminated by a customer-managed reverse proxy in front of the `web` service.

Recommended reverse proxy behavior:

- Terminate TLS at the proxy
- Forward traffic to `web:80`
- Restrict network egress so only the chosen model endpoint is reachable if required by policy

## Network Boundary Reminder

The application stores files only on customer-managed infrastructure. If the configured model endpoint is external, translated text is sent to that endpoint during processing.

