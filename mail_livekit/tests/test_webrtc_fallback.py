# -*- coding: utf-8 -*-

from odoo.tests.common import TransactionCase


class TestWebRTCFallback(TransactionCase):
    """Test cases for WebRTC fallback when no LiveKit server is configured"""

    def setUp(self):
        super().setUp()
        self.MailChannel = self.env["mail.channel"]
        self.MailChannelPartner = self.env["mail.channel.partner"]
        self.LiveKitServer = self.env["mail.livekit.server"]

        # Create a test channel
        self.test_channel = self.MailChannel.create(
            {
                "name": "Test Channel",
                "channel_type": "chat",
            }
        )

        # Create a test partner
        self.test_partner = self.env["res.partner"].create(
            {
                "name": "Test Partner",
                "email": "test@example.com",
            }
        )

        # Create channel partner relationship
        self.channel_partner = self.MailChannelPartner.create(
            {
                "channel_id": self.test_channel.id,
                "partner_id": self.test_partner.id,
            }
        )

    def test_fallback_when_no_livekit_server_configured(self):
        """Test that system falls back to WebRTC when no LiveKit server is configured"""

        # Ensure no active LiveKit servers exist
        active_servers = self.LiveKitServer.search([("active", "=", True)])
        active_servers.write({"active": False})

        # Attempt to join call
        result = self.channel_partner._rtc_join_call()

        # Should succeed with WebRTC (no error)
        self.assertNotIn("error", result)

        # Should have session ID (WebRTC session created)
        self.assertIn("sessionId", result)

        # Should NOT have LiveKit-specific data
        self.assertNotIn("livekitEnabled", result)
        self.assertNotIn("livekitServerUrl", result)
        self.assertNotIn("livekitAccessToken", result)

        # Should have WebRTC-specific data (iceServers)
        self.assertIn("iceServers", result)

    def test_livekit_used_when_server_configured(self):
        """Test that LiveKit is used when server is configured and active"""

        # Create an active LiveKit server
        livekit_server = self.LiveKitServer.create(
            {
                "name": "Test LiveKit Server",
                "server_url": "wss://test.livekit.example.com",
                "api_key": "test_key",
                "api_secret": "test_secret_that_is_long_enough_for_jwt",
                "active": True,
            }
        )

        # Attempt to join call
        result = self.channel_partner._rtc_join_call()

        # Should succeed with LiveKit
        self.assertNotIn("error", result)

        # Should have session ID
        self.assertIn("sessionId", result)

        # Should have LiveKit-specific data
        self.assertIn("livekitEnabled", result)
        self.assertTrue(result["livekitEnabled"])
        self.assertIn("livekitServerUrl", result)
        self.assertEqual(result["livekitServerUrl"], livekit_server.server_url)

        # Should NOT have WebRTC-specific data (iceServers removed)
        self.assertNotIn("iceServers", result)

    def test_fallback_when_server_exists_but_inactive(self):
        """Test fallback when LiveKit server exists but is inactive"""

        # Create an inactive LiveKit server
        self.LiveKitServer.create(
            {
                "name": "Inactive LiveKit Server",
                "server_url": "wss://inactive.livekit.example.com",
                "api_key": "test_key",
                "api_secret": "test_secret_that_is_long_enough_for_jwt",
                "active": False,  # Inactive
            }
        )

        # Attempt to join call
        result = self.channel_partner._rtc_join_call()

        # Should fall back to WebRTC (no error)
        self.assertNotIn("error", result)

        # Should have session ID (WebRTC session created)
        self.assertIn("sessionId", result)

        # Should NOT have LiveKit-specific data
        self.assertNotIn("livekitEnabled", result)

        # Should have WebRTC-specific data
        self.assertIn("iceServers", result)

    def test_multiple_servers_uses_first_active(self):
        """Test that first active server is used when multiple exist"""

        # Create multiple LiveKit servers
        server1 = self.LiveKitServer.create(
            {
                "name": "First Server",
                "server_url": "wss://first.livekit.example.com",
                "api_key": "test_key1",
                "api_secret": "test_secret_that_is_long_enough_for_jwt_1",
                "active": True,
            }
        )

        server2 = self.LiveKitServer.create(
            {
                "name": "Second Server",
                "server_url": "wss://second.livekit.example.com",
                "api_key": "test_key2",
                "api_secret": "test_secret_that_is_long_enough_for_jwt_2",
                "active": True,
            }
        )

        # Attempt to join call
        result = self.channel_partner._rtc_join_call()

        # Should use LiveKit
        self.assertIn("livekitEnabled", result)
        self.assertTrue(result["livekitEnabled"])

        # Should use the first server found (database order)
        # Note: The exact server used depends on database ordering
        self.assertIn(
            result["livekitServerUrl"], [server1.server_url, server2.server_url]
        )
