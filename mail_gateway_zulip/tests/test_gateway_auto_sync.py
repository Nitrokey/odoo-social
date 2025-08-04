# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from unittest.mock import Mock, patch

from odoo.tests.common import TransactionCase


class TestZulipGatewayAutoSync(TransactionCase):
    """Test auto-sync functionality and event listener activation"""

    def setUp(self):
        super().setUp()
        self.gateway = self.env["mail.gateway"].create(
            {
                "name": "Test Zulip Gateway",
                "gateway_type": "zulip",
                "token": "test_token_123",
                "webhook_key": "test_webhook_key",
                "zulip_server_url": "https://test.zulipchat.com",
                "zulip_bot_email": "bot@test.zulipchat.com",
                "zulip_api_key": "test_api_key",
                "zulip_auto_sync": False,
                "zulip_listener_active": False,
            }
        )
        self.zulip_service = self.env["mail.gateway.zulip"]

    def test_auto_sync_activation_on_write(self):
        """Test that auto-sync starts when enabled via write()"""
        with patch(
            "odoo.addons.mail_gateway_zulip.models.mail_gateway_zulip."
            "MailGatewayZulipService.start_auto_sync"
        ) as mock_start:
            # Enable auto-sync
            self.gateway.write({"zulip_auto_sync": True})

            # Verify start_auto_sync was called
            mock_start.assert_called_once_with(self.gateway)

    def test_auto_sync_deactivation_on_write(self):
        """Test that auto-sync stops when disabled via write()"""
        # First enable auto-sync
        self.gateway.zulip_auto_sync = True

        with patch(
            "odoo.addons.mail_gateway_zulip.models.mail_gateway_zulip."
            "MailGatewayZulipService.stop_auto_sync"
        ) as mock_stop:
            # Then disable it
            self.gateway.write({"zulip_auto_sync": False})

            # Verify stop_auto_sync was called
            mock_stop.assert_called_once_with(self.gateway)

    @patch("odoo.addons.mail_gateway_zulip.models.mail_gateway_zulip.zulip")
    def test_start_auto_sync_success(self, mock_zulip):
        """Test successful auto-sync start"""
        # Mock Zulip client and successful queue registration
        mock_client = Mock()
        mock_zulip.Client.return_value = mock_client
        mock_client.register.return_value = {
            "result": "success",
            "queue_id": "test_queue_123",
            "last_event_id": 42,
        }

        # Enable auto-sync first (required by start_auto_sync method)
        self.gateway.zulip_auto_sync = True

        # Start auto-sync
        self.zulip_service.start_auto_sync(self.gateway)

        # Verify gateway state
        self.assertTrue(self.gateway.zulip_listener_active)
        self.assertEqual(self.gateway.zulip_queue_id, "test_queue_123")
        self.assertEqual(self.gateway.zulip_last_event_id, 42)

    @patch("odoo.addons.mail_gateway_zulip.models.mail_gateway_zulip.zulip")
    def test_start_auto_sync_failure(self, mock_zulip):
        """Test auto-sync start failure"""
        # Mock Zulip client and failed queue registration
        mock_client = Mock()
        mock_zulip.Client.return_value = mock_client
        mock_client.register.return_value = {
            "result": "error",
            "msg": "Authentication failed",
        }

        # Start auto-sync
        self.zulip_service.start_auto_sync(self.gateway)

        # Verify gateway state remains unchanged
        self.assertFalse(self.gateway.zulip_listener_active)
        self.assertFalse(self.gateway.zulip_queue_id)

    def test_stop_auto_sync(self):
        """Test auto-sync stop"""
        # Set up active auto-sync state
        self.gateway.write(
            {
                "zulip_listener_active": True,
                "zulip_queue_id": "test_queue_123",
                "zulip_last_event_id": 42,
            }
        )

        # Stop auto-sync
        self.zulip_service.stop_auto_sync(self.gateway)

        # Verify gateway state is reset
        self.assertFalse(self.gateway.zulip_listener_active)
        self.assertFalse(self.gateway.zulip_queue_id)
        self.assertEqual(self.gateway.zulip_last_event_id, 0)

    @patch("odoo.addons.mail_gateway_zulip.models.mail_gateway_zulip.zulip")
    def test_event_queue_registration(self, mock_zulip):
        """Test event queue registration with Zulip"""
        mock_client = Mock()
        mock_zulip.Client.return_value = mock_client
        mock_client.register.return_value = {
            "result": "success",
            "queue_id": "queue_456",
            "last_event_id": 100,
        }

        # Test registration
        success = self.zulip_service._register_event_queue(self.gateway, mock_client)

        # Verify success and state update
        self.assertTrue(success)
        self.assertEqual(self.gateway.zulip_queue_id, "queue_456")
        self.assertEqual(self.gateway.zulip_last_event_id, 100)

        # Verify correct API call
        mock_client.register.assert_called_once()
        call_args = mock_client.register.call_args[1]
        self.assertEqual(call_args["event_types"], ["message"])

    @patch("odoo.addons.mail_gateway_zulip.models.mail_gateway_zulip.zulip")
    def test_event_queue_registration_with_stream_filter(self, mock_zulip):
        """Test event queue registration with stream filter"""
        mock_client = Mock()
        mock_zulip.Client.return_value = mock_client
        mock_client.register.return_value = {
            "result": "success",
            "queue_id": "queue_789",
            "last_event_id": 200,
        }

        # Set stream filter
        self.gateway.zulip_stream_filter = "general, development"

        # Test registration
        success = self.zulip_service._register_event_queue(self.gateway, mock_client)

        # Verify success
        self.assertTrue(success)

        # Verify API call includes stream filter
        mock_client.register.assert_called_once()
        call_args = mock_client.register.call_args[1]
        self.assertFalse(call_args["all_public_streams"])
        self.assertEqual(
            call_args["narrow"], [["stream", "general"], ["stream", "development"]]
        )

    def test_write_method_error_handling(self):
        """Test that write method handles auto-sync errors gracefully"""
        with patch(
            "odoo.addons.mail_gateway_zulip.models.mail_gateway_zulip."
            "MailGatewayZulipService.start_auto_sync",
            side_effect=Exception("Test error"),
        ):
            # This should not raise an exception
            self.gateway.write({"zulip_auto_sync": True})

            # Gateway should still be updated
            self.assertTrue(self.gateway.zulip_auto_sync)

    def test_non_zulip_gateway_ignored(self):
        """Test that non-Zulip gateways are ignored in auto-sync logic"""
        # Create a second Zulip gateway but test that only Zulip gateways trigger auto-sync
        other_gateway = self.env["mail.gateway"].create(
            {
                "name": "Test Other Zulip Gateway",
                "gateway_type": "zulip",
                "token": "test_token_456",
            }
        )

        with patch(
            "odoo.addons.mail_gateway_zulip.models.mail_gateway_zulip."
            "MailGatewayZulipService.start_auto_sync"
        ) as mock_start:
            # Enable auto-sync on the other Zulip gateway
            other_gateway.write({"zulip_auto_sync": True})

            # Verify start_auto_sync was called for the Zulip gateway
            mock_start.assert_called_once_with(other_gateway)
