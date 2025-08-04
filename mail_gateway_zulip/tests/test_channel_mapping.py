# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from unittest.mock import Mock, patch

from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase


class TestZulipChannelMapping(TransactionCase):
    """Test Zulip channel mapping functionality"""

    def setUp(self):
        super().setUp()
        self.gateway = self.env["mail.gateway"].create(
            {
                "name": "Test Zulip Gateway",
                "gateway_type": "zulip",
                "token": "test_token_123",
                "zulip_server_url": "https://test.zulipchat.com",
                "zulip_bot_email": "bot@test.zulipchat.com",
                "zulip_api_key": "test_api_key",
            }
        )
        self.channel = self.env["mail.channel"].create(
            {
                "name": "Test Channel",
                "channel_type": "channel",
            }
        )

        # Mock the stream selection method to return test streams
        def mock_get_streams_selection(self):
            return [
                ("general", "general"),
                ("development", "development"),
                ("support", "support"),
            ]

        self.stream_selection_patcher = patch.object(
            self.env["zulip.channel.mapping"].__class__,
            "_get_zulip_streams_selection",
            mock_get_streams_selection,
        )
        self.stream_selection_patcher.start()

    def tearDown(self):
        super().tearDown()
        if hasattr(self, "stream_selection_patcher"):
            self.stream_selection_patcher.stop()

    def test_mapping_name_computation(self):
        """Test automatic name computation for mappings"""
        # Test with topic
        mapping = self.env["zulip.channel.mapping"].create(
            {
                "gateway_id": self.gateway.id,
                "zulip_stream": "general",
                "zulip_topic": "announcements",
                "odoo_channel_id": self.channel.id,
            }
        )
        self.assertEqual(mapping.name, "general / announcements")

        # Test without topic
        mapping2 = self.env["zulip.channel.mapping"].create(
            {
                "gateway_id": self.gateway.id,
                "zulip_stream": "development",
                "odoo_channel_id": self.channel.id,
            }
        )
        self.assertEqual(mapping2.name, "development (all topics)")

    def test_unique_mapping_constraint(self):
        """Test that duplicate mappings are not allowed"""
        # Create first mapping
        self.env["zulip.channel.mapping"].create(
            {
                "gateway_id": self.gateway.id,
                "zulip_stream": "general",
                "zulip_topic": "test",
                "odoo_channel_id": self.channel.id,
            }
        )

        # Try to create duplicate mapping
        with self.assertRaises(ValidationError):
            self.env["zulip.channel.mapping"].create(
                {
                    "gateway_id": self.gateway.id,
                    "zulip_stream": "general",
                    "zulip_topic": "test",
                    "odoo_channel_id": self.channel.id,
                }
            )

    @patch("odoo.addons.mail_gateway_zulip.models.mail_gateway_zulip.zulip")
    def test_channel_configuration_on_create(self, mock_zulip):
        """Test that channel is configured for gateway on mapping creation"""
        # Mock Zulip client
        mock_client = Mock()
        mock_zulip.Client.return_value = mock_client

        # Create mapping
        self.env["zulip.channel.mapping"].create(
            {
                "gateway_id": self.gateway.id,
                "zulip_stream": "general",
                "zulip_topic": "test",
                "odoo_channel_id": self.channel.id,
            }
        )

        # Verify channel was configured
        self.assertEqual(self.channel.gateway_id, self.gateway)
        self.assertEqual(self.channel.gateway_channel_token, "general#test")
        # Channel type should NOT be changed to 'gateway' (our fix)
        self.assertEqual(self.channel.channel_type, "channel")

    def test_find_mapping_for_message_exact_match(self):
        """Test finding mapping with exact stream/topic match"""
        mapping = self.env["zulip.channel.mapping"].create(
            {
                "gateway_id": self.gateway.id,
                "zulip_stream": "general",
                "zulip_topic": "announcements",
                "odoo_channel_id": self.channel.id,
            }
        )

        found = self.env["zulip.channel.mapping"].find_mapping_for_message(
            self.gateway, "general", "announcements"
        )

        self.assertEqual(found, mapping)

    def test_find_mapping_for_message_stream_only(self):
        """Test finding mapping with stream-only match"""
        mapping = self.env["zulip.channel.mapping"].create(
            {
                "gateway_id": self.gateway.id,
                "zulip_stream": "general",
                "zulip_topic": False,  # All topics
                "odoo_channel_id": self.channel.id,
            }
        )

        found = self.env["zulip.channel.mapping"].find_mapping_for_message(
            self.gateway, "general", "any_topic"
        )

        self.assertEqual(found, mapping)

    def test_find_mapping_for_message_priority(self):
        """Test that exact matches have priority over stream-only matches"""
        # Create stream-only mapping
        self.env["zulip.channel.mapping"].create(
            {
                "gateway_id": self.gateway.id,
                "zulip_stream": "general",
                "zulip_topic": False,
                "odoo_channel_id": self.channel.id,
            }
        )

        # Create exact mapping
        channel2 = self.env["mail.channel"].create(
            {
                "name": "Test Channel 2",
                "channel_type": "channel",
            }
        )
        exact_mapping = self.env["zulip.channel.mapping"].create(
            {
                "gateway_id": self.gateway.id,
                "zulip_stream": "general",
                "zulip_topic": "specific",
                "odoo_channel_id": channel2.id,
            }
        )

        # Test exact match takes priority
        found = self.env["zulip.channel.mapping"].find_mapping_for_message(
            self.gateway, "general", "specific"
        )
        self.assertEqual(found, exact_mapping)

        # Test fallback to stream-only
        stream_mapping = self.env["zulip.channel.mapping"].search(
            [
                ("gateway_id", "=", self.gateway.id),
                ("zulip_stream", "=", "general"),
                ("zulip_topic", "=", False),
            ]
        )
        found = self.env["zulip.channel.mapping"].find_mapping_for_message(
            self.gateway, "general", "other_topic"
        )
        self.assertEqual(found, stream_mapping)

    def test_find_mapping_for_outgoing_message(self):
        """Test finding mapping for outgoing messages from Odoo channel"""
        mapping = self.env["zulip.channel.mapping"].create(
            {
                "gateway_id": self.gateway.id,
                "zulip_stream": "general",
                "zulip_topic": "test",
                "odoo_channel_id": self.channel.id,
            }
        )

        found = self.env["zulip.channel.mapping"].find_mapping_for_outgoing_message(
            self.channel
        )

        self.assertEqual(found, mapping)

    def test_update_sync_stats(self):
        """Test sync statistics update"""
        mapping = self.env["zulip.channel.mapping"].create(
            {
                "gateway_id": self.gateway.id,
                "zulip_stream": "general",
                "zulip_topic": "test",
                "odoo_channel_id": self.channel.id,
                "message_count": 5,
            }
        )

        # Update stats
        mapping.update_sync_stats()

        # Verify updates
        self.assertEqual(mapping.message_count, 6)
        self.assertEqual(mapping.status, "active")
        self.assertFalse(mapping.error_message)
        self.assertTrue(mapping.last_sync)

    @patch("odoo.addons.mail_gateway_zulip.models.mail_gateway_zulip.zulip")
    def test_action_test_mapping_success(self, mock_zulip):
        """Test successful mapping test"""
        # Mock successful Zulip responses
        mock_client = Mock()
        mock_zulip.Client.return_value = mock_client
        mock_client.get_streams.return_value = {
            "result": "success",
            "streams": [{"name": "general"}, {"name": "development"}],
        }

        # Create mapping with configured channel
        self.channel.write(
            {
                "gateway_id": self.gateway.id,
                "gateway_channel_token": "general#test",
            }
        )
        mapping = self.env["zulip.channel.mapping"].create(
            {
                "gateway_id": self.gateway.id,
                "zulip_stream": "general",
                "zulip_topic": "test",
                "odoo_channel_id": self.channel.id,
            }
        )

        # Test mapping
        result = mapping.action_test_mapping()

        # Verify success response
        self.assertEqual(result["type"], "ir.actions.client")
        self.assertEqual(result["tag"], "display_notification")
        self.assertEqual(result["params"]["type"], "success")
        self.assertEqual(mapping.status, "active")

    @patch("odoo.addons.mail_gateway_zulip.models.mail_gateway_zulip.zulip")
    def test_action_test_mapping_stream_not_found(self, mock_zulip):
        """Test mapping test when stream doesn't exist"""
        # Mock Zulip response without the required stream
        mock_client = Mock()
        mock_zulip.Client.return_value = mock_client
        mock_client.get_streams.return_value = {
            "result": "success",
            "streams": [{"name": "development"}],  # Missing 'general'
        }

        mapping = self.env["zulip.channel.mapping"].create(
            {
                "gateway_id": self.gateway.id,
                "zulip_stream": "general",  # This stream doesn't exist
                "zulip_topic": "test",
                "odoo_channel_id": self.channel.id,
            }
        )

        # Test mapping
        result = mapping.action_test_mapping()

        # Verify error response
        self.assertEqual(result["type"], "ir.actions.client")
        self.assertEqual(result["tag"], "display_notification")
        self.assertEqual(result["params"]["type"], "danger")
        self.assertEqual(mapping.status, "error")

    def test_action_sync_now(self):
        """Test manual sync trigger"""
        mapping = self.env["zulip.channel.mapping"].create(
            {
                "gateway_id": self.gateway.id,
                "zulip_stream": "general",
                "zulip_topic": "test",
                "odoo_channel_id": self.channel.id,
            }
        )

        # Trigger sync
        result = mapping.action_sync_now()

        # Verify response
        self.assertEqual(result["type"], "ir.actions.client")
        self.assertEqual(result["tag"], "display_notification")
        self.assertEqual(result["params"]["type"], "success")

        # Verify state update
        self.assertTrue(mapping.last_sync)
        self.assertEqual(mapping.status, "active")

    def test_channel_membership_preservation(self):
        """Test that channel membership is preserved during configuration"""
        # Add user to channel
        user = self.env.user
        self.channel.channel_partner_ids = [(4, user.partner_id.id)]
        original_members = self.channel.channel_partner_ids.ids

        # Create mapping (triggers channel configuration)
        with patch("odoo.addons.mail_gateway_zulip.models.mail_gateway_zulip.zulip"):
            self.env["zulip.channel.mapping"].create(
                {
                    "gateway_id": self.gateway.id,
                    "zulip_stream": "general",
                    "zulip_topic": "test",
                    "odoo_channel_id": self.channel.id,
                }
            )

        # Verify membership is preserved
        current_members = self.channel.channel_partner_ids.ids
        self.assertEqual(set(current_members), set(original_members))

    def test_inactive_mapping_ignored(self):
        """Test that inactive mappings are ignored in searches"""
        # Create inactive mapping
        self.env["zulip.channel.mapping"].create(
            {
                "gateway_id": self.gateway.id,
                "zulip_stream": "general",
                "zulip_topic": "test",
                "odoo_channel_id": self.channel.id,
                "active": False,
            }
        )

        # Search should not find inactive mapping
        found = self.env["zulip.channel.mapping"].find_mapping_for_message(
            self.gateway, "general", "test"
        )

        self.assertFalse(found)
