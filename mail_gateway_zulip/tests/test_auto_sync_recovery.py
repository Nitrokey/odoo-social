# Copyright 2025 Nitrokey GmbH
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from unittest.mock import patch

from odoo.tests.common import TransactionCase


class TestAutoSyncRecovery(TransactionCase):
    """Test auto-sync recovery functionality for inconsistent states"""

    def setUp(self):
        super().setUp()

        # Create a test gateway
        self.gateway = self.env["mail.gateway"].create(
            {
                "name": "Test Zulip Gateway",
                "gateway_type": "zulip",
                "token": "test-gateway-token",
                "zulip_server_url": "https://test.zulipchat.com",
                "zulip_bot_email": "bot@test.zulipchat.com",
                "zulip_api_key": "test-api-key",
                "zulip_listener_active": False,  # Listener inactive (inconsistent state)
                "zulip_queue_id": "test-queue-123",  # Has queue ID
            }
        )

    def test_auto_recovery_on_write(self):
        """Test that inconsistent state is detected and fixed on write"""
        # Verify initial inconsistent state (configured but listener inactive)
        self.assertTrue(self.gateway._is_zulip_configured())
        self.assertFalse(self.gateway.zulip_listener_active)

        # Mock the start_auto_sync method to simulate successful activation
        with patch(
            "odoo.addons.mail_gateway_zulip.models.mail_gateway_zulip."
            "MailGatewayZulipService.start_auto_sync"
        ) as mock_start_auto_sync:
            # Simulate successful listener activation
            def activate_listener(gateway):
                gateway.zulip_listener_active = True

            mock_start_auto_sync.side_effect = activate_listener

            # Trigger write operation (any field change should trigger recovery)
            self.gateway.write({"name": "Updated Gateway Name"})

            # Verify that start_auto_sync was called
            mock_start_auto_sync.assert_called_once_with(self.gateway)

            # Verify that the inconsistent state was fixed
            self.assertTrue(self.gateway.zulip_listener_active)

    def test_no_recovery_when_consistent(self):
        """Test that no recovery is attempted when state is consistent"""
        # Set consistent state (configured and listener active)
        self.gateway.write(
            {
                "zulip_listener_active": True,
            }
        )

        with patch(
            "odoo.addons.mail_gateway_zulip.models.mail_gateway_zulip."
            "MailGatewayZulipService.start_auto_sync"
        ) as mock_start_auto_sync:
            # Trigger write operation
            self.gateway.write({"name": "Updated Gateway Name"})

            # Verify that start_auto_sync was NOT called (no recovery needed)
            mock_start_auto_sync.assert_not_called()

    def test_recovery_when_not_configured(self):
        """Test that no recovery is attempted when gateway is not configured"""
        # Set state where gateway is not configured (missing API key)
        self.gateway.write(
            {
                "zulip_api_key": False,
                "zulip_listener_active": True,  # Listener active but not configured
            }
        )

        with patch(
            "odoo.addons.mail_gateway_zulip.models.mail_gateway_zulip."
            "MailGatewayZulipService.start_auto_sync"
        ) as mock_start_auto_sync:
            # Trigger write operation
            self.gateway.write({"name": "Updated Gateway Name"})

            # Verify that start_auto_sync was NOT called
            mock_start_auto_sync.assert_not_called()

    def test_recovery_failure_handling(self):
        """Test that recovery failure is handled gracefully"""
        # Verify initial inconsistent state
        self.assertTrue(self.gateway._is_zulip_configured())
        self.assertFalse(self.gateway.zulip_listener_active)

        # Mock start_auto_sync to fail
        with patch(
            "odoo.addons.mail_gateway_zulip.models.mail_gateway_zulip."
            "MailGatewayZulipService.start_auto_sync"
        ) as mock_start_auto_sync:
            # Simulate failure (listener remains inactive)
            mock_start_auto_sync.return_value = None

            # Trigger write operation - should not raise exception
            self.gateway.write({"name": "Updated Gateway Name"})

            # Verify that start_auto_sync was called
            mock_start_auto_sync.assert_called_once_with(self.gateway)

            # Verify that the state remains inconsistent (recovery failed)
            self.assertTrue(self.gateway._is_zulip_configured())
            self.assertFalse(self.gateway.zulip_listener_active)

    def test_recovery_with_exception(self):
        """Test that exceptions during recovery don't break the write operation"""
        # Verify initial inconsistent state
        self.assertTrue(self.gateway._is_zulip_configured())
        self.assertFalse(self.gateway.zulip_listener_active)

        # Mock start_auto_sync to raise exception
        with patch(
            "odoo.addons.mail_gateway_zulip.models.mail_gateway_zulip."
            "MailGatewayZulipService.start_auto_sync"
        ) as mock_start_auto_sync:
            mock_start_auto_sync.side_effect = Exception("Connection failed")

            # Trigger write operation - should not raise exception
            self.gateway.write({"name": "Updated Gateway Name"})

            # Verify that the write operation completed successfully
            self.assertEqual(self.gateway.name, "Updated Gateway Name")

            # Verify that start_auto_sync was called
            mock_start_auto_sync.assert_called_once_with(self.gateway)

    def test_should_retry_activation_helper(self):
        """Test the _should_retry_activation helper method"""
        # Test with inconsistent state (configured but listener inactive)
        self.gateway.write(
            {
                "zulip_listener_active": False,
            }
        )
        self.assertTrue(self.gateway._should_retry_activation())

        # Test with consistent state (configured and listener active)
        self.gateway.write(
            {
                "zulip_listener_active": True,
            }
        )
        self.assertFalse(self.gateway._should_retry_activation())

        # Test with not configured
        self.gateway.write(
            {
                "zulip_api_key": False,
                "zulip_listener_active": False,
            }
        )
        self.assertFalse(self.gateway._should_retry_activation())

    def test_test_connection_detects_inconsistent_state(self):
        """Test that the Test Connection button detects and fixes inconsistent state"""
        # Verify initial inconsistent state
        self.assertTrue(self.gateway._is_zulip_configured())
        self.assertFalse(self.gateway.zulip_listener_active)

        # Mock the Zulip service methods
        with patch(
            "odoo.addons.mail_gateway_zulip.models.mail_gateway_zulip."
            "MailGatewayZulipService.test_zulip_connection"
        ) as mock_test_connection, patch(
            "odoo.addons.mail_gateway_zulip.models.mail_gateway_zulip."
            "MailGatewayZulipService.start_auto_sync"
        ) as mock_start_auto_sync, patch(
            "odoo.addons.mail_gateway_zulip.models.mail_gateway_zulip."
            "MailGatewayZulipService.manual_poll_test"
        ) as mock_poll_test:
            # Mock successful connection test
            mock_test_connection.return_value = True
            mock_poll_test.return_value = True

            # Simulate successful listener activation
            def activate_listener(gateway):
                gateway.zulip_listener_active = True

            mock_start_auto_sync.side_effect = activate_listener

            # Run the test connection
            result = self.gateway.action_test_zulip_connection()

            # Verify that the test was run
            mock_test_connection.assert_called_once_with(self.gateway)

            # Verify that start_auto_sync was called to fix the inconsistent state
            mock_start_auto_sync.assert_called_once_with(self.gateway)

            # Verify that the listener is now active
            self.assertTrue(self.gateway.zulip_listener_active)

            # Verify that a wizard was created with results
            self.assertEqual(result["type"], "ir.actions.act_window")
            self.assertEqual(result["res_model"], "mail.gateway.zulip.test.wizard")

    def test_multiple_gateways_recovery(self):
        """Test recovery works with multiple gateways"""
        # Create second gateway with inconsistent state
        gateway2 = self.env["mail.gateway"].create(
            {
                "name": "Test Zulip Gateway 2",
                "gateway_type": "zulip",
                "token": "test-gateway-token-2",
                "zulip_server_url": "https://test2.zulipchat.com",
                "zulip_bot_email": "bot2@test.zulipchat.com",
                "zulip_api_key": "test-api-key-2",
                "zulip_listener_active": False,
            }
        )

        # Create recordset with both gateways
        gateways = self.gateway | gateway2

        with patch(
            "odoo.addons.mail_gateway_zulip.models.mail_gateway_zulip."
            "MailGatewayZulipService.start_auto_sync"
        ) as mock_start_auto_sync:
            # Simulate successful activation for both
            def activate_listener(gateway):
                gateway.zulip_listener_active = True

            mock_start_auto_sync.side_effect = activate_listener

            # Trigger write on both gateways
            gateways.write({"name": "Updated"})

            # Verify that start_auto_sync was called for both gateways
            self.assertEqual(mock_start_auto_sync.call_count, 2)

            # Verify both gateways are now consistent
            self.assertTrue(self.gateway.zulip_listener_active)
            self.assertTrue(gateway2.zulip_listener_active)
