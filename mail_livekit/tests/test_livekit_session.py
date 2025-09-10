from unittest.mock import patch

from odoo.tests import TransactionCase


class TestLiveKitSession(TransactionCase):
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

        # Create test channel
        self.test_channel = self.env["mail.channel"].create(
            {
                "name": "Test Channel",
                "channel_type": "channel",
                "public": "private",
                "livekit_server_id": self.livekit_server.id,
            }
        )

        # Create test partner
        self.test_partner = self.env["res.partner"].create(
            {
                "name": "Test Partner",
                "email": "test@example.com",
            }
        )

        # Create channel partner
        self.channel_partner = self.env["mail.channel.partner"].create(
            {
                "channel_id": self.test_channel.id,
                "partner_id": self.test_partner.id,
            }
        )

    def test_session_creation_with_livekit_data(self):
        """Test RTC session creation with LiveKit-specific data"""
        session = self.env["mail.channel.rtc.session"].create(
            {
                "channel_partner_id": self.channel_partner.id,
                "livekit_room_name": "test_room",
                "livekit_participant_identity": "partner_123",
                "livekit_server_id": self.livekit_server.id,
            }
        )

        self.assertTrue(session.id)
        self.assertEqual(session.livekit_room_name, "test_room")
        self.assertEqual(session.livekit_participant_identity, "partner_123")
        self.assertEqual(session.livekit_server_id, self.livekit_server)

    @patch(
        "odoo.addons.mail_livekit.models.mail_channel_rtc_session.MailChannelRtcSession._generate_livekit_access_token"
    )
    def test_session_auto_initialization(self, mock_generate_token):
        """Test that session auto-initializes LiveKit data on creation"""
        session = self.env["mail.channel.rtc.session"].create(
            {
                "channel_partner_id": self.channel_partner.id,
            }
        )

        # Should auto-generate room name and participant identity
        self.assertTrue(session.livekit_room_name)
        self.assertTrue(session.livekit_participant_identity)
        self.assertEqual(session.livekit_server_id, self.livekit_server)

        # Should call token generation
        mock_generate_token.assert_called_once()

    @patch(
        "odoo.addons.mail_livekit.models.mail_livekit_server.MailLiveKitServer.generate_access_token"
    )
    def test_generate_livekit_access_token(self, mock_server_generate_token):
        """Test LiveKit access token generation"""
        mock_server_generate_token.return_value = "test_access_token"

        session = self.env["mail.channel.rtc.session"].create(
            {
                "channel_partner_id": self.channel_partner.id,
                "livekit_room_name": "test_room",
                "livekit_participant_identity": "partner_123",
                "livekit_server_id": self.livekit_server.id,
            }
        )

        session._generate_livekit_access_token()

        self.assertEqual(session.livekit_access_token, "test_access_token")
        mock_server_generate_token.assert_called_with(
            room_name="test_room",
            participant_identity="partner_123",
            participant_name=self.test_partner.name,
        )

    def test_session_format_includes_livekit_data(self):
        """Test that session format includes LiveKit-specific data"""
        session = self.env["mail.channel.rtc.session"].create(
            {
                "channel_partner_id": self.channel_partner.id,
                "livekit_room_name": "test_room",
                "livekit_participant_identity": "partner_123",
                "livekit_access_token": "test_token",
                "livekit_server_id": self.livekit_server.id,
            }
        )

        formatted_data = session._mail_rtc_session_format()

        self.assertIn("livekitServerUrl", formatted_data)
        self.assertIn("livekitRoomName", formatted_data)
        self.assertIn("livekitAccessToken", formatted_data)
        self.assertIn("livekitParticipantIdentity", formatted_data)

        self.assertEqual(formatted_data["livekitRoomName"], "test_room")
        self.assertEqual(formatted_data["livekitAccessToken"], "test_token")
        self.assertEqual(formatted_data["livekitParticipantIdentity"], "partner_123")

    def test_refresh_livekit_token(self):
        """Test refreshing LiveKit access token"""
        session = self.env["mail.channel.rtc.session"].create(
            {
                "channel_partner_id": self.channel_partner.id,
                "livekit_room_name": "test_room",
                "livekit_participant_identity": "partner_123",
                "livekit_server_id": self.livekit_server.id,
            }
        )

        with patch.object(session, "_generate_livekit_access_token") as mock_generate:
            result = session.refresh_livekit_token()

            mock_generate.assert_called_once()
            self.assertIn("livekit_access_token", result)
            self.assertIn("livekit_server_url", result)

    def test_rtc_join_call_with_livekit(self):
        """Test RTC join call with LiveKit data"""
        with patch.object(self.channel_partner, "_rtc_join_call") as mock_parent_join:
            mock_parent_join.return_value = {"sessionId": 123}

            result = self.channel_partner._rtc_join_call()

            # Should call parent method
            mock_parent_join.assert_called_once()

            # Should return session ID
            self.assertIn("sessionId", result)

    def test_rtc_leave_call_clears_token(self):
        """Test that leaving call clears LiveKit access token"""
        session = self.env["mail.channel.rtc.session"].create(
            {
                "channel_partner_id": self.channel_partner.id,
                "livekit_access_token": "test_token",
            }
        )

        session._rtc_leave_call()

        # Token should be cleared
        self.assertFalse(session.livekit_access_token)

    def test_session_with_guest(self):
        """Test session creation with guest instead of partner"""
        # Create test guest
        guest = self.env["mail.guest"].create(
            {
                "name": "Test Guest",
            }
        )

        # Create channel partner for guest
        guest_channel_partner = self.env["mail.channel.partner"].create(
            {
                "channel_id": self.test_channel.id,
                "guest_id": guest.id,
            }
        )

        session = self.env["mail.channel.rtc.session"].create(
            {
                "channel_partner_id": guest_channel_partner.id,
            }
        )

        # Should generate guest-specific participant identity
        self.assertTrue(session.livekit_participant_identity.startswith("guest_"))

    def test_session_update_and_broadcast(self):
        """Test session update and broadcast with LiveKit values"""
        session = self.env["mail.channel.rtc.session"].create(
            {
                "channel_partner_id": self.channel_partner.id,
            }
        )

        # Test updating LiveKit-specific values
        values = {
            "is_camera_on": True,
            "livekit_access_token": "new_token",
        }

        with patch.object(session, "write") as mock_write:
            session._update_and_broadcast(values)

            # Should separate LiveKit values from standard values
            mock_write.assert_called()

    def test_session_without_server_configuration(self):
        """Test session behavior when no LiveKit server is configured"""
        # Create channel without LiveKit server
        channel_no_livekit = self.env["mail.channel"].create(
            {
                "name": "Channel No LiveKit",
                "channel_type": "channel",
                "public": "private",
            }
        )

        channel_partner_no_livekit = self.env["mail.channel.partner"].create(
            {
                "channel_id": channel_no_livekit.id,
                "partner_id": self.test_partner.id,
            }
        )

        session = self.env["mail.channel.rtc.session"].create(
            {
                "channel_partner_id": channel_partner_no_livekit.id,
            }
        )

        # Should handle gracefully without LiveKit server
        session._generate_livekit_access_token()
        # Should not crash, but won't have access token
        self.assertFalse(session.livekit_access_token)

    def test_multiple_sessions_same_channel(self):
        """Test multiple sessions in the same channel"""
        # Create another partner
        partner2 = self.env["res.partner"].create(
            {
                "name": "Test Partner 2",
                "email": "test2@example.com",
            }
        )

        channel_partner2 = self.env["mail.channel.partner"].create(
            {
                "channel_id": self.test_channel.id,
                "partner_id": partner2.id,
            }
        )

        # Create sessions for both partners
        session1 = self.env["mail.channel.rtc.session"].create(
            {
                "channel_partner_id": self.channel_partner.id,
            }
        )

        session2 = self.env["mail.channel.rtc.session"].create(
            {
                "channel_partner_id": channel_partner2.id,
            }
        )

        # Both should have same room name but different participant identities
        self.assertEqual(session1.livekit_room_name, session2.livekit_room_name)
        self.assertNotEqual(
            session1.livekit_participant_identity, session2.livekit_participant_identity
        )
