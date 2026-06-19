# Operations

## Health check

```bash
curl -fsS https://promptlyapi.com/health
```

Expected response:

```json
{"status":"ok"}
```

## Rate limits

- 120 requests/min per IP
- 60 requests/min per API key

## Balance behavior

When a user runs out of tokens, inference requests return `402 Payment Required`.

## Dashboard

Users can view balance and usage at:

`https://promptlyapi.com/dashboard?key=sk-your-key-here`
