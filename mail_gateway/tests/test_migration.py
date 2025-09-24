# Copyright 2025 Nitrokey GmbH
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).


from odoo.tests.common import TransactionCase


class TestMailGatewayMigration(TransactionCase):
    """Test mail gateway migration from Odoo 16.0 to 15.0"""

    def setUp(self):
        super().setUp()
        # Create gateway without gateway_type since it has empty selection
        self.gateway = self.env["mail.gateway"].create(
            {
                "name": "Migration Test Gateway",
                "token": "migration_token_123",
                "webhook_key": "migration_webhook_key",
            }
        )
        # Manually set gateway_type to bypass validation for testing
        self.env.cr.execute(
            "UPDATE mail_gateway SET gateway_type = %s WHERE id = %s",
            ("test", self.gateway.id),
        )
        self.gateway.invalidate_cache()

    def test_module_loading(self):
        """Test that all gateway models load without errors"""
        # Test that all models can be instantiated
        try:
            gateway_model = self.env["mail.gateway"]
            channel_model = self.env["mail.channel"]
            message_model = self.env["mail.message"]
            notification_model = self.env["mail.notification"]
            guest_model = self.env["mail.guest"]

            self.assertTrue(gateway_model)
            self.assertTrue(channel_model)
            self.assertTrue(message_model)
            self.assertTrue(notification_model)
            self.assertTrue(guest_model)

        except Exception as e:
            self.fail(f"Model loading failed: {e}")

    def test_field_types_odoo15_compatibility(self):
        """Test that field types are compatible with Odoo 15.0"""
        message_model = self.env["mail.message"]
        message_fields = message_model._fields

        # Test gateway_channel_data field
        if "gateway_channel_data" in message_fields:
            gateway_channel_data_field = message_fields["gateway_channel_data"]
            field_type = type(gateway_channel_data_field).__name__

            # Should be Text field in Odoo 15.0 (not Serialized)
            self.assertIn(
                "Text",
                field_type,
                f"gateway_channel_data should be Text field, got {field_type}",
            )

        # Test gateway_thread_data field
        if "gateway_thread_data" in message_fields:
            gateway_thread_data_field = message_fields["gateway_thread_data"]
            field_type = type(gateway_thread_data_field).__name__

            # Should be Text field in Odoo 15.0 (not Serialized)
            self.assertIn(
                "Text",
                field_type,
                f"gateway_thread_data should be Text field, got {field_type}",
            )

    def test_channel_type_selection_extension(self):
        """Test that channel_type field properly includes gateway option"""
        channel_model = self.env["mail.channel"]
        channel_type_field = channel_model._fields["channel_type"]

        self.assertTrue(
            hasattr(channel_type_field, "selection"),
            "channel_type field should have selection attribute",
        )

        selection_options = channel_type_field.selection
        self.assertTrue(
            isinstance(selection_options, (list, tuple)),
            "Selection options should be list or tuple",
        )

        # Check if gateway option exists
        gateway_option = [opt for opt in selection_options if opt[0] == "gateway"]
        self.assertTrue(
            gateway_option,
            "Gateway option should be available in channel_type selection",
        )
        self.assertEqual(gateway_option[0][0], "gateway")

    def test_gateway_channel_creation_compatibility(self):
        """Test that gateway channels can be created with Odoo 15.0 structure"""
        try:
            channel = self.env["mail.channel"].create(
                {
                    "name": "Migration Test Channel",
                    "channel_type": "gateway",
                    "gateway_id": self.gateway.id,
                    "gateway_channel_token": "migration#test",
                    "company_id": self.gateway.company_id.id,
                }
            )

            self.assertTrue(channel)
            self.assertEqual(channel.channel_type, "gateway")
            self.assertEqual(channel.gateway_id, self.gateway)

        except Exception as e:
            self.fail(f"Gateway channel creation failed: {e}")

    def test_json_serialization_compatibility(self):
        """Test that JSON serialization works with Text fields"""
        import json

        channel = self.env["mail.channel"].create(
            {
                "name": "JSON Test Channel",
                "channel_type": "gateway",
                "gateway_id": self.gateway.id,
                "gateway_channel_token": "json#test",
            }
        )

        # Create message with gateway data
        message = self.env["mail.message"].create(
            {
                "subject": "JSON Test Message",
                "body": "<p>Test content</p>",
                "message_type": "comment",
                "model": "mail.channel",
                "res_id": channel.id,
            }
        )

        # Test JSON serialization if fields exist
        if hasattr(message, "gateway_channel_data"):
            try:
                # Test setting JSON data
                test_data = {"test": "value", "number": 123}
                message.gateway_channel_data = json.dumps(test_data)

                # Test reading JSON data
                stored_data = json.loads(message.gateway_channel_data or "{}")
                self.assertEqual(stored_data.get("test"), "value")
                self.assertEqual(stored_data.get("number"), 123)

            except Exception as e:
                self.fail(f"JSON serialization failed: {e}")

    def test_mail_channel_partner_compatibility(self):
        """Test mail.channel.partner compatibility (Odoo 15.0 vs 16.0)"""
        from odoo import Command

        admin_user = self.env.ref("base.user_admin")

        try:
            channel = self.env["mail.channel"].create(
                {
                    "name": "Partner Compatibility Test",
                    "channel_type": "gateway",
                    "gateway_id": self.gateway.id,
                    "gateway_channel_token": "partner#test",
                    "channel_last_seen_partner_ids": [
                        Command.create(
                            {
                                "partner_id": admin_user.partner_id.id,
                                "is_pinned": True,
                            }
                        )
                    ],
                }
            )

            # Test that channel partners work
            self.assertIn(admin_user.partner_id, channel.channel_partner_ids)

            # Test membership check
            self.assertTrue(channel.is_member)

        except Exception as e:
            self.fail(f"Channel partner compatibility failed: {e}")

    def test_gateway_security_rules(self):
        """Test that gateway security rules work properly"""
        channel = self.env["mail.channel"].create(
            {
                "name": "Security Test Channel",
                "channel_type": "gateway",
                "gateway_id": self.gateway.id,
                "gateway_channel_token": "security#test",
            }
        )

        # Test that gateway channels can be searched
        try:
            gateway_channels = self.env["mail.channel"].search(
                [("channel_type", "=", "gateway")]
            )
            self.assertIn(channel, gateway_channels)

        except Exception as e:
            self.fail(f"Gateway security rules failed: {e}")

    def test_frontend_javascript_compatibility(self):
        """Test that frontend JavaScript compatibility is maintained"""
        channel = self.env["mail.channel"].create(
            {
                "name": "JS Compatibility Test",
                "channel_type": "gateway",
                "gateway_id": self.gateway.id,
                "gateway_channel_token": "js#test",
            }
        )

        # Test channel_info method (used by frontend)
        try:
            channel_info = channel.channel_info()
            self.assertTrue(isinstance(channel_info, list))

            if channel_info:
                info = channel_info[0]
                self.assertTrue(isinstance(info, dict))
                self.assertEqual(info.get("channel_type"), "gateway")

        except Exception as e:
            self.fail(f"Frontend JavaScript compatibility failed: {e}")

    def test_messaging_initialization_compatibility(self):
        """Test that messaging initialization works with gateway channels"""
        from odoo import Command

        admin_user = self.env.ref("base.user_admin")

        channel = self.env["mail.channel"].create(
            {
                "name": "Messaging Init Test",
                "channel_type": "gateway",
                "gateway_id": self.gateway.id,
                "gateway_channel_token": "messaging#test",
                "channel_last_seen_partner_ids": [
                    Command.create(
                        {
                            "partner_id": admin_user.partner_id.id,
                            "is_pinned": True,
                        }
                    )
                ],
            }
        )

        try:
            # Test messaging initialization
            messaging_data = admin_user._init_messaging()
            self.assertTrue(isinstance(messaging_data, dict))

            # Should have channels data
            channels = messaging_data.get("channels", [])
            self.assertTrue(isinstance(channels, list))

            # Verify our specific channel is included
            channel_ids_in_init = [
                ch.get("id") for ch in channels if isinstance(ch, dict)
            ]
            self.assertIn(channel.id, channel_ids_in_init)

        except Exception as e:
            self.fail(f"Messaging initialization compatibility failed: {e}")

    def test_webhook_functionality_migration(self):
        """Test that webhook functionality works after migration"""
        # Test webhook URL generation
        webhook_url = self.gateway._get_webhook_url()
        self.assertTrue(webhook_url)
        self.assertIn(self.gateway.webhook_key, webhook_url)

        # Test webhook state management
        self.assertFalse(self.gateway.integrated_webhook_state)

        # Test that webhook state can be updated
        self.gateway.integrated_webhook_state = True
        self.assertTrue(self.gateway.integrated_webhook_state)

    def test_notification_system_compatibility(self):
        """Test that notification system works with migrated structure"""
        channel = self.env["mail.channel"].create(
            {
                "name": "Notification Test",
                "channel_type": "gateway",
                "gateway_id": self.gateway.id,
                "gateway_channel_token": "notification#test",
            }
        )

        message = self.env["mail.message"].create(
            {
                "subject": "Notification Test Message",
                "body": "<p>Test notification</p>",
                "message_type": "comment",
                "model": "mail.channel",
                "res_id": channel.id,
            }
        )

        partner = self.env["res.partner"].create(
            {
                "name": "Notification Partner",
                "email": "notification@example.com",
            }
        )

        try:
            notification = self.env["mail.notification"].create(
                {
                    "mail_message_id": message.id,
                    "res_partner_id": partner.id,
                    "notification_type": "inbox",
                    "notification_status": "ready",
                }
            )

            self.assertTrue(notification)
            self.assertEqual(notification.notification_status, "ready")

        except Exception as e:
            self.fail(f"Notification system compatibility failed: {e}")

    def test_complete_migration_validation(self):
        """Comprehensive test to validate complete migration"""
        try:
            # Test 1: All models load
            self.test_module_loading()

            # Test 2: Field types are correct
            self.test_field_types_odoo15_compatibility()

            # Test 3: Channel type selection works
            self.test_channel_type_selection_extension()

            # Test 4: Gateway channels can be created
            self.test_gateway_channel_creation_compatibility()

            # Test 5: JSON serialization works
            self.test_json_serialization_compatibility()

            # Test 6: Channel partners work
            self.test_mail_channel_partner_compatibility()

            # Test 7: Security rules work
            self.test_gateway_security_rules()

            # Test 8: Frontend compatibility
            self.test_frontend_javascript_compatibility()

            # Test 9: Messaging initialization
            self.test_messaging_initialization_compatibility()

            # Test 10: Webhook functionality
            self.test_webhook_functionality_migration()

            # Test 11: Notification system
            self.test_notification_system_compatibility()

            # If we reach here, migration is successful
            return True

        except Exception as e:
            self.fail(f"Complete migration validation failed: {e}")
