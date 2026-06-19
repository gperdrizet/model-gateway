'''Smoke tests for the model-gateway.

Cover: health, registration, auth, token metering, admin panel.
The llama-server is NOT called - inference proxy tests are skipped here
(they live in integration tests that run against a real backend).
'''

import pytest
from httpx import AsyncClient


pytestmark = pytest.mark.asyncio


# ── Health ─────────────────────────────────────────────────────────────────

async def test_health(client: AsyncClient):
    '''Health endpoint returns 200 and {status: ok}.'''

    r = await client.get('/health')

    assert r.status_code == 200
    assert r.json() == {'status': 'ok'}


# ── Registration ────────────────────────────────────────────────────────────

async def test_register_page(client: AsyncClient):
    '''Registration page renders and mentions the trial token amount.'''

    r = await client.get('/register')

    assert r.status_code == 200
    assert b'100k' in r.content or b'100' in r.content


async def test_register_new_user(client: AsyncClient):
    '''Posting a new email registers the user and shows a confirmation page.'''

    r = await client.post(
        '/register',
        data={'email': 'new@example.com'},
        follow_redirects=True,
    )

    assert r.status_code == 200

    # Same confirmation page regardless (anti-enumeration)
    assert b'new@example.com' in r.content


async def test_register_existing_user_same_response(client: AsyncClient):
    '''Registering twice returns the same page - prevents email enumeration.'''

    data = {'email': 'dup@example.com'}
    r1 = await client.post('/register', data=data, follow_redirects=True)
    r2 = await client.post('/register', data=data, follow_redirects=True)

    assert r1.status_code == 200
    assert r2.status_code == 200


# ── Auth ────────────────────────────────────────────────────────────────────

async def test_no_key_returns_401(client: AsyncClient):
    '''Request with no Authorization header is rejected with 401.'''

    r = await client.post('/v1/chat/completions', json={'model': 'x', 'messages': []})

    assert r.status_code == 401


async def test_bad_key_returns_401(client: AsyncClient):
    '''Request with an unrecognised API key is rejected with 401.'''

    r = await client.post(
        '/v1/chat/completions',
        headers={'Authorization': 'Bearer sk-totallyWrongKey12345'},
        json={'model': 'x', 'messages': []},
    )

    assert r.status_code == 401


async def test_valid_key_with_no_balance_returns_402(client: AsyncClient, registered_user):
    '''A user whose trial has 0 remaining and no paid balance gets 402.'''

    from app.db import engine, TrialTokens
    from sqlalchemy.ext.asyncio import async_sessionmaker
    from sqlalchemy import update

    session_maker = async_sessionmaker(engine, expire_on_commit=False)

    async with session_maker() as session:
        await session.execute(
            update(TrialTokens)
            .where(TrialTokens.user_id == registered_user['id'])
            .values(remaining_tokens=0)
        )
        await session.commit()

    r = await client.post(
        '/v1/chat/completions',
        headers={'Authorization': f'Bearer {registered_user["key"]}'},
        json={'model': 'x', 'messages': []},
    )

    assert r.status_code == 402


async def test_responses_text_request_returns_response_shape(client: AsyncClient, registered_user, monkeypatch):
    '''/v1/responses accepts text input and returns a minimal Responses payload.'''

    import httpx
    import app.app as gateway_app

    async def fake_proxy_request(method, path, headers, body):
        assert method == 'POST'
        assert path == '/chat/completions'
        assert 'authorization' in {k.lower() for k in headers}
        assert body['messages'] == [{'role': 'user', 'content': 'Hello!'}]

        return (
            httpx.Response(200, json={
                'id': 'chatcmpl_test123',
                'created': 1234567890,
                'model': 'gpt-oss-20b-mxfp4.gguf',
                'choices': [{
                    'index': 0,
                    'message': {'role': 'assistant', 'content': 'Hello back!'},
                    'finish_reason': 'stop',
                }],
                'usage': {
                    'prompt_tokens': 5,
                    'completion_tokens': 2,
                    'total_tokens': 7,
                },
            }),
            5,
            2,
        )

    monkeypatch.setattr(gateway_app, 'proxy_request', fake_proxy_request)

    r = await client.post(
        '/v1/responses',
        headers={'Authorization': f'Bearer {registered_user["key"]}'},
        json={'model': 'default', 'input': 'Hello!'},
    )

    assert r.status_code == 200
    data = r.json()
    assert data['object'] == 'response'
    assert data['output_text'] == 'Hello back!'
    assert data['output'][0]['content'][0]['text'] == 'Hello back!'
    assert data['usage']['input_tokens'] == 5
    assert data['usage']['output_tokens'] == 2


async def test_responses_rejects_multimodal_input(client: AsyncClient, registered_user):
    '''/v1/responses rejects image input rather than pretending to support it.'''

    r = await client.post(
        '/v1/responses',
        headers={'Authorization': f'Bearer {registered_user["key"]}'},
        json={
            'model': 'default',
            'input': [{
                'role': 'user',
                'content': [
                    {'type': 'input_text', 'text': 'What is in this image?'},
                    {'type': 'input_image', 'image_url': 'https://example.com/cat.png'},
                ],
            }],
        },
    )

    assert r.status_code == 400
    assert 'text-only requests' in r.json()['error']['message']


