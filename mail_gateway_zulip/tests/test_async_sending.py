# Copyright 2024 Dixmit
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from unittest.mock import patch

from odoo.tests.common import TransactionCase


class TestAsyncSending(TransactionCase):
    def setUp(self):
        super().setUp()
        
        # Create a test gateway (async sending is enabled by default)
        self.gateway = self.env["mail.gateway"].create({
            "name": "Test Zulip Gateway",
            "gateway_type": "zulip",
            "token": "test_token_123",
            "webhook_key": "test_webhook_key",
            "zulip_server_url": "https://test.zulipchat.com",
            "zulip_bot_email": "test-bot@test.zulipchat.com",
            "zulip_api_key": "test_api_key_123456789",
        })
        
        # Create a test channel
        self.channel = self.env["mail.channel"].create({
            "name": "Test Channel",
            "gateway_id": self.gateway.id,
            "gateway_channel_token": "general#test",
        })
        
        # Create a test message
        self.message = self.env["mail.message"].create({
            "subject": "Test Message",
            "body": "<p>This is a test message</p>",
            "message_type": "comment",
        })
        
        # Create a partner to associate with the notification
        self.partner = self.env["res.partner"].create({
            "name": "Test Partner",
            "email": "test@example.com",
        })
        
        # Create a notification for the message
        self.notification = self.env["mail.notification"].create({
            "mail_message_id": self.message.id,
            "res_partner_id": self.partner.id,
            "notification_type": "inbox",
            "notification_status": "ready",
        })
        
        # Set the gateway channel manually since it's not a standard field
        self.notification.gateway_channel_id = self.channel.id

    def test_async_sending_queues_message(self):
        """Test that async sending queues the message instead of sending immediately"""
        zulip_service = self.env["mail.gateway.zulip"]
        
        # Call the _send method (async is enabled by default)
        zulip_service._send(self.gateway, self.notification)
        
        # Verify the message was queued (status should be 'ready')
        self.assertEqual(self.notification.notification_status, "ready")
        self.assertFalse(self.notification.failure_reason)
        self.assertFalse(self.notification.failure_type)

    def test_sync_sending_sends_immediately(self):
        """Test that sync sending sends the message immediately"""
        # Disable async sending
        self.gateway.zulip_async_send = False
        
        zulip_service = self.env["mail.gateway.zulip"]
        
        # Mock the _send_message_now method using patch
        with patch('odoo.addons.mail_gateway_zulip.models.mail_gateway_zulip.MailGatewayZulipService._send_message_now') as mock_send_now:
            # Call the _send method
            zulip_service._send(self.gateway, self.notification)
            
            # Verify _send_message_now was called
            mock_send_now.assert_called_once_with(
                self.gateway, self.notification, False, False, False
            )

    def test_cron_job_processes_pending_messages(self):
        """Test that the cron job processes pending messages"""
        zulip_service = self.env["mail.gateway.zulip"]
        
        # Mock the sending methods
        with patch('odoo.addons.mail_gateway_zulip.models.mail_gateway_zulip.MailGatewayZulipService._send_message_now') as mock_send:
            # Mock successful sending - need to accept all parameters
            def mock_send_side_effect(gateway, notification, auto_commit=False, raise_exception=False):
                notification.notification_status = "sent"
                notification.gateway_message_id = "12345"
            
            mock_send.side_effect = mock_send_side_effect
            
            # Call the pending messages method
            zulip_service._send_pending_messages(self.gateway)
            
            # Verify the message was processed
            mock_send.assert_called_once()
            self.assertEqual(self.notification.notification_status, "sent")
            self.assertEqual(self.notification.gateway_message_id, "12345")

    def test_cron_job_handles_failed_messages(self):
        """Test that the cron job handles failed messages correctly"""
        zulip_service = self.env["mail.gateway.zulip"]
        
        # Mock the sending method to raise an exception
        with patch('odoo.addons.mail_gateway_zulip.models.mail_gateway_zulip.MailGatewayZulipService._send_message_now') as mock_send:
            mock_send.side_effect = Exception("Test error")
            
            # Call the pending messages method
            zulip_service._send_pending_messages(self.gateway)
            
            # Verify the message was marked as failed
            self.assertEqual(self.notification.notification_status, "exception")
            self.assertEqual(self.notification.failure_reason, "Test error")
            self.assertEqual(self.notification.failure_type, "unknown")

    def test_cron_job_combines_event_polling_and_async_sending(self):
        """Test that the main cron job handles both event polling and async sending"""
        # Enable both auto-sync and async sending
        self.gateway.write({
            "zulip_auto_sync": True,
            "zulip_listener_active": True,
        })
        
        zulip_service = self.env["mail.gateway.zulip"]
        
        # Mock both methods
        with patch('odoo.addons.mail_gateway_zulip.models.mail_gateway_zulip.MailGatewayZulipService._poll_gateway_events') as mock_poll, \
             patch('odoo.addons.mail_gateway_zulip.models.mail_gateway_zulip.MailGatewayZulipService._send_pending_messages') as mock_send:
            
            # Call the main cron job
            zulip_service._cron_poll_events()
            
            # Verify both methods were called (may be called multiple times for different gateways)
            # Just verify our gateway was called at least once
            mock_poll.assert_called()
            mock_send.assert_called()
            
            # Check that our specific gateway was in the calls
            poll_calls = [call[0][0] for call in mock_poll.call_args_list]
            send_calls = [call[0][0] for call in mock_send.call_args_list]
            
            self.assertIn(self.gateway, poll_calls)
            self.assertIn(self.gateway, send_calls)

    def test_no_pending_messages_handled_gracefully(self):
        """Test that cron job handles case with no pending messages"""
        # Mark the notification as already sent
        self.notification.notification_status = "sent"
        
        zulip_service = self.env["mail.gateway.zulip"]
        
        # This should not raise any exceptions
        zulip_service._send_pending_messages(self.gateway)
        
        # Status should remain unchanged
        self.assertEqual(self.notification.notification_status, "sent")
