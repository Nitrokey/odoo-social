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

        # Create a user with a specific name to test the prefix
        test_user = self.env["res.users"].create({
            "name": "John Doe",
            "login": "john.doe@example.com",
            "email": "john.doe@example.com",
        })

        # Create notification record
        message = self.env["mail.message"].create(
            {
                "subject": "Test Message",
                "body": "<p>Hello Zulip!</p>",
                "author_id": test_user.partner_id.id,
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
        
        # Verify that the user name prefix is included in the content
        content = call_args["content"]
        self.assertIn("Sent from John Doe:", content)
        self.assertIn("Hello Zulip!", content)

        # Verify notification status
        self.assertEqual(notification.notification_status, "sent")
        self.assertEqual(notification.gateway_message_id, "98765")

    def test_markdown_conversion(self):
        """Test markdown to HTML and HTML to markdown conversion"""
        # Test markdown to HTML
        html = self.zulip_service._markdown_to_html("**bold** text")
        self.assertEqual(html, "<p>**bold** text</p>")

        # Test HTML to markdown - now uses html2text for proper conversion
        markdown = self.zulip_service._html_to_markdown(
            "<p><strong>bold</strong> text</p>"
        )
        self.assertEqual(markdown, "**bold** text")

        # Test empty content
        self.assertEqual(self.zulip_service._markdown_to_html(""), "")
        self.assertEqual(self.zulip_service._html_to_markdown(""), "")

    def test_html_to_markdown_bold_formatting(self):
        """Test that HTML bold tags are properly converted to Zulip markdown"""
        # Test <strong> tag conversion
        html_strong = "<p><strong>Sent from John Doe:</strong></p>"
        markdown_result = self.zulip_service._html_to_markdown(html_strong)
        self.assertEqual(markdown_result, "**Sent from John Doe:**")

        # Test <b> tag conversion
        html_b = "<p><b>Sent from Jane Smith:</b></p>"
        markdown_result = self.zulip_service._html_to_markdown(html_b)
        self.assertEqual(markdown_result, "**Sent from Jane Smith:**")

        # Test mixed content with bold
        html_mixed = "<p><strong>Important:</strong> This is a test message with <em>italic</em> text.</p>"
        markdown_result = self.zulip_service._html_to_markdown(html_mixed)
        self.assertIn("**Important:**", markdown_result)
        self.assertIn("*italic*", markdown_result)
        self.assertIn("This is a test message", markdown_result)

    def test_user_prefix_bold_formatting(self):
        """Test that the user prefix appears as bold in Zulip"""
        # Create a test user
        test_user = self.env["res.users"].create({
            "name": "Test User",
            "login": "test.user@example.com",
            "email": "test.user@example.com",
        })

        # Create a test message
        message = self.env["mail.message"].create({
            "body": "<p>Hello World!</p>",
            "author_id": test_user.partner_id.id,
            "message_type": "comment",
        })

        # Create a test notification
        notification = self.env["mail.notification"].create({
            "mail_message_id": message.id,
            "notification_type": "inbox",
            "notification_status": "ready",
        })

        # Get the message body with prefix
        body_with_prefix = self.zulip_service._get_message_body(notification)
        
        # Convert to markdown
        markdown_content = self.zulip_service._html_to_markdown(body_with_prefix)
        
        # Verify the prefix appears as bold markdown
        self.assertIn("**Sent from Test User:**", markdown_content)
        self.assertIn("Hello World!", markdown_content)

    def test_zulip_mention_conversion(self):
        """Test conversion of Zulip mentions (@**User Name**) to Odoo mentions"""
        # Create a test user
        test_user = self.env["res.users"].create({
            "name": "Alice Smith",
            "login": "alice.smith@example.com",
            "email": "alice.smith@example.com",
        })

        # Test mention conversion with gateway
        zulip_content = "Hello @**Alice Smith**, how are you?"
        html_result = self.zulip_service._markdown_to_html(zulip_content, self.gateway)
        
        # Should convert to Odoo mention format
        expected_html = f'<p>Hello <a data-oe-model="res.partner" data-oe-id="{test_user.partner_id.id}">@Alice Smith</a>, how are you?</p>'
        self.assertEqual(html_result, expected_html)

    def test_zulip_mention_conversion_no_user_found(self):
        """Test mention conversion when no matching user is found"""
        # Test with non-existent user
        zulip_content = "Hello @**Unknown User**, how are you?"
        html_result = self.zulip_service._markdown_to_html(zulip_content, self.gateway)
        
        # Should remove ** formatting but keep @mention
        expected_html = "<p>Hello @Unknown User, how are you?</p>"
        self.assertEqual(html_result, expected_html)

    def test_zulip_mention_conversion_multiple_mentions(self):
        """Test conversion of multiple mentions in one message"""
        # Create test users
        user1 = self.env["res.users"].create({
            "name": "Bob Jones",
            "login": "bob.jones@example.com",
            "email": "bob.jones@example.com",
        })
        user2 = self.env["res.users"].create({
            "name": "Carol White",
            "login": "carol.white@example.com", 
            "email": "carol.white@example.com",
        })

        # Test multiple mentions
        zulip_content = "Meeting with @**Bob Jones** and @**Carol White** at 3pm. @**Unknown Person** is also invited."
        html_result = self.zulip_service._markdown_to_html(zulip_content, self.gateway)
        
        # Should convert known users and leave unknown as plain text
        expected_html = (
            f'<p>Meeting with <a data-oe-model="res.partner" data-oe-id="{user1.partner_id.id}">@Bob Jones</a> '
            f'and <a data-oe-model="res.partner" data-oe-id="{user2.partner_id.id}">@Carol White</a> '
            f'at 3pm. @Unknown Person is also invited.</p>'
        )
        self.assertEqual(html_result, expected_html)

    def test_zulip_mention_conversion_without_gateway(self):
        """Test that mentions are not converted when no gateway is provided"""
        zulip_content = "Hello @**Alice Smith**, how are you?"
        html_result = self.zulip_service._markdown_to_html(zulip_content)
        
        # Should not convert mentions without gateway
        expected_html = "<p>Hello @**Alice Smith**, how are you?</p>"
        self.assertEqual(html_result, expected_html)

    def test_zulip_mention_conversion_with_gateway_mapping(self):
        """Test mention conversion using Gateway Partner Channel mapping"""
        # Create a partner
        partner = self.env["res.partner"].create({
            "name": "David Brown",
            "email": "david.brown@example.com",
        })

        # Create Gateway Partner Channel mapping
        self.env["res.partner.gateway.channel"].create({
            "partner_id": partner.id,
            "gateway_id": self.gateway.id,
            "gateway_token": "david.brown@example.com",
        })

        # Test mention conversion
        zulip_content = "Hi @**David Brown**, please review this."
        html_result = self.zulip_service._markdown_to_html(zulip_content, self.gateway)
        
        # Should find user via Gateway Partner Channel mapping
        expected_html = f'<p>Hi <a data-oe-model="res.partner" data-oe-id="{partner.id}">@David Brown</a>, please review this.</p>'
        self.assertEqual(html_result, expected_html)

    def test_zulip_quote_block_processing(self):
        """Test processing of Zulip quote code fences with CSS override for visibility"""
        # Test basic quote block with code fence format
        zulip_content = "```quote\nThis is the quoted message\n```"
        html_result = self.zulip_service._markdown_to_html(zulip_content, self.gateway)
        
        # Should use native blockquote with CSS override to force visibility
        expected_html = '<blockquote data-o-mail-quote="0" style="display: block !important; opacity: 1 !important;">This is the quoted message</blockquote>'
        self.assertEqual(html_result, expected_html)

    def test_zulip_quote_block_with_following_content(self):
        """Test quote block followed by regular content"""
        zulip_content = "```quote\nThis is the quoted message\n```\n\nThis is a new message"
        html_result = self.zulip_service._markdown_to_html(zulip_content, self.gateway)
        
        # Should have native blockquote with CSS override followed by paragraph
        self.assertIn('<blockquote data-o-mail-quote="0" style="display: block !important; opacity: 1 !important;">This is the quoted message</blockquote>', html_result)
        self.assertIn("<p>This is a new message</p>", html_result)

    def test_zulip_quote_block_multiline(self):
        """Test quote block with multiple lines"""
        zulip_content = "```quote\nFirst line of quote\nSecond line of quote\n```"
        html_result = self.zulip_service._markdown_to_html(zulip_content, self.gateway)
        
        # Should convert line breaks to <br> tags within the blockquote with CSS override
        expected_html = '<blockquote data-o-mail-quote="0" style="display: block !important; opacity: 1 !important;">First line of quote<br>Second line of quote</blockquote>'
        self.assertEqual(html_result, expected_html)

    def test_zulip_quote_block_real_format(self):
        """Test with actual Zulip quote format from debug log"""
        # This is the actual format from the debug log
        zulip_content = "@_**Jan Suhr|113** [said](https://zulip.nitrokey.com/#narrow/channel/78-Jans-Sandbox/topic/general/near/25519):\n```quote\nvon Zulip 1\n```\n\neins"
        html_result = self.zulip_service._markdown_to_html(zulip_content, self.gateway)
        
        # Should convert the quote block to native blockquote with CSS override
        self.assertIn('<blockquote data-o-mail-quote="0" style="display: block !important; opacity: 1 !important;">von Zulip 1</blockquote>', html_result)
        # Should preserve the attribution and following content
        self.assertIn("@_**Jan Suhr|113**", html_result)
        self.assertIn("[said]", html_result)
        self.assertIn("<p>eins</p>", html_result)

    def test_zulip_quote_block_at_end_of_message(self):
        """Test quote block at the end of a message"""
        zulip_content = "```quote\nThis is the quoted message at the end\n```"
        html_result = self.zulip_service._markdown_to_html(zulip_content, self.gateway)
        
        expected_html = '<blockquote data-o-mail-quote="0" style="display: block !important; opacity: 1 !important;">This is the quoted message at the end</blockquote>'
        self.assertEqual(html_result, expected_html)

    def test_zulip_quote_always_visible(self):
        """Test that all Zulip quotes use CSS override to force visibility"""
        # Test short quote
        short_quote = "```quote\nShort\n```"
        html_result = self.zulip_service._markdown_to_html(short_quote, self.gateway)
        self.assertIn('<blockquote data-o-mail-quote="0"', html_result)
        self.assertIn('style="display: block !important; opacity: 1 !important;"', html_result)
        
        # Test long quote
        long_quote = "```quote\nThis is a very long quote that would normally be collapsed by Odoo but should always be visible when coming from Zulip gateway\n```"
        html_result = self.zulip_service._markdown_to_html(long_quote, self.gateway)
        self.assertIn('<blockquote data-o-mail-quote="0"', html_result)
        self.assertIn('style="display: block !important; opacity: 1 !important;"', html_result)
        
        # Test multi-line quote
        multiline_quote = "```quote\nLine 1\nLine 2\nLine 3\n```"
        html_result = self.zulip_service._markdown_to_html(multiline_quote, self.gateway)
        self.assertIn('<blockquote data-o-mail-quote="0"', html_result)
        self.assertIn('style="display: block !important; opacity: 1 !important;"', html_result)

    def test_zulip_quote_css_override(self):
        """Test that Zulip quotes have CSS override to prevent collapse"""
        zulip_content = "```quote\nCSS override test\n```"
        html_result = self.zulip_service._markdown_to_html(zulip_content, self.gateway)
        
        # Should use native blockquote element with forced visibility
        self.assertIn('<blockquote', html_result)
        self.assertIn('data-o-mail-quote="0"', html_result)
        self.assertIn('display: block !important', html_result)
        self.assertIn('opacity: 1 !important', html_result)
        self.assertIn('CSS override test', html_result)

    def test_no_quote_block_processing(self):
        """Test that regular content is not affected by quote processing"""
        zulip_content = "This is a regular message with the word quote in it"
        html_result = self.zulip_service._markdown_to_html(zulip_content, self.gateway)
        
        expected_html = "<p>This is a regular message with the word quote in it</p>"
        self.assertEqual(html_result, expected_html)

    def test_zulip_quote_block_with_mentions(self):
        """Test quote block containing user mentions"""
        # Create a test user
        test_user = self.env["res.users"].create({
            "name": "Quoted User",
            "login": "quoted.user@example.com",
            "email": "quoted.user@example.com",
        })

        zulip_content = "```quote\nMessage from @**Quoted User**: Hello there!\n```"
        html_result = self.zulip_service._markdown_to_html(zulip_content, self.gateway)
        
        # Should have both native blockquote and mention processing
        self.assertIn('<blockquote data-o-mail-quote="0"', html_result)
        self.assertIn(f'data-oe-id="{test_user.partner_id.id}"', html_result)
        self.assertIn("@Quoted User", html_result)
        self.assertIn("Hello there!", html_result)

    def test_process_zulip_quotes_method_directly(self):
        """Test the _process_zulip_quotes method directly"""
        # Test basic functionality with code fence format
        content = "```quote\nThis is quoted\n```"
        result = self.zulip_service._process_zulip_quotes(content)
        expected = '<blockquote data-o-mail-quote="0">This is quoted</blockquote>'
        self.assertEqual(result, expected)

        # Test with following content
        content = "```quote\nThis is quoted\n```\n\nThis is not quoted"
        result = self.zulip_service._process_zulip_quotes(content)
        self.assertIn('<blockquote data-o-mail-quote="0">This is quoted</blockquote>', result)
        self.assertIn("This is not quoted", result)
        self.assertNotIn('data-o-mail-quote="0".*This is not quoted', result)

    def test_zulip_quote_attribution_cleaning(self):
        """Test cleaning of Zulip quote attributions with [said](URL) format"""
        # Test basic attribution cleaning with actual format from logs
        zulip_content = "@_**Jan Suhr|113** [said](https://zulip.nitrokey.com/#narrow/channel/78-Jans-Sandbox/topic/general/near/25567):\n\nHello world!"
        html_result = self.zulip_service._markdown_to_html(zulip_content, self.gateway)
        
        # Should clean the attribution but keep the link
        self.assertIn("Jan Suhr [said](https://zulip.nitrokey.com/#narrow/channel/78-Jans-Sandbox/topic/general/near/25567):", html_result)
        self.assertNotIn("@_**Jan Suhr|113**", html_result)
        self.assertIn("Hello world!", html_result)

    def test_zulip_quote_attribution_with_quote_block(self):
        """Test attribution cleaning combined with quote blocks"""
        zulip_content = "@_**Jan Suhr|113** [said](https://zulip.nitrokey.com/#narrow/channel/78-Jans-Sandbox/topic/general/near/25567):\n```quote\nvon Zulip 1\n```\n\neins"
        html_result = self.zulip_service._markdown_to_html(zulip_content, self.gateway)
        
        # Should clean attribution, keep link, and process quote block
        self.assertIn("Jan Suhr [said](https://zulip.nitrokey.com/#narrow/channel/78-Jans-Sandbox/topic/general/near/25567):", html_result)
        self.assertNotIn("@_**Jan Suhr|113**", html_result)
        self.assertIn('<blockquote data-o-mail-quote="0"', html_result)
        self.assertIn("von Zulip 1", html_result)
        self.assertIn("eins", html_result)

    def test_zulip_quote_attribution_multiple_users(self):
        """Test attribution cleaning with different user names and IDs"""
        # Test with different user name format
        zulip_content = "@_**Alice Smith|456** [said](https://example.com/link1):\n\nThis is Alice's message."
        html_result = self.zulip_service._markdown_to_html(zulip_content, self.gateway)
        
        self.assertIn("Alice Smith [said](https://example.com/link1):", html_result)
        self.assertNotIn("@_**Alice Smith|456**", html_result)
        self.assertIn("This is Alice's message.", html_result)

        # Test with user name containing spaces
        zulip_content2 = "@_**John Doe Jr|789** [said](https://example.com/link2):\n\nAnother message here."
        html_result2 = self.zulip_service._markdown_to_html(zulip_content2, self.gateway)
        
        self.assertIn("John Doe Jr [said](https://example.com/link2):", html_result2)
        self.assertNotIn("@_**John Doe Jr|789**", html_result2)

    def test_zulip_quote_attribution_cleaning_method_directly(self):
        """Test the _clean_zulip_quote_attributions method directly"""
        # Test basic functionality with [said](URL) format
        content = "@_**Test User|123** [said](https://example.com/test):\n\nMessage content"
        result = self.zulip_service._clean_zulip_quote_attributions(content)
        expected = "Test User [said](https://example.com/test):\n\nMessage content"
        self.assertEqual(result, expected)

        # Test with multiple attributions
        content = "@_**User One|111** [said](https://example.com/1):\n\nFirst message\n\n@_**User Two|222** [said](https://example.com/2):\n\nSecond message"
        result = self.zulip_service._clean_zulip_quote_attributions(content)
        self.assertIn("User One [said](https://example.com/1):", result)
        self.assertIn("User Two [said](https://example.com/2):", result)
        self.assertNotIn("@_**User One|111**", result)
        self.assertNotIn("@_**User Two|222**", result)

    def test_zulip_quote_attribution_no_match(self):
        """Test that content without attributions is not affected"""
        # Test regular content
        content = "This is a regular message with no attributions"
        result = self.zulip_service._clean_zulip_quote_attributions(content)
        self.assertEqual(result, content)

        # Test content with similar but not matching patterns
        content = "@**Regular Mention** and some text"
        result = self.zulip_service._clean_zulip_quote_attributions(content)
        self.assertEqual(result, content)

        # Test old format without [said](URL) - should not match
        content = "@_**Jan Suhr|113** said:\n\nOld format"
        result = self.zulip_service._clean_zulip_quote_attributions(content)
        self.assertEqual(result, content)  # Should remain unchanged

    def test_zulip_quote_attribution_edge_cases(self):
        """Test edge cases for attribution cleaning"""
        # Test with special characters in user name
        content = "@_**User-Name_123|999** [said](https://example.com/special):\n\nSpecial chars test"
        result = self.zulip_service._clean_zulip_quote_attributions(content)
        self.assertIn("User-Name_123 [said](https://example.com/special):", result)
        self.assertNotIn("@_**User-Name_123|999**", result)

        # Test with empty user name (edge case)
        content = "@_**|123** [said](https://example.com/empty):\n\nEmpty name test"
        result = self.zulip_service._clean_zulip_quote_attributions(content)
        self.assertIn("[said](https://example.com/empty):", result)
        self.assertNotIn("@_**|123**", result)

        # Test with complex URL containing special characters
        content = "@_**Test User|456** [said](https://zulip.example.com/#narrow/channel/123-test/topic/general/near/789):\n\nComplex URL test"
        result = self.zulip_service._clean_zulip_quote_attributions(content)
        self.assertIn("Test User [said](https://zulip.example.com/#narrow/channel/123-test/topic/general/near/789):", result)
        self.assertNotIn("@_**Test User|456**", result)
