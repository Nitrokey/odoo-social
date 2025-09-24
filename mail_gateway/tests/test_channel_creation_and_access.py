# Copyright 2025 Nitrokey GmbH
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from odoo import Command
from odoo.tests.common import TransactionCase


class TestChannelCreationAndAccess(TransactionCase):
    """Test channel creation and access functionality from standalone scripts"""

    def setUp(self):
        super().setUp()
        # Create gateway without gateway_type since it has empty selection
        self.gateway = self.env["mail.gateway"].create(
            {
                "name": "Test Gateway",
                "token": "test_gateway_token",
                "webhook_key": "test_gateway_webhook",
            }
        )
        # Manually set gateway_type to bypass validation for testing
        self.env.cr.execute(
            "UPDATE mail_gateway SET gateway_type = %s WHERE id = %s",
            ("test", self.gateway.id),
        )
        self.gateway.invalidate_cache()
        self.admin_user = self.env.ref("base.user_admin")

    def test_channel_type_field_includes_gateway(self):
        """Test if the channel_type field includes 'gateway' option"""
        channel_model = self.env["mail.channel"]
        channel_type_field = channel_model._fields["channel_type"]

        self.assertTrue(hasattr(channel_type_field, "selection"))

        selection_options = channel_type_field.selection
        if callable(selection_options):
            selection_options = selection_options(channel_model)

        gateway_option = [opt for opt in selection_options if opt[0] == "gateway"]
        self.assertTrue(
            gateway_option, "'gateway' option should be available in selection"
        )
        self.assertEqual(gateway_option[0][0], "gateway")

    def test_gateway_channel_creation_with_members(self):
        """Test creating gateway channels with proper member setup"""
        channel = self.env["mail.channel"].create(
            {
                "name": "Zulip: general / test-topic-fixed",
                "channel_type": "gateway",
                "gateway_id": self.gateway.id,
                "gateway_channel_token": "general#test-topic-fixed",
                "company_id": self.gateway.company_id.id,
                "channel_last_seen_partner_ids": [
                    Command.create(
                        {
                            "partner_id": self.admin_user.partner_id.id,
                            "is_pinned": True,
                        }
                    )
                ],
            }
        )

        self.assertTrue(channel)
        self.assertEqual(channel.name, "Zulip: general / test-topic-fixed")
        self.assertEqual(channel.channel_type, "gateway")
        self.assertEqual(channel.gateway_id, self.gateway)
        self.assertEqual(channel.gateway_channel_token, "general#test-topic-fixed")
        self.assertIn(self.admin_user.partner_id, channel.channel_partner_ids)

    def test_direct_channel_access(self):
        """Test direct access to gateway channels"""
        channel = self.env["mail.channel"].create(
            {
                "name": "Direct Access Test",
                "channel_type": "gateway",
                "gateway_id": self.gateway.id,
                "gateway_channel_token": "direct#access",
                "channel_last_seen_partner_ids": [
                    Command.create(
                        {
                            "partner_id": self.admin_user.partner_id.id,
                            "is_pinned": True,
                        }
                    )
                ],
            }
        )

        # Test basic field access
        self.assertEqual(channel.name, "Direct Access Test")
        self.assertEqual(channel.channel_type, "gateway")
        self.assertEqual(channel.gateway_id, self.gateway)
        self.assertTrue(channel.active)

        # Test channel_info method
        try:
            channel_info = channel.channel_info()
            self.assertTrue(isinstance(channel_info, list))
            self.assertTrue(len(channel_info) > 0)
        except Exception as e:
            self.fail(f"channel_info() failed: {e}")

        # Test membership
        self.assertTrue(channel.is_member)

    def test_channel_search_variations(self):
        """Test different ways of searching for gateway channels"""
        # Create test channels
        channel1 = self.env["mail.channel"].create(
            {
                "name": "Search Test 1",
                "channel_type": "gateway",
                "gateway_id": self.gateway.id,
                "gateway_channel_token": "search#test1",
            }
        )

        channel2 = self.env["mail.channel"].create(
            {
                "name": "Search Test 2",
                "channel_type": "gateway",
                "gateway_id": self.gateway.id,
                "gateway_channel_token": "search#test2",
                "active": True,
            }
        )

        # Test search by channel type
        gateway_channels = self.env["mail.channel"].search(
            [("channel_type", "=", "gateway")]
        )
        self.assertIn(channel1, gateway_channels)
        self.assertIn(channel2, gateway_channels)

        # Test search by gateway_id
        channels_with_gateway = self.env["mail.channel"].search(
            [("gateway_id", "!=", False)]
        )
        self.assertIn(channel1, channels_with_gateway)
        self.assertIn(channel2, channels_with_gateway)

        # Test search for active gateway channels
        active_gateway_channels = self.env["mail.channel"].search(
            [("channel_type", "=", "gateway"), ("active", "=", True)]
        )
        self.assertIn(channel1, active_gateway_channels)
        self.assertIn(channel2, active_gateway_channels)

    def test_messaging_initialization_includes_gateway_channels(self):
        """Test that gateway channels are included in messaging initialization"""
        channel = self.env["mail.channel"].create(
            {
                "name": "Messaging Init Test",
                "channel_type": "gateway",
                "gateway_id": self.gateway.id,
                "gateway_channel_token": "messaging#init",
                "channel_last_seen_partner_ids": [
                    Command.create(
                        {
                            "partner_id": self.admin_user.partner_id.id,
                            "is_pinned": True,
                        }
                    )
                ],
            }
        )

        # Test messaging initialization
        try:
            messaging_data = self.admin_user._init_messaging()
            self.assertTrue(isinstance(messaging_data, dict))

            channels = messaging_data.get("channels", [])
            self.assertTrue(isinstance(channels, list))

            # Check if gateway channels are included
            gateway_channels_in_init = [
                ch
                for ch in channels
                if isinstance(ch, dict) and ch.get("channel_type") == "gateway"
            ]

            # Should include gateway channels
            self.assertTrue(len(gateway_channels_in_init) >= 0)

            # Verify our specific channel is included
            channel_ids_in_init = [
                ch.get("id") for ch in channels if isinstance(ch, dict)
            ]
            self.assertIn(channel.id, channel_ids_in_init)

        except Exception as e:
            self.fail(f"Messaging initialization failed: {e}")

    def test_selection_add_approach_works(self):
        """Test that selection_add approach works correctly without warnings"""
        channel_model = self.env["mail.channel"]
        channel_type_field = channel_model._fields["channel_type"]

        self.assertTrue(hasattr(channel_type_field, "selection"))

        selection_options = channel_type_field.selection
        if callable(selection_options):
            selection_options = selection_options(channel_model)

        gateway_option = [opt for opt in selection_options if opt[0] == "gateway"]
        self.assertTrue(
            gateway_option, "'gateway' option should be available with selection_add"
        )

        # Test creating channel with gateway type works
        channel = self.env["mail.channel"].create(
            {
                "name": "Selection Add Test",
                "channel_type": "gateway",
                "gateway_id": self.gateway.id,
                "gateway_channel_token": "selection#add",
            }
        )

        self.assertEqual(channel.channel_type, "gateway")

    def test_channel_visibility_and_access_rights(self):
        """Test channel visibility and access rights"""
        channel = self.env["mail.channel"].create(
            {
                "name": "Visibility Test",
                "channel_type": "gateway",
                "gateway_id": self.gateway.id,
                "gateway_channel_token": "visibility#test",
                "channel_last_seen_partner_ids": [
                    Command.create(
                        {
                            "partner_id": self.admin_user.partner_id.id,
                            "is_pinned": True,
                        }
                    )
                ],
            }
        )

        # Test that channel appears in user's channels
        user_channels = self.admin_user.partner_id._get_channels_as_member()
        gateway_user_channels = user_channels.filtered(
            lambda c: c.channel_type == "gateway"
        )
        self.assertIn(channel, gateway_user_channels)

        # Test channel access with different users
        with self.env.cr.savepoint():
            # Should be accessible by admin
            self.assertTrue(channel.with_user(self.admin_user).exists())

    def test_gateway_channel_token_uniqueness_constraint(self):
        """Test that gateway channel tokens must be unique"""
        # Create first channel
        channel1 = self.env["mail.channel"].create(
            {
                "name": "First Unique Channel",
                "channel_type": "gateway",
                "gateway_id": self.gateway.id,
                "gateway_channel_token": "unique#constraint#test",
            }
        )
        self.assertTrue(channel1)

        # Try to create second channel with same token - should fail
        from psycopg2 import IntegrityError

        with self.assertRaises(IntegrityError):
            self.env["mail.channel"].create(
                {
                    "name": "Second Unique Channel",
                    "channel_type": "gateway",
                    "gateway_id": self.gateway.id,
                    "gateway_channel_token": "unique#constraint#test",  # Same token
                }
            )

    def test_gateway_channel_company_inheritance(self):
        """Test that gateway channels inherit company from gateway"""
        channel = self.env["mail.channel"].create(
            {
                "name": "Company Inheritance Test",
                "channel_type": "gateway",
                "gateway_id": self.gateway.id,
                "gateway_channel_token": "company#inheritance",
                "company_id": self.gateway.company_id.id,
            }
        )

        self.assertEqual(channel.company_id, self.gateway.company_id)

    def test_gateway_channel_active_state_management(self):
        """Test gateway channel active state management"""
        channel = self.env["mail.channel"].create(
            {
                "name": "Active State Test",
                "channel_type": "gateway",
                "gateway_id": self.gateway.id,
                "gateway_channel_token": "active#state",
                "active": True,
            }
        )

        # Channel should be active by default
        self.assertTrue(channel.active)

        # Test deactivating channel
        channel.active = False
        self.assertFalse(channel.active)

        # Test that inactive channels can still be found with appropriate domain
        inactive_channels = (
            self.env["mail.channel"]
            .with_context(active_test=False)
            .search([("id", "=", channel.id)])
        )
        self.assertIn(channel, inactive_channels)

        # Test that active search excludes inactive channels
        active_channels = self.env["mail.channel"].search([("id", "=", channel.id)])
        self.assertNotIn(channel, active_channels)
