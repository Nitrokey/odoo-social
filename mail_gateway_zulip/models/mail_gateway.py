# Copyright 2025 Nitrokey GmbH
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

import logging

from odoo import _, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class MailGateway(models.Model):
    _inherit = "mail.gateway"

    gateway_type = fields.Selection(
        selection_add=[("zulip", "Zulip")], ondelete={"zulip": "cascade"}
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
    zulip_listener_active = fields.Boolean(
        string="Event Listener Active",
        default=False,
        readonly=True,
        help="Indicates whether the real-time event listener is currently "
        "running for this gateway. Automatically managed by the system.",
    )
    zulip_activation_retry_count = fields.Integer(
        string="Activation Retry Count",
        default=0,
        readonly=True,
        help="Number of consecutive failed attempts to activate Events API. "
        "Reset when Events API is successfully activated or manually disabled.",
    )
    zulip_activation_last_retry = fields.Datetime(
        string="Last Activation Retry",
        readonly=True,
        help="Timestamp of the last attempt to activate Events API. "
        "Used to implement cooldown periods between retry attempts.",
    )
    zulip_activation_failure_reason = fields.Text(
        string="Activation Failure Reason",
        readonly=True,
        help="Detailed reason for the last Events API activation failure. "
        "Helps with troubleshooting connection and configuration issues.",
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

    def _is_zulip_configured(self):
        """Check if Zulip gateway is properly configured"""
        return (
            self.gateway_type == "zulip"
            and self.zulip_server_url
            and self.zulip_bot_email
            and self.zulip_api_key
        )


    def _should_retry_activation(self):
        """Check if any gateway needs activation retry due to inconsistent state"""
        from datetime import timedelta

        now = fields.Datetime.now()

        for gateway in self:
            if (
                gateway._is_zulip_configured()
                and not gateway.zulip_listener_active
            ):
                # Check retry limits and cooldown
                max_retries = 5  # Maximum consecutive retry attempts
                cooldown_minutes = [1, 2, 5, 10, 30]  # Progressive cooldown periods

                # If we've exceeded max retries, don't retry
                if gateway.zulip_activation_retry_count >= max_retries:
                    continue

                # If we're in cooldown period, don't retry
                if gateway.zulip_activation_last_retry:
                    retry_index = min(
                        gateway.zulip_activation_retry_count, len(cooldown_minutes) - 1
                    )
                    cooldown_period = timedelta(minutes=cooldown_minutes[retry_index])
                    if now < gateway.zulip_activation_last_retry + cooldown_period:
                        continue

                # This gateway needs retry
                return True

        return False

    def write(self, vals):
        """Override to handle automatic activation when gateway is configured"""
        result = super().write(vals)

        # Check if configuration fields were updated or if we need to retry activation
        config_fields = ["zulip_server_url", "zulip_bot_email", "zulip_api_key"]
        config_changed = any(field in vals for field in config_fields)
        
        if config_changed or self._should_retry_activation():
            zulip_service = self.env["mail.gateway.zulip"]
            for gateway in self:
                if gateway.gateway_type == "zulip":
                    try:
                        if gateway._is_zulip_configured():
                            # Gateway is properly configured - activate if not already active
                            if not gateway.zulip_listener_active:
                                # Check if this is a retry due to inconsistent state
                                is_retry = (
                                    not config_changed
                                    and gateway._is_zulip_configured()
                                    and not gateway.zulip_listener_active
                                )

                                # Reset retry count if configuration was manually changed
                                if config_changed:
                                    gateway.sudo().write(
                                        {
                                            "zulip_activation_retry_count": 0,
                                            "zulip_activation_last_retry": False,
                                            "zulip_activation_failure_reason": False,
                                        }
                                    )

                                if is_retry:
                                    # Update retry tracking
                                    gateway.sudo().write(
                                        {
                                            "zulip_activation_retry_count": (
                                                gateway.zulip_activation_retry_count + 1
                                            ),
                                            "zulip_activation_last_retry": fields.Datetime.now(),
                                        }
                                    )

                                    _logger.info(
                                        "Detected inactive event listener for configured gateway %s "
                                        "(retry %d/5), attempting to activate",
                                        gateway.name,
                                        gateway.zulip_activation_retry_count,
                                    )
                                else:
                                    _logger.info(
                                        "Gateway %s is configured - automatically activating event listener",
                                        gateway.name,
                                    )

                                # Attempt to start event listener with enhanced error reporting
                                (
                                    success,
                                    error_message,
                                ) = zulip_service.start_auto_sync_with_details(gateway)

                                # Verify the listener actually started
                                if not gateway.zulip_listener_active or not success:
                                    # Store failure reason
                                    gateway.sudo().write(
                                        {
                                            "zulip_activation_failure_reason": error_message
                                            or "Event listener activation failed"
                                        }
                                    )

                                    if is_retry:
                                        if gateway.zulip_activation_retry_count >= 5:
                                            _logger.error(
                                                "Event listener activation failed for gateway "
                                                "%s after %d attempts. Giving up. Last "
                                                "error: %s. Please check connection, "
                                                "credentials, and bot permissions.",
                                                gateway.name,
                                                gateway.zulip_activation_retry_count,
                                                error_message or "Unknown error",
                                            )
                                        else:
                                            next_retry_minutes = [1, 2, 5, 10, 30][
                                                min(gateway.zulip_activation_retry_count, 4)
                                            ]
                                            _logger.warning(
                                                "Event listener activation failed for gateway "
                                                "%s (attempt %d/5). "
                                                "Error: %s. Will retry in %d minutes.",
                                                gateway.name,
                                                gateway.zulip_activation_retry_count,
                                                error_message or "Unknown error",
                                                next_retry_minutes,
                                            )
                                    else:
                                        _logger.warning(
                                            "Gateway %s is configured but event listener "
                                            "activation failed. Error: %s. "
                                            "Will retry automatically with backoff.",
                                            gateway.name,
                                            error_message or "Unknown error",
                                        )
                                else:
                                    # Success - reset retry tracking
                                    gateway.sudo().write(
                                        {
                                            "zulip_activation_retry_count": 0,
                                            "zulip_activation_last_retry": False,
                                            "zulip_activation_failure_reason": False,
                                        }
                                    )

                                    if is_retry:
                                        _logger.info(
                                            "Successfully activated event listener for gateway %s "
                                            "after retry",
                                            gateway.name,
                                        )
                                    else:
                                        _logger.info(
                                            "Event listener successfully activated for gateway %s",
                                            gateway.name,
                                        )
                        else:
                            # Gateway is not properly configured - deactivate if active
                            if gateway.zulip_listener_active:
                                _logger.info(
                                    "Gateway %s configuration incomplete - deactivating event listener",
                                    gateway.name,
                                )
                                zulip_service.stop_auto_sync(gateway)
                                
                            # Reset retry tracking when configuration is incomplete
                            gateway.sudo().write(
                                {
                                    "zulip_activation_retry_count": 0,
                                    "zulip_activation_last_retry": False,
                                    "zulip_activation_failure_reason": False,
                                }
                            )
                    except Exception as e:
                        # Store exception details
                        gateway.sudo().write(
                            {"zulip_activation_failure_reason": f"Exception: {str(e)}"}
                        )

                        _logger.error(
                            "Failed to manage event listener for gateway %s: %s",
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
        connection_success = False

        try:
            # Connection Test
            test_results.append("Connection Test:")
            connection_success = zulip_service.test_zulip_connection(self)

            if connection_success:
                test_results.append("✅ API connectivity successful")
                test_results.append("✅ Bot authentication working")
                test_results.append("✅ Event queue registration successful")
                test_results.append("")

                # Integration Status Check
                test_results.append("Integration Status Check:")

                if self._is_zulip_configured():
                    if self.zulip_listener_active:
                        test_results.append(
                            "✅ Gateway configured and event listener active"
                        )
                    else:
                        test_results.append(
                            "⚠️  Gateway configured but event listener inactive"
                        )
                        test_results.append(
                            "   Attempting to activate event listener..."
                        )

                        # Try to fix the inconsistent state
                        try:
                            zulip_service.start_auto_sync(self)
                            if self.zulip_listener_active:
                                test_results.append(
                                    "✅ Event listener successfully activated"
                                )
                                test_results.append(
                                    "   Integration state has been corrected"
                                )
                            else:
                                test_results.append(
                                    "❌ Failed to activate event listener"
                                )
                                test_results.append(
                                    "   • Check Odoo logs for detailed errors"
                                )
                                test_results.append(
                                    "   • Verify bot has necessary permissions"
                                )
                        except Exception as e:
                            test_results.append(
                                f"❌ Error activating listener: {str(e)}"
                            )
                            test_results.append(
                                "   • Check connection and API credentials"
                            )
                            test_results.append(
                                "   • Review Odoo logs for full error details"
                            )
                else:
                    test_results.append(
                        "ℹ️  Gateway not fully configured - event listener inactive"
                    )
                    test_results.append(
                        "   Complete server URL, bot email, and API key to activate"
                    )

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
                if self._is_zulip_configured() and self.zulip_listener_active:
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
                elif self._is_zulip_configured() and not self.zulip_listener_active:
                    test_results.append(
                        "1. Fix the event listener activation issue above"
                    )
                    test_results.append("2. Check connection and credentials")
                    test_results.append("3. Run this test again to verify the fix")
                else:
                    test_results.append(
                        "1. Complete gateway configuration (server URL, bot email, API key)"
                    )
                    test_results.append("2. Configure stream/topic filters as needed")
                    test_results.append(
                        "3. Run this test again after completing configuration"
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
                "connection_successful": connection_success,
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
