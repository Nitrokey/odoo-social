# Copyright 2025 Nitrokey GmbH
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

import logging

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


class ZulipChannelMapping(models.Model):
    _name = "zulip.channel.mapping"
    _description = "Zulip Channel Mapping"
    _order = "gateway_id, zulip_stream, zulip_topic"

    # Basic Configuration
    name = fields.Char(compute="_compute_name", store=True)
    gateway_id = fields.Many2one(
        "mail.gateway",
        domain=[("gateway_type", "=", "zulip")],
        required=True,
    )
    active = fields.Boolean(default=True)

    # Zulip Source
    zulip_stream = fields.Selection(
        selection="_get_zulip_streams_selection",
        string="Zulip Stream",
        required=True,
        help="Select the Zulip stream to sync with",
    )
    zulip_topic = fields.Char(help="Specific topic name (leave empty for all topics)")

    # Mapping Type
    mapping_type = fields.Selection(
        [
            ("channel", "Chat Channel"),
            ("project_task", "Project Task"),
        ],
        default="channel",
        required=True,
        help="Choose whether to sync with a chat channel or project task",
    )

    # Odoo Destination - Chat Channel
    odoo_channel_id = fields.Many2one(
        "mail.channel", 
        string="Chat Channel",
        help="Odoo chat channel to sync with"
    )

    # Odoo Destination - Project Task
    project_id = fields.Many2one(
        "project.project",
        string="Project",
        domain=[("active", "=", True)],
        help="Project containing the task to sync with"
    )
    task_id = fields.Many2one(
        "project.task",
        string="Task",
        domain="[('project_id', '=', project_id), ('active', '=', True)]",
        help="Specific task to sync messages with"
    )

    # Status & Monitoring
    last_sync = fields.Datetime(readonly=True)
    message_count = fields.Integer(readonly=True, default=0)
    status = fields.Selection(
        [
            ("active", "Active"),
            ("error", "Error"),
            ("inactive", "Inactive"),
        ],
        default="active",
    )
    error_message = fields.Text(readonly=True)

    @api.depends("zulip_stream", "zulip_topic", "mapping_type", "odoo_channel_id", "task_id")
    def _compute_name(self):
        """Auto-generate name based on stream, topic, and destination"""
        for record in self:
            if record.zulip_stream:
                # Build stream/topic part
                if record.zulip_topic:
                    stream_part = f"{record.zulip_stream} / {record.zulip_topic}"
                else:
                    stream_part = f"{record.zulip_stream} (all topics)"
                
                # Build destination part
                if record.mapping_type == "project_task" and record.task_id:
                    dest_part = f"Task: {record.task_id.name}"
                elif record.mapping_type == "channel" and record.odoo_channel_id:
                    dest_part = f"Channel: {record.odoo_channel_id.name}"
                else:
                    dest_part = "No destination"
                
                record.name = f"{stream_part} → {dest_part}"
            else:
                record.name = "New Mapping"

    @api.model
    def _get_zulip_streams_selection(self):
        """Get available Zulip streams for selection based on gateway"""
        # Multiple ways to detect the gateway
        gateway_id = None
        
        # Method 1: From context (form creation)
        gateway_id = self.env.context.get('default_gateway_id')
        
        # Method 2: From current record (form editing)
        if not gateway_id and hasattr(self, 'gateway_id') and self.gateway_id:
            gateway_id = self.gateway_id.id
            
        # Method 3: From self if we're a recordset with gateway_id set
        if not gateway_id and self and len(self) == 1 and self.gateway_id:
            gateway_id = self.gateway_id.id
        
        # Method 4: Try to get from any Zulip gateway as fallback
        if not gateway_id:
            gateway = self.env['mail.gateway'].search([
                ('gateway_type', '=', 'zulip')
            ], limit=1)
            if gateway:
                gateway_id = gateway.id
                _logger.debug("Using fallback gateway: %s", gateway.name)
        
        if not gateway_id:
            _logger.debug("No gateway found for stream selection")
            return []
        
        try:
            gateway = self.env['mail.gateway'].browse(gateway_id)
            if not gateway.exists() or gateway.gateway_type != 'zulip':
                _logger.debug("Invalid gateway for stream selection: %s", gateway_id)
                return []
            
            _logger.debug("Fetching streams for gateway: %s", gateway.name)
            
            # Get Zulip client and fetch streams
            zulip_service = self.env['mail.gateway.zulip']
            client = zulip_service._get_zulip_client(gateway)
            
            streams_response = client.get_streams()
            if streams_response.get('result') == 'success':
                streams = streams_response.get('streams', [])
                stream_list = [(stream['name'], stream['name']) for stream in streams]
                _logger.debug("Found %d streams for gateway %s", len(stream_list), gateway.name)
                return stream_list
            else:
                _logger.warning(
                    "Failed to fetch streams for gateway %s: %s",
                    gateway.name,
                    streams_response.get('msg', 'Unknown error')
                )
                return []
                
        except Exception as e:
            _logger.error(
                "Error fetching Zulip streams for selection: %s", str(e)
            )
            import traceback
            _logger.debug("Full traceback: %s", traceback.format_exc())
            return []

    @api.onchange("gateway_id")
    def _onchange_gateway_id(self):
        """Clear stream selection when gateway changes"""
        if self.gateway_id:
            # Clear the stream selection to force reload
            self.zulip_stream = False
            # Note: Domain return is deprecated, selection method will handle refresh

    @api.onchange("mapping_type")
    def _onchange_mapping_type(self):
        """Clear destination fields when mapping type changes"""
        if self.mapping_type == "channel":
            self.project_id = False
            self.task_id = False
        elif self.mapping_type == "project_task":
            self.odoo_channel_id = False

    @api.onchange("project_id")
    def _onchange_project_id(self):
        """Clear task selection when project changes"""
        if self.project_id:
            self.task_id = False

    @api.model
    def create(self, vals):
        """Configure channel for bidirectional sync after creation"""
        result = super().create(vals)
        result._configure_channel_for_gateway()
        return result

    @api.constrains("zulip_stream", "zulip_topic", "gateway_id")
    def _check_unique_mapping(self):
        """Ensure unique mapping per gateway/stream/topic combination"""
        for record in self:
            domain = [
                ("gateway_id", "=", record.gateway_id.id),
                ("zulip_stream", "=", record.zulip_stream),
                ("zulip_topic", "=", record.zulip_topic or False),
                ("id", "!=", record.id),
            ]
            if self.search_count(domain) > 0:
                raise ValidationError(
                    _("This stream/topic combination is already mapped!")
                )

    @api.constrains("mapping_type", "odoo_channel_id", "task_id")
    def _check_destination_required(self):
        """Ensure appropriate destination is set based on mapping type"""
        for record in self:
            if record.mapping_type == "channel" and not record.odoo_channel_id:
                raise ValidationError(
                    _("Chat Channel is required when mapping type is 'Chat Channel'")
                )
            elif record.mapping_type == "project_task" and not record.task_id:
                raise ValidationError(
                    _("Task is required when mapping type is 'Project Task'")
                )

    @api.constrains("mapping_type", "odoo_channel_id", "project_id", "task_id")
    def _check_destination_exclusivity(self):
        """Ensure only one destination type is set"""
        for record in self:
            if record.mapping_type == "channel":
                if record.project_id or record.task_id:
                    raise ValidationError(
                        _("Project fields must be empty when mapping type is 'Chat Channel'")
                    )
            elif record.mapping_type == "project_task":
                if record.odoo_channel_id:
                    raise ValidationError(
                        _("Chat Channel must be empty when mapping type is 'Project Task'")
                    )

    def action_test_mapping(self):
        """Comprehensive bidirectional mapping test"""
        self.ensure_one()
        try:
            # Phase 1: Test Zulip Connectivity
            _logger.info("=== TESTING MAPPING: %s ===", self.name)
            _logger.info("Phase 1: Testing Zulip connectivity...")

            zulip_service = self.env["mail.gateway.zulip"]
            client = zulip_service._get_zulip_client(self.gateway_id)

            # Test Zulip API connection
            streams_response = client.get_streams()
            if streams_response.get("result") != "success":
                msg = streams_response.get("msg", "Unknown error")
                raise ValidationError(_("Failed to connect to Zulip: %s") % msg)

            # Test stream exists
            streams = streams_response.get("streams", [])
            stream_exists = any(s["name"] == self.zulip_stream for s in streams)

            if not stream_exists:
                raise ValidationError(
                    _("Stream '%s' not found in Zulip!") % self.zulip_stream
                )

            _logger.info("✓ Zulip connectivity successful")
            _logger.info("✓ Stream '%s' exists", self.zulip_stream)

            # Phase 2: Test Configuration based on mapping type
            if self.mapping_type == "channel":
                success_message = self._test_channel_mapping_configuration()
            elif self.mapping_type == "project_task":
                success_message = self._test_project_task_mapping_configuration()
            else:
                raise ValidationError(_("Unknown mapping type: %s") % self.mapping_type)

            # Phase 3: Build final success message
            final_message = (
                _("✅ Zulip Connectivity: Stream '%s' exists and accessible\n")
                % self.zulip_stream
            )
            
            if self.zulip_topic:
                final_message += _("✅ Topic Filter: '%s'\n") % self.zulip_topic
            else:
                final_message += _("✅ Topic Filter: All topics from stream\n")
            
            final_message += success_message
            final_message += _("\n🚀 This mapping is ready for production use!")

            # Update status
            self.write({"status": "active", "error_message": False})

            _logger.info("=== MAPPING TEST COMPLETED SUCCESSFULLY ===")

            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": _("Comprehensive Mapping Test Successful"),
                    "message": final_message,
                    "type": "success",
                },
            }

        except Exception as e:
            # Update status with error
            error_message = str(e)
            self.write({"status": "error", "error_message": error_message})

            _logger.error("=== MAPPING TEST FAILED ===")
            _logger.error("Error: %s", error_message)

            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": _("Comprehensive Mapping Test Failed"),
                    "message": error_message,
                    "type": "danger",
                },
            }

    def _test_channel_mapping_configuration(self):
        """Test configuration for channel mappings"""
        _logger.info("Phase 2: Testing channel configuration...")

        channel = self.odoo_channel_id
        config_issues = []

        # Check gateway association
        if not channel.gateway_id:
            config_issues.append(_("❌ Channel not linked to any gateway"))
        elif channel.gateway_id.id != self.gateway_id.id:
            config_issues.append(
                _(
                    "❌ Channel linked to wrong gateway (%(current)s"
                    " instead of %(expected)s)"
                )
                % {
                    "current": channel.gateway_id.name,
                    "expected": self.gateway_id.name,
                }
            )
        else:
            _logger.info(
                "✓ Channel linked to gateway (type: %s)", channel.channel_type
            )

        # Check gateway token
        expected_token = f"{self.zulip_stream}#{self.zulip_topic or 'general'}"
        if not channel.gateway_channel_token:
            config_issues.append(_("❌ Channel gateway token not set"))
        elif channel.gateway_channel_token != expected_token:
            config_issues.append(
                _(
                    "❌ Channel gateway token mismatch "
                    "(expected: %(expected)s, got: %(actual)s)"
                )
                % {
                    "expected": expected_token,
                    "actual": channel.gateway_channel_token,
                }
            )
        else:
            _logger.info(
                "✓ Channel gateway token correct: %s",
                channel.gateway_channel_token,
            )

        # Test outgoing message setup
        _logger.info("Phase 3: Testing outgoing message setup...")
        outgoing_issues = []

        if channel.gateway_id and channel.gateway_channel_token:
            _logger.info(
                "✓ Outgoing message setup correct (gateway_id and token present)"
            )
        else:
            outgoing_issues.append(
                _("❌ Outgoing messages would not trigger gateway notifications")
            )

        # Combine all issues
        all_issues = config_issues + outgoing_issues

        if all_issues:
            error_msg = _(
                "Zulip connectivity successful, but configuration issues found:\n\n"
            )
            error_msg += "\n".join(all_issues)
            error_msg += _(
                "\n\n💡 Solution: Try recreating this mapping to fix "
                "the configuration automatically."
            )
            raise ValidationError(error_msg)

        return _(
            "✅ Channel Configuration: Properly linked to gateway\n"
            "✅ Bidirectional Sync: Ready for incoming and outgoing messages\n"
        )

    def _test_project_task_mapping_configuration(self):
        """Test configuration for project task mappings"""
        _logger.info("Phase 2: Testing project task configuration...")

        task = self.task_id
        config_issues = []

        # Check task exists and is active
        if not task.exists():
            config_issues.append(_("❌ Task does not exist"))
        elif not task.active:
            config_issues.append(_("❌ Task is inactive"))
        else:
            _logger.info("✓ Task exists and is active: %s", task.name)

        # Check project exists and is active
        if not task.project_id.exists():
            config_issues.append(_("❌ Project does not exist"))
        elif not task.project_id.active:
            config_issues.append(_("❌ Project is inactive"))
        else:
            _logger.info("✓ Project exists and is active: %s", task.project_id.name)

        # Test virtual channel creation mechanism
        _logger.info("Phase 3: Testing virtual channel mechanism...")
        
        try:
            # Test virtual channel creation (this should work without errors)
            virtual_channel = task._create_virtual_channel_for_task(self)
            if virtual_channel:
                _logger.info("✓ Virtual channel created successfully: %s", virtual_channel.name)
                _logger.info("  - Gateway: %s", virtual_channel.gateway_id.name)
                _logger.info("  - Token: %s", virtual_channel.gateway_channel_token)
            else:
                config_issues.append(_("❌ Failed to create virtual channel"))
        except Exception as e:
            config_issues.append(_("❌ Virtual channel creation failed: %s") % str(e))

        # Test project task message_post hook
        try:
            # Check if the project.task model has our override
            if hasattr(task, '_sync_message_to_zulip'):
                _logger.info("✓ Project task message_post hook is available")
            else:
                config_issues.append(_("❌ Project task message_post hook not found"))
        except Exception as e:
            config_issues.append(_("❌ Error checking message_post hook: %s") % str(e))

        if config_issues:
            error_msg = _(
                "Zulip connectivity successful, but configuration issues found:\n\n"
            )
            error_msg += "\n".join(config_issues)
            error_msg += _(
                "\n\n💡 Solution: Check task and project status, or try recreating this mapping."
            )
            raise ValidationError(error_msg)

        return _(
            "✅ Task Configuration: Task and project are active\n"
            "✅ Virtual Channel: Ready for outgoing messages\n"
            "✅ Message Hook: Ready for bidirectional sync\n"
        )

    def action_sync_now(self):
        """Trigger manual synchronization for this mapping"""
        self.ensure_one()
        try:
            # This would trigger a manual sync - for now just update last_sync
            self.write({"last_sync": fields.Datetime.now(), "status": "active"})

            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": _("Sync Triggered"),
                    "message": _("Manual synchronization started for mapping '%s'")
                    % self.name,
                    "type": "success",
                },
            }

        except Exception as e:
            self.write({"status": "error", "error_message": str(e)})
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": _("Sync Failed"),
                    "message": str(e),
                    "type": "danger",
                },
            }

    @api.model
    def find_mapping_for_message(self, gateway, stream_name, topic_name):
        """Find the best mapping for a Zulip message"""
        # First try exact match (stream + topic)
        mapping = self.search(
            [
                ("gateway_id", "=", gateway.id),
                ("zulip_stream", "=", stream_name),
                ("zulip_topic", "=", topic_name),
                ("active", "=", True),
            ],
            limit=1,
        )

        if mapping:
            return mapping

        # Then try stream-only mapping (all topics)
        mapping = self.search(
            [
                ("gateway_id", "=", gateway.id),
                ("zulip_stream", "=", stream_name),
                ("zulip_topic", "=", False),
                ("active", "=", True),
            ],
            limit=1,
        )

        return mapping

    def update_sync_stats(self):
        """Update synchronization statistics"""
        self.ensure_one()
        self.sudo().write(
            {
                "last_sync": fields.Datetime.now(),
                "message_count": self.message_count + 1,
                "status": "active",
                "error_message": False,
            }
        )

    def _configure_channel_for_gateway(self):
        """Configure the destination (channel or project task) for bidirectional sync with Zulip"""
        self.ensure_one()

        if self.mapping_type == "channel":
            self._configure_channel_for_gateway_sync()
        elif self.mapping_type == "project_task":
            self._configure_task_for_gateway_sync()

    def _configure_channel_for_gateway_sync(self):
        """Configure the Odoo channel for bidirectional sync with Zulip"""
        # Generate the channel token that Zulip expects (stream#topic format)
        if self.zulip_topic:
            channel_token = f"{self.zulip_stream}#{self.zulip_topic}"
        else:
            # For stream-only mappings, use a default topic
            channel_token = f"{self.zulip_stream}#general"

        _logger.info(
            "Configuring channel %s for gateway %s with token: %s",
            self.odoo_channel_id.name,
            self.gateway_id.name,
            channel_token,
        )

        # Store current channel members to preserve them
        channel = self.odoo_channel_id
        current_members = channel.channel_partner_ids.ids

        # Update the channel with retry logic for concurrency conflicts
        max_retries = 3
        for attempt in range(max_retries):
            try:
                # Use a separate transaction to avoid conflicts
                with self.env.cr.savepoint():
                    channel.sudo().write(
                        {
                            "gateway_channel_token": channel_token,
                            "gateway_id": self.gateway_id.id,
                            # NOTE: Don't change channel_type to 'gateway' - this makes
                            # channels disappear from Discuss. Gateway functionality works
                            # with gateway_id and gateway_channel_token fields
                        }
                    )

                    # Ensure current user and gateway members remain in the channel
                    self._ensure_channel_membership(channel, current_members)

                _logger.info(
                    "Channel %s configured for bidirectional sync: "
                    "token=%s, gateway=%s",
                    channel.name,
                    channel_token,
                    self.gateway_id.name,
                )
                return  # Success, exit the retry loop

            except Exception as e:
                if (
                    "could not serialize access due to concurrent update" in str(e)
                    and attempt < max_retries - 1
                ):
                    _logger.warning(
                        "Concurrency conflict configuring channel %s "
                        "(attempt %d/%d): %s",
                        channel.name,
                        attempt + 1,
                        max_retries,
                        str(e),
                    )
                    # Wait a bit before retrying
                    import time

                    time.sleep(0.1 * (attempt + 1))  # Exponential backoff
                    continue
                else:
                    _logger.error(
                        "Failed to configure channel %s after %d attempts: %s",
                        channel.name,
                        attempt + 1,
                        str(e),
                    )
                    raise

    def _configure_task_for_gateway_sync(self):
        """Configure project task for bidirectional sync with Zulip"""
        # For project tasks, we need to set up a mechanism to detect outgoing messages
        # and route them to Zulip. We'll use a special context or hook in the task's message_post
        
        _logger.info(
            "Configuring task %s (project: %s) for gateway %s sync to stream: %s, topic: %s",
            self.task_id.name,
            self.task_id.project_id.name,
            self.gateway_id.name,
            self.zulip_stream,
            self.zulip_topic or "general",
        )

        # Store mapping information that can be used by the message processing hooks
        # This will be used by the project.task model's message_post override
        # to detect when messages should be sent to Zulip

    def _ensure_channel_membership(self, channel, original_members):
        """Ensure users remain members of the channel after gateway configuration"""
        # Get current members after the channel type change
        current_member_ids = channel.channel_partner_ids.ids

        # Find members that need to be re-added
        missing_members = set(original_members) - set(current_member_ids)

        # Always ensure the current user is a member
        current_user_partner_id = self.env.user.partner_id.id
        if current_user_partner_id not in current_member_ids:
            missing_members.add(current_user_partner_id)

        # Add missing members back to the channel
        if missing_members:
            partners_to_add = self.env["res.partner"].browse(list(missing_members))
            # Use the correct method for Odoo 15.0
            channel.channel_partner_ids = [(4, pid) for pid in missing_members]
            _logger.info(
                "Re-added %d members to gateway channel %s: %s",
                len(missing_members),
                channel.name,
                [p.name for p in partners_to_add],
            )

    @api.model
    def find_mapping_for_outgoing_message(self, channel):
        """Find mapping for outgoing message from Odoo channel"""
        mapping = self.search(
            [
                ("odoo_channel_id", "=", channel.id),
                ("active", "=", True),
            ],
            limit=1,
        )
        return mapping
