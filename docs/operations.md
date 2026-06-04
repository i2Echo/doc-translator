# Operations

## Health Endpoints

- API live: `/api/v1/health/live`
- API ready: `/api/v1/health/ready`
- Worker live: `/health/live`
- Worker ready: `/health/ready`

## Backup and Restore

### Backup

- Back up the PostgreSQL database volume.
- Back up the shared file storage volume.
- Keep a secure copy of the `.env` values or their secret-store equivalents.

### Restore

1. Restore `postgres_data`.
2. Restore `files_data`.
3. Start the stack with the same or compatible image versions.
4. Verify API and worker readiness.

## Retention Cleanup

- The worker runs periodic cleanup based on `FILE_RETENTION_DAYS`.
- Expired files are removed from disk and marked as deleted in the database.
- Audit logs record retention deletions.

## Troubleshooting

### Model connection failures

- Verify `MODEL_BASE_URL`, `MODEL_API_KEY`, and `MODEL_NAME`.
- Use the admin connection test to confirm the endpoint responds.
- Check whether outbound network policy allows the configured host.

### Jobs stay queued

- Confirm Redis is healthy.
- Check the worker health endpoint.
- Review worker logs for translation failures or OCR errors.

### OCR quality is poor

- Verify that `OCR_ENABLED` is set to `true`.
- Try a higher-quality scan or a more specific `OCR_LANGUAGE_HINT`.
- Review job events to confirm OCR was used.

### Downloads fail after completion

- Check whether the retention window has already expired.
- Confirm the shared `files_data` volume is mounted in both `api` and `worker`.

