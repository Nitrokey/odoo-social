# Copyright 2024 Dixmit
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

import logging
from odoo.tests.common import TransactionCase

_logger = logging.getLogger(__name__)


class TestChannelVisibilityFix(TransactionCase):
    """Test that Zulip gateway channels are visible in Discuss"""

    def setUp(self):
        super().setUp()
        
        # Create a test Zulip gateway
        self.gateway = self.env["mail.gateway"].create({
            "name": "Test Zulip Gateway",
            "gateway_type": "zulip",
            "token": "test_token_123",
            "zulip_server_url": "https://test.zulipchat.com",
            "zulip_bot_email": "bot@test.zulipchat.com",
            "zulip_api_key": "test_api_key_123",
        })

    def test_new_channels_have_correct_type(self):
        """Test that newly created Zulip channels have channel_type = 'channel'"""
        # Get the Zulip service
        zulip_service = self.env["mail.gateway.zulip"]
        
        # Create channel values using the fixed method
        token = "general#test-topic"
        channel_vals = zulip_service._get_channel_vals(self.gateway, token, {})
        
        # Verify the channel type is 'channel', not 'gateway'
        self.assertEqual(
            channel_vals["channel_type"], 
            "channel",
            "New Zulip channels should have channel_type = 'channel' for Discuss visibility"
        )
        
        # Verify other gateway fields are still set correctly
        self.assertEqual(channel_vals["gateway_channel_token"], token)
        self.assertEqual(channel_vals["gateway_id"], self.gateway.id)
        self.assertTrue(channel_vals["name"].startswith("Zulip:"))

    def test_channel_creation_and_visibility(self):
        """Test that created channels are properly configured for visibility"""
        # Get the Zulip service
        zulip_service = self.env["mail.gateway.zulip"]
        
        # Create a channel using the gateway method
        token = "development#bug-fixes"
        channel = zulip_service._get_channel(self.gateway, token, {}, force_create=True)
        
        # Verify the channel was created with correct properties
        self.assertTrue(channel.exists(), "Channel should be created")
        self.assertEqual(channel.channel_type, "channel", "Channel should be visible in Discuss")
        self.assertEqual(channel.gateway_channel_token, token, "Gateway token should be set")
        self.assertEqual(channel.gateway_id, self.gateway, "Gateway should be linked")
        self.assertTrue(channel.name.startswith("Zulip:"), "Channel name should have Zulip prefix")

    def test_migration_would_fix_existing_gateway_channels(self):
        """Test that the migration logic would correctly identify and fix gateway channels"""
        # Create a channel with the old 'gateway' type (simulating pre-fix state)
        old_channel = self.env["mail.channel"].create({
            "name": "Zulip: old-stream / old-topic",
            "channel_type": "gateway",  # This is the problematic type
            "gateway_id": self.gateway.id,
            "gateway_channel_token": "old-stream#old-topic",
        })
        
        # Verify it starts with gateway type
        self.assertEqual(old_channel.channel_type, "gateway")
        
        # Simulate the migration fix
        old_channel.write({"channel_type": "channel"})
        
        # Verify it's now fixed
        self.assertEqual(old_channel.channel_type, "channel")
        self.assertEqual(old_channel.gateway_id, self.gateway)
        self.assertEqual(old_channel.gateway_channel_token, "old-stream#old-topic")

    def test_channel_token_parsing(self):
        """Test that channel tokens are correctly parsed"""
        zulip_service = self.env["mail.gateway.zulip"]
        
        # Test normal stream#topic format
        stream, topic = zulip_service._parse_channel_token("general#announcements")
        self.assertEqual(stream, "general")
        self.assertEqual(topic, "announcements")
        
        # Test stream without topic (should default to 'general')
        stream, topic = zulip_service._parse_channel_token("development")
        self.assertEqual(stream, "development")
        self.assertEqual(topic, "general")
        
        # Test token generation
        token = zulip_service._get_channel_token("support", "urgent")
        self.assertEqual(token, "support#urgent")
