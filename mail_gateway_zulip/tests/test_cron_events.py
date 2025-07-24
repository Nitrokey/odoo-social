# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from unittest.mock import Mock, patch

from odoo.tests.common import TransactionCase


class TestZulipCronEvents(TransactionCase):
    """Test Zulip cron job and event polling functionality"""

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
                "zulip_auto_sync": True,
                "zulip_listener_active": True,
                "zulip_queue_id": "test_queue_123",
                "zulip_last_event_id": 100,
            }
        )
        self.zulip_service = self.env["mail.gateway.zulip"]

    def test_cron_poll_events_finds_active_gateways(self):
        """Test that cron job finds active gateways"""
        # Create inactive gateway
        inactive_gateway = self.env["mail.gateway"].create(
            {
                "name": "Inactive Gateway",
                "gateway_type": "zulip",
                "token": "inactive_token",
                "zulip_auto_sync": False,  # Not active
                "zulip_listener_active": False,
            }
        )

        with patch("odoo.addons.mail_gateway_zulip.models.mail_gateway_zulip.MailGatewayZulipService._poll_gateway_events") as mock_poll:
            self.zulip_service._cron_poll_events()

            # Should poll active gateways (there might be more than one)
            self.assertTrue(mock_poll.called)
            # Verify our test gateway was called
            called_gateways = [call[0][0] for call in mock_poll.call_args_list]
            self.assertIn(self.gateway, called_gateways)
            # Verify inactive gateway was not called
            self.assertNotIn(inactive_gateway, called_gateways)

    @patch("odoo.addons.mail_gateway_zulip.models.mail_gateway_zulip.zulip")
    def test_poll_gateway_events_success(self, mock_zulip):
        """Test successful event polling"""
        # Mock Zulip client and events
        mock_client = Mock()
        mock_zulip.Client.return_value = mock_client
        mock_client.get_events.return_value = {
            "result": "success",
            "events": [
                {
                    "id": 101,
                    "type": "message",
                    "message": {
                        "display_recipient": "general",
                        "subject": "test",
                        "content": "Hello!",
                        "sender_email": "user@example.com",
                        "sender_full_name": "Test User",
                    },
                },
                {
                    "id": 102,
                    "type": "message",
                    "message": {
                        "display_recipient": "development",
                        "subject": "bug",
                        "content": "Fixed!",
                        "sender_email": "dev@example.com",
                        "sender_full_name": "Developer",
                    },
                },
            ],
        }

        with patch("odoo.addons.mail_gateway_zulip.models.mail_gateway_zulip.MailGatewayZulipService._process_event") as mock_process:
            self.zulip_service._poll_gateway_events(self.gateway)

            # Verify API call
            mock_client.get_events.assert_called_once_with(
                queue_id="test_queue_123",
                last_event_id=100,
                dont_block=True,
            )

            # Verify events were processed
            self.assertEqual(mock_process.call_count, 2)
            mock_process.assert_any_call(self.gateway, mock_client.get_events.return_value["events"][0])
            mock_process.assert_any_call(self.gateway, mock_client.get_events.return_value["events"][1])

            # Verify last event ID was updated
            self.assertEqual(self.gateway.zulip_last_event_id, 102)

    @patch("odoo.addons.mail_gateway_zulip.models.mail_gateway_zulip.zulip")
    def test_poll_gateway_events_no_events(self, mock_zulip):
        """Test polling when no new events"""
        mock_client = Mock()
        mock_zulip.Client.return_value = mock_client
        mock_client.get_events.return_value = {
            "result": "success",
            "events": [],  # No events
        }

        with patch("odoo.addons.mail_gateway_zulip.models.mail_gateway_zulip.MailGatewayZulipService._process_event") as mock_process:
            self.zulip_service._poll_gateway_events(self.gateway)

            # Verify no events were processed
            mock_process.assert_not_called()

            # Last event ID should remain unchanged
            self.assertEqual(self.gateway.zulip_last_event_id, 100)

    @patch("odoo.addons.mail_gateway_zulip.models.mail_gateway_zulip.zulip")
    def test_poll_gateway_events_bad_queue_id(self, mock_zulip):
        """Test handling of bad queue ID error"""
        mock_client = Mock()
        mock_zulip.Client.return_value = mock_client
        mock_client.get_events.return_value = {
            "result": "error",
            "msg": "Bad event queue id: test_queue_123",
        }

        self.zulip_service._poll_gateway_events(self.gateway)

        # Queue ID should be reset to force re-registration
        self.assertFalse(self.gateway.zulip_queue_id)

    @patch("odoo.addons.mail_gateway_zulip.models.mail_gateway_zulip.zulip")
    def test_poll_gateway_events_no_queue_id(self, mock_zulip):
        """Test polling when no queue ID exists"""
        # Remove queue ID
        self.gateway.zulip_queue_id = False

        # Mock successful queue registration
        mock_client = Mock()
        mock_zulip.Client.return_value = mock_client

        with patch("odoo.addons.mail_gateway_zulip.models.mail_gateway_zulip.MailGatewayZulipService._register_event_queue", return_value=True) as mock_register:
            self.zulip_service._poll_gateway_events(self.gateway)

            # Should attempt to register queue
            mock_register.assert_called_once_with(self.gateway, mock_client)

    @patch("odoo.addons.mail_gateway_zulip.models.mail_gateway_zulip.zulip")
    def test_poll_gateway_events_registration_failure(self, mock_zulip):
        """Test polling when queue registration fails"""
        # Remove queue ID
        self.gateway.zulip_queue_id = False

        mock_client = Mock()
        mock_zulip.Client.return_value = mock_client

        with patch("odoo.addons.mail_gateway_zulip.models.mail_gateway_zulip.MailGatewayZulipService._register_event_queue", return_value=False) as mock_register:
            # Should not raise exception
            self.zulip_service._poll_gateway_events(self.gateway)

            # Should attempt registration but not proceed with polling
            mock_register.assert_called_once()
            mock_client.get_events.assert_not_called()

    @patch("odoo.addons.mail_gateway_zulip.models.mail_gateway_zulip.zulip")
    def test_poll_gateway_events_exception_handling(self, mock_zulip):
        """Test exception handling during polling"""
        mock_client = Mock()
        mock_zulip.Client.return_value = mock_client
        mock_client.get_events.side_effect = Exception("Connection error")

        # Should not raise exception
        self.zulip_service._poll_gateway_events(self.gateway)

        # Queue ID should be reset on error
        self.assertFalse(self.gateway.zulip_queue_id)

    def test_cron_poll_events_handles_exceptions(self):
        """Test that cron job handles individual gateway exceptions"""
        # Create second gateway
        gateway2 = self.env["mail.gateway"].create(
            {
                "name": "Gateway 2",
                "gateway_type": "zulip",
                "token": "token_456",
                "zulip_auto_sync": True,
                "zulip_listener_active": True,
            }
        )

        call_count = 0

        def mock_poll_with_exception(gateway):
            nonlocal call_count
            call_count += 1
            if gateway == self.gateway:
                raise Exception("Test error")
            # Second gateway should still be processed

        with patch("odoo.addons.mail_gateway_zulip.models.mail_gateway_zulip.MailGatewayZulipService._poll_gateway_events", side_effect=mock_poll_with_exception):
            # Should not raise exception
            self.zulip_service._cron_poll_events()

            # At least both gateways should have been attempted (there might be more)
            self.assertGreaterEqual(call_count, 2)

    def test_cron_job_configuration(self):
        """Test that cron job is properly configured"""
        cron = self.env["ir.cron"].search([("name", "=", "Zulip Events Polling")])

        self.assertTrue(cron)
        self.assertEqual(cron.model_id.model, "mail.gateway.zulip")
        self.assertEqual(cron.code, "model._cron_poll_events()")
        self.assertEqual(cron.interval_number, 1)
        self.assertEqual(cron.interval_type, "minutes")
        self.assertTrue(cron.active)

    def test_process_event_calls_receive_update(self):
        """Test that process_event properly calls _receive_update"""
        event = {
            "type": "message",
            "message": {
                "display_recipient": "general",
                "subject": "test",
                "content": "Hello!",
                "sender_email": "user@example.com",
                "sender_full_name": "Test User",
            },
        }

        with patch("odoo.addons.mail_gateway_zulip.models.mail_gateway_zulip.MailGatewayZulipService._receive_update") as mock_receive:
            self.zulip_service._process_event(self.gateway, event)

            # Should call _receive_update with proper format
            mock_receive.assert_called_once()
            args = mock_receive.call_args[0]
            self.assertEqual(args[0], self.gateway)
            self.assertEqual(args[1]["message"], event["message"])
            self.assertEqual(args[1]["type"], "message")

    def test_process_event_filters_streams(self):
        """Test that process_event respects stream filters"""
        # Set stream filter
        self.gateway.zulip_stream_filter = "allowed_stream"

        # Event from allowed stream
        allowed_event = {
            "type": "message",
            "message": {
                "display_recipient": "allowed_stream",
                "subject": "test",
                "content": "Allowed",
                "sender_email": "user@example.com",
            },
        }

        # Event from filtered stream
        filtered_event = {
            "type": "message",
            "message": {
                "display_recipient": "filtered_stream",
                "subject": "test",
                "content": "Filtered",
                "sender_email": "user@example.com",
            },
        }

        with patch("odoo.addons.mail_gateway_zulip.models.mail_gateway_zulip.MailGatewayZulipService._receive_update") as mock_receive:
            # Allowed event should be processed
            self.zulip_service._process_event(self.gateway, allowed_event)
            mock_receive.assert_called_once()

            mock_receive.reset_mock()

            # Filtered event should not be processed
            self.zulip_service._process_event(self.gateway, filtered_event)
            mock_receive.assert_not_called()

    def test_process_event_filters_topics(self):
        """Test that process_event respects topic filters"""
        # Set topic filter
        self.gateway.zulip_topic_filter = "allowed_topic"

        # Event with allowed topic
        allowed_event = {
            "type": "message",
            "message": {
                "display_recipient": "general",
                "subject": "allowed_topic",
                "content": "Allowed",
                "sender_email": "user@example.com",
            },
        }

        # Event with filtered topic
        filtered_event = {
            "type": "message",
            "message": {
                "display_recipient": "general",
                "subject": "filtered_topic",
                "content": "Filtered",
                "sender_email": "user@example.com",
            },
        }

        with patch("odoo.addons.mail_gateway_zulip.models.mail_gateway_zulip.MailGatewayZulipService._receive_update") as mock_receive:
            # Allowed event should be processed
            self.zulip_service._process_event(self.gateway, allowed_event)
            mock_receive.assert_called_once()

            mock_receive.reset_mock()

            # Filtered event should not be processed
            self.zulip_service._process_event(self.gateway, filtered_event)
            mock_receive.assert_not_called()

    def test_process_event_ignores_bot_messages(self):
        """Test that process_event ignores messages from the bot itself"""
        event = {
            "type": "message",
            "message": {
                "display_recipient": "general",
                "subject": "test",
                "content": "Bot message",
                "sender_email": "bot@test.zulipchat.com",  # Same as gateway bot
            },
        }

        with patch("odoo.addons.mail_gateway_zulip.models.mail_gateway_zulip.MailGatewayZulipService._receive_update") as mock_receive:
            self.zulip_service._process_event(self.gateway, event)
            mock_receive.assert_not_called()
