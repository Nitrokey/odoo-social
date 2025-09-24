# Copyright 2025 Nitrokey GmbH
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

import logging

from odoo import api, models

_logger = logging.getLogger(__name__)


class ProjectTask(models.Model):
    _inherit = "project.task"

    @api.returns("mail.message", lambda value: value.id)
    def message_post(self, **kwargs):
        """Override message_post to handle Zulip synchronization for project tasks"""
        # Call the original message_post first
        message = super().message_post(**kwargs)
        
        # Check if this task has a Zulip mapping and should sync to Zulip
        if not self.env.context.get("no_zulip_sync", False):
            self._sync_message_to_zulip(message)
        
        return message

    def _sync_message_to_zulip(self, message):
        """Sync a message posted on this task to Zulip if mapping exists"""
        self.ensure_one()
        
        # Find mapping for this task
        mapping = self.env["zulip.channel.mapping"].search([
            ("mapping_type", "=", "project_task"),
            ("task_id", "=", self.id),
            ("active", "=", True),
        ], limit=1)
        
        if not mapping:
            return
        
        try:
            # Create a virtual channel for this task to use existing gateway infrastructure
            virtual_channel = self._create_virtual_channel_for_task(mapping)
            
            # Create gateway notification for the message
            notification = self.env["mail.notification"].create({
                "mail_message_id": message.id,
                "gateway_channel_id": virtual_channel.id,
                "notification_type": "gateway",
                "gateway_type": mapping.gateway_id.gateway_type,
                "notification_status": "ready",  # Always start with "ready" status
            })
            
            # Send immediately if not async, otherwise it will be picked up by cron
            if not mapping.gateway_id.zulip_async_send:
                notification.send_gateway()
            
            _logger.info(
                "Created notification %s for task message (async: %s)",
                notification.id,
                mapping.gateway_id.zulip_async_send
            )
            
            _logger.info(
                "Queued message from task %s to Zulip stream %s/%s",
                self.name,
                mapping.zulip_stream,
                mapping.zulip_topic or "general"
            )
            
        except Exception as e:
            _logger.error(
                "Failed to sync message from task %s to Zulip: %s",
                self.name,
                str(e)
            )

    def _create_virtual_channel_for_task(self, mapping):
        """Create or get a virtual channel for this task to enable Zulip sync"""
        # Generate a unique channel token for this task mapping
        channel_token = f"{mapping.zulip_stream}#{mapping.zulip_topic or 'general'}"
        
        # Look for existing virtual channel
        virtual_channel = self.env["mail.channel"].search([
            ("gateway_id", "=", mapping.gateway_id.id),
            ("gateway_channel_token", "=", channel_token),
            ("name", "ilike", f"Task: {self.name}"),
        ], limit=1)
        
        if virtual_channel:
            return virtual_channel
        
        # Create virtual channel for this task
        virtual_channel = self.env["mail.channel"].create({
            "name": f"Task: {self.name} → Zulip",
            "channel_type": "channel",
            "gateway_id": mapping.gateway_id.id,
            "gateway_channel_token": channel_token,
            "description": f"Virtual channel for syncing task '{self.name}' to Zulip stream '{mapping.zulip_stream}'",
        })
        
        _logger.info(
            "Created virtual channel %s for task %s → Zulip sync",
            virtual_channel.name,
            self.name
        )
        
        return virtual_channel
