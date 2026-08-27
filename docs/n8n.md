# Using Promptly with n8n

[n8n](https://n8n.io) is a workflow automation tool with built-in AI nodes. Its native **OpenAI** credential and **OpenAI Chat Model** node authenticate directly against `api.openai.com` and don't expose a base URL override in their documented settings, so you can't point that specific node at Promptly.

The practical way to use Promptly from n8n is its generic **HTTP Request** node, which can call any REST API - including Promptly's OpenAI-compatible endpoint directly.

## 1. Get a Promptly API key

If you don't already have one, go to `https://promptlyapi.com`, create an account, and you'll receive an API key by email.

## 2. Add an HTTP Request node

Configure it as follows:

- **Method:** `POST`
- **URL:** `https://promptlyapi.com/v1/chat/completions`
- **Authentication:** Generic Credential Type -> Header Auth
  - **Name:** `Authorization`
  - **Value:** `Bearer sk-your-key-here`
- **Body Content Type:** JSON
- **Body:**

```json
{
  "model": "default",
  "messages": [
    {"role": "user", "content": "={{ $json.prompt }}"}
  ]
}
```

Adjust the `messages` expression to pull from whatever field earlier nodes in your workflow produce. The response lands in the HTTP Request node's output at `choices[0].message.content`, same as any OpenAI-compatible client.

## Streaming

n8n's HTTP Request node isn't built for streaming SSE responses in a workflow context, so leave `"stream"` unset (or `false`) - workflows generally want a single complete response per node execution anyway.

## Notes

- Promptly ignores whatever `model` field you send and always serves whichever model is currently loaded (currently `Qwen3.8-27B-Q8_0.gguf`, 262,144-token context).
- The model defaults to `reasoning_effort: medium`; you can override it per request by adding a top-level `"reasoning_effort"` field (`none`, `low`, `medium`, `high`) to the JSON body above.
- Check your token balance any time at `https://promptlyapi.com/dashboard?key=sk-your-key-here`.
- If n8n adds native custom-base-URL support to its OpenAI node in the future, that would be a more direct integration than the HTTP Request node - worth checking n8n's release notes if this becomes a frequent workflow for you.
