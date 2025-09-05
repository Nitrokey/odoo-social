# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from unittest.mock import Mock, patch

from odoo.tests.common import TransactionCase


class TestZulipGatewayAutomatic(TransactionCase):
    """Test automatic Events API activation and event listener functionality"""

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
                "zulip_listener_active": False,
            }
        )
        self.zulip_service = self.env["mail.gateway.zulip"]

    def test_automatic_activation_on_configuration(self):
        """Test that Events API starts automatically when gateway is configured"""
        # Create gateway without full configuration
        incomplete_gateway = self.env["mail.gateway"].create(
            {
                "name": "Incomplete Gateway",
                "gateway_type": "zulip",
                "token": "test_token_456",
                "zulip_server_url": "https://test.zulipchat.com",
                "zulip_bot_email": "bot@test.zulipchat.com",
                # Missing zulip_api_key
            }
        )

        with patch(
            "odoo.addons.mail_gateway_zulip.models.mail_gateway_zulip."
            "MailGatewayZulipService.start_auto_sync"
        ) as mock_start:
            # Complete the configuration by adding API key
            incomplete_gateway.write({"zulip_api_key": "new_api_key"})

            # Verify start_auto_sync was called (automatic activation)
            mock_start.assert_called_once_with(incomplete_gateway)

    def test_no_activation_when_already_active(self):
        """Test that no activation occurs when listener is already active"""
        # Set gateway as already active
        self.gateway.write({"zulip_listener_active": True})

        with patch(
            "odoo.addons.mail_gateway_zulip.models.mail_gateway_zulip."
            "MailGatewayZulipService.start_auto_sync"
        ) as mock_start:
            # Update gateway configuration
            self.gateway.write({"name": "Updated Gateway Name"})

            # Verify start_auto_sync was NOT called (already active)
            mock_start.assert_not_called()

    def test_no_activation_when_not_configured(self):
        """Test that no activation occurs when gateway is not fully configured"""
        # Create gateway without API key
        incomplete_gateway = self.env["mail.gateway"].create(
            {
                "name": "Incomplete Gateway",
                "gateway_type": "zulip",
                "token": "test_token_789",
                "zulip_server_url": "https://test.zulipchat.com",
                "zulip_bot_email": "bot@test.zulipchat.com",
                # Missing zulip_api_key
            }
        )

        with patch(
            "odoo.addons.mail_gateway_zulip.models.mail_gateway_zulip."
            "MailGatewayZulipService.start_auto_sync"
        ) as mock_start:
            # Update gateway name (but still not configured)
            incomplete_gateway.write({"name": "Still Incomplete"})

            # Verify start_auto_sync was NOT called (not configured)
            mock_start.assert_not_called()

    @patch("odoo.addons.mail_gateway_zulip.models.mail_gateway_zulip.zulip")
    def test_start_events_api_success(self, mock_zulip):
        """Test successful Events API start"""
        # Mock Zulip client and successful queue registration
        mock_client = Mock()
        mock_zulip.Client.return_value = mock_client
        mock_client.register.return_value = {
            "result": "success",
            "queue_id": "test_queue_123",
            "last_event_id": 42,
        }

        # Start Events API
        self.zulip_service.start_auto_sync(self.gateway)

        # Verify gateway state
        self.assertTrue(self.gateway.zulip_listener_active)
        self.assertEqual(self.gateway.zulip_queue_id, "test_queue_123")
        self.assertEqual(self.gateway.zulip_last_event_id, 42)

    @patch("odoo.addons.mail_gateway_zulip.models.mail_gateway_zulip.zulip")
    def test_start_events_api_failure(self, mock_zulip):
        """Test Events API start failure"""
        # Mock Zulip client and failed queue registration
        mock_client = Mock()
        mock_zulip.Client.return_value = mock_client
        mock_client.register.return_value = {
            "result": "error",
            "msg": "Authentication failed",
        }

        # Start Events API
        self.zulip_service.start_auto_sync(self.gateway)

        # Verify gateway state remains unchanged
        self.assertFalse(self.gateway.zulip_listener_active)
        self.assertFalse(self.gateway.zulip_queue_id)

    def test_stop_events_api(self):
        """Test Events API stop"""
        # Set up active Events API state
        self.gateway.write(
            {
                "zulip_listener_active": True,
                "zulip_queue_id": "test_queue_123",
                "zulip_last_event_id": 42,
            }
        )

        # Stop Events API
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
        """Test that write method handles Events API activation errors gracefully"""
        with patch(
            "odoo.addons.mail_gateway_zulip.models.mail_gateway_zulip."
            "MailGatewayZulipService.start_auto_sync",
            side_effect=Exception("Test error"),
        ):
            # This should not raise an exception
            self.gateway.write({"zulip_api_key": "new_key"})

            # Gateway should still be updated
            self.assertEqual(self.gateway.zulip_api_key, "new_key")

    def test_configuration_check_helper(self):
        """Test the _is_zulip_configured helper method"""
        # Test with incomplete configuration
        incomplete_gateway = self.env["mail.gateway"].create(
            {
                "name": "Incomplete Gateway",
                "gateway_type": "zulip",
                "token": "test_token",
                "zulip_server_url": "https://test.zulipchat.com",
                "zulip_bot_email": "bot@test.zulipchat.com",
                # Missing zulip_api_key
            }
        )
        self.assertFalse(incomplete_gateway._is_zulip_configured())

        # Test with complete configuration
        self.assertTrue(self.gateway._is_zulip_configured())

    def test_should_retry_activation_helper(self):
        """Test the _should_retry_activation helper method"""
        # Test with configured but inactive gateway
        self.gateway.write({"zulip_listener_active": False})
        self.assertTrue(self.gateway._should_retry_activation())

        # Test with configured and active gateway
        self.gateway.write({"zulip_listener_active": True})
        self.assertFalse(self.gateway._should_retry_activation())

        # Test with unconfigured gateway
        self.gateway.write({"zulip_api_key": False, "zulip_listener_active": False})
        self.assertFalse(self.gateway._should_retry_activation())
