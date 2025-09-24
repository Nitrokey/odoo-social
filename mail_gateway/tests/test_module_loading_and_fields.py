# Copyright 2025 Nitrokey GmbH
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from odoo.tests.common import TransactionCase


class TestModuleLoadingAndFields(TransactionCase):
    """Test module loading and field functionality from standalone scripts"""

    def setUp(self):
        super().setUp()
        # Create gateway without gateway_type since it has empty selection
        self.gateway = self.env["mail.gateway"].create(
            {
                "name": "Test Gateway",
                "token": "test_token_123",
                "webhook_key": "test_webhook_key",
            }
        )
        # Manually set gateway_type to bypass validation for testing
        self.env.cr.execute(
            "UPDATE mail_gateway SET gateway_type = %s WHERE id = %s",
            ("test", self.gateway.id),
        )
        self.gateway.invalidate_cache()

    def test_mail_gateway_model_accessibility(self):
        """Test if the mail_gateway models are accessible"""
        # Test mail.gateway model
        try:
            gateway_model = self.env["mail.gateway"]
            self.assertTrue(gateway_model)
        except Exception as e:
            self.fail(f"mail.gateway model not accessible: {e}")

        # Test mail.channel model
        try:
            channel_model = self.env["mail.channel"]
            self.assertTrue(channel_model)
        except Exception as e:
            self.fail(f"mail.channel model not accessible: {e}")

        # Test mail.message model
        try:
            message_model = self.env["mail.message"]
            self.assertTrue(message_model)
        except Exception as e:
            self.fail(f"mail.message model not accessible: {e}")

    def test_message_gateway_fields_exist(self):
        """Test if gateway-related fields exist on mail.message"""
        message_model = self.env["mail.message"]
        message_fields = message_model._fields

        # Test gateway_channel_data field exists
        self.assertIn(
            "gateway_channel_data",
            message_fields,
            "gateway_channel_data field should exist on mail.message",
        )

        # Test gateway_thread_data field exists
        self.assertIn(
            "gateway_thread_data",
            message_fields,
            "gateway_thread_data field should exist on mail.message",
        )

        # Test gateway_channel_id field exists
        self.assertIn(
            "gateway_channel_id",
            message_fields,
            "gateway_channel_id field should exist on mail.message",
        )

    def test_message_gateway_fields_types(self):
        """Test that gateway fields have correct types for Odoo 15.0"""
        message_model = self.env["mail.message"]
        message_fields = message_model._fields

        # Check gateway_channel_data field type
        if "gateway_channel_data" in message_fields:
            gateway_channel_data_field = message_fields["gateway_channel_data"]
            # Should be Text field in Odoo 15.0 (not Serialized)
            field_type = type(gateway_channel_data_field).__name__
            self.assertIn(
                "Text",
                field_type,
                f"gateway_channel_data should be Text field, got {field_type}",
            )

        # Check gateway_thread_data field type
        if "gateway_thread_data" in message_fields:
            gateway_thread_data_field = message_fields["gateway_thread_data"]
            # Should be Text field in Odoo 15.0 (not Serialized)
            field_type = type(gateway_thread_data_field).__name__
            self.assertIn(
                "Text",
                field_type,
                f"gateway_thread_data should be Text field, got {field_type}",
            )

    def test_channel_type_field_includes_gateway(self):
        """Test that channel_type field includes gateway option"""
        channel_model = self.env["mail.channel"]
        channel_fields = channel_model._fields

        self.assertIn("channel_type", channel_fields, "channel_type field should exist")

        channel_type_field = channel_fields["channel_type"]
        self.assertTrue(
            hasattr(channel_type_field, "selection"),
            "channel_type field should have selection",
        )

        selection_options = channel_type_field.selection
        if callable(selection_options):
            selection_options = selection_options(channel_model)

        gateway_option = [opt for opt in selection_options if opt[0] == "gateway"]
        self.assertTrue(gateway_option, "channel_type should include 'gateway' option")

    def test_gateway_functionality_basic(self):
        """Test basic gateway functionality"""
        # Test gateway search
        try:
            gateways = self.env["mail.gateway"].search([])
            self.assertTrue(isinstance(gateways, type(self.env["mail.gateway"])))
        except Exception as e:
            self.fail(f"Gateway search failed: {e}")

        # Test gateway channel search
        try:
            gateway_channels = self.env["mail.channel"].search(
                [("channel_type", "=", "gateway")]
            )
            self.assertTrue(
                isinstance(gateway_channels, type(self.env["mail.channel"]))
            )
        except Exception as e:
            self.fail(f"Gateway channel search failed: {e}")

    def test_gateway_channel_creation_and_info(self):
        """Test gateway channel creation and info method"""
        # Create test gateway channel
        try:
            channel = self.env["mail.channel"].create(
                {
                    "name": "Test Gateway Channel",
                    "channel_type": "gateway",
                    "gateway_id": self.gateway.id,
                    "gateway_channel_token": "test#channel",
                }
            )
            self.assertTrue(channel)
        except Exception as e:
            self.fail(f"Gateway channel creation failed: {e}")

        # Test channel_info method
        try:
            channel_info = channel.channel_info()
            self.assertTrue(isinstance(channel_info, list))
        except Exception as e:
            self.fail(f"channel_info() method failed: {e}")

    def test_message_fields_accessibility(self):
        """Test that message fields are accessible and work correctly"""
        # Create a test message
        try:
            message = self.env["mail.message"].create(
                {
                    "subject": "Test Message",
                    "body": "Test body",
                    "message_type": "comment",
                }
            )
            self.assertTrue(message)
        except Exception as e:
            self.fail(f"Message creation failed: {e}")

        # Test accessing gateway_channel_data field
        try:
            gateway_channel_data = message.gateway_channel_data
            # Field should be accessible (can be None/empty)
            self.assertTrue(gateway_channel_data is None or gateway_channel_data)
        except Exception as e:
            self.fail(f"gateway_channel_data field access failed: {e}")

        # Test accessing gateway_thread_data field
        try:
            gateway_thread_data = message.gateway_thread_data
            # Field should be accessible (can be None/empty)
            self.assertTrue(gateway_thread_data is None or gateway_thread_data)
        except Exception as e:
            self.fail(f"gateway_thread_data field access failed: {e}")

        # Clean up
        message.unlink()

    def test_gateway_models_integration(self):
        """Test integration between gateway models"""
        # Create gateway channel
        channel = self.env["mail.channel"].create(
            {
                "name": "Integration Test Channel",
                "channel_type": "gateway",
                "gateway_id": self.gateway.id,
                "gateway_channel_token": "integration#test",
            }
        )

        # Create message in channel
        message = self.env["mail.message"].create(
            {
                "subject": "Integration Test Message",
                "body": "<p>Test content</p>",
                "message_type": "comment",
                "model": "mail.channel",
                "res_id": channel.id,
            }
        )

        # Test relationships
        self.assertEqual(message.model, "mail.channel")
        self.assertEqual(message.res_id, channel.id)
        self.assertEqual(channel.gateway_id, self.gateway)

    def test_gateway_guest_model_functionality(self):
        """Test gateway guest model functionality"""
        try:
            # Test guest creation
            guest = self.env["mail.guest"].create(
                {
                    "name": "Test Guest",
                    "gateway_id": self.gateway.id,
                    "gateway_token": "guest_token_123",
                }
            )

            self.assertTrue(guest)
            self.assertEqual(guest.name, "Test Guest")
            self.assertEqual(guest.gateway_id, self.gateway)
            self.assertEqual(guest.gateway_token, "guest_token_123")

        except Exception as e:
            self.fail(f"Gateway guest functionality failed: {e}")

    def test_gateway_notification_model_functionality(self):
        """Test gateway notification model functionality"""
        # Create test channel and message
        channel = self.env["mail.channel"].create(
            {
                "name": "Notification Test Channel",
                "channel_type": "gateway",
                "gateway_id": self.gateway.id,
                "gateway_channel_token": "notification#test",
            }
        )

        message = self.env["mail.message"].create(
            {
                "subject": "Notification Test Message",
                "body": "<p>Test content</p>",
                "message_type": "comment",
                "model": "mail.channel",
                "res_id": channel.id,
            }
        )

        # Create partner for notification
        partner = self.env["res.partner"].create(
            {
                "name": "Test Partner",
                "email": "test@example.com",
            }
        )

        try:
            # Test notification creation
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
            self.fail(f"Gateway notification functionality failed: {e}")

    def test_serialized_to_json_field_migration(self):
        """Test that Serialized fields have been properly migrated to Json/Text"""
        message_model = self.env["mail.message"]
        message_fields = message_model._fields

        # Check that fields exist and are not Serialized type
        for field_name in ["gateway_channel_data", "gateway_thread_data"]:
            if field_name in message_fields:
                field = message_fields[field_name]
                field_type = type(field).__name__
                # Should not be Serialized field anymore
                self.assertNotIn(
                    "Serialized",
                    field_type,
                    f"{field_name} should not be Serialized field in Odoo 15.0",
                )
                # Should be Text or Json field
                self.assertTrue(
                    "Text" in field_type or "Json" in field_type,
                    f"{field_name} should be Text or Json field, got {field_type}",
                )

    def test_gateway_webhook_functionality(self):
        """Test gateway webhook functionality"""
        # Test webhook URL generation
        try:
            webhook_url = self.gateway._get_webhook_url()
            self.assertTrue(webhook_url)
            self.assertIn(self.gateway.webhook_key, webhook_url)
        except Exception as e:
            self.fail(f"Webhook URL generation failed: {e}")

        # Test webhook state management
        try:
            # Initially should be False/None
            self.assertFalse(self.gateway.integrated_webhook_state)

            # Test can_set_webhook computation
            can_set = self.gateway._can_set_webhook()
            self.assertTrue(isinstance(can_set, bool))

        except Exception as e:
            self.fail(f"Webhook functionality failed: {e}")

    def test_gateway_company_and_user_associations(self):
        """Test gateway company and user associations"""
        # Test company association
        self.assertTrue(self.gateway.company_id)

        # Test webhook user
        self.assertTrue(self.gateway.webhook_user_id)

        # Test member associations
        try:
            # Should be able to access members
            members = self.gateway.member_ids
            self.assertTrue(isinstance(members, type(self.env["res.users"])))
        except Exception as e:
            self.fail(f"Gateway member access failed: {e}")
