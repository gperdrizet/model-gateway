# API quickstart

## Register and get a key

Go to `https://promptlyapi.com` and create an account.

You will receive an API key by email.

## Python (OpenAI SDK): chat completions

```python
import os
from openai import OpenAI

client = OpenAI(
    base_url="https://promptlyapi.com/v1",
    api_key=os.environ["PROMPTLY_API_KEY"],
)

completion = client.chat.completions.create(
    model="default",
    messages=[{"role": "user", "content": "Hello!"}],
)

print(completion.choices[0].message.content)
```

## Python (OpenAI SDK): responses

```python
import os
from openai import OpenAI

client = OpenAI(
    base_url="https://promptlyapi.com/v1",
    api_key=os.environ["PROMPTLY_API_KEY"],
)

response = client.responses.create(
    model="default",
    input="Hello!",
)

print(response.output_text)
```

## curl

```bash
curl https://promptlyapi.com/v1/chat/completions \
  -H "Authorization: Bearer sk-your-key-here" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "default",
    "messages": [{"role": "user", "content": "Hello!"}]
  }'
```
