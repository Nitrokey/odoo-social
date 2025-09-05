# Copyright 2024 Dixmit
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

import logging
import traceback
from io import StringIO

from odoo import _, api, models
from odoo.tools import html2plaintext

from odoo.addons.base.models.ir_mail_server import MailDeliveryException

_logger = logging.getLogger(__name__)

try:
    import zulip
except (ImportError, IOError) as err:
    _logger.debug(err)


class MailGatewayZulipService(models.AbstractModel):
    _inherit = "mail.gateway.abstract"
    _name = "mail.gateway.zulip"
    _description = "Zulip Gateway services"

    def _get_zulip_client(self, gateway):
        """Get Zulip client instance"""
        _logger.debug("=== ZULIP CLIENT CREATION ===")
        _logger.debug("Gateway: %s (ID: %s)", gateway.name, gateway.id)
        _logger.debug("Server: %s", gateway.zulip_server_url)
        _logger.debug("Bot Email: %s", gateway.zulip_bot_email)
        _logger.debug(
            "API Key: %s***",
            gateway.zulip_api_key[:8] if gateway.zulip_api_key else "None",
        )

        client = zulip.Client(
            email=gateway.zulip_bot_email,
            api_key=gateway.zulip_api_key,
            site=gateway.zulip_server_url,
        )

        _logger.debug("Zulip client created successfully")
        return client


    def _get_channel_token(self, stream_name, topic_name):
        """Generate unique channel token for stream/topic combination"""
        return f"{stream_name}#{topic_name}"

    def _parse_channel_token(self, token):
        """Parse channel token to get stream and topic"""
        if "#" in token:
            return token.split("#", 1)
        return token, "general"

    def _get_channel_vals(self, gateway, token, update):
        """Get channel values for creating new channel"""
        result = super()._get_channel_vals(gateway, token, update)

        stream_name, topic_name = self._parse_channel_token(token)
        result["name"] = f"Zulip: {stream_name} / {topic_name}"
        result["anonymous_name"] = f"{stream_name} / {topic_name}"

        return result

    def _markdown_to_html(self, markdown_text):
        """Convert Zulip markdown to HTML (simplified)"""
        if not markdown_text:
            return ""

        # For now, just return the text as-is wrapped in <p> tags
        # In the future, you could implement proper markdown parsing
        return f"<p>{markdown_text}</p>"

    def _html_to_markdown(self, html_text):
        """Convert HTML to Zulip markdown (simplified)"""
        if not html_text:
            return ""

        # Simple conversion - in practice, you might want to use html2text
        text = html2plaintext(html_text)
        return text


    def _process_zulip_message(
        self, chat, content, sender_email, sender_full_name, message_id, gateway
    ):
        """Process a Zulip message and create corresponding Odoo message"""
        chat.ensure_one()

        # Convert markdown to HTML
        body = self._markdown_to_html(content)

        # Get or create author
        author = self._get_author_from_email(gateway, sender_email, sender_full_name)

        # Create message in Odoo with no_gateway_notification context to prevent
        # automatic notification creation and sending back to Zulip (avoid infinite loop)
        new_message = chat.with_context(no_gateway_notification=True).message_post(
            body=body,
            author_id=author._name == "res.partner" and author.id,
            gateway_type="zulip",
            subtype_xmlid="mail.mt_comment",
            message_type="comment",
        )

        _logger.debug(
            "Created message %s from Zulip with no_gateway_notification context "
            "(original Zulip message: %s)",
            new_message.id,
            message_id,
        )

        self._post_process_message(new_message, chat)
        return new_message

    def _get_author_from_email(self, gateway, email, full_name):
        """Get or create author from email and name with enhanced mapping"""
        if not email:
            return super()._get_author(gateway, {})

        # 1. FIRST: Check for manual Gateway Partner Channel mapping
        partner_channel = self.env["res.partner.gateway.channel"].search(
            [
                ("gateway_id", "=", gateway.id),
                ("gateway_token", "=", email),
            ],
            limit=1,
        )
        if partner_channel:
            _logger.info(
                "Found manual user mapping: %s (%s) -> %s",
                email,
                full_name,
                partner_channel.partner_id.name,
            )
            return partner_channel.partner_id

        # 2. Enhanced auto-mapping logic (existing)
        if gateway.zulip_auto_map_users:
            # Check domain restriction
            if gateway.zulip_auto_map_domain:
                email_domain = email.split("@")[1] if "@" in email else ""
                if email_domain == gateway.zulip_auto_map_domain:
                    # Try auto-mapping for allowed domain
                    author = self._try_auto_map_user(email)
                    if author:
                        # Create Gateway Partner Channel mapping for future use
                        self._create_partner_channel_mapping(gateway, email, author)
                        return author
            else:
                # No domain restriction - try auto-mapping for all
                author = self._try_auto_map_user(email)
                if author:
                    # Create Gateway Partner Channel mapping for future use
                    self._create_partner_channel_mapping(gateway, email, author)
                    return author

        # 3. Check for existing gateway guest
        guest = self.env["mail.guest"].search(
            [
                ("gateway_id", "=", gateway.id),
                ("gateway_token", "=", email),
            ],
            limit=1,
        )
        if guest:
            return guest

        # 4. Create guest if enabled
        if gateway.zulip_create_guests:
            return self._create_gateway_guest(gateway, email, full_name)

        # 5. Fallback to system user
        return self.env.ref("base.user_root").partner_id

    def _try_auto_map_user(self, email):
        """Try to map by email to existing user/partner"""
        # Try user first
        user = self.env["res.users"].search(
            [("email", "=", email), ("active", "=", True)], limit=1
        )
        if user:
            return user.partner_id

        # Try partner
        partner = self.env["res.partner"].search([("email", "=", email)], limit=1)
        if partner:
            return partner

        return None

    def _create_gateway_guest(self, gateway, email, full_name):
        """Create a gateway guest with configurable name format"""
        # Format guest name based on configuration
        if gateway.zulip_guest_name_format == "email_prefix":
            guest_name = email.split("@")[0] if "@" in email else email
        elif gateway.zulip_guest_name_format == "email_full":
            guest_name = email
        else:  # full_name (default)
            guest_name = full_name or email.split("@")[0] if "@" in email else email

        return self.env["mail.guest"].create(
            {
                "name": guest_name,
                "gateway_id": gateway.id,
                "gateway_token": email,
            }
        )

    def _create_partner_channel_mapping(self, gateway, email, partner):
        """Create Gateway Partner Channel mapping for successful auto-mapping"""
        try:
            # Check if mapping already exists
            existing = self.env["res.partner.gateway.channel"].search(
                [
                    ("gateway_id", "=", gateway.id),
                    ("gateway_token", "=", email),
                ],
                limit=1,
            )

            if existing:
                _logger.debug(
                    "Gateway Partner Channel mapping already exists: %s -> %s",
                    email,
                    existing.partner_id.name,
                )
                return existing

            # Create new mapping
            mapping = self.env["res.partner.gateway.channel"].create(
                {
                    "partner_id": partner.id,
                    "gateway_id": gateway.id,
                    "gateway_token": email,
                }
            )

            _logger.info(
                "Created Gateway Partner Channel mapping: %s (%s) -> %s",
                email,
                partner.name,
                gateway.name,
            )
            return mapping

        except Exception as e:
            _logger.warning(
                "Failed to create Gateway Partner Channel mapping for %s: %s",
                email,
                str(e),
            )
            return None

    def _send(
        self,
        gateway,
        record,
        auto_commit=False,
        raise_exception=False,
        parse_mode=False,
    ):
        """Send message to Zulip"""
        # CRITICAL: Check if message is already sent to prevent infinite loops
        if record.notification_status == "sent":
            _logger.debug(
                "Skipping message that is already sent (loop prevention): "
                "Gateway %s, Record %s, Zulip Message ID: %s",
                gateway.name,
                record.id,
                record.gateway_message_id,
            )
            return

        # Check if async sending is enabled
        if gateway.zulip_async_send:
            _logger.debug("=== QUEUING MESSAGE FOR ASYNC SENDING ===")
            _logger.debug("Gateway: %s", gateway.name)
            _logger.debug("Record ID: %s", record.id)

            # Mark message as ready for sending by cron job
            record.sudo().write(
                {
                    "notification_status": "ready",
                    "failure_reason": False,
                    "failure_type": False,
                }
            )

            _logger.info(
                "Message queued for async sending: Gateway %s, Record %s",
                gateway.name,
                record.id,
            )
            return

        # Original synchronous sending logic
        self._send_message_now(
            gateway, record, auto_commit, raise_exception, parse_mode
        )

    def _send_message_now(
        self,
        gateway,
        record,
        auto_commit=False,
        raise_exception=False,
        parse_mode=False,
    ):
        """Send message to Zulip immediately (synchronous)"""
        try:
            _logger.debug("=== SENDING MESSAGE TO ZULIP ===")
            _logger.debug("Gateway: %s", gateway.name)
            _logger.debug("Record ID: %s", record.id)

            client = self._get_zulip_client(gateway)

            # Get channel information
            channel = record.gateway_channel_id
            stream_name, topic_name = self._parse_channel_token(
                channel.gateway_channel_token
            )

            _logger.debug("Channel: %s", channel.name)
            _logger.debug("Stream: %s", stream_name)
            _logger.debug("Topic: %s", topic_name)

            # Get message content
            body = self._get_message_body(record)
            content = self._html_to_markdown(body)

            _logger.debug("Original body: %s", body)
            _logger.debug("Converted content: %s", content)

            # Prepare message data
            message_data = {
                "type": "stream",
                "to": stream_name,
                "topic": topic_name,
                "content": content,
            }

            _logger.debug("=== ZULIP API REQUEST: SEND MESSAGE ===")
            _logger.debug("Gateway: %s", gateway.name)
            _logger.debug("Message data: %s", message_data)

            # Send message to Zulip
            result = client.send_message(message_data)

            _logger.debug("=== ZULIP API RESPONSE: SEND MESSAGE ===")
            _logger.debug("Gateway: %s", gateway.name)
            _logger.debug("Response: %s", result)

            if result["result"] == "success":
                record.sudo().write(
                    {
                        "notification_status": "sent",
                        "failure_reason": False,
                        "failure_type": False,
                        "gateway_message_id": result.get("id", ""),
                    }
                )
                _logger.info("Message sent to Zulip: %s", result.get("id"))
            else:
                raise Exception(
                    f"Zulip API error: {result.get('msg', 'Unknown error')}"
                )

        except Exception as exc:
            buff = StringIO()
            traceback.print_exc(file=buff)
            _logger.error(buff.getvalue())

            if raise_exception:
                raise MailDeliveryException(
                    _("Unable to send the Zulip message"), exc
                ) from None
            else:
                _logger.warning(
                    "Issue sending message with id {}: {}".format(record.id, exc)
                )
                record.sudo().write(
                    {
                        "notification_status": "exception",
                        "failure_reason": str(exc),
                        "failure_type": "unknown",
                    }
                )

        # Notify frontend
        self.env["bus.bus"]._sendone(
            record.gateway_channel_id,
            "mail.message/insert",
            {
                "id": record.mail_message_id.id,
            },
        )

        # Note: Direct commit removed as it's not allowed in Odoo
        # The transaction will be committed by the calling code
        if auto_commit:
            # Instead of direct commit, we ensure the transaction is flushed
            self.env.flush_all()

    def _update_content_after_hook(self, channel, message):
        """Update message content in Zulip after editing"""
        try:
            client = self._get_zulip_client(channel.gateway_id)

            # Get Zulip message ID
            notification = message.gateway_notification_ids.filtered(
                lambda n: n.gateway_channel_id == channel
            )
            if not notification or not notification.gateway_message_id:
                return

            # Update message in Zulip
            content = self._html_to_markdown(message.body)
            result = client.update_message(
                {
                    "message_id": int(notification.gateway_message_id),
                    "content": content,
                }
            )

            if result["result"] != "success":
                _logger.warning("Failed to update Zulip message: %s", result.get("msg"))

        except Exception as e:
            _logger.error("Error updating Zulip message: %s", str(e))

    # ===== DIAGNOSTIC AND TESTING METHODS =====

    @api.model
    def run_connection_test(self):
        """Run connection test for all Zulip gateways (callable from Odoo shell)"""
        gateways = self.env["mail.gateway"].search([("gateway_type", "=", "zulip")])

        if not gateways:
            _logger.error("No Zulip gateways found!")
            return False

        for gateway in gateways:
            _logger.info("Testing gateway: %s", gateway.name)
            self.check_gateway_status(gateway)
            success = self.test_zulip_connection(gateway)
            if success:
                self.manual_poll_test(gateway)

        return True

    def test_zulip_connection(self, gateway):
        """Test basic Zulip API connectivity and permissions"""
        try:
            _logger.info(
                "=== TESTING ZULIP CONNECTION FOR GATEWAY %s ===", gateway.name
            )

            # Test 1: Basic client creation
            _logger.info("Test 1: Creating Zulip client...")
            client = self._get_zulip_client(gateway)
            _logger.info("✓ Zulip client created successfully")

            # Test 2: Get user info (basic API test)
            _logger.info("Test 2: Testing basic API connectivity...")
            _logger.debug("=== ZULIP API REQUEST: GET PROFILE ===")
            _logger.debug("Gateway: %s", gateway.name)

            user_info = client.get_profile()

            _logger.debug("=== ZULIP API RESPONSE: GET PROFILE ===")
            _logger.debug("Gateway: %s", gateway.name)
            _logger.debug("Response: %s", user_info)

            if user_info.get("result") == "success":
                _logger.info("✓ API connectivity successful")
                _logger.info(
                    "  Bot user: %s (%s)",
                    user_info.get("full_name"),
                    user_info.get("email"),
                )
                _logger.info("  User ID: %s", user_info.get("user_id"))
            else:
                _logger.error("✗ API connectivity failed: %s", user_info.get("msg"))
                return False

            # Test 3: Get subscriptions (check stream access)
            _logger.info("Test 3: Checking bot stream subscriptions...")
            _logger.debug("=== ZULIP API REQUEST: GET SUBSCRIPTIONS ===")
            _logger.debug("Gateway: %s", gateway.name)

            subscriptions = client.get_subscriptions()

            _logger.debug("=== ZULIP API RESPONSE: GET SUBSCRIPTIONS ===")
            _logger.debug("Gateway: %s", gateway.name)
            _logger.debug("Response: %s", subscriptions)

            if subscriptions.get("result") == "success":
                streams = subscriptions.get("subscriptions", [])
                _logger.info("✓ Bot is subscribed to %d streams:", len(streams))
                for stream in streams[:5]:  # Show first 5 streams
                    _logger.info("  - %s", stream.get("name"))
                if len(streams) > 5:
                    _logger.info("  ... and %d more streams", len(streams) - 5)
            else:
                _logger.error(
                    "✗ Failed to get subscriptions: %s", subscriptions.get("msg")
                )

            # Test 4: Test event queue registration
            _logger.info("Test 4: Testing event queue registration...")
            success = self._register_event_queue(gateway, client)
            if success:
                _logger.info("✓ Event queue registration successful")
                _logger.info("  Queue ID: %s", gateway.zulip_queue_id)
                _logger.info("  Last Event ID: %s", gateway.zulip_last_event_id)
            else:
                _logger.error("✗ Event queue registration failed")
                return False

            _logger.info("=== CONNECTION TEST COMPLETED SUCCESSFULLY ===")
            return True

        except Exception as e:
            _logger.error("=== CONNECTION TEST FAILED ===")
            _logger.error("Exception: %s", str(e))
            _logger.error("Traceback: %s", traceback.format_exc())
            return False

    def manual_poll_test(self, gateway):
        """Manually poll for events and log detailed results"""
        try:
            _logger.info("=== MANUAL EVENT POLL TEST FOR GATEWAY %s ===", gateway.name)

            client = self._get_zulip_client(gateway)

            # Ensure we have a queue
            if not gateway.zulip_queue_id:
                _logger.info("No queue ID found, registering new queue...")
                success = self._register_event_queue(gateway, client)
                if not success:
                    _logger.error("Failed to register queue for manual test")
                    return False

            _logger.info("Polling events with queue ID: %s", gateway.zulip_queue_id)
            _logger.info("Last event ID: %s", gateway.zulip_last_event_id)

            # Poll for events
            events = client.get_events(
                queue_id=gateway.zulip_queue_id,
                last_event_id=gateway.zulip_last_event_id,
                dont_block=True,
            )

            _logger.info("Poll response: %s", events)

            if events.get("result") == "success":
                event_list = events.get("events", [])
                _logger.info("✓ Successfully received %d events", len(event_list))

                for i, event in enumerate(event_list):
                    _logger.info("Event %d:", i + 1)
                    _logger.info("  Type: %s", event.get("type"))
                    _logger.info("  ID: %s", event.get("id"))

                    if event.get("type") == "message":
                        message = event.get("message", {})
                        _logger.info("  Message details:")
                        _logger.info("    Stream: %s", message.get("display_recipient"))
                        _logger.info("    Topic: %s", message.get("subject"))
                        _logger.info(
                            "    Sender: %s (%s)",
                            message.get("sender_full_name"),
                            message.get("sender_email"),
                        )
                        _logger.info(
                            "    Content: %s",
                            message.get("content", "")[:100] + "..."
                            if len(message.get("content", "")) > 100
                            else message.get("content", ""),
                        )

                        # Test if this message would be processed
                        self._test_message_processing(gateway, event)

                if not event_list:
                    _logger.info("No new events since last poll")

            else:
                _logger.error("✗ Failed to poll events: %s", events.get("msg"))
                return False

            _logger.info("=== MANUAL POLL TEST COMPLETED ===")
            return True

        except Exception as e:
            _logger.error("=== MANUAL POLL TEST FAILED ===")
            _logger.error("Exception: %s", str(e))
            _logger.error("Traceback: %s", traceback.format_exc())
            return False

    def _test_message_processing(self, gateway, event):
        """Test if a message event would be processed (without actually processing it)"""
        try:
            _logger.info("    Testing message processing filters...")

            message = event.get("message", {})
            if not message:
                _logger.info("    ✗ No message data in event")
                return False

            # Test stream filter
            stream_name = message.get("display_recipient", "")
            streams = gateway._get_zulip_streams()
            if streams and stream_name not in streams:
                _logger.info("    ✗ Message filtered out by stream filter")
                _logger.info(
                    "      Stream: %s, Allowed streams: %s", stream_name, streams
                )
                return False

            # Test topic filter
            topic_name = message.get("subject", "")
            topics = gateway._get_zulip_topics()
            if topics and topic_name not in topics:
                _logger.info("    ✗ Message filtered out by topic filter")
                _logger.info("      Topic: %s, Allowed topics: %s", topic_name, topics)
                return False

            # Test bot message filter
            sender_email = message.get("sender_email", "")
            if sender_email == gateway.zulip_bot_email:
                _logger.info("    ✗ Message filtered out (sent by bot itself)")
                return False

            _logger.info("    ✓ Message would be processed")
            _logger.info(
                "      Stream: %s, Topic: %s, Sender: %s",
                stream_name,
                topic_name,
                sender_email,
            )
            return True

        except Exception as e:
            _logger.error("    ✗ Error testing message processing: %s", str(e))
            return False

    def check_gateway_status(self, gateway):
        """Check comprehensive status of gateway configuration"""
        try:
            _logger.info("=== GATEWAY STATUS CHECK FOR %s ===", gateway.name)

            # Basic configuration
            _logger.info("Configuration:")
            _logger.info("  Gateway Type: %s", gateway.gateway_type)
            _logger.info("  Server URL: %s", gateway.zulip_server_url)
            _logger.info("  Bot Email: %s", gateway.zulip_bot_email)
            _logger.info(
                "  API Key: %s",
                "***" + gateway.zulip_api_key[-4:]
                if gateway.zulip_api_key
                else "NOT SET",
            )
            _logger.info("  Configured: %s", gateway._is_zulip_configured())

            # Filters
            _logger.info("Filters:")
            _logger.info(
                "  Stream Filter: %s", gateway.zulip_stream_filter or "ALL STREAMS"
            )
            _logger.info(
                "  Topic Filter: %s", gateway.zulip_topic_filter or "ALL TOPICS"
            )

            # Event queue status
            _logger.info("Event Queue:")
            _logger.info("  Queue ID: %s", gateway.zulip_queue_id or "NOT SET")
            _logger.info("  Last Event ID: %s", gateway.zulip_last_event_id)
            _logger.info("  Listener Active: %s", gateway.zulip_listener_active)

            _logger.info("=== STATUS CHECK COMPLETED ===")

        except Exception as e:
            _logger.error("Error checking gateway status: %s", str(e))

    # ===== EVENTS API / LONG-POLLING METHODS =====

    @api.model
    def _cron_poll_events(self):
        """Cron job to poll events AND send pending messages for all active Zulip gateways"""
        _logger.debug("=== ZULIP CRON JOB STARTED ===")

        # Search for gateways with Events API enabled (based on configuration and listener status)
        event_gateways = self.env["mail.gateway"].search(
            [
                ("gateway_type", "=", "zulip"),
                ("zulip_listener_active", "=", True),
            ]
        )

        # Search for gateways with async sending enabled
        async_gateways = self.env["mail.gateway"].search(
            [
                ("gateway_type", "=", "zulip"),
                ("zulip_async_send", "=", True),
            ]
        )

        # Combine both sets of gateways (remove duplicates)
        all_gateways = event_gateways | async_gateways

        _logger.debug("Found %d gateways for event polling", len(event_gateways))
        _logger.debug("Found %d gateways for async sending", len(async_gateways))
        _logger.debug("Processing %d total gateways", len(all_gateways))

        for gateway in all_gateways:
            try:
                # Handle incoming events (if listener is active)
                if gateway in event_gateways:
                    self._poll_gateway_events(gateway)

                # Handle outgoing messages (if async sending is enabled)
                if gateway in async_gateways:
                    self._send_pending_messages(gateway)

            except Exception as e:
                _logger.error(
                    "Error in cron job for gateway %s: %s", gateway.name, str(e)
                )

        _logger.debug("=== ZULIP CRON JOB COMPLETED ===")

    def _send_pending_messages(self, gateway):
        """Send all pending messages for a specific gateway"""
        try:
            _logger.debug(
                "=== SENDING PENDING MESSAGES FOR GATEWAY %s ===", gateway.name
            )

            # Find all pending notifications for this gateway
            pending_notifications = self.env["mail.notification"].search(
                [
                    ("notification_type", "=", "inbox"),
                    ("gateway_channel_id.gateway_id", "=", gateway.id),
                    ("notification_status", "=", "ready"),
                ]
            )

            if not pending_notifications:
                _logger.debug("No pending messages for gateway %s", gateway.name)
                return

            _logger.info(
                "Found %d pending messages for gateway %s",
                len(pending_notifications),
                gateway.name,
            )

            sent_count = 0
            failed_count = 0

            for notification in pending_notifications:
                try:
                    _logger.debug(
                        "Sending pending notification ID: %s", notification.id
                    )

                    # Send the message using the existing synchronous method
                    self._send_message_now(
                        gateway, notification, auto_commit=False, raise_exception=False
                    )

                    # Check if it was sent successfully
                    if notification.notification_status == "sent":
                        sent_count += 1
                        _logger.debug(
                            "Successfully sent notification ID: %s", notification.id
                        )
                    else:
                        failed_count += 1
                        _logger.warning(
                            "Failed to send notification ID: %s, status: %s",
                            notification.id,
                            notification.notification_status,
                        )

                except Exception as e:
                    failed_count += 1
                    _logger.error(
                        "Exception sending notification ID %s: %s",
                        notification.id,
                        str(e),
                    )

                    # Mark as failed if not already marked
                    if notification.notification_status == "ready":
                        notification.sudo().write(
                            {
                                "notification_status": "exception",
                                "failure_reason": str(e),
                                "failure_type": "unknown",
                            }
                        )

            if sent_count > 0 or failed_count > 0:
                _logger.info(
                    "Pending messages for gateway %s: %d sent, %d failed",
                    gateway.name,
                    sent_count,
                    failed_count,
                )

        except Exception as e:
            _logger.error(
                "Error processing pending messages for gateway %s: %s",
                gateway.name,
                str(e),
            )
            _logger.error("Full traceback: %s", traceback.format_exc())

    def _poll_gateway_events(self, gateway):
        """Poll events for a specific gateway"""
        try:
            _logger.debug("=== POLLING EVENTS FOR GATEWAY %s ===", gateway.name)
            client = self._get_zulip_client(gateway)

            # Register event queue if not exists
            if not gateway.zulip_queue_id:
                _logger.debug("No queue ID found, attempting to register new queue")
                success = self._register_event_queue(gateway, client)
                if not success:
                    _logger.warning(
                        "Skipping event polling for gateway %s - queue registration failed",
                        gateway.name,
                    )
                    return

            # Skip if still no queue ID after registration attempt
            if not gateway.zulip_queue_id:
                _logger.warning(
                    "No queue ID available for gateway %s, skipping event polling",
                    gateway.name,
                )
                return

            # Get events since last poll
            _logger.debug("=== ZULIP API REQUEST: GET EVENTS ===")
            _logger.debug("Gateway: %s", gateway.name)
            _logger.debug("Queue ID: %s", gateway.zulip_queue_id)
            _logger.debug("Last Event ID: %s", gateway.zulip_last_event_id)
            _logger.debug("Don't block: True (cron job)")

            events = client.get_events(
                queue_id=gateway.zulip_queue_id,
                last_event_id=gateway.zulip_last_event_id,
                dont_block=True,  # Don't block for cron job
            )

            _logger.debug("=== ZULIP API RESPONSE: GET EVENTS ===")
            _logger.debug("Gateway: %s", gateway.name)
            _logger.debug("Response: %s", events)

            if events.get("result") == "success":
                event_list = events.get("events", [])
                _logger.debug("Successfully received %d events", len(event_list))

                for event in event_list:
                    _logger.debug(
                        "Processing event ID %s, type: %s",
                        event.get("id"),
                        event.get("type"),
                    )
                    self._process_event(gateway, event)
                    gateway.zulip_last_event_id = event["id"]
                    _logger.debug("Updated last_event_id to: %s", event["id"])

                if event_list:
                    _logger.info(
                        "Processed %d events for gateway %s",
                        len(event_list),
                        gateway.name,
                    )
                else:
                    _logger.debug("No new events for gateway %s", gateway.name)
            else:
                _logger.warning(
                    "Failed to get events for gateway %s: %s",
                    gateway.name,
                    events.get("msg", "Unknown error"),
                )
                # Reset queue on "bad queue ID" error to force re-registration
                if "bad event queue id" in events.get("msg", "").lower():
                    _logger.info(
                        "Resetting queue ID for gateway %s due to bad queue ID error",
                        gateway.name,
                    )
                    gateway.zulip_queue_id = False

        except Exception as e:
            _logger.error(
                "Error polling events for gateway %s: %s", gateway.name, str(e)
            )
            _logger.error("Full traceback: %s", traceback.format_exc())
            # Reset queue on error to force re-registration
            gateway.zulip_queue_id = False

    def _register_event_queue(self, gateway, client):
        """Register event queue with Zulip"""
        try:
            _logger.debug(
                "=== REGISTERING EVENT QUEUE FOR GATEWAY %s ===", gateway.name
            )

            # Get monitored streams
            streams = gateway._get_zulip_streams()
            _logger.debug("Stream filter: %s", streams or "ALL STREAMS")

            # Register for message events
            queue_data = {
                "event_types": ["message"],
                "all_public_streams": not streams,  # Monitor all if no filter
            }

            # Add specific streams if filtered
            if streams:
                queue_data["narrow"] = [["stream", stream] for stream in streams]

            _logger.debug("=== ZULIP API REQUEST: REGISTER QUEUE ===")
            _logger.debug("Gateway: %s", gateway.name)
            _logger.debug("Request data: %s", queue_data)

            result = client.register(**queue_data)

            _logger.debug("=== ZULIP API RESPONSE: REGISTER QUEUE ===")
            _logger.debug("Gateway: %s", gateway.name)
            _logger.debug("Response: %s", result)

            if result.get("result") == "success":
                gateway.zulip_queue_id = result["queue_id"]
                gateway.zulip_last_event_id = result["last_event_id"]
                _logger.info(
                    "Successfully registered event queue %s for gateway %s (last_event_id: %s)",
                    result["queue_id"],
                    gateway.name,
                    result["last_event_id"],
                )
                return True
            else:
                _logger.error(
                    "Failed to register event queue for gateway %s: %s",
                    gateway.name,
                    result.get("msg", "Unknown error"),
                )
                return False

        except Exception as e:
            _logger.error(
                "Exception registering event queue for gateway %s: %s",
                gateway.name,
                str(e),
            )
            _logger.error("Full traceback: %s", traceback.format_exc())
            return False

    def _process_event(self, gateway, event):
        """Process a single Zulip event"""
        if event.get("type") != "message":
            return

        message = event.get("message", {})
        if not message:
            return

        # Apply stream filter
        stream_name = message.get("display_recipient", "")
        streams = gateway._get_zulip_streams()
        if streams and stream_name not in streams:
            return

        # Apply topic filter
        topic_name = message.get("subject", "")
        topics = gateway._get_zulip_topics()
        if topics and topic_name not in topics:
            return

        # Skip messages from our own bot to avoid loops
        sender_email = message.get("sender_email", "")
        if sender_email == gateway.zulip_bot_email:
            return

        # Process the message
        try:
            # Extract message information
            stream_name = message.get("display_recipient", "")
            topic_name = message.get("subject", "general")
            content = message.get("content", "")
            sender_email = message.get("sender_email", "")
            sender_full_name = message.get("sender_full_name", "")
            message_id = message.get("id", "")

            if not stream_name or not content:
                return

            # Check for explicit channel mapping first
            mapping = self.env["zulip.channel.mapping"].find_mapping_for_message(
                gateway, stream_name, topic_name
            )

            if mapping:
                chat = mapping.odoo_channel_id
                # Update mapping stats
                mapping.update_sync_stats()
            else:
                # Fallback to auto-creation
                channel_token = self._get_channel_token(stream_name, topic_name)
                chat = self._get_channel(gateway, channel_token, {})

            if not chat:
                return

            self._process_zulip_message(
                chat, content, sender_email, sender_full_name, message_id, gateway
            )

        except Exception as e:
            _logger.error(
                "Error processing event message for gateway %s: %s",
                gateway.name,
                str(e),
            )

    def _register_event_queue_with_details(self, gateway, client):
        """Register event queue with Zulip with detailed error reporting"""
        try:
            # Get monitored streams
            streams = gateway._get_zulip_streams()

            # Register for message events
            queue_data = {
                "event_types": ["message"],
                "all_public_streams": not streams,  # Monitor all if no filter
            }

            # Add specific streams if filtered
            if streams:
                queue_data["narrow"] = [["stream", stream] for stream in streams]

            result = client.register(**queue_data)

            if result.get("result") == "success":
                gateway.zulip_queue_id = result["queue_id"]
                gateway.zulip_last_event_id = result["last_event_id"]
                return True, None
            else:
                error_msg = f"Zulip API error: {result.get('msg', 'Unknown error')}"
                return False, error_msg

        except Exception as e:
            error_msg = f"Exception during queue registration: {str(e)}"
            return False, error_msg

    def start_auto_sync_with_details(self, gateway):
        """Start event listener for a gateway with detailed error reporting"""
        if not gateway._is_zulip_configured():
            return False, "Gateway is not properly configured"

        try:
            # Create client and test basic connectivity
            client = self._get_zulip_client(gateway)

            # Test basic API connectivity
            user_info = client.get_profile()
            if user_info.get("result") != "success":
                error_msg = (
                    "API connectivity test failed: "
                    f"{user_info.get('msg', 'Unknown error')}"
                )
                return False, error_msg

            # Register event queue for cron job polling
            success, error_message = self._register_event_queue_with_details(
                gateway, client
            )

            if success:
                # CRITICAL: Mark as active using sudo() to ensure it's written immediately
                gateway.sudo().write({"zulip_listener_active": True})
                _logger.info(
                    "Event listener started for gateway %s (cron-based polling)",
                    gateway.name,
                )
                return True, None
            else:
                return False, error_message

        except Exception as e:
            error_msg = f"Exception during event listener startup: {str(e)}"
            return False, error_msg

    def start_auto_sync(self, gateway):
        """Start auto-sync for a gateway (legacy method for backward compatibility)"""
        success, _ = self.start_auto_sync_with_details(gateway)
        return success

    def stop_auto_sync(self, gateway):
        """Stop auto-sync for a gateway"""
        gateway.zulip_listener_active = False
        gateway.zulip_queue_id = False
        gateway.zulip_last_event_id = 0

        _logger.info("Auto-sync stopped for gateway %s", gateway.name)
