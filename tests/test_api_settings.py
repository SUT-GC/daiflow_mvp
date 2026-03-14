"""Tests for settings API endpoints."""


class TestSettingsAPI:
    async def test_get_settings_empty(self, client):
        resp = await client.get("/api/settings")
        assert resp.status_code == 200
        assert resp.json() == {}

    async def test_put_settings(self, client):
        resp = await client.put("/api/settings", json={
            "cody_model": "claude-opus-4-6",
            "cody_base_url": "https://api.anthropic.com",
            "cody_api_key": "sk-ant-12345678901234567890",
        })
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    async def test_get_settings_masks_api_key(self, client):
        await client.put("/api/settings", json={
            "cody_api_key": "sk-ant-12345678901234567890",
        })
        resp = await client.get("/api/settings")
        data = resp.json()
        key = data["cody_api_key"]
        # Key should be masked: first 4 + *** + last 4
        assert key.startswith("sk-a")
        assert key.endswith("7890")
        assert "****" in key or "*" in key

    async def test_get_settings_masks_short_api_key(self, client):
        await client.put("/api/settings", json={"cody_api_key": "short"})
        resp = await client.get("/api/settings")
        assert resp.json()["cody_api_key"] == "****"

    async def test_update_theme(self, client):
        resp = await client.put("/api/settings", json={"theme": "light"})
        assert resp.status_code == 200
        resp = await client.get("/api/settings")
        assert resp.json()["theme"] == "light"

    async def test_update_overwrites(self, client):
        await client.put("/api/settings", json={"cody_model": "model-a"})
        await client.put("/api/settings", json={"cody_model": "model-b"})
        resp = await client.get("/api/settings")
        assert resp.json()["cody_model"] == "model-b"

    async def test_check_not_configured(self, client):
        resp = await client.get("/api/settings/check")
        assert resp.status_code == 200
        data = resp.json()
        assert data["configured"] is False
        assert data["model"] == ""

    async def test_check_configured(self, client):
        await client.put("/api/settings", json={
            "cody_model": "claude-opus-4-6",
            "cody_base_url": "https://api.anthropic.com",
            "cody_api_key": "sk-ant-12345678901234567890",
        })
        resp = await client.get("/api/settings/check")
        data = resp.json()
        assert data["configured"] is True
        assert data["model"] == "claude-opus-4-6"

    async def test_check_partial_config(self, client):
        await client.put("/api/settings", json={
            "cody_model": "claude-opus-4-6",
            # Missing base_url and api_key
        })
        resp = await client.get("/api/settings/check")
        assert resp.json()["configured"] is False

    async def test_empty_string_value_rejected(self, client):
        await client.put("/api/settings", json={"cody_model": "model-a"})
        # Sending empty string should return 400 for required AI fields
        resp = await client.put("/api/settings", json={"cody_model": "   "})
        assert resp.status_code == 400
        # Original value should be preserved
        resp = await client.get("/api/settings")
        assert resp.json()["cody_model"] == "model-a"

    async def test_empty_base_url_rejected(self, client):
        resp = await client.put("/api/settings", json={"cody_base_url": ""})
        assert resp.status_code == 400
        assert "cody_base_url" in resp.json()["detail"]

    async def test_empty_api_key_rejected(self, client):
        resp = await client.put("/api/settings", json={"cody_api_key": "  "})
        assert resp.status_code == 400
        assert "cody_api_key" in resp.json()["detail"]

    async def test_empty_theme_allowed(self, client):
        """Theme and language are optional fields — empty values should be accepted."""
        resp = await client.put("/api/settings", json={"theme": ""})
        assert resp.status_code == 200

    async def test_masked_api_key_not_overwritten(self, client):
        """Sending back a masked API key should not overwrite the real key."""
        real_key = "sk-ant-12345678901234567890"
        await client.put("/api/settings", json={
            "cody_model": "claude-opus-4-6",
            "cody_base_url": "https://api.anthropic.com",
            "cody_api_key": real_key,
        })
        # Get the masked value
        resp = await client.get("/api/settings")
        masked_key = resp.json()["cody_api_key"]
        assert "****" in masked_key
        # Send the masked value back — should not overwrite
        await client.put("/api/settings", json={"cody_api_key": masked_key})
        # Verify the real key is preserved (check still passes)
        resp = await client.get("/api/settings/check")
        assert resp.json()["configured"] is True
