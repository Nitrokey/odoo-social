import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class MailChannel(models.Model):
    _inherit = "mail.channel"

    # LiveKit-specific fields
    livekit_room_name = fields.Char(
        "LiveKit Room Name", help="Name of the LiveKit room for this channel"
    )
    livekit_server_id = fields.Many2one(
        "mail.livekit.server",
        string="LiveKit Server",
        help="LiveKit server configuration for this channel",
    )

    @api.model_create_multi
    def create(self, vals_list):
        """Override create to initialize LiveKit room data"""
        channels = super().create(vals_list)

        # Initialize LiveKit room data for new channels
        for channel in channels:
            if not channel.livekit_room_name:
                channel.livekit_room_name = f"odoo_channel_{channel.id}"

            if not channel.livekit_server_id:
                # Get the default LiveKit server
                default_server = self.env["mail.livekit.server"].search(
                    [("active", "=", True)], limit=1
                )
                if default_server:
                    channel.livekit_server_id = default_server.id

        return channels

    def _rtc_cancel_invitations(self, partner_ids=None, guest_ids=None):
        """Override to handle LiveKit-specific invitation cancellation"""
        self.ensure_one()

        # Call parent method to maintain Odoo's invitation tracking
        result = super()._rtc_cancel_invitations(
            partner_ids=partner_ids, guest_ids=guest_ids
        )

        # LiveKit-specific logic: LiveKit handles invitations internally through room access tokens
        # We mainly need to ensure the access tokens are invalidated for uninvited participants
        if partner_ids or guest_ids:
            domain = [
                ("channel_id", "=", self.id),
                "|",
                ("partner_id", "in", partner_ids or []),
                ("guest_id", "in", guest_ids or []),
            ]
            sessions_to_update = self.env["mail.channel.rtc.session"].search(domain)
            # Clear access tokens for uninvited participants
            sessions_to_update.write({"livekit_access_token": False})

            _logger.info("Cancelled LiveKit invitations for channel %s", self.id)

        return result

    def channel_info(self):
        """Override to include LiveKit-specific information in channel info"""
        channel_infos = super().channel_info()

        # Add LiveKit-specific data to each channel info
        for i, channel_info in enumerate(channel_infos):
            channel = self.browse(channel_info["id"])
            if channel.livekit_server_id:
                channel_info.update(
                    {
                        "livekitServerUrl": channel.livekit_server_id.server_url,
                        "livekitRoomName": channel.livekit_room_name,
                        "livekitEnabled": True,
                    }
                )
            else:
                channel_info["livekitEnabled"] = False

        return channel_infos

    def _rtc_join_call(self, check_rtc_session_ids=None):
        """Override to handle LiveKit room joining"""
        self.ensure_one()

        # Ensure LiveKit room is configured
        if not self.livekit_room_name:
            self.livekit_room_name = f"odoo_channel_{self.id}"

        if not self.livekit_server_id:
            default_server = self.env["mail.livekit.server"].search(
                [("active", "=", True)], limit=1
            )
            if default_server:
                self.livekit_server_id = default_server.id
            else:
                _logger.error("No LiveKit server configured for channel %s", self.id)
                return {"error": "No LiveKit server configured"}

        # Call parent method if it exists (for compatibility)
        result = {}
        if hasattr(super(), "_rtc_join_call"):
            result = super()._rtc_join_call(check_rtc_session_ids=check_rtc_session_ids)

        # Only add LiveKit enabled flag - the actual LiveKit configuration data
        # will be provided through the session's _mail_rtc_session_format method
        result.update(
            {
                "livekit_enabled": True,
            }
        )

        _logger.info("Prepared LiveKit room join for channel %s", self.id)
        return result

    def _rtc_leave_call(self):
        """Override to handle LiveKit room leaving"""
        self.ensure_one()

        _logger.info("Handling LiveKit room leave for channel %s", self.id)

        # Call parent method if it exists (for compatibility)
        result = {}
        if hasattr(super(), "_rtc_leave_call"):
            result = super()._rtc_leave_call()

        return result

    def _get_rtc_session_values(self, partner_id=None, guest_id=None):
        """Helper method to get RTC session values with LiveKit data"""
        self.ensure_one()

        values = {
            "channel_id": self.id,
        }

        if partner_id:
            values["partner_id"] = partner_id
            values["livekit_participant_identity"] = f"partner_{partner_id}"
        elif guest_id:
            values["guest_id"] = guest_id
            values["livekit_participant_identity"] = f"guest_{guest_id}"

        values.update(
            {
                "livekit_room_name": self.livekit_room_name,
                "livekit_server_id": self.livekit_server_id.id
                if self.livekit_server_id
                else None,
            }
        )

        return values

    def _notify_thread(self, message, msg_vals=False, notify_by_email=True, **kwargs):
        """Override to handle LiveKit-specific notifications if needed"""
        # For now, just call parent method
        # Future enhancement: could add LiveKit-specific real-time notifications
        return super()._notify_thread(
            message, msg_vals=msg_vals, notify_by_email=notify_by_email, **kwargs
        )

    def write(self, vals):
        """Override to handle LiveKit room name changes"""
        result = super().write(vals)

        # If LiveKit room name is changed, update all active sessions
        if "livekit_room_name" in vals:
            for channel in self:
                active_sessions = channel.rtc_session_ids.filtered(
                    "livekit_access_token"
                )
                if active_sessions:
                    # Regenerate access tokens for the new room name
                    for session in active_sessions:
                        session._generate_livekit_access_token()
                    _logger.info(
                        "Updated LiveKit room name for channel %s to %s",
                        channel.id,
                        vals["livekit_room_name"],
                    )

        return result

    def get_livekit_room_info(self):
        """Public method to get LiveKit room information"""
        self.ensure_one()

        if not self.livekit_server_id:
            return {"error": "No LiveKit server configured"}

        return {
            "server_url": self.livekit_server_id.server_url,
            "room_name": self.livekit_room_name,
            "server_name": self.livekit_server_id.name,
        }

    def create_livekit_access_token(
        self, participant_identity, participant_name=None, permissions=None
    ):
        """Public method to create LiveKit access token for this channel"""
        self.ensure_one()

        if not self.livekit_server_id:
            _logger.error("No LiveKit server configured for channel %s", self.id)
            return None

        try:
            return self.livekit_server_id.generate_access_token(
                room_name=self.livekit_room_name,
                participant_identity=participant_identity,
                participant_name=participant_name,
                permissions=permissions,
            )
        except Exception as e:
            _logger.error(
                "Failed to create LiveKit access token for channel %s: %s",
                self.id,
                str(e),
            )
            return None
