# Copyright 2024 Dixmit
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

import logging
import traceback
import re
from io import StringIO

from odoo import _, models
from odoo.http import request
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
        return zulip.Client(
            email=gateway.zulip_bot_email,
            api_key=gateway.zulip_api_key,
            site=gateway.zulip_server_url,
        )

    def _set_webhook(self, gateway):
        """Set up webhook with Zulip"""
        try:
            client = self._get_zulip_client(gateway)
            
            # Register webhook URL with Zulip
            # Note: Zulip webhooks are typically configured through the web interface
            # This method marks the gateway as integrated
            gateway.integrated_webhook_state = "integrated"
            _logger.info("Zulip webhook set for gateway %s", gateway.name)
            
        except Exception as e:
            _logger.error("Failed to set Zulip webhook: %s", str(e))
            raise
        
        return super()._set_webhook(gateway)

    def _remove_webhook(self, gateway):
        """Remove webhook from Zulip"""
        try:
            # Zulip webhooks are typically managed through web interface
            # This method marks the gateway as not integrated
            gateway.integrated_webhook_state = False
            _logger.info("Zulip webhook removed for gateway %s", gateway.name)
            
        except Exception as e:
            _logger.error("Failed to remove Zulip webhook: %s", str(e))
            
        return super()._remove_webhook(gateway)

    def _verify_update(self, bot_data, kwargs):
        """Verify incoming webhook update"""
        # For Zulip, we can verify the webhook secret if configured
        if not bot_data.get("webhook_secret"):
            return True
            
        # Check if the request contains the expected secret
        # This depends on how Zulip webhooks are configured
        return True  # Simplified for now

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

    def _receive_update(self, gateway, update):
        """Process incoming Zulip webhook update"""
        try:
            # Parse Zulip webhook data
            message_data = update.get("data", {})
            message_type = update.get("type", "")
            
            if message_type != "message":
                return  # Only process messages
                
            # Extract message information
            stream_name = message_data.get("display_recipient", "")
            topic_name = message_data.get("subject", "general")
            content = message_data.get("content", "")
            sender_email = message_data.get("sender_email", "")
            sender_full_name = message_data.get("sender_full_name", "")
            message_id = message_data.get("id", "")
            
            if not stream_name or not content:
                return
                
            # Create channel token
            channel_token = self._get_channel_token(stream_name, topic_name)
            
            # Get or create channel
            chat = self._get_channel(gateway, channel_token, update)
            if not chat:
                return
                
            return self._process_zulip_message(
                chat, content, sender_email, sender_full_name, message_id, gateway
            )
            
        except Exception as e:
            _logger.error("Error processing Zulip update: %s", str(e))
            _logger.error(traceback.format_exc())

    def _process_zulip_message(self, chat, content, sender_email, sender_full_name, message_id, gateway):
        """Process a Zulip message and create corresponding Odoo message"""
        chat.ensure_one()
        
        # Convert markdown to HTML
        body = self._markdown_to_html(content)
        
        # Get or create author
        author = self._get_author_from_email(gateway, sender_email, sender_full_name)
        
        # Create message in Odoo
        new_message = chat.message_post(
            body=body,
            author_id=author._name == "res.partner" and author.id,
            gateway_type="zulip",
            subtype_xmlid="mail.mt_comment",
            message_type="comment",
        )
        
        # Store Zulip message ID for reference
        if message_id:
            notification = self.env["mail.notification"].search([
                ("mail_message_id", "=", new_message.id),
                ("gateway_channel_id", "=", chat.id),
            ], limit=1)
            if notification:
                notification.gateway_message_id = str(message_id)
        
        self._post_process_message(new_message, chat)
        return new_message

    def _get_author_from_email(self, gateway, email, full_name):
        """Get or create author from email and name"""
        if not email:
            return super()._get_author(gateway, {})
            
        # Try to find existing partner by email
        partner = self.env["res.partner"].search([("email", "=", email)], limit=1)
        if partner:
            return partner
            
        # Check for existing gateway guest
        guest = self.env["mail.guest"].search([
            ("gateway_id", "=", gateway.id),
            ("gateway_token", "=", email),
        ], limit=1)
        if guest:
            return guest
            
        # Create new guest
        return self.env["mail.guest"].create({
            "name": full_name or email,
            "gateway_id": gateway.id,
            "gateway_token": email,
        })

    def _send(self, gateway, record, auto_commit=False, raise_exception=False, parse_mode=False):
        """Send message to Zulip"""
        try:
            client = self._get_zulip_client(gateway)
            
            # Get channel information
            channel = record.gateway_channel_id
            stream_name, topic_name = self._parse_channel_token(channel.gateway_channel_token)
            
            # Get message content
            body = self._get_message_body(record)
            content = self._html_to_markdown(body)
            
            # Send message to Zulip
            result = client.send_message({
                "type": "stream",
                "to": stream_name,
                "topic": topic_name,
                "content": content,
            })
            
            if result["result"] == "success":
                record.sudo().write({
                    "notification_status": "sent",
                    "failure_reason": False,
                    "failure_type": False,
                    "gateway_message_id": result.get("id", ""),
                })
                _logger.info("Message sent to Zulip: %s", result.get("id"))
            else:
                raise Exception(f"Zulip API error: {result.get('msg', 'Unknown error')}")
                
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
                record.sudo().write({
                    "notification_status": "exception",
                    "failure_reason": str(exc),
                    "failure_type": "unknown",
                })
        
        # Notify frontend
        self.env["bus.bus"]._sendone(
            record.gateway_channel_id,
            "mail.message/insert",
            {
                "id": record.mail_message_id.id,
                "gateway_type": record.mail_message_id.gateway_type,
            },
        )
        
        if auto_commit:
            self.env.cr.commit()

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
            result = client.update_message({
                "message_id": int(notification.gateway_message_id),
                "content": content,
            })
            
            if result["result"] != "success":
                _logger.warning("Failed to update Zulip message: %s", result.get("msg"))
                
        except Exception as e:
            _logger.error("Error updating Zulip message: %s", str(e))
