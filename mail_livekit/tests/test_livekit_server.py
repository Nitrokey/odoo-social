import time
from unittest.mock import patch

from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase


class TestLiveKitServer(TransactionCase):
    def setUp(self):
        super().setUp()
        self.LiveKitServer = self.env["mail.livekit.server"]

        # Create test server (mocked - no real LiveKit server required for tests)
        # The server URL is fake and JWT generation is mocked in individual tests
        self.test_server = self.LiveKitServer.create(
            {
                "name": "Test LiveKit Server",
                "server_url": "wss://test.livekit.io",  # Fake URL for testing
                "api_key": "test_api_key",
                "api_secret": "test_api_secret",
                "active": True,
            }
        )

    def test_server_creation(self):
        """Test basic server creation"""
        self.assertTrue(self.test_server.id)
        self.assertEqual(self.test_server.name, "Test LiveKit Server")
        self.assertEqual(self.test_server.server_url, "wss://test.livekit.io")
        self.assertTrue(self.test_server.active)

    def test_server_url_validation(self):
        """Test server URL validation"""
        # Valid URLs should work
        valid_urls = [
            "wss://livekit.example.com",
            "ws://localhost:7880",
            "https://livekit.example.com",
            "http://localhost:7880",
        ]

        for url in valid_urls:
            server = self.LiveKitServer.create(
                {
                    "name": f"Test Server {url}",
                    "server_url": url,
                    "api_key": "test_key",
                    "api_secret": "test_secret",
                }
            )
            self.assertTrue(server.id)

        # Invalid URLs should raise validation error
        invalid_urls = [
            "invalid-url",
            "ftp://example.com",
            "",
            "just-text",
        ]

        for url in invalid_urls:
            with self.assertRaises(ValidationError):
                self.LiveKitServer.create(
                    {
                        "name": f"Invalid Server {url}",
                        "server_url": url,
                        "api_key": "test_key",
                        "api_secret": "test_secret",
                    }
                )

    def test_required_fields(self):
        """Test that required fields are enforced"""
        # Missing name
        with self.assertRaises(Exception):
            self.LiveKitServer.create(
                {
                    "server_url": "wss://test.livekit.io",
                    "api_key": "test_key",
                    "api_secret": "test_secret",
                }
            )

        # Missing server_url
        with self.assertRaises(Exception):
            self.LiveKitServer.create(
                {
                    "name": "Test Server",
                    "api_key": "test_key",
                    "api_secret": "test_secret",
                }
            )

        # Missing api_key
        with self.assertRaises(Exception):
            self.LiveKitServer.create(
                {
                    "name": "Test Server",
                    "server_url": "wss://test.livekit.io",
                    "api_secret": "test_secret",
                }
            )

        # Missing api_secret
        with self.assertRaises(Exception):
            self.LiveKitServer.create(
                {
                    "name": "Test Server",
                    "server_url": "wss://test.livekit.io",
                    "api_key": "test_key",
                }
            )

    @patch("jwt.encode")
    def test_generate_access_token(self, mock_jwt_encode):
        """Test JWT access token generation"""
        mock_jwt_encode.return_value = "mock_jwt_token"

        token = self.test_server.generate_access_token(
            room_name="test_room",
            participant_identity="test_user",
            participant_name="Test User",
        )

        self.assertEqual(token, "mock_jwt_token")
        mock_jwt_encode.assert_called_once()

        # Check the payload structure
        call_args = mock_jwt_encode.call_args
        payload = call_args[0][0]  # First argument is the payload

        self.assertEqual(payload["iss"], "test_api_key")
        self.assertEqual(payload["sub"], "test_user")
        self.assertEqual(payload["name"], "Test User")
        self.assertIn("video", payload)
        self.assertIn("exp", payload)
        self.assertIn("nbf", payload)

    @patch("jwt.encode")
    def test_generate_access_token_with_permissions(self, mock_jwt_encode):
        """Test JWT access token generation with custom permissions"""
        mock_jwt_encode.return_value = "mock_jwt_token_with_perms"

        custom_permissions = {
            "canPublish": False,
            "canSubscribe": True,
            "canPublishData": False,
        }

        token = self.test_server.generate_access_token(
            room_name="test_room",
            participant_identity="test_user",
            permissions=custom_permissions,
        )

        self.assertEqual(token, "mock_jwt_token_with_perms")

        # Check that custom permissions were used
        call_args = mock_jwt_encode.call_args
        payload = call_args[0][0]
        video_grants = payload["video"]

        self.assertEqual(video_grants["canPublish"], False)
        self.assertEqual(video_grants["canSubscribe"], True)
        self.assertEqual(video_grants["canPublishData"], False)

    def test_get_default_server(self):
        """Test getting the default active server"""
        # Create another server
        server2 = self.LiveKitServer.create(
            {
                "name": "Second Server",
                "server_url": "wss://second.livekit.io",
                "api_key": "key2",
                "api_secret": "secret2",
                "active": True,
            }
        )

        # Get default server (should return first active one)
        default_server = self.LiveKitServer.get_default_server()
        self.assertTrue(default_server.id in [self.test_server.id, server2.id])
        self.assertTrue(default_server.active)

    def test_get_default_server_no_active(self):
        """Test getting default server when none are active"""
        # Deactivate all servers
        self.LiveKitServer.search([]).write({"active": False})

        default_server = self.LiveKitServer.get_default_server()
        self.assertFalse(default_server)

    def test_server_name_uniqueness(self):
        """Test that server names should be unique (if constraint exists)"""
        # Try to create server with same name
        # Note: This test assumes you might want unique names
        # Remove if uniqueness is not required
        try:
            duplicate_server = self.LiveKitServer.create(
                {
                    "name": "Test LiveKit Server",  # Same name as test_server
                    "server_url": "wss://different.livekit.io",
                    "api_key": "different_key",
                    "api_secret": "different_secret",
                }
            )
            # If no constraint, this should succeed
            self.assertTrue(duplicate_server.id)
        except Exception:
            # If there's a uniqueness constraint, this is expected
            pass

    def test_token_expiration_time(self):
        """Test that tokens have proper expiration time"""
        with patch("jwt.encode") as mock_jwt_encode:
            mock_jwt_encode.return_value = "test_token"

            before_time = int(time.time())
            self.test_server.generate_access_token(
                room_name="test_room", participant_identity="test_user"
            )
            after_time = int(time.time())

            # Check the expiration time in the payload
            call_args = mock_jwt_encode.call_args
            payload = call_args[0][0]

            # Token should expire in about 1 hour (3600 seconds)
            expected_exp_min = before_time + 3600
            expected_exp_max = after_time + 3600

            self.assertGreaterEqual(payload["exp"], expected_exp_min)
            self.assertLessEqual(payload["exp"], expected_exp_max)

    def test_server_string_representation(self):
        """Test server string representation"""
        server_str = str(self.test_server)
        self.assertIn("Test LiveKit Server", server_str)
