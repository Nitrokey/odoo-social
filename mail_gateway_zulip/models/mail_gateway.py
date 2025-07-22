# Copyright 2024 Dixmit
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from odoo import fields, models


class MailGateway(models.Model):
    _inherit = "mail.gateway"

    gateway_type = fields.Selection(
        selection_add=[("zulip", "Zulip")], ondelete={"zulip": "set default"}
    )
    zulip_server_url = fields.Char(
        string="Zulip Server URL",
        help="URL of the Zulip server (e.g., https://your-org.zulipchat.com)",
    )
    zulip_bot_email = fields.Char(
        string="Bot Email",
        help="Email address of the Zulip bot",
    )
    zulip_api_key = fields.Char(
        string="API Key",
        help="API key for the Zulip bot",
    )
    zulip_stream_filter = fields.Char(
        string="Stream Filter",
        help="Comma-separated list of streams to monitor (leave empty for all streams)",
    )
    zulip_topic_filter = fields.Char(
        string="Topic Filter",
        help="Comma-separated list of topics to monitor (leave empty for all topics)",
    )

    def _get_zulip_streams(self):
        """Get list of streams to monitor based on filter"""
        if not self.zulip_stream_filter:
            return []
        return [stream.strip() for stream in self.zulip_stream_filter.split(",") if stream.strip()]

    def _get_zulip_topics(self):
        """Get list of topics to monitor based on filter"""
        if not self.zulip_topic_filter:
            return []
        return [topic.strip() for topic in self.zulip_topic_filter.split(",") if topic.strip()]
