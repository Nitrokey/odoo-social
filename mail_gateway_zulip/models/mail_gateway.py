# Copyright 2024 Dixmit
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

import logging

from odoo import _, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class MailGateway(models.Model):
    _inherit = "mail.gateway"

    gateway_type = fields.Selection(
        selection_add=[("zulip", "Zulip")], ondelete={"zulip": "set default"}
    )
    zulip_server_url = fields.Char(
        string="Zulip Server URL",
        help="Complete URL of your Zulip organization (e.g., "
        "https://your-org.zulipchat.com). This is the URL you use to access "
        "Zulip in your browser. Do not include trailing slashes or paths.",
    )
    zulip_bot_email = fields.Char(
        string="Bot Email",
        help="Email address of the Zulip bot account. Create a bot in Zulip "
        "(Settings → Your bots → Add a new bot) and use the email address "
        "shown there. This is the account that will send messages to Zulip "
        "on behalf of Odoo.",
    )
    zulip_api_key = fields.Char(
        string="API Key",
        help="Secret API key for your Zulip bot. Found in Zulip under "
        "Settings → Your bots → [Your Bot] → API key. This authenticates "
        "Odoo with Zulip and should be kept secure. Click 'Generate new API "
        "key' if needed.",
    )
    zulip_stream_filter = fields.Char(
        string="Stream Filter",
        help="Comma-separated list of Zulip streams to monitor (e.g., "
        "'general, development, support'). Only messages from these streams "
        "will be synchronized to Odoo. Leave empty to monitor ALL streams. "
        "Stream names are case-sensitive and must match exactly as they "
        "appear in Zulip.",
    )
    zulip_topic_filter = fields.Char(
        string="Topic Filter",
        help="Comma-separated list of topics to monitor across all streams "
        "(e.g., 'urgent, announcements, releases'). Only messages from these "
        "topics will be synchronized to Odoo. Leave empty to monitor ALL "
        "topics. Topic names are case-sensitive and work across all "
        "monitored streams.",
    )
    zulip_auto_sync = fields.Boolean(
        string="Auto-sync Messages",
        default=False,
        help="Enable automatic synchronization of all messages from monitored "
        "streams. When enabled, all messages (not just @-mentions) will be "
        "synchronized to Odoo in real-time using Zulip's Events API. This "
        "provides seamless bidirectional messaging without requiring @-mentions.",
    )
    zulip_queue_id = fields.Char(
        string="Event Queue ID",
        readonly=True,
        help="Internal Zulip Events API queue identifier. Automatically "
        "managed by the system for real-time event processing. Do not modify "
        "manually.",
    )
    zulip_last_event_id = fields.Integer(
        string="Last Event ID",
        default=0,
        readonly=True,
        help="ID of the last processed Zulip event. Used to track event "
        "processing progress and ensure no messages are missed. Automatically "
        "updated by the system.",
    )
    zulip_webhook_enabled = fields.Boolean(
        string="Enable Webhook",
        default=False,
        help="Enable webhook integration for receiving messages from Zulip. "
        "This is optional - you can use Events API (auto-sync) without webhooks. "
        "Webhooks provide an alternative way to receive messages via HTTP callbacks.",
    )
    zulip_listener_active = fields.Boolean(
        string="Event Listener Active",
        default=False,
        readonly=True,
        help="Indicates whether the real-time event listener is currently "
        "running for this gateway. Automatically managed by the system.",
    )

    # User Mapping Configuration
    zulip_auto_map_users = fields.Boolean(
        string="Auto-map Users by Email",
        default=True,
        help="Automatically map Zulip users to Odoo users/partners by email address",
    )
    zulip_auto_map_domain = fields.Char(
        string="Auto-map Domain",
        help="Only auto-map users from this email domain (leave empty for all domains)",
    )
    zulip_create_guests = fields.Boolean(
        string="Create Guests for External Users",
        default=True,
        help="Create guest users for Zulip users not found in Odoo",
    )
    zulip_guest_name_format = fields.Selection(
        [
            ("full_name", "Use Full Name"),
            ("email_prefix", "Use Email Prefix"),
            ("email_full", "Use Full Email"),
        ],
        default="full_name",
        string="Guest Name Format",
        help="How to format names for created guest users",
    )
    zulip_async_send = fields.Boolean(
        string="Send Messages Asynchronously",
        default=True,
        help="Send messages to Zulip via cron job instead of immediately. "
        "This prevents blocking operations and improves performance for "
        "high-volume messaging. Messages will be queued and sent within "
        "1-2 minutes by the background cron job.",
    )

    def _get_zulip_streams(self):
        """Get list of streams to monitor based on filter"""
        if not self.zulip_stream_filter:
            return []
        return [
            stream.strip()
            for stream in self.zulip_stream_filter.split(",")
            if stream.strip()
        ]

    def _get_zulip_topics(self):
        """Get list of topics to monitor based on filter"""
        if not self.zulip_topic_filter:
            return []
        return [
            topic.strip()
            for topic in self.zulip_topic_filter.split(",")
            if topic.strip()
        ]

    def _get_webhook_url(self):
        """Override to return JSON endpoint for Zulip webhooks"""
        if self.gateway_type == "zulip":
            base_url = super()._get_webhook_url()
            return base_url + "/json"
        return super()._get_webhook_url()

    def write(self, vals):
        """Override to handle auto-sync and webhook changes"""
        # Handle webhook state reset when webhooks are disabled
        if "zulip_webhook_enabled" in vals and self.gateway_type == "zulip":
            if not vals["zulip_webhook_enabled"]:
                # Clear webhook state when webhooks are disabled
                vals["integrated_webhook_state"] = False

        result = super().write(vals)

        # Handle auto-sync changes - process after write to ensure fields are updated
        if "zulip_auto_sync" in vals:
            zulip_service = self.env["mail.gateway.zulip"]
            for gateway in self:
                if gateway.gateway_type == "zulip":
                    try:
                        if vals["zulip_auto_sync"]:
                            _logger.info(
                                "Starting auto-sync for gateway %s", gateway.name
                            )
                            zulip_service.start_auto_sync(gateway)
                            # Verify the listener actually started
                            if not gateway.zulip_listener_active:
                                _logger.warning(
                                    "Auto-sync enabled but listener not active for gateway %s. "
                                    "Check connection and API credentials.",
                                    gateway.name,
                                )
                            else:
                                _logger.info(
                                    "Event listener successfully activated for gateway %s",
                                    gateway.name,
                                )
                        else:
                            _logger.info(
                                "Stopping auto-sync for gateway %s", gateway.name
                            )
                            zulip_service.stop_auto_sync(gateway)
                    except Exception as e:
                        _logger.error(
                            "Failed to %s auto-sync for gateway %s: %s",
                            "start" if vals["zulip_auto_sync"] else "stop",
                            gateway.name,
                            str(e),
                        )

        return result

    def action_test_zulip_connection(self):
        """Test Zulip connection and show results in a wizard"""
        self.ensure_one()

        if self.gateway_type != "zulip":
            raise UserError(_("This action is only available for Zulip gateways."))

        # Get Zulip service
        zulip_service = self.env["mail.gateway.zulip"]

        # Run tests and collect results
        test_results = []

        try:
            # Connection Test
            test_results.append("Connection Test:")
            connection_success = zulip_service.test_zulip_connection(self)

            if connection_success:
                test_results.append("✅ API connectivity successful")
                test_results.append("✅ Bot authentication working")
                test_results.append("✅ Event queue registration successful")
                test_results.append("")

                # Event Polling Test
                test_results.append("Event Polling Test:")
                poll_success = zulip_service.manual_poll_test(self)

                if poll_success:
                    test_results.append("✅ Event queue is working")
                    test_results.append("✅ Ready to receive messages")
                else:
                    test_results.append("❌ Event polling failed")
                    test_results.append("• Check Odoo logs for details")

            else:
                test_results.append("❌ Connection failed")
                test_results.append("• Check server URL, bot email, and API key")
                test_results.append("• Verify bot has necessary permissions")
                test_results.append("• Check Odoo logs for detailed error messages")

            test_results.append("")
            test_results.append("Next Steps:")
            if connection_success:
                test_results.append("1. Send a test message in Zulip")
                test_results.append(
                    "2. Check if message appears in Odoo within 1-2 minutes"
                )
                test_results.append(
                    "3. If no message appears, check bot stream subscriptions"
                )
                test_results.append(
                    "4. Verify stream/topic filters are not too restrictive"
                )
            else:
                test_results.append("1. Fix connection issues shown above")
                test_results.append("2. Run the test again to verify fixes")
                test_results.append("3. Check Odoo logs for detailed error information")

        except Exception as e:
            test_results.append("❌ Test failed with exception")
            test_results.append(f"Error: {str(e)}")
            test_results.append("Check Odoo logs for full traceback")

        # Create and return wizard with results
        wizard = self.env["mail.gateway.zulip.test.wizard"].create(
            {
                "gateway_id": self.id,
                "test_results": "\n".join(test_results),
                "connection_successful": connection_success
                if "connection_success" in locals()
                else False,
            }
        )

        return {
            "type": "ir.actions.act_window",
            "name": "Zulip Connection Test Results",
            "res_model": "mail.gateway.zulip.test.wizard",
            "res_id": wizard.id,
            "view_mode": "form",
            "target": "new",
            "context": self.env.context,
        }
