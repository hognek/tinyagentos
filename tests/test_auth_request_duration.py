import pytest


class TestAuthRequestDuration:
    """Human-readable duration formatting for auth requests and notifications."""

    @pytest.mark.asyncio
    async def test_backend_notification_includes_human_duration_when_duration_secs_is_set(self, client, monkeypatch, tmp_path):
        from tinyagentos.agent_registry_store import AgentRegistryStore, load_or_create_signing_keypair, mint_registry_token
        from tinyagentos.auth_requests_store import AuthRequestsStore
        from tinyagentos.agent_grants_store import AgentGrantsStore

        registry = AgentRegistryStore(tmp_path / "reg-duration.db")
        await registry.init()
        auth_store = AuthRequestsStore(tmp_path / "auth-duration.db")
        await auth_store.init()
        grants = AgentGrantsStore(tmp_path / "grants-duration.db")
        await grants.init()
        priv, pub = load_or_create_signing_keypair(tmp_path / "keys-duration")

        monkeypatch.setattr(client._transport.app.state, "agent_registry", registry)
        monkeypatch.setattr(client._transport.app.state, "auth_requests", auth_store)
        monkeypatch.setattr(client._transport.app.state, "agent_grants", grants)
        monkeypatch.setattr(client._transport.app.state, "agent_registry_keypair", (priv, pub))

        resp = await client.post(
            "/api/agents/auth-requests",
            json={
                "identity_claim": "duration-bot",
                "framework": "duration-cli",
                "requested_scopes": ["files_read"],
                "duration_secs": 3600,  # 1 hour
            },
        )
        assert resp.status_code == 200, resp.text
        request_id = resp.json()["request_id"]

        # Get the notification created for this request
        notifs = getattr(client._transport.app.state, "notifications", None)
        assert notifs is not None, "Notifications store not available"
        pending = [n for n in await notifs.list() if n.get("data", {}).get("request_id") == request_id]
        assert len(pending) > 0, "No notification created"
        notification = pending[0]

        # Verify the notification message includes human-readable duration
        # The current implementation now includes this in the message body
        assert notification["message"] == "duration-bot is requesting files_read expires in 1 hour", \
            f"Expected message to include duration info, got: {notification['message']}"

        # Verify the notification data includes human_duration in the payload
        assert "data" in notification and "human_duration" in notification["data"], \
            "human_duration missing from notification data"
        assert notification["data"]["human_duration"] == "expires in 1 hour", \
            f"Expected 'expires in 1 hour', got: {notification['data']['human_duration']}"

        await registry.close()
        await auth_store.close()
        await grants.close()

    @pytest.mark.asyncio
    async def test_backend_notification_has_no_expiry_when_duration_secs_is_not_set(self, client, monkeypatch, tmp_path):
        from tinyagentos.agent_registry_store import AgentRegistryStore, load_or_create_signing_keypair, mint_registry_token
        from tinyagentos.auth_requests_store import AuthRequestsStore
        from tinyagentos.agent_grants_store import AgentGrantsStore

        registry = AgentRegistryStore(tmp_path / "reg-no-expiry.db")
        await registry.init()
        auth_store = AuthRequestsStore(tmp_path / "auth-no-expiry.db")
        await auth_store.init()
        grants = AgentGrantsStore(tmp_path / "grants-no-expiry.db")
        await grants.init()
        priv, pub = load_or_create_signing_keypair(tmp_path / "keys-no-expiry")

        monkeypatch.setattr(client._transport.app.state, "agent_registry", registry)
        monkeypatch.setattr(client._transport.app.state, "auth_requests", auth_store)
        monkeypatch.setattr(client._transport.app.state, "agent_grants", grants)
        monkeypatch.setattr(client._transport.app.state, "agent_registry_keypair", (priv, pub))

        resp = await client.post(
            "/api/agents/auth-requests",
            json={
                "identity_claim": "no-expiry-bot",
                "framework": "no-expiry-cli",
                "requested_scopes": ["files_read"],
            },
        )
        assert resp.status_code == 200, resp.text
        request_id = resp.json()["request_id"]

        notifs = getattr(client._transport.app.state, "notifications", None)
        assert notifs is not None, "Notifications store not available"
        pending = [n for n in await notifs.list() if n.get("data", {}).get("request_id") == request_id]
        assert len(pending) > 0, "No notification created"
        notification = pending[0]

        # Verify the notification data includes human_duration
        assert "data" in notification and "human_duration" in notification["data"], \
            "human_duration missing from notification data"
        assert notification["data"]["human_duration"] == "no expiry", \
            f"Expected 'no expiry', got: {notification['data']['human_duration']}"

        await registry.close()
        await auth_store.close()
        await grants.close()

    @pytest.mark.asyncio
    async def test_backend_auth_request_status_includes_human_duration_when_duration_secs_is_set(self, client, monkeypatch, tmp_path):
        from tinyagentos.agent_registry_store import AgentRegistryStore, load_or_create_signing_keypair, mint_registry_token
        from tinyagentos.auth_requests_store import AuthRequestsStore
        from tinyagentos.agent_grants_store import AgentGrantsStore

        registry = AgentRegistryStore(tmp_path / "reg-status-duration.db")
        await registry.init()
        auth_store = AuthRequestsStore(tmp_path / "auth-status-duration.db")
        await auth_store.init()
        grants = AgentGrantsStore(tmp_path / "grants-status-duration.db")
        await grants.init()
        priv, pub = load_or_create_signing_keypair(tmp_path / "keys-status-duration")

        monkeypatch.setattr(client._transport.app.state, "agent_registry", registry)
        monkeypatch.setattr(client._transport.app.state, "auth_requests", auth_store)
        monkeypatch.setattr(client._transport.app.state, "agent_grants", grants)
        monkeypatch.setattr(client._transport.app.state, "agent_registry_keypair", (priv, pub))

        resp = await client.post(
            "/api/agents/auth-requests",
            json={
                "identity_claim": "status-duration-bot",
                "framework": "status-duration-cli",
                "requested_scopes": ["files_read"],
                "duration_secs": 7200,  # 2 hours
            },
        )
        assert resp.status_code == 200, resp.text
        request_id = resp.json()["request_id"]

        # Get the auth request status
        resp = await client.get(f"/api/agents/auth-requests/{request_id}")
        assert resp.status_code == 200, resp.text
        data = resp.json()

        # Verify the status response includes human_duration
        assert "human_duration" in data, f"Expected 'human_duration' in response, got: {data}"
        assert data["human_duration"] == "expires in 2 hours", \
            f"Expected 'expires in 2 hours', got: {data['human_duration']}"

        await registry.close()
        await auth_store.close()
        await grants.close()
