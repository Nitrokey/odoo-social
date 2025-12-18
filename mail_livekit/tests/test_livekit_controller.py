import json
from unittest.mock import patch

from odoo.tests import HttpCase


class TestLiveKitController(HttpCase):
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

        # Create test user and partner
        self.test_user = self.env["res.users"].create(
            {
                "name": "Test User",
                "login": "testuser",
                "password": "testuser",  # Set password for authentication
                "email": "test@example.com",
                "groups_id": [(6, 0, [self.env.ref("base.group_user").id])],
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

        # Create channel partner
        self.channel_partner = self.env["mail.channel.partner"].create(
            {
                "channel_id": self.test_channel.id,
                "partner_id": self.test_user.partner_id.id,
            }
        )

    def test_channel_call_join_with_livekit(self):
        """Test joining call via controller with LiveKit data"""
        self.authenticate(self.test_user.login, self.test_user.login)

        with patch(
            "odoo.addons.mail_livekit.controllers.discuss.LiveKitDiscussController.channel_call_join"
        ) as mock_join:
            mock_join.return_value = {
                "sessionId": 123,
                "livekitEnabled": True,
                "livekitServerUrl": "wss://test.livekit.io",
                "livekitRoomName": "test_room",
                "livekitAccessToken": "test_token",
                "livekitParticipantIdentity": "partner_123",
            }

            response = self.url_open(
                "/mail/rtc/channel/join_call",
                data=json.dumps(
                    {
                        "params": {
                            "channel_id": self.test_channel.id,
                        }
                    }
                ),
                headers={"Content-Type": "application/json"},
            )

            self.assertEqual(response.status_code, 200)
            result = response.json()

            self.assertIn("livekitEnabled", result["result"])
            self.assertIn("livekitServerUrl", result["result"])
            self.assertIn("livekitAccessToken", result["result"])

    def test_channel_call_leave_with_livekit(self):
        """Test leaving call via controller"""
        self.authenticate(self.test_user.login, self.test_user.login)

        with patch(
            "odoo.addons.mail_livekit.controllers.discuss.LiveKitDiscussController.channel_call_leave"
        ) as mock_leave:
            mock_leave.return_value = {"success": True}

            response = self.url_open(
                "/mail/rtc/channel/leave_call",
                data=json.dumps(
                    {
                        "params": {
                            "channel_id": self.test_channel.id,
                        }
                    }
                ),
                headers={"Content-Type": "application/json"},
            )

            self.assertEqual(response.status_code, 200)

    def test_livekit_get_room_info(self):
        """Test getting LiveKit room info via controller"""
        self.authenticate(self.test_user.login, self.test_user.login)

        response = self.url_open(
            "/mail/livekit/channel/get_room_info",
            data=json.dumps(
                {
                    "params": {
                        "channel_id": self.test_channel.id,
                    }
                }
            ),
            headers={"Content-Type": "application/json"},
        )

        self.assertEqual(response.status_code, 200)
        result = response.json()

        self.assertIn("server_url", result["result"])
        self.assertIn("room_name", result["result"])
        self.assertEqual(result["result"]["server_url"], self.livekit_server.server_url)

    def test_livekit_refresh_access_token(self):
        """Test refreshing LiveKit access token via controller"""
        self.authenticate(self.test_user.login, self.test_user.login)

        # Create RTC session
        session = self.env["mail.channel.rtc.session"].create(
            {
                "channel_partner_id": self.channel_partner.id,
                "livekit_access_token": "old_token",
            }
        )

        with patch.object(session, "refresh_livekit_token") as mock_refresh:
            mock_refresh.return_value = {
                "livekit_access_token": "new_token",
                "livekit_server_url": "wss://test.livekit.io",
            }

            response = self.url_open(
                "/mail/livekit/session/refresh_token",
                data=json.dumps(
                    {
                        "params": {
                            "channel_id": self.test_channel.id,
                        }
                    }
                ),
                headers={"Content-Type": "application/json"},
            )

            self.assertEqual(response.status_code, 200)
            result = response.json()

            self.assertIn("livekit_access_token", result["result"])

    def test_livekit_get_session_info(self):
        """Test getting LiveKit session info via controller"""
        self.authenticate(self.test_user.login, self.test_user.login)

        # Create RTC session
        self.env["mail.channel.rtc.session"].create(
            {
                "channel_partner_id": self.channel_partner.id,
                "livekit_room_name": "test_room",
                "livekit_participant_identity": "partner_123",
                "livekit_access_token": "test_token",
            }
        )

        response = self.url_open(
            "/mail/livekit/session/get_info",
            data=json.dumps(
                {
                    "params": {
                        "channel_id": self.test_channel.id,
                    }
                }
            ),
            headers={"Content-Type": "application/json"},
        )

        self.assertEqual(response.status_code, 200)
        result = response.json()

        self.assertIn("room_name", result["result"])
        self.assertIn("participant_identity", result["result"])
        self.assertEqual(result["result"]["room_name"], "test_room")

    def test_livekit_create_access_token(self):
        """Test creating LiveKit access token via controller"""
        self.authenticate(self.test_user.login, self.test_user.login)

        participant_identity = f"partner_{self.test_user.partner_id.id}"

        with patch.object(
            self.test_channel, "create_livekit_access_token"
        ) as mock_create_token:
            mock_create_token.return_value = "new_access_token"

            response = self.url_open(
                "/mail/livekit/channel/create_access_token",
                data=json.dumps(
                    {
                        "params": {
                            "channel_id": self.test_channel.id,
                            "participant_identity": participant_identity,
                            "participant_name": "Test User",
                        }
                    }
                ),
                headers={"Content-Type": "application/json"},
            )

            self.assertEqual(response.status_code, 200)
            result = response.json()

            self.assertIn("access_token", result["result"])
            self.assertEqual(result["result"]["access_token"], "new_access_token")

    def test_livekit_create_access_token_wrong_identity(self):
        """Test creating access token with wrong participant identity (should fail)"""
        self.authenticate(self.test_user.login, self.test_user.login)

        # Try to create token for different user
        wrong_identity = "partner_999"

        response = self.url_open(
            "/mail/livekit/channel/create_access_token",
            data=json.dumps(
                {
                    "params": {
                        "channel_id": self.test_channel.id,
                        "participant_identity": wrong_identity,
                    }
                }
            ),
            headers={"Content-Type": "application/json"},
        )

        # Should return 404 (NotFound)
        self.assertEqual(response.status_code, 404)

    def test_livekit_list_servers_admin(self):
        """Test listing LiveKit servers as admin"""
        # Make user admin
        self.test_user.groups_id = [(6, 0, [self.env.ref("base.group_system").id])]
        self.authenticate(self.test_user.login, self.test_user.login)

        response = self.url_open(
            "/mail/livekit/server/list",
            data=json.dumps({"params": {}}),
            headers={"Content-Type": "application/json"},
        )

        self.assertEqual(response.status_code, 200)
        result = response.json()

        self.assertIsInstance(result["result"], list)
        self.assertTrue(len(result["result"]) > 0)

        server_data = result["result"][0]
        self.assertIn("id", server_data)
        self.assertIn("name", server_data)
        self.assertIn("server_url", server_data)

    def test_livekit_list_servers_non_admin(self):
        """Test listing LiveKit servers as non-admin (should fail)"""
        self.authenticate(self.test_user.login, self.test_user.login)

        response = self.url_open(
            "/mail/livekit/server/list",
            data=json.dumps({"params": {}}),
            headers={"Content-Type": "application/json"},
        )

        # Should return 404 (NotFound) for non-admin
        self.assertEqual(response.status_code, 404)

    def test_livekit_test_server_connection_admin(self):
        """Test testing LiveKit server connection as admin"""
        # Make user admin
        self.test_user.groups_id = [(6, 0, [self.env.ref("base.group_system").id])]
        self.authenticate(self.test_user.login, self.test_user.login)

        with patch.object(
            self.livekit_server, "generate_access_token"
        ) as mock_generate:
            mock_generate.return_value = "test_token"

            response = self.url_open(
                "/mail/livekit/server/test_connection",
                data=json.dumps(
                    {
                        "params": {
                            "server_id": self.livekit_server.id,
                        }
                    }
                ),
                headers={"Content-Type": "application/json"},
            )

            self.assertEqual(response.status_code, 200)
            result = response.json()

            self.assertIn("success", result["result"])
            self.assertTrue(result["result"]["success"])

    def test_livekit_test_server_connection_non_admin(self):
        """Test testing server connection as non-admin (should fail)"""
        self.authenticate(self.test_user.login, self.test_user.login)

        response = self.url_open(
            "/mail/livekit/server/test_connection",
            data=json.dumps(
                {
                    "params": {
                        "server_id": self.livekit_server.id,
                    }
                }
            ),
            headers={"Content-Type": "application/json"},
        )

        # Should return 404 (NotFound) for non-admin
        self.assertEqual(response.status_code, 404)

    def test_session_update_and_broadcast_livekit(self):
        """Test updating session with LiveKit-specific values"""
        self.authenticate(self.test_user.login, self.test_user.login)

        # Create RTC session
        session = self.env["mail.channel.rtc.session"].create(
            {
                "channel_partner_id": self.channel_partner.id,
            }
        )

        with patch.object(session, "write"):
            response = self.url_open(
                "/mail/rtc/session/update_and_broadcast",
                data=json.dumps(
                    {
                        "params": {
                            "session_id": session.id,
                            "values": {
                                "is_camera_on": True,
                                "livekit_access_token": "new_token",
                            },
                        }
                    }
                ),
                headers={"Content-Type": "application/json"},
            )

            self.assertEqual(response.status_code, 200)

    def test_controller_without_channel_access(self):
        """Test controller endpoints without proper channel access"""
        # Create user without access to the channel
        other_user = self.env["res.users"].create(
            {
                "name": "Other User",
                "login": "otheruser",
                "email": "other@example.com",
                "groups_id": [(6, 0, [self.env.ref("base.group_user").id])],
            }
        )

        self.authenticate(other_user.login, other_user.login)

        response = self.url_open(
            "/mail/livekit/channel/get_room_info",
            data=json.dumps(
                {
                    "params": {
                        "channel_id": self.test_channel.id,
                    }
                }
            ),
            headers={"Content-Type": "application/json"},
        )

        # Should return 404 (NotFound) due to lack of access
        self.assertEqual(response.status_code, 404)

    def test_public_channel_template_with_livekit(self):
        """Test public channel template includes LiveKit data"""
        # Create public channel
        public_channel = self.env["mail.channel"].create(
            {
                "name": "Public Channel",
                "channel_type": "channel",
                "public": "public",
                "livekit_server_id": self.livekit_server.id,
                "uuid": "test-uuid-123",
            }
        )

        response = self.url_open(f"/chat/{public_channel.uuid}")

        self.assertEqual(response.status_code, 200)
        # Should contain LiveKit configuration in the response
        self.assertIn("livekitEnabled", response.text)

    def test_invalid_channel_id(self):
        """Test controller endpoints with invalid channel ID"""
        self.authenticate(self.test_user.login, self.test_user.login)

        response = self.url_open(
            "/mail/livekit/channel/get_room_info",
            data=json.dumps(
                {
                    "params": {
                        "channel_id": 99999,  # Non-existent channel
                    }
                }
            ),
            headers={"Content-Type": "application/json"},
        )

        # Should return 404 (NotFound)
        self.assertEqual(response.status_code, 404)

    def test_controller_error_handling(self):
        """Test controller error handling"""
        self.authenticate(self.test_user.login, self.test_user.login)

        # Test with channel that has no LiveKit server
        channel_no_server = self.env["mail.channel"].create(
            {
                "name": "No Server Channel",
                "channel_type": "channel",
                "public": "private",
            }
        )

        # Add user to channel
        self.env["mail.channel.partner"].create(
            {
                "channel_id": channel_no_server.id,
                "partner_id": self.test_user.partner_id.id,
            }
        )

        response = self.url_open(
            "/mail/livekit/channel/get_room_info",
            data=json.dumps(
                {
                    "params": {
                        "channel_id": channel_no_server.id,
                    }
                }
            ),
            headers={"Content-Type": "application/json"},
        )

        self.assertEqual(response.status_code, 200)
        result = response.json()

        # Should return error message
        self.assertIn("error", result["result"])

    def test_channel_call_join_no_server_fallback(self):
        """Test joining a call when no LiveKit server is configured - should fallback to WebRTC"""
        # Ensure no active servers
        self.env["mail.livekit.server"].search([]).write({"active": False})

        # Use the existing channel partner from setUp
        channel_partner = self.channel_partner

        self.authenticate(self.test_user.login, self.test_user.login)

        # Mock the parent _rtc_join_call to return a valid session
        with patch("odoo.addons.mail.models.mail_channel_partner.ChannelPartner._rtc_join_call", return_value={"sessionId": 123}):
            result = channel_partner._rtc_join_call()

            # Should not return error and should fall back to WebRTC
            self.assertNotIn("error", result)
            self.assertIn("sessionId", result)
            # When falling back to WebRTC, LiveKit data should not be present
            self.assertNotIn("livekitEnabled", result)

    def test_channel_call_join_missing_session_id(self):
        """Test handling of missing session ID in join call response"""
        # Use the existing channel_partner from setUp
        channel_partner = self.channel_partner

        # Mock the parent _rtc_join_call to return response without sessionId
        # We need to mock the parent class method specifically
        with patch("odoo.addons.mail.models.mail_channel_partner.ChannelPartner._rtc_join_call", return_value={}):
            result = channel_partner._rtc_join_call()

            # Should return error when no session ID is provided
            self.assertIn("error", result)
            self.assertEqual(result["error"], "Failed to create RTC session")
