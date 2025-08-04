# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from unittest.mock import Mock, patch

from odoo.tests.common import TransactionCase


class TestZulipMessageProcessing(TransactionCase):
    """Test Zulip message processing and event handling"""

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
            }
        )
        self.channel = self.env["mail.channel"].create(
            {
                "name": "Test Channel",
                "channel_type": "channel",
                "gateway_id": self.gateway.id,
                "gateway_channel_token": "general#test",
            }
        )
        self.zulip_service = self.env["mail.gateway.zulip"]

    def test_receive_update_with_mapping(self):
        """Test receiving Zulip update with existing channel mapping"""
        # Create channel mapping
        mapping = self.env["zulip.channel.mapping"].create(
            {
                "gateway_id": self.gateway.id,
                "zulip_stream": "general",
                "zulip_topic": "test",
                "odoo_channel_id": self.channel.id,
            }
        )

        # Mock update data
        update = {
            "message": {
                "display_recipient": "general",
                "subject": "test",
                "content": "Hello from Zulip!",
                "sender_email": "user@example.com",
                "sender_full_name": "Test User",
                "id": 12345,
            }
        }

        # Process update
        with patch(
            "odoo.addons.mail_gateway_zulip.models.mail_gateway_zulip."
            "MailGatewayZulipService._process_zulip_message"
        ) as mock_process:
            mock_process.return_value = Mock()
            self.zulip_service._receive_update(self.gateway, update)

            # Verify mapping was used
            mock_process.assert_called_once()
            args = mock_process.call_args[0]
            self.assertEqual(args[0], self.channel)  # Channel from mapping
            self.assertEqual(args[1], "Hello from Zulip!")  # Content
            self.assertEqual(args[2], "user@example.com")  # Sender email

        # Verify mapping stats were updated
        self.assertTrue(mapping.last_sync)
        self.assertEqual(mapping.message_count, 1)

    def test_receive_update_without_mapping(self):
        """Test receiving Zulip update without existing mapping (auto-creation)"""
        update = {
            "message": {
                "display_recipient": "development",
                "subject": "bug-fix",
                "content": "Fixed the issue!",
                "sender_email": "dev@example.com",
                "sender_full_name": "Developer",
                "id": 67890,
            }
        }

        # Mock channel creation
        with patch(
            "odoo.addons.mail_gateway.models.mail_gateway_abstract."
            "MailGatewayAbstract._get_channel"
        ) as mock_get_channel, patch(
            "odoo.addons.mail_gateway_zulip.models.mail_gateway_zulip."
            "MailGatewayZulipService._process_zulip_message"
        ) as mock_process:
            mock_channel = Mock()
            mock_get_channel.return_value = mock_channel
            mock_process.return_value = Mock()

            self.zulip_service._receive_update(self.gateway, update)

            # Verify auto-creation was used
            mock_get_channel.assert_called_once_with(
                self.gateway, "development#bug-fix", update
            )
            mock_process.assert_called_once_with(
                mock_channel,
                "Fixed the issue!",
                "dev@example.com",
                "Developer",
                67890,
                self.gateway,
            )

    def test_receive_update_missing_fields(self):
        """Test receiving update with missing required fields"""
        # Update without content
        update = {
            "message": {
                "display_recipient": "general",
                "subject": "test",
                # Missing 'content'
                "sender_email": "user@example.com",
                "sender_full_name": "Test User",
            }
        }

        result = self.zulip_service._receive_update(self.gateway, update)
        self.assertIsNone(result)

        # Update without stream
        update = {
            "message": {
                # Missing 'display_recipient'
                "subject": "test",
                "content": "Hello!",
                "sender_email": "user@example.com",
                "sender_full_name": "Test User",
            }
        }

        result = self.zulip_service._receive_update(self.gateway, update)
        self.assertIsNone(result)

    def test_process_zulip_message(self):
        """Test processing a Zulip message into Odoo"""
        # Create partner for author
        partner = self.env["res.partner"].create(
            {
                "name": "Test User",
                "email": "user@example.com",
            }
        )

        # Process message
        with patch(
            "odoo.addons.mail_gateway_zulip.models.mail_gateway_zulip."
            "MailGatewayZulipService._get_author_from_email",
            return_value=partner,
        ):
            message = self.zulip_service._process_zulip_message(
                self.channel,
                "Hello from Zulip!",
                "user@example.com",
                "Test User",
                12345,
                self.gateway,
            )

        # Verify message was created
        self.assertTrue(message)
        self.assertEqual(message.body, "<p>Hello from Zulip!</p>")
        self.assertEqual(message.author_id, partner)
        self.assertEqual(message.message_type, "comment")

    def test_get_author_from_email_existing_partner(self):
        """Test getting author when partner exists"""
        partner = self.env["res.partner"].create(
            {
                "name": "Existing User",
                "email": "existing@example.com",
            }
        )

        author = self.zulip_service._get_author_from_email(
            self.gateway, "existing@example.com", "Existing User"
        )

        self.assertEqual(author, partner)

    def test_get_author_from_email_auto_mapping_enabled(self):
        """Test auto-mapping when enabled"""
        # Enable auto-mapping
        self.gateway.zulip_auto_map_users = True

        # Create user with matching email
        user = self.env["res.users"].create(
            {
                "name": "Auto Mapped User",
                "login": "automapped@example.com",
                "email": "automapped@example.com",
            }
        )

        author = self.zulip_service._get_author_from_email(
            self.gateway, "automapped@example.com", "Auto Mapped User"
        )

        self.assertEqual(author, user.partner_id)

    def test_get_author_from_email_domain_restriction(self):
        """Test auto-mapping with domain restriction"""
        # Enable auto-mapping with domain restriction
        self.gateway.write(
            {
                "zulip_auto_map_users": True,
                "zulip_auto_map_domain": "company.com",
            }
        )

        # Create user with matching domain
        user = self.env["res.users"].create(
            {
                "name": "Company User",
                "login": "user@company.com",
                "email": "user@company.com",
            }
        )

        # Test matching domain
        author = self.zulip_service._get_author_from_email(
            self.gateway, "user@company.com", "Company User"
        )
        self.assertEqual(author, user.partner_id)

        # Test non-matching domain - should create guest
        author = self.zulip_service._get_author_from_email(
            self.gateway, "external@other.com", "External User"
        )
        self.assertEqual(author._name, "mail.guest")

    def test_get_author_from_email_guest_creation(self):
        """Test guest creation for unknown users"""
        # Enable guest creation
        self.gateway.zulip_create_guests = True

        author = self.zulip_service._get_author_from_email(
            self.gateway, "guest@example.com", "Guest User"
        )

        self.assertEqual(author._name, "mail.guest")
        self.assertEqual(author.name, "Guest User")
        self.assertEqual(author.gateway_token, "guest@example.com")
        self.assertEqual(author.gateway_id, self.gateway)

    def test_get_author_from_email_guest_name_formats(self):
        """Test different guest name formats"""
        self.gateway.write(
            {
                "zulip_create_guests": True,
                "zulip_guest_name_format": "email_prefix",
            }
        )

        author = self.zulip_service._get_author_from_email(
            self.gateway, "testuser@example.com", "Full Name"
        )

        self.assertEqual(author.name, "testuser")

        # Test email_full format
        self.gateway.zulip_guest_name_format = "email_full"
        author2 = self.zulip_service._get_author_from_email(
            self.gateway, "another@example.com", "Another User"
        )

        self.assertEqual(author2.name, "another@example.com")

    def test_process_event_message_filtering(self):
        """Test event processing with message filtering"""
        # Set up stream filter
        self.gateway.zulip_stream_filter = "general, development"

        event = {
            "type": "message",
            "message": {
                "display_recipient": "general",
                "subject": "test",
                "content": "Filtered message",
                "sender_email": "user@example.com",
                "sender_full_name": "Test User",
            },
        }

        # Mock the receive_update method
        with patch(
            "odoo.addons.mail_gateway_zulip.models.mail_gateway_zulip."
            "MailGatewayZulipService._receive_update"
        ) as mock_receive:
            self.zulip_service._process_event(self.gateway, event)
            mock_receive.assert_called_once()

        # Test filtered out stream
        event["message"]["display_recipient"] = "random"
        with patch(
            "odoo.addons.mail_gateway_zulip.models.mail_gateway_zulip."
            "MailGatewayZulipService._receive_update"
        ) as mock_receive:
            self.zulip_service._process_event(self.gateway, event)
            mock_receive.assert_not_called()

    def test_process_event_bot_message_filtering(self):
        """Test that bot's own messages are filtered out"""
        event = {
            "type": "message",
            "message": {
                "display_recipient": "general",
                "subject": "test",
                "content": "Bot message",
                "sender_email": "bot@test.zulipchat.com",  # Same as gateway bot
                "sender_full_name": "Bot",
            },
        }

        with patch(
            "odoo.addons.mail_gateway_zulip.models.mail_gateway_zulip."
            "MailGatewayZulipService._receive_update"
        ) as mock_receive:
            self.zulip_service._process_event(self.gateway, event)
            mock_receive.assert_not_called()

    def test_process_event_non_message_ignored(self):
        """Test that non-message events are ignored"""
        event = {
            "type": "subscription",  # Not a message
            "data": {"some": "data"},
        }

        with patch(
            "odoo.addons.mail_gateway_zulip.models.mail_gateway_zulip."
            "MailGatewayZulipService._receive_update"
        ) as mock_receive:
            self.zulip_service._process_event(self.gateway, event)
            mock_receive.assert_not_called()

    @patch("odoo.addons.mail_gateway_zulip.models.mail_gateway_zulip.zulip")
    def test_send_message_to_zulip(self, mock_zulip):
        """Test sending message from Odoo to Zulip"""
        # Disable async sending for this test to test immediate sending
        self.gateway.zulip_async_send = False

        # Mock Zulip client
        mock_client = Mock()
        mock_zulip.Client.return_value = mock_client
        mock_client.send_message.return_value = {
            "result": "success",
            "id": 98765,
        }

        # Create notification record
        message = self.env["mail.message"].create(
            {
                "subject": "Test Message",
                "body": "<p>Hello Zulip!</p>",
                "message_type": "comment",
            }
        )

        # Create a partner to associate with the notification
        partner = self.env["res.partner"].create(
            {
                "name": "Test Partner",
                "email": "test@example.com",
            }
        )

        notification = self.env["mail.notification"].create(
            {
                "mail_message_id": message.id,
                "res_partner_id": partner.id,
                "notification_type": "inbox",
                "notification_status": "ready",
            }
        )

        # Set the gateway channel manually since it's not a standard field
        notification.gateway_channel_id = self.channel.id

        # Send message
        self.zulip_service._send(self.gateway, notification)

        # Verify API call
        mock_client.send_message.assert_called_once()
        call_args = mock_client.send_message.call_args[0][0]
        self.assertEqual(call_args["type"], "stream")
        self.assertEqual(call_args["to"], "general")
        self.assertEqual(call_args["topic"], "test")
        self.assertEqual(call_args["content"], "Hello Zulip!")

        # Verify notification status
        self.assertEqual(notification.notification_status, "sent")
        self.assertEqual(notification.gateway_message_id, "98765")

    def test_markdown_conversion(self):
        """Test markdown to HTML and HTML to markdown conversion"""
        # Test markdown to HTML
        html = self.zulip_service._markdown_to_html("**bold** text")
        self.assertEqual(html, "<p>**bold** text</p>")

        # Test HTML to markdown - the implementation uses html2plaintext
        # which converts <strong> to *text*
        markdown = self.zulip_service._html_to_markdown(
            "<p><strong>bold</strong> text</p>"
        )
        self.assertEqual(markdown, "*bold* text")

        # Test empty content
        self.assertEqual(self.zulip_service._markdown_to_html(""), "")
        self.assertEqual(self.zulip_service._html_to_markdown(""), "")
