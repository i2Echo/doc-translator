# Doc Translator

Doc Translator is a private-deployment document translation MVP for small companies. It keeps original and translated files inside customer-controlled storage, lets admins configure a customer-provided OpenAI-compatible model endpoint, and runs asynchronous PDF or DOCX translation jobs with audit logging.

## Privacy Boundary

Files stay inside the customer's environment, but translated text may still leave the network if the configured model endpoint is external.

- File storage remains on customer-controlled volumes.
- Model traffic goes only to the endpoint configured by the customer.
- If the model endpoint is outside the trusted network, document text is sent there by design.

## MVP Capabilities

- Local authentication with admin and standard user roles
- Admin settings for model endpoint, storage, OCR, retention, and concurrency
- PDF and DOCX upload with asynchronous translation jobs
- OCR fallback for scanned PDFs
- Job events, retry, cancel, download, and audit logs
- Retention cleanup for expired stored files
- Docker Compose deployment with `web`, `api`, `worker`, `postgres`, and `redis`

## Repository Layout

```text
doc-translator/
  apps/
    api/
    web/
    worker/
  docs/
  infra/
  plan.md
  docker-compose.yml
```

## Quick Start

1. Copy `.env.example` to `.env` and replace the secrets and model settings.
2. Start the stack with `docker compose up --build`.
3. Open [http://localhost:3000](http://localhost:3000).
4. Sign in with `ADMIN_EMAIL` and `ADMIN_PASSWORD` from the environment.
5. Update the model endpoint in the admin settings screen if needed.

## Running Without Docker

The Docker path is the supported default for the MVP. If you need a local Python workflow instead:

1. Create PostgreSQL and Redis instances.
2. Install `apps/api/requirements.txt`.
3. Export environment variables from `.env.example`.
4. Run `alembic upgrade head`.
5. Start the API with `uvicorn --app-dir apps/api doc_translator.api.main:app --reload`.
6. Start the worker with `python apps/worker/main.py`.
7. Serve `apps/web` from any static web server that proxies `/api` to the API service.

## Documentation

- [Architecture](docs/architecture.md)
- [Deployment](docs/deployment.md)
- [Operations](docs/operations.md)
