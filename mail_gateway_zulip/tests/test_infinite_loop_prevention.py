# Copyright 2024 Dixmit
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from unittest.mock import MagicMock, patch

from odoo.tests.common import TransactionCase


class TestInfiniteLoopPrevention(TransactionCase):
    """Test infinite loop prevention for messages from Zulip"""

    def setUp(self):
        super().setUp()

        # Create a test gateway
        self.gateway = self.env["mail.gateway"].create(
            {
                "name": "Test Zulip Gateway",
                "gateway_type": "zulip",
                "token": "test-gateway-token",
                "webhook_key": "test-webhook-key",
                "zulip_server_url": "https://test.zulipchat.com",
                "zulip_bot_email": "bot@test.zulipchat.com",
                "zulip_api_key": "test-api-key",
                "zulip_auto_sync": True,
                "zulip_listener_active": True,
                "zulip_async_send": False,  # Test synchronous sending first
            }
        )

        # Create a test channel
        self.channel = self.env["mail.channel"].create(
            {
                "name": "Test Channel",
                "channel_type": "gateway",
                "gateway_id": self.gateway.id,
                "gateway_channel_token": "general#test",
            }
        )

        # Get Zulip service
        self.zulip_service = self.env["mail.gateway.zulip"]

    def test_incoming_message_marked_as_sent(self):
        """Test that incoming messages from Zulip are marked as sent to prevent loops"""
        # Simulate incoming Zulip message
        update_data = {
            "message": {
                "display_recipient": "general",
                "subject": "test",
                "content": "Hello from Zulip!",
                "sender_email": "user@example.com",
                "sender_full_name": "Test User",
                "id": "12345",
            },
            "type": "message",
        }

        # Process the incoming message
        result = self.zulip_service._receive_update(self.gateway, update_data)

        # Verify message was created
        self.assertTrue(result)
        self.assertEqual(result.body, "<p>Hello from Zulip!</p>")

        # Verify that notifications were created and marked as sent
        notifications = self.env["mail.notification"].search(
            [
                ("mail_message_id", "=", result.id),
                ("gateway_channel_id", "=", self.channel.id),
            ]
        )

        self.assertTrue(notifications)
        for notification in notifications:
            self.assertEqual(notification.notification_status, "sent")
            self.assertEqual(notification.gateway_message_id, "12345")

    def test_send_method_skips_already_sent_messages(self):
        """Test that _send method skips messages already marked as sent"""
        # Create a notification that's already sent
        message = self.env["mail.message"].create(
            {
                "body": "Test message",
                "message_type": "comment",
            }
        )

        notification = self.env["mail.notification"].create(
            {
                "mail_message_id": message.id,
                "gateway_channel_id": self.channel.id,
                "notification_type": "inbox",
                "notification_status": "sent",  # Already sent
                "gateway_message_id": "existing-12345",
            }
        )

        # Mock the Zulip client to track if send_message is called
        with patch(
            "odoo.addons.mail_gateway_zulip.models.mail_gateway_zulip."
            "MailGatewayZulipService._get_zulip_client"
        ) as mock_get_client:
            mock_client = MagicMock()
            mock_get_client.return_value = mock_client

            # Try to send the already-sent message
            self.zulip_service._send(self.gateway, notification)

            # Verify that Zulip client was never called (message was skipped)
            mock_get_client.assert_not_called()
            mock_client.send_message.assert_not_called()

    def test_async_sending_skips_already_sent_messages(self):
        """Test that async sending also respects the sent status"""
        # Enable async sending
        self.gateway.zulip_async_send = True

        # Create a notification that's already sent
        message = self.env["mail.message"].create(
            {
                "body": "Test message",
                "message_type": "comment",
            }
        )

        notification = self.env["mail.notification"].create(
            {
                "mail_message_id": message.id,
                "gateway_channel_id": self.channel.id,
                "notification_type": "inbox",
                "notification_status": "sent",  # Already sent
                "gateway_message_id": "existing-12345",
            }
        )

        # Try to send the already-sent message
        self.zulip_service._send(self.gateway, notification)

        # Verify status remains "sent" (not changed to "ready")
        self.assertEqual(notification.notification_status, "sent")

    def test_full_loop_prevention_scenario(self):
        """Test complete scenario: Zulip message → Odoo → should not go back to Zulip"""
        # Mock Zulip client for any potential outgoing calls
        with patch(
            "odoo.addons.mail_gateway_zulip.models.mail_gateway_zulip."
            "MailGatewayZulipService._get_zulip_client"
        ) as mock_get_client:
            mock_client = MagicMock()
            mock_get_client.return_value = mock_client

            # Simulate incoming Zulip message
            update_data = {
                "message": {
                    "display_recipient": "general",
                    "subject": "test",
                    "content": "This should not loop back!",
                    "sender_email": "user@example.com",
                    "sender_full_name": "Test User",
                    "id": "loop-test-12345",
                },
                "type": "message",
            }

            # Process the incoming message
            result = self.zulip_service._receive_update(self.gateway, update_data)

            # Verify message was created in Odoo
            self.assertTrue(result)
            self.assertEqual(result.body, "<p>This should not loop back!</p>")

            # Verify that no outgoing Zulip API calls were made
            # (the message should be marked as sent, preventing any send attempts)
            mock_client.send_message.assert_not_called()

            # Verify notifications are marked as sent
            notifications = self.env["mail.notification"].search(
                [
                    ("mail_message_id", "=", result.id),
                    ("gateway_channel_id", "=", self.channel.id),
                ]
            )

            for notification in notifications:
                self.assertEqual(notification.notification_status, "sent")

    def test_normal_outgoing_messages_still_work(self):
        """Test that normal outgoing messages (not from Zulip) still work correctly"""
        # Create a normal message (not from Zulip)
        message = self.env["mail.message"].create(
            {
                "body": "Normal outgoing message",
                "message_type": "comment",
            }
        )

        notification = self.env["mail.notification"].create(
            {
                "mail_message_id": message.id,
                "gateway_channel_id": self.channel.id,
                "notification_type": "inbox",
                "notification_status": "ready",  # Ready to send
            }
        )

        # Mock successful Zulip API response
        with patch(
            "odoo.addons.mail_gateway_zulip.models.mail_gateway_zulip."
            "MailGatewayZulipService._get_zulip_client"
        ) as mock_get_client:
            mock_client = MagicMock()
            mock_get_client.return_value = mock_client
            mock_client.send_message.return_value = {
                "result": "success",
                "id": "outgoing-12345",
            }

            # Send the normal message
            self.zulip_service._send(self.gateway, notification)

            # Verify that Zulip API was called
            mock_client.send_message.assert_called_once()

            # Verify message was marked as sent
            self.assertEqual(notification.notification_status, "sent")
            self.assertEqual(notification.gateway_message_id, "outgoing-12345")

    def test_async_cron_job_respects_sent_status(self):
        """Test that async cron job only processes 'ready' messages, not 'sent' ones"""
        # Enable async sending
        self.gateway.zulip_async_send = True

        # Create one ready message and one sent message
        ready_message = self.env["mail.message"].create(
            {
                "body": "Ready to send",
                "message_type": "comment",
            }
        )

        sent_message = self.env["mail.message"].create(
            {
                "body": "Already sent",
                "message_type": "comment",
            }
        )

        ready_notification = self.env["mail.notification"].create(
            {
                "mail_message_id": ready_message.id,
                "gateway_channel_id": self.channel.id,
                "notification_type": "inbox",
                "notification_status": "ready",
            }
        )

        sent_notification = self.env["mail.notification"].create(
            {
                "mail_message_id": sent_message.id,
                "gateway_channel_id": self.channel.id,
                "notification_type": "inbox",
                "notification_status": "sent",  # Already sent
                "gateway_message_id": "already-sent-12345",
            }
        )

        # Mock successful Zulip API response
        with patch(
            "odoo.addons.mail_gateway_zulip.models.mail_gateway_zulip."
            "MailGatewayZulipService._get_zulip_client"
        ) as mock_get_client:
            mock_client = MagicMock()
            mock_get_client.return_value = mock_client
            mock_client.send_message.return_value = {
                "result": "success",
                "id": "cron-sent-12345",
            }

            # Run the async sending cron job
            self.zulip_service._send_pending_messages(self.gateway)

            # Verify only the ready message was sent (called once)
            mock_client.send_message.assert_called_once()

            # Verify statuses
            self.assertEqual(ready_notification.notification_status, "sent")
            self.assertEqual(ready_notification.gateway_message_id, "cron-sent-12345")

            # Sent message should remain unchanged
            self.assertEqual(sent_notification.notification_status, "sent")
            self.assertEqual(sent_notification.gateway_message_id, "already-sent-12345")

    def test_bot_message_filtering_in_event_processing(self):
        """Test that messages from the bot itself are filtered out during event processing"""
        # Simulate message from the bot itself
        bot_event = {
            "type": "message",
            "message": {
                "display_recipient": "general",
                "subject": "test",
                "content": "Message from bot",
                "sender_email": "bot@test.zulipchat.com",  # Same as gateway bot
                "sender_full_name": "Bot User",
                "id": "bot-message-12345",
            },
        }

        # Mock the _receive_update method to track if it's called
        with patch.object(self.zulip_service, "_receive_update") as mock_receive_update:
            # Process the bot message event
            self.zulip_service._process_event(self.gateway, bot_event)

            # Verify that _receive_update was NOT called (message filtered out)
            mock_receive_update.assert_not_called()

    def test_user_message_processing_in_events(self):
        """Test that messages from users (not bot) are processed correctly in events"""
        # Simulate message from a user
        user_event = {
            "type": "message",
            "message": {
                "display_recipient": "general",
                "subject": "test",
                "content": "Message from user",
                "sender_email": "user@example.com",  # Different from bot
                "sender_full_name": "Real User",
                "id": "user-message-12345",
            },
        }

        # Mock the _receive_update method to track if it's called
        with patch.object(self.zulip_service, "_receive_update") as mock_receive_update:
            # Process the user message event
            self.zulip_service._process_event(self.gateway, user_event)

            # Verify that _receive_update WAS called (message processed)
            mock_receive_update.assert_called_once()

            # Verify the correct data was passed
            call_args = mock_receive_update.call_args
            self.assertEqual(call_args[0][0], self.gateway)
            self.assertEqual(
                call_args[0][1]["message"]["sender_email"], "user@example.com"
            )
