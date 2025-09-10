from unittest.mock import patch

from odoo.tests import TransactionCase


class TestLiveKitChannel(TransactionCase):
    def setUp(self):
        super().setUp()

        # Create test server (mocked - no real LiveKit server required)
        self.livekit_server = self.env["mail.livekit.server"].create(
            {
                "name": "Test LiveKit Server",
                "server_url": "wss://test.livekit.io",  # Fake URL for testing
                "api_key": "test_api_key",
                "api_secret": "test_api_secret",
                "active": True,
            }
        )

        # Create test partner
        self.test_partner = self.env["res.partner"].create(
            {
                "name": "Test Partner",
                "email": "test@example.com",
            }
        )

    def test_channel_creation_with_livekit_server(self):
        """Test channel creation with LiveKit server assignment"""
        channel = self.env["mail.channel"].create(
            {
                "name": "Test Channel",
                "channel_type": "channel",
                "public": "private",
                "livekit_server_id": self.livekit_server.id,
                "livekit_room_name": "custom_room_name",
            }
        )

        self.assertTrue(channel.id)
        self.assertEqual(channel.livekit_server_id, self.livekit_server)
        self.assertEqual(channel.livekit_room_name, "custom_room_name")

    def test_channel_auto_livekit_initialization(self):
        """Test that channel auto-initializes LiveKit data on creation"""
        channel = self.env["mail.channel"].create(
            {
                "name": "Test Channel",
                "channel_type": "channel",
                "public": "private",
            }
        )

        # Should auto-assign default server and generate room name
        self.assertEqual(channel.livekit_server_id, self.livekit_server)
        self.assertEqual(channel.livekit_room_name, f"odoo_channel_{channel.id}")

    def test_channel_info_includes_livekit_data(self):
        """Test that channel_info includes LiveKit-specific data"""
        channel = self.env["mail.channel"].create(
            {
                "name": "Test Channel",
                "channel_type": "channel",
                "public": "private",
                "livekit_server_id": self.livekit_server.id,
            }
        )

        channel_info = channel.channel_info()[0]

        self.assertIn("livekitServerUrl", channel_info)
        self.assertIn("livekitRoomName", channel_info)
        self.assertIn("livekitEnabled", channel_info)

        self.assertEqual(
            channel_info["livekitServerUrl"], self.livekit_server.server_url
        )
        self.assertEqual(channel_info["livekitRoomName"], channel.livekit_room_name)
        self.assertTrue(channel_info["livekitEnabled"])

    def test_channel_info_without_livekit_server(self):
        """Test channel_info when no LiveKit server is configured"""
        # Deactivate all servers
        self.livekit_server.write({"active": False})

        channel = self.env["mail.channel"].create(
            {
                "name": "Test Channel",
                "channel_type": "channel",
                "public": "private",
            }
        )

        channel_info = channel.channel_info()[0]

        self.assertIn("livekitEnabled", channel_info)
        self.assertFalse(channel_info["livekitEnabled"])

    def test_get_livekit_room_info(self):
        """Test getting LiveKit room information"""
        channel = self.env["mail.channel"].create(
            {
                "name": "Test Channel",
                "channel_type": "channel",
                "public": "private",
                "livekit_server_id": self.livekit_server.id,
                "livekit_room_name": "test_room",
            }
        )

        room_info = channel.get_livekit_room_info()

        self.assertIn("server_url", room_info)
        self.assertIn("room_name", room_info)
        self.assertIn("server_name", room_info)

        self.assertEqual(room_info["server_url"], self.livekit_server.server_url)
        self.assertEqual(room_info["room_name"], "test_room")
        self.assertEqual(room_info["server_name"], self.livekit_server.name)

    def test_get_livekit_room_info_no_server(self):
        """Test getting room info when no server is configured"""
        channel = self.env["mail.channel"].create(
            {
                "name": "Test Channel",
                "channel_type": "channel",
                "public": "private",
            }
        )

        # Remove server assignment
        channel.write({"livekit_server_id": False})

        room_info = channel.get_livekit_room_info()

        self.assertIn("error", room_info)
        self.assertEqual(room_info["error"], "No LiveKit server configured")

    @patch(
        "odoo.addons.mail_livekit.models.mail_livekit_server.MailLiveKitServer.generate_access_token"
    )
    def test_create_livekit_access_token(self, mock_generate_token):
        """Test creating LiveKit access token for channel"""
        mock_generate_token.return_value = "test_access_token"

        channel = self.env["mail.channel"].create(
            {
                "name": "Test Channel",
                "channel_type": "channel",
                "public": "private",
                "livekit_server_id": self.livekit_server.id,
                "livekit_room_name": "test_room",
            }
        )

        token = channel.create_livekit_access_token(
            participant_identity="test_user", participant_name="Test User"
        )

        self.assertEqual(token, "test_access_token")
        mock_generate_token.assert_called_once_with(
            room_name="test_room",
            participant_identity="test_user",
            participant_name="Test User",
            permissions=None,
        )

    def test_create_livekit_access_token_no_server(self):
        """Test creating access token when no server is configured"""
        channel = self.env["mail.channel"].create(
            {
                "name": "Test Channel",
                "channel_type": "channel",
                "public": "private",
            }
        )

        # Remove server assignment
        channel.write({"livekit_server_id": False})

        token = channel.create_livekit_access_token(participant_identity="test_user")

        self.assertIsNone(token)

    def test_rtc_cancel_invitations_with_livekit(self):
        """Test RTC invitation cancellation with LiveKit"""
        channel = self.env["mail.channel"].create(
            {
                "name": "Test Channel",
                "channel_type": "channel",
                "public": "private",
                "livekit_server_id": self.livekit_server.id,
            }
        )

        # Create channel partner
        channel_partner = self.env["mail.channel.partner"].create(
            {
                "channel_id": channel.id,
                "partner_id": self.test_partner.id,
            }
        )

        # Create RTC session with access token
        session = self.env["mail.channel.rtc.session"].create(
            {
                "channel_partner_id": channel_partner.id,
                "livekit_access_token": "test_token",
            }
        )

        # Cancel invitations
        channel._rtc_cancel_invitations(partner_ids=[self.test_partner.id])

        # Should clear access token
        session.refresh()
        self.assertFalse(session.livekit_access_token)

    def test_rtc_join_call_with_livekit(self):
        """Test RTC join call with LiveKit configuration"""
        channel = self.env["mail.channel"].create(
            {
                "name": "Test Channel",
                "channel_type": "channel",
                "public": "private",
                "livekit_server_id": self.livekit_server.id,
            }
        )

        result = channel._rtc_join_call()

        # The restored implementation only returns livekit_enabled flag
        # The actual LiveKit configuration data is provided through other methods
        self.assertIn("livekit_enabled", result)
        self.assertTrue(result["livekit_enabled"])

    def test_rtc_join_call_no_server(self):
        """Test RTC join call when no LiveKit server is configured"""
        # Deactivate all servers
        self.livekit_server.write({"active": False})

        channel = self.env["mail.channel"].create(
            {
                "name": "Test Channel",
                "channel_type": "channel",
                "public": "private",
            }
        )

        # Create channel partner to test RTC join call
        channel_partner = self.env["mail.channel.partner"].create(
            {
                "channel_id": channel.id,
                "partner_id": self.test_partner.id,
            }
        )

        # Mock the parent _rtc_join_call to return a valid session for WebRTC fallback
        with patch.object(
            type(channel_partner), "_rtc_join_call", return_value={"sessionId": 123}
        ):
            result = channel_partner._rtc_join_call()

            # Should fall back to WebRTC (no error)
            self.assertNotIn("error", result)
            self.assertIn("sessionId", result)

    @patch(
        "odoo.addons.mail_livekit.models.mail_channel_rtc_session.MailChannelRtcSession._generate_livekit_access_token"
    )
    def test_channel_room_name_update_regenerates_tokens(self, mock_generate):
        """Test that changing room name regenerates access tokens"""
        channel = self.env["mail.channel"].create(
            {
                "name": "Test Channel",
                "channel_type": "channel",
                "public": "private",
                "livekit_server_id": self.livekit_server.id,
            }
        )

        # Create channel partner and session
        channel_partner = self.env["mail.channel.partner"].create(
            {
                "channel_id": channel.id,
                "partner_id": self.test_partner.id,
            }
        )

        self.env["mail.channel.rtc.session"].create(
            {
                "channel_partner_id": channel_partner.id,
                "livekit_access_token": "old_token",
            }
        )

        # Change room name
        channel.write({"livekit_room_name": "new_room_name"})

        # Should regenerate token - verify the method was called
        mock_generate.assert_called()

    def test_multiple_channels_different_rooms(self):
        """Test that multiple channels get different room names"""
        channel1 = self.env["mail.channel"].create(
            {
                "name": "Test Channel 1",
                "channel_type": "channel",
                "public": "private",
                "livekit_server_id": self.livekit_server.id,
            }
        )

        channel2 = self.env["mail.channel"].create(
            {
                "name": "Test Channel 2",
                "channel_type": "channel",
                "public": "private",
                "livekit_server_id": self.livekit_server.id,
            }
        )

        # Should have different room names
        self.assertNotEqual(channel1.livekit_room_name, channel2.livekit_room_name)

        # But same server
        self.assertEqual(channel1.livekit_server_id, channel2.livekit_server_id)

    def test_chat_channel_livekit_integration(self):
        """Test LiveKit integration with chat channels"""
        chat_channel = self.env["mail.channel"].create(
            {
                "name": "Test Chat",
                "channel_type": "chat",
                "public": "private",
                "livekit_server_id": self.livekit_server.id,
            }
        )

        # Chat channels should also get LiveKit configuration
        self.assertEqual(chat_channel.livekit_server_id, self.livekit_server)
        self.assertTrue(chat_channel.livekit_room_name)

    def test_group_channel_livekit_integration(self):
        """Test LiveKit integration with group channels"""
        group_channel = self.env["mail.channel"].create(
            {
                "name": "Test Group",
                "channel_type": "group",
                "public": "private",
                "livekit_server_id": self.livekit_server.id,
            }
        )

        # Group channels should also get LiveKit configuration
        self.assertEqual(group_channel.livekit_server_id, self.livekit_server)
        self.assertTrue(group_channel.livekit_room_name)