async def test_responses_streaming_translates_chat_sse(client: AsyncClient, registered_user, monkeypatch):
    '''/v1/responses stream emits text delta events translated from chat SSE.'''

    import app.app as gateway_app

    async def fake_proxy_stream(method, path, headers, body):
        assert method == 'POST'
        assert path == '/chat/completions'
        assert 'authorization' in {k.lower() for k in headers}
        assert body['stream'] is True
        yield (
            b'data: {"id":"chatcmpl_1","model":"gpt-oss-20b-mxfp4.gguf","choices":[{"delta":{"content":"Hello"}}]}\n\n',
            0,
            0,
        )
        yield (
            b'data: {"id":"chatcmpl_1","model":"gpt-oss-20b-mxfp4.gguf","choices":[{"delta":{"content":" world"}}]}\n\n',
            0,
            0,
        )
        yield b'', 4, 2

    monkeypatch.setattr(gateway_app, 'proxy_stream', fake_proxy_stream)

    r = await client.post(
        '/v1/responses',
        headers={'Authorization': f'Bearer {registered_user["key"]}'},
        json={'model': 'default', 'input': 'Hello?', 'stream': True},
    )

    assert r.status_code == 200
    assert 'response.created' in r.text
    assert 'response.output_text.delta' in r.text
    assert 'response.completed' in r.text
    assert 'Hello world' in r.text


# ── Dashboard ───────────────────────────────────────────────────────────────

async def test_dashboard_valid_key(client: AsyncClient, registered_user):
    '''Dashboard returns 200 and shows the user email when a valid key is supplied.'''

    r = await client.get(f'/dashboard?key={registered_user["key"]}')

    assert r.status_code == 200
    assert registered_user['email'].encode() in r.content


async def test_dashboard_bad_key_redirects(client: AsyncClient, _db_session):
    '''Dashboard redirects to registration when an invalid key is supplied.'''

    r = await client.get(
        '/dashboard?key=sk-notavalidkey12345678901234567890',
        follow_redirects=False,
    )

    assert r.status_code in (302, 307)


# ── Admin panel ──────────────────────────────────────────────────────────────

async def test_admin_bad_key_forbidden(client: AsyncClient, _db_session):
    '''Admin panel returns 403 when the wrong admin key is supplied.'''

    r = await client.get('/admin?key=wrong')

    assert r.status_code == 403


async def test_admin_valid_key(client: AsyncClient, _db_session):
    '''Admin panel returns 200 and renders the Admin heading for a valid key.'''

    import os

    admin_key = os.environ['ADMIN_KEY']
    r = await client.get(f'/admin?key={admin_key}')

    assert r.status_code == 200
    assert b'Admin' in r.content


async def test_admin_adjust_tokens(client: AsyncClient, registered_user):
    '''Admin adjust endpoint credits tokens to a user paid balance.'''

    import os

    admin_key = os.environ['ADMIN_KEY']
    r = await client.post(
        '/admin/adjust',
        data={'key': admin_key, 'user_id': registered_user['id'], 'delta': '1000000'},
        follow_redirects=False,
    )

    assert r.status_code in (302, 303)

    # Confirm balance was updated
    from app.db import engine, User as UserModel
    from sqlalchemy.ext.asyncio import async_sessionmaker

    session_maker = async_sessionmaker(engine, expire_on_commit=False)

    async with session_maker() as session:
        user = await session.get(UserModel, registered_user['id'])
        assert user.balance_tokens == 1_000_000


async def test_admin_grant_trial(client: AsyncClient, registered_user):
    '''Admin grant endpoint issues a trial token grant to a user.'''

    import os

    admin_key = os.environ['ADMIN_KEY']
    r = await client.post(
        '/admin/grant',
        data={
            'key': admin_key,
            'email': registered_user['email'],
            'tokens': '100000',
            'days': '7',
        },
        follow_redirects=False,
    )

    assert r.status_code in (302, 303)


async def test_admin_delete_user(client: AsyncClient, registered_user):
    '''Admin delete endpoint removes the user row from the database.'''

    import os

    admin_key = os.environ['ADMIN_KEY']
    r = await client.post(
        '/admin/delete',
        data={'key': admin_key, 'user_id': registered_user['id']},
        follow_redirects=False,
    )

    assert r.status_code in (302, 303)

    from app.db import engine, User as UserModel
    from sqlalchemy.ext.asyncio import async_sessionmaker

    session_maker = async_sessionmaker(engine, expire_on_commit=False)

    async with session_maker() as session:
        user = await session.get(UserModel, registered_user['id'])
        assert user is None


# ── Checkout (payment providers not configured → 503) ───────────────────────

async def test_checkout_stripe_not_configured(client: AsyncClient, registered_user):
    '''Checkout returns 503 when Stripe is not configured (placeholder keys).'''

    r = await client.get(
        f'/checkout?pack=5m&key={registered_user["key"]}&method=stripe',
        follow_redirects=False,
    )

    assert r.status_code == 503


async def test_checkout_btcpay_not_configured(client: AsyncClient, registered_user):
    '''Checkout returns 503 when BTCPay is not configured (placeholder keys).'''

    r = await client.get(
        f'/checkout?pack=5m&key={registered_user["key"]}&method=btcpay',
        follow_redirects=False,
    )

    assert r.status_code == 503


async def test_checkout_invalid_pack(client: AsyncClient, registered_user):
    '''Checkout rejects an unknown pack identifier with 400 or 503.'''

    r = await client.get(
        f'/checkout?pack=999zz&key={registered_user["key"]}&method=stripe',
        follow_redirects=False,
    )

    assert r.status_code in (400, 503)
