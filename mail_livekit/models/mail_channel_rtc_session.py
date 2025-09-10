import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class MailChannelRtcSession(models.Model):
    _inherit = "mail.channel.rtc.session"

    # LiveKit-specific fields
    livekit_room_name = fields.Char(
        "LiveKit Room Name", help="Name of the LiveKit room"
    )
    livekit_participant_identity = fields.Char(
        "LiveKit Participant Identity",
        help="Unique identity for the participant in LiveKit",
    )
    livekit_access_token = fields.Text(
        "LiveKit Access Token", help="JWT token for accessing the LiveKit room"
    )
    livekit_server_id = fields.Many2one(
        "mail.livekit.server",
        string="LiveKit Server",
        help="LiveKit server configuration",
    )
    livekit_server_url = fields.Char(
        "LiveKit Server URL",
        compute="_compute_livekit_server_url",
        help="URL of the LiveKit server",
    )

    @api.model_create_multi
    def create(self, vals_list):
        """Override create to initialize LiveKit session data"""
        # Initialize LiveKit-specific data for each session
        for vals in vals_list:
            if not vals.get("livekit_server_id"):
                # Get the default LiveKit server
                all_servers = self.env["mail.livekit.server"].search([])
                default_server = self.env["mail.livekit.server"].search(
                    [("active", "=", True)], limit=1
                )

                _logger.info(
                    "Session creation: searching for LiveKit server, found %d total, %d active",
                    len(all_servers),
                    len(default_server),
                )

                if default_server:
                    vals["livekit_server_id"] = default_server.id
                    _logger.info(
                        "Session creation: assigned server %s (%s) to new session",
                        default_server.id,
                        default_server.name,
                    )

            # Generate LiveKit room name and participant identity if not provided
            if not vals.get("livekit_room_name") and vals.get("channel_partner_id"):
                channel_partner = self.env["mail.channel.partner"].browse(
                    vals["channel_partner_id"]
                )
                vals[
                    "livekit_room_name"
                ] = f"odoo_channel_{channel_partner.channel_id.id}"

            if not vals.get("livekit_participant_identity") and vals.get(
                "channel_partner_id"
            ):
                channel_partner = self.env["mail.channel.partner"].browse(
                    vals["channel_partner_id"]
                )
                if channel_partner.partner_id:
                    vals[
                        "livekit_participant_identity"
                    ] = f"partner_{channel_partner.partner_id.id}"
                elif channel_partner.guest_id:
                    vals[
                        "livekit_participant_identity"
                    ] = f"guest_{channel_partner.guest_id.id}"

        rtc_sessions = super().create(vals_list)

        # Generate LiveKit access tokens for new sessions only if server is configured
        for session in rtc_sessions:
            if session.livekit_server_id:
                session._generate_livekit_access_token()
            else:
                _logger.info(
                    "No LiveKit server configured for session %s, skipping token generation",
                    session.id,
                )

        return rtc_sessions

    @api.depends("livekit_server_id")
    def _compute_livekit_server_url(self):
        """Compute the LiveKit server URL from the server relation"""
        for session in self:
            session.livekit_server_url = (
                session.livekit_server_id.server_url
                if session.livekit_server_id
                else None
            )

    def _validate_session_data(self):
        """Validation helper for session creation"""
        self.ensure_one()
        if not self.id:
            raise ValueError("Session ID is required but not set")
        return True

    def _generate_livekit_access_token(self):
        """Generate LiveKit access token for the session"""
        self.ensure_one()
        if not self.livekit_server_id:
            _logger.warning("No LiveKit server configured for session %s", self.id)
            return

        if not self.livekit_room_name or not self.livekit_participant_identity:
            _logger.warning(
                "Missing room name or participant identity for session %s", self.id
            )
            return

        try:
            # Determine participant name
            participant_name = None
            if self.partner_id:
                participant_name = self.partner_id.name
            elif self.guest_id:
                participant_name = self.guest_id.name

            # Generate access token
            access_token = self.livekit_server_id.generate_access_token(
                room_name=self.livekit_room_name,
                participant_identity=self.livekit_participant_identity,
                participant_name=participant_name,
            )

            self.write({"livekit_access_token": access_token})
            _logger.info("Generated LiveKit access token for session %s", self.id)

        except Exception as e:
            _logger.error(
                "Failed to generate LiveKit access token for session %s: %s",
                self.id,
                str(e),
            )

    def _rtc_join_call(self):
        """Override to handle LiveKit room joining"""
        self.ensure_one()

        # Ensure we have a valid LiveKit access token
        if not self.livekit_access_token:
            self._generate_livekit_access_token()

        # Call parent method to maintain Odoo's session tracking
        result = super()._rtc_join_call() if hasattr(super(), "_rtc_join_call") else {}

        # Note: LiveKit-specific data is excluded from the result to prevent database field errors
        # The frontend gets all LiveKit configuration through the mail_channel_partner join call response

        _logger.info(
            "User %s joined LiveKit room %s",
            self.livekit_participant_identity,
            self.livekit_room_name,
        )
        return result

    def _rtc_leave_call(self):
        """Override to handle LiveKit room leaving"""
        self.ensure_one()

        _logger.info(
            "User %s leaving LiveKit room %s",
            self.livekit_participant_identity,
            self.livekit_room_name,
        )

        # Clear LiveKit access token on leave
        self.write({"livekit_access_token": False})

        # Call parent method to maintain Odoo's session tracking
        return super()._rtc_leave_call() if hasattr(super(), "_rtc_leave_call") else {}

    def action_disconnect(self):
        """Override to handle LiveKit disconnection"""
        _logger.info("Disconnecting LiveKit session %s", self.id)
        return super().action_disconnect()

    def _mail_rtc_session_format(self, complete_info=True):
        """Override to include LiveKit-specific data in session format"""
        vals = super()._mail_rtc_session_format(complete_info=complete_info)

        # Note: LiveKit-specific data is excluded from session format to prevent database field errors
        # The frontend gets LiveKit configuration through the join call response instead
        # All LiveKit fields (livekit_server_url, livekit_room_name, livekit_access_token, etc.)
        # are actual database fields and will be included automatically by the parent method

        return vals

    def _update_and_broadcast(self, values):
        """Override to handle LiveKit-specific state updates"""
        # Handle LiveKit-specific values
        livekit_values = {}
        if "livekit_access_token" in values:
            livekit_values["livekit_access_token"] = values.pop("livekit_access_token")

        # Update LiveKit-specific fields if present
        if livekit_values:
            self.write(livekit_values)

        # Call parent method for standard RTC state updates
        return super()._update_and_broadcast(values)

    @api.model
    def _inactive_rtc_session_domain(self):
        """Inherit the inactive session domain - LiveKit sessions use the same timeout logic"""
        return super()._inactive_rtc_session_domain()

    def _notify_peers(self, notifications):
        """Override to maintain peer-to-peer communication for LiveKit sessions"""
        # LiveKit handles most peer communication internally, but we maintain
        # Odoo's notification system for compatibility
        return super()._notify_peers(notifications)

    def refresh_livekit_token(self):
        """Public method to refresh LiveKit access token"""
        self.ensure_one()
        self._generate_livekit_access_token()
        return {
            "livekit_access_token": self.livekit_access_token,
            "livekit_server_url": self.livekit_server_id.server_url
            if self.livekit_server_id
            else None,
        }
