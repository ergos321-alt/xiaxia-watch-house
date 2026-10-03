# Security

- Never commit `.env`, database URLs, bearer tokens, provider keys, or credentials. Load them from server-side environment variables or secure runtime configuration.
- Use unique, high-entropy bearer tokens. Keep provider keys and Supabase service-role credentials server-side only.
- Screen, sensor, location, device, and activity data are highly sensitive. Keep production databases private; do not publish screenshots, raw logs, database exports, or personal location history.
- Do not include secrets or private activity data in public issues. Use GitHub private vulnerability reporting when enabled, or contact the maintainer privately through GitHub.
