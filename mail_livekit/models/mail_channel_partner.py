import logging

from odoo import models

_logger = logging.getLogger(__name__)


class MailChannelPartner(models.Model):
    _inherit = "mail.channel.partner"

    def _rtc_join_call(self, check_rtc_session_ids=None):
        """Override to handle LiveKit room joining"""
        self.ensure_one()

        _logger.info(
            "Partner %s joining LiveKit call in channel %s",
            self.partner_id.name if self.partner_id else self.guest_id.name,
            self.channel_id.id,
        )

        # Ensure channel has LiveKit configuration
        if not self.channel_id.livekit_room_name:
            self.channel_id.livekit_room_name = f"odoo_channel_{self.channel_id.id}"

        # Require LiveKit server configuration - no WebRTC fallback for testing
        if not self.channel_id.livekit_server_id:
            # Debug: Check what servers exist
            all_servers = self.env["mail.livekit.server"].search([])
            active_servers = self.env["mail.livekit.server"].search(
                [("active", "=", True)], limit=1
            )

            _logger.info(
                "LiveKit server search for channel %s: found %d total servers, %d active servers",
                self.channel_id.id,
                len(all_servers),
                len(active_servers),
            )

            if all_servers:
                for server in all_servers:
                    _logger.info(
                        "LiveKit server found: ID=%s, Name='%s', Active=%s, URL='%s'",
                        server.id,
                        server.name,
                        server.active,
                        server.server_url,
                    )

            if active_servers:
                default_server = active_servers[0]
                self.channel_id.livekit_server_id = default_server.id
                _logger.info(
                    "Assigned LiveKit server %s (%s) to channel %s",
                    default_server.id,
                    default_server.name,
                    self.channel_id.id,
                )
            else:
                _logger.info(
                    "No active LiveKit server found for channel %s - falling back to WebRTC",
                    self.channel_id.id,
                )
                # Fall back to standard WebRTC
                return super()._rtc_join_call(
                    check_rtc_session_ids=check_rtc_session_ids
                )
        else:
            _logger.info(
                "Channel %s already has LiveKit server %s assigned",
                self.channel_id.id,
                self.channel_id.livekit_server_id.id,
            )

        # Call parent method to maintain Odoo's RTC session management
        result = super()._rtc_join_call(check_rtc_session_ids=check_rtc_session_ids)

        # Ensure we have a valid session ID in the result
        if "error" not in result and result.get("sessionId"):
            # Get the newly created RTC session
            rtc_session = self.rtc_session_ids.filtered(
                lambda s: s.id == result.get("sessionId")
            )

            if rtc_session:
                # Add LiveKit-specific data to the result
                result.update(
                    {
                        "livekitEnabled": True,
                        "livekitServerUrl": self.channel_id.livekit_server_id.server_url,
                        "livekitRoomName": self.channel_id.livekit_room_name,
                        "livekitAccessToken": rtc_session.livekit_access_token,
                        "livekitParticipantIdentity": rtc_session.livekit_participant_identity,
                    }
                )

                # Remove WebRTC-specific iceServers since we're using LiveKit
                if "iceServers" in result:
                    del result["iceServers"]

                _logger.info(
                    "Successfully prepared LiveKit join for participant %s in room %s",
                    rtc_session.livekit_participant_identity,
                    self.channel_id.livekit_room_name,
                )
            else:
                _logger.error(
                    "Failed to create RTC session for channel %s", self.channel_id.id
                )
                result = {"error": "Failed to create RTC session"}
        elif "error" not in result:
            # If no sessionId in result, this is an error condition
            _logger.error(
                "RTC session creation failed - no session ID returned for channel %s",
                self.channel_id.id,
            )
            result = {"error": "Failed to create RTC session"}

        return result

    def _rtc_leave_call(self):
        """Override to handle LiveKit room leaving"""
        self.ensure_one()

        _logger.info(
            "Partner %s leaving LiveKit call in channel %s",
            self.partner_id.name if self.partner_id else self.guest_id.name,
            self.channel_id.id,
        )

        # Call parent method to maintain Odoo's RTC session management
        result = super()._rtc_leave_call()

        return result

    def _rtc_sync_sessions(self, check_rtc_session_ids=None):
        """Override to handle LiveKit session synchronization"""
        self.ensure_one()

        # Call parent method for standard session sync
        current_rtc_sessions, outdated_rtc_sessions = super()._rtc_sync_sessions(
            check_rtc_session_ids=check_rtc_session_ids
        )

        # LiveKit-specific session validation
        # Ensure all current sessions have valid LiveKit access tokens
        for session in current_rtc_sessions:
            if not session.livekit_access_token:
                session._generate_livekit_access_token()

        return current_rtc_sessions, outdated_rtc_sessions

    def _rtc_invite_members(self, partner_ids=None, guest_ids=None):
        """Override to handle LiveKit-specific invitations"""
        self.ensure_one()

        _logger.info(
            "Inviting members to LiveKit call in channel %s", self.channel_id.id
        )

        # Call parent method to maintain Odoo's invitation system
        invited_partners, invited_guests = super()._rtc_invite_members(
            partner_ids=partner_ids, guest_ids=guest_ids
        )

        # LiveKit-specific invitation logic
        # In LiveKit, invitations are handled through access tokens
        # The actual invitation mechanism is managed by the parent method
        # We just need to ensure that when invited members join, they get proper LiveKit tokens

        if invited_partners or invited_guests:
            _logger.info(
                "Invited %d partners and %d guests to LiveKit room %s",
                len(invited_partners),
                len(invited_guests),
                self.channel_id.livekit_room_name,
            )

        return invited_partners, invited_guests

    def get_livekit_session_info(self):
        """Get LiveKit session information for this channel partner"""
        self.ensure_one()

        if not self.rtc_session_ids:
            return {"error": "No active RTC session"}

        session = self.rtc_session_ids[0]  # Get the first (should be only one) session

        return {
            "server_url": session.livekit_server_id.server_url
            if session.livekit_server_id
            else None,
            "room_name": session.livekit_room_name,
            "access_token": session.livekit_access_token,
            "participant_identity": session.livekit_participant_identity,
            "session_id": session.id,
        }

    def refresh_livekit_access_token(self):
        """Refresh LiveKit access token for active sessions"""
        self.ensure_one()

        if not self.rtc_session_ids:
            return {"error": "No active RTC session"}

        results = []
        for session in self.rtc_session_ids:
            result = session.refresh_livekit_token()
            results.append(result)

        return results[0] if len(results) == 1 else results

    def _get_livekit_participant_permissions(self):
        """Get LiveKit participant permissions based on channel and user context"""
        self.ensure_one()

        # Default permissions for channel participants
        permissions = {
            "canPublish": True,
            "canSubscribe": True,
            "canPublishData": True,
        }

        # Customize permissions based on channel type or user role
        if self.channel_id.channel_type == "chat":
            # In direct chats, both participants have full permissions
            permissions.update(
                {
                    "canPublish": True,
                    "canSubscribe": True,
                    "canPublishData": True,
                }
            )
        elif self.channel_id.channel_type == "channel":
            # In channels, permissions might be more restricted
            # This could be extended based on user roles or channel settings
            pass

        return permissions

    def _create_livekit_session_values(self):
        """Helper method to create session values with LiveKit data"""
        self.ensure_one()

        values = {
            "channel_partner_id": self.id,
            "livekit_room_name": self.channel_id.livekit_room_name,
            "livekit_server_id": self.channel_id.livekit_server_id.id
            if self.channel_id.livekit_server_id
            else None,
        }

        if self.partner_id:
            values["livekit_participant_identity"] = f"partner_{self.partner_id.id}"
        elif self.guest_id:
            values["livekit_participant_identity"] = f"guest_{self.guest_id.id}"

        return values
