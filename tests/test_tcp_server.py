"""
Tests for the TCP Presence Server.

These tests run the asyncio TCP server in-process and connect a test client.
"""
import asyncio
import json
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tcp-server"))

# Override env vars for the tcp server module
os.environ.setdefault("JWT_SECRET", "test_secret_key")
os.environ.setdefault("JWT_ALGORITHM", "HS256")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/15")


def make_token(user_id: str = "test-user-123") -> str:
    """Create a JWT token for testing."""
    from jose import jwt
    return jwt.encode(
        {"sub": user_id},
        "test_secret_key",
        algorithm="HS256",
    )


@pytest.mark.asyncio
async def test_tcp_heartbeat():
    """Test a valid heartbeat updates presence and returns OK."""
    mock_redis = AsyncMock()
    mock_redis.setex = AsyncMock(return_value=True)

    with patch("server.get_redis", return_value=mock_redis):
        # Import after patching
        import importlib
        import server as srv
        importlib.reload(srv)

        with patch("server.get_redis", return_value=mock_redis):
            # Start server on random port
            tcp_server = await asyncio.start_server(srv.handle_client, "127.0.0.1", 0)
            port = tcp_server.sockets[0].getsockname()[1]

            async with tcp_server:
                reader, writer = await asyncio.open_connection("127.0.0.1", port)
                token = make_token("user-abc")
                writer.write((json.dumps({"action": "heartbeat", "token": token}) + "\n").encode())
                await writer.drain()

                response_raw = await asyncio.wait_for(reader.readline(), timeout=5)
                response = json.loads(response_raw.decode().strip())

                assert response["status"] == "ok"
                assert response["user_id"] == "user-abc"
                assert "online_count" in response

                # Disconnect gracefully
                writer.write((json.dumps({"action": "disconnect"}) + "\n").encode())
                await writer.drain()
                bye_raw = await asyncio.wait_for(reader.readline(), timeout=5)
                bye = json.loads(bye_raw.decode().strip())
                assert bye["status"] == "bye"

                writer.close()
                await writer.wait_closed()


@pytest.mark.asyncio
async def test_tcp_invalid_token():
    """Test that an invalid JWT returns an error."""
    mock_redis = AsyncMock()

    with patch("server.get_redis", return_value=mock_redis):
        import importlib
        import server as srv
        importlib.reload(srv)

        with patch("server.get_redis", return_value=mock_redis):
            tcp_server = await asyncio.start_server(srv.handle_client, "127.0.0.1", 0)
            port = tcp_server.sockets[0].getsockname()[1]

            async with tcp_server:
                reader, writer = await asyncio.open_connection("127.0.0.1", port)
                writer.write((json.dumps({"action": "heartbeat", "token": "invalid.jwt.token"}) + "\n").encode())
                await writer.drain()

                response_raw = await asyncio.wait_for(reader.readline(), timeout=5)
                response = json.loads(response_raw.decode().strip())
                assert "error" in response

                writer.close()
                await writer.wait_closed()


@pytest.mark.asyncio
async def test_tcp_invalid_json():
    """Test that non-JSON input returns an error response."""
    mock_redis = AsyncMock()

    with patch("server.get_redis", return_value=mock_redis):
        import importlib
        import server as srv
        importlib.reload(srv)

        with patch("server.get_redis", return_value=mock_redis):
            tcp_server = await asyncio.start_server(srv.handle_client, "127.0.0.1", 0)
            port = tcp_server.sockets[0].getsockname()[1]

            async with tcp_server:
                reader, writer = await asyncio.open_connection("127.0.0.1", port)
                writer.write(b"not valid json\n")
                await writer.drain()

                response_raw = await asyncio.wait_for(reader.readline(), timeout=5)
                response = json.loads(response_raw.decode().strip())
                assert "error" in response

                writer.close()
                await writer.wait_closed()


def test_decode_token_valid():
    """Unit test for decode_token helper."""
    import importlib
    import server as srv
    importlib.reload(srv)
    token = make_token("test-uid-999")
    result = srv.decode_token(token)
    assert result == "test-uid-999"


def test_decode_token_invalid():
    """Unit test for decode_token with bad token."""
    import importlib
    import server as srv
    importlib.reload(srv)
    result = srv.decode_token("bad.token.here")
    assert result is None
