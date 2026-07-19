"""Tests for SecretsStore and the secrets routes, including the new
github-installation category and get_agent_github_installations."""

from __future__ import annotations

import json

import pytest


class TestGitHubInstallationCategory:
    """Tests for the github-installation secret category."""

    @pytest.mark.asyncio
    async def test_github_installation_in_categories(self, client):
        """The github-installation category appears in the categories list."""
        resp = await client.get("/api/secrets/categories")
        assert resp.status_code == 200
        categories = [c["name"] for c in resp.json()]
        assert "github-installation" in categories

    @pytest.mark.asyncio
    async def test_create_github_installation_secret(self, client):
        """Creating a secret with category github-installation works."""
        payload = {
            "name": "owner/repo",
            "value": json.dumps({"installation_id": 42, "repo_full_name": "owner/repo", "permissions": ["contents:read"]}),
            "category": "github-installation",
            "description": "Test GitHub App installation",
            "agents": ["test-agent"],
        }
        resp = await client.post("/api/secrets", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] is not None
        assert data["status"] == "created"

    @pytest.mark.asyncio
    async def test_list_secrets_by_github_installation_category(self, client):
        """Listing secrets filtered by github-installation category works."""
        await client.post("/api/secrets", json={
            "name": "owner/repo2",
            "value": json.dumps({"installation_id": 43, "repo_full_name": "owner/repo2", "permissions": []}),
            "category": "github-installation",
            "description": "Another test",
            "agents": ["test-agent"],
        })

        resp = await client.get("/api/secrets", params={"category": "github-installation"})
        assert resp.status_code == 200
        secrets = resp.json()
        assert any(s["name"] == "owner/repo2" for s in secrets)

    @pytest.mark.asyncio
    async def test_get_agent_github_installations_endpoint(self, client):
        """The GET /api/secrets/agent/{name}/github endpoint returns installations."""
        await client.post("/api/secrets", json={
            "name": "org/repo-a",
            "value": json.dumps({"installation_id": 99, "repo_full_name": "org/repo-a", "permissions": ["contents:read"]}),
            "category": "github-installation",
            "description": "Installation A",
            "agents": ["code-reviewer"],
        })

        resp = await client.get("/api/secrets/agent/code-reviewer/github")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert any(inst["repo_full_name"] == "org/repo-a" and inst["installation_id"] == 99 for inst in data)

    @pytest.mark.asyncio
    async def test_get_agent_github_installations_no_grants(self, client):
        """An agent with no grants returns an empty list."""
        resp = await client.get("/api/secrets/agent/nonexistent-agent/github")
        assert resp.status_code == 200
        assert resp.json() == []

    @pytest.mark.asyncio
    async def test_duplicate_secret_rejected(self, client):
        """Creating a secret with a duplicate name returns 409."""
        await client.post("/api/secrets", json={
            "name": "dup/repo",
            "value": "test",
            "category": "github-installation",
            "description": "",
            "agents": [],
        })
        resp = await client.post("/api/secrets", json={
            "name": "dup/repo",
            "value": "test2",
            "category": "github-installation",
            "description": "",
            "agents": [],
        })
        assert resp.status_code == 409

    @pytest.mark.asyncio
    async def test_update_secret_agents(self, client):
        """Updating a secret's agent list works."""
        await client.post("/api/secrets", json={
            "name": "update-test/repo",
            "value": json.dumps({"installation_id": 77, "repo_full_name": "update-test/repo", "permissions": []}),
            "category": "github-installation",
            "description": "",
            "agents": [],
        })

        resp = await client.put("/api/secrets/update-test/repo", json={
            "agents": ["agent-1", "agent-2"],
        })
        assert resp.status_code == 200
