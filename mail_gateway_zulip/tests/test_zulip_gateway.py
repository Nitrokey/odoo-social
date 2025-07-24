# Copyright 2024 Dixmit
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from unittest.mock import Mock, patch

from odoo.tests.common import TransactionCase


class TestZulipGateway(TransactionCase):
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
            }
        )
        self.zulip_service = self.env["mail.gateway.zulip"]

    def test_channel_token_generation(self):
        """Test channel token generation for stream/topic combination"""
        token = self.zulip_service._get_channel_token("general", "test topic")
        self.assertEqual(token, "general#test topic")

    def test_channel_token_parsing(self):
        """Test parsing channel token back to stream and topic"""
        stream, topic = self.zulip_service._parse_channel_token("general#test topic")
        self.assertEqual(stream, "general")
        self.assertEqual(topic, "test topic")

        # Test token without topic
        stream, topic = self.zulip_service._parse_channel_token("general")
        self.assertEqual(stream, "general")
        self.assertEqual(topic, "general")

    def test_markdown_to_html_simple(self):
        """Test simple markdown to HTML conversion"""
        html = self.zulip_service._markdown_to_html("Hello world")
        self.assertEqual(html, "<p>Hello world</p>")

        # Test empty content
        html = self.zulip_service._markdown_to_html("")
        self.assertEqual(html, "")

    def test_get_channel_vals(self):
        """Test channel values generation"""
        token = "general#announcements"
        update = {}
        vals = self.zulip_service._get_channel_vals(self.gateway, token, update)

        self.assertEqual(vals["name"], "Zulip: general / announcements")
        self.assertEqual(vals["anonymous_name"], "general / announcements")
        self.assertEqual(vals["gateway_channel_token"], token)
        self.assertEqual(vals["gateway_id"], self.gateway.id)

    @patch("odoo.addons.mail_gateway_zulip.models.mail_gateway_zulip.zulip")
    def test_get_zulip_client(self, mock_zulip):
        """Test Zulip client creation"""
        mock_client = Mock()
        mock_zulip.Client.return_value = mock_client

        client = self.zulip_service._get_zulip_client(self.gateway)

        mock_zulip.Client.assert_called_once_with(
            email="bot@test.zulipchat.com",
            api_key="test_api_key",
            site="https://test.zulipchat.com",
        )
        self.assertEqual(client, mock_client)

    def test_get_author_from_email_existing_partner(self):
        """Test getting author from email when partner exists"""
        partner = self.env["res.partner"].create(
            {
                "name": "Test User",
                "email": "test@example.com",
            }
        )

        author = self.zulip_service._get_author_from_email(
            self.gateway, "test@example.com", "Test User"
        )

        self.assertEqual(author, partner)

    def test_get_author_from_email_new_guest(self):
        """Test creating new guest when email doesn't exist"""
        author = self.zulip_service._get_author_from_email(
            self.gateway, "newuser@example.com", "New User"
        )

        self.assertEqual(author._name, "mail.guest")
        self.assertEqual(author.name, "New User")
        self.assertEqual(author.gateway_token, "newuser@example.com")
        self.assertEqual(author.gateway_id, self.gateway)

    def test_stream_filter_parsing(self):
        """Test stream filter parsing"""
        self.gateway.zulip_stream_filter = "general, development, support"
        streams = self.gateway._get_zulip_streams()
        self.assertEqual(streams, ["general", "development", "support"])

        # Test empty filter
        self.gateway.zulip_stream_filter = ""
        streams = self.gateway._get_zulip_streams()
        self.assertEqual(streams, [])

    def test_topic_filter_parsing(self):
        """Test topic filter parsing"""
        self.gateway.zulip_topic_filter = "announcements, urgent, help"
        topics = self.gateway._get_zulip_topics()
        self.assertEqual(topics, ["announcements", "urgent", "help"])

        # Test empty filter
        self.gateway.zulip_topic_filter = ""
        topics = self.gateway._get_zulip_topics()
        self.assertEqual(topics, [])
