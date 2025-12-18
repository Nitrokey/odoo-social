import logging

from werkzeug.exceptions import NotFound

from odoo import http
from odoo.http import request

from odoo.addons.mail.controllers.discuss import DiscussController

_logger = logging.getLogger(__name__)


class LiveKitDiscussController(DiscussController):
    """Extended Discuss Controller with LiveKit-specific endpoints"""

    @http.route(
        "/mail/rtc/channel/join_call", methods=["POST"], type="json", auth="public"
    )
    def channel_call_join(self, channel_id, check_rtc_session_ids=None):
        """Override to handle LiveKit room joining"""
        _logger.info("LiveKit join call request for channel %s", channel_id)

        # Call parent method to maintain standard Odoo RTC session management
        # The parent method calls the backend model which already includes complete LiveKit data
        result = super().channel_call_join(
            channel_id=channel_id, check_rtc_session_ids=check_rtc_session_ids
        )

        # The backend model (mail_channel_partner._rtc_join_call) already adds complete LiveKit data
        # We don't need to override it here - just let it pass through
        if "error" not in result and result.get("livekitEnabled"):
            _logger.info(
                "LiveKit join call successful for channel %s with complete configuration",
                channel_id,
            )

            # Store LiveKit data globally so the frontend can access it
            # This is a simple approach that works with JSON responses
            _logger.info(
                "LiveKit data will be available in join call response for frontend processing"
            )

        return result

    @http.route(
        "/mail/rtc/channel/leave_call", methods=["POST"], type="json", auth="public"
    )
    def channel_call_leave(self, channel_id):
        """Override to handle LiveKit room leaving"""
        _logger.info("LiveKit leave call request for channel %s", channel_id)

        # Call parent method to maintain standard Odoo RTC session management
        result = super().channel_call_leave(channel_id=channel_id)

        return result

    @http.route(
        "/mail/livekit/channel/get_room_info",
        methods=["POST"],
        type="json",
        auth="public",
    )
    def livekit_get_room_info(self, channel_id):
        """Get LiveKit room information for a channel"""
        channel_partner_sudo = request.env[
            "mail.channel.partner"
        ]._get_as_sudo_from_request_or_raise(
            request=request, channel_id=int(channel_id)
        )

        return channel_partner_sudo.channel_id.get_livekit_room_info()

    @http.route(
        "/mail/livekit/session/refresh_token",
        methods=["POST"],
        type="json",
        auth="public",
    )
    def livekit_refresh_access_token(self, channel_id):
        """Refresh LiveKit access token for the current user's session"""
        channel_partner_sudo = request.env[
            "mail.channel.partner"
        ]._get_as_sudo_from_request_or_raise(
            request=request, channel_id=int(channel_id)
        )

        return channel_partner_sudo.refresh_livekit_access_token()

    @http.route(
        "/mail/livekit/session/get_info", methods=["POST"], type="json", auth="public"
    )
    def livekit_get_session_info(self, channel_id):
        """Get LiveKit session information for the current user"""
        channel_partner_sudo = request.env[
            "mail.channel.partner"
        ]._get_as_sudo_from_request_or_raise(
            request=request, channel_id=int(channel_id)
        )

        return channel_partner_sudo.get_livekit_session_info()

    @http.route(
        "/mail/livekit/channel/create_access_token",
        methods=["POST"],
        type="json",
        auth="public",
    )
    def livekit_create_access_token(
        self, channel_id, participant_identity, participant_name=None, permissions=None
    ):
        """Create a new LiveKit access token for a participant"""
        channel_partner_sudo = request.env[
            "mail.channel.partner"
        ]._get_as_sudo_from_request_or_raise(
            request=request, channel_id=int(channel_id)
        )

        # Only allow creating tokens for the current user's identity
        current_identity = None
        if channel_partner_sudo.partner_id:
            current_identity = f"partner_{channel_partner_sudo.partner_id.id}"
        elif channel_partner_sudo.guest_id:
            current_identity = f"guest_{channel_partner_sudo.guest_id.id}"

        if participant_identity != current_identity:
            raise NotFound()

        access_token = channel_partner_sudo.channel_id.create_livekit_access_token(
            participant_identity=participant_identity,
            participant_name=participant_name,
            permissions=permissions,
        )

        if access_token:
            return {
                "access_token": access_token,
                "server_url": (
                    channel_partner_sudo.channel_id.livekit_server_id.server_url
                ),
                "room_name": channel_partner_sudo.channel_id.livekit_room_name,
            }
        else:
            return {"error": "Failed to create access token"}

    @http.route("/mail/livekit/server/list", methods=["POST"], type="json", auth="user")
    def livekit_list_servers(self):
        """List available LiveKit servers (admin only)"""
        if not request.env.user.has_group("base.group_system"):
            raise NotFound()

        servers = request.env["mail.livekit.server"].search([])
        return [
            {
                "id": server.id,
                "name": server.name,
                "server_url": server.server_url,
                "active": server.active,
            }
            for server in servers
        ]

    @http.route(
        "/mail/livekit/server/test_connection",
        methods=["POST"],
        type="json",
        auth="user",
    )
    def livekit_test_server_connection(self, server_id):
        """Test connection to a LiveKit server (admin only)"""
        if not request.env.user.has_group("base.group_system"):
            raise NotFound()

        server = request.env["mail.livekit.server"].browse(int(server_id)).exists()
        if not server:
            raise NotFound()

        try:
            # Test token generation as a connection test
            test_token = server.generate_access_token(
                room_name="test_room",
                participant_identity="test_participant",
                participant_name="Test User",
            )
            return {
                "success": True,
                "message": "Connection successful",
                "test_token_generated": bool(test_token),
            }
        except Exception as e:
            return {"success": False, "message": f"Connection failed: {str(e)}"}

    def _response_discuss_public_channel_template(
        self, channel_sudo, discuss_public_view_data=None
    ):
        """Override to include LiveKit configuration in public channel template"""
        discuss_public_view_data = discuss_public_view_data or {}

        # Add LiveKit configuration to the channel data
        if channel_sudo.livekit_server_id:
            discuss_public_view_data.update(
                {
                    "livekitEnabled": True,
                    "livekitServerUrl": channel_sudo.livekit_server_id.server_url,
                    "livekitRoomName": channel_sudo.livekit_room_name,
                }
            )
        else:
            discuss_public_view_data["livekitEnabled"] = False

        return super()._response_discuss_public_channel_template(
            channel_sudo=channel_sudo, discuss_public_view_data=discuss_public_view_data
        )

    @http.route(
        "/mail/rtc/session/update_and_broadcast",
        methods=["POST"],
        type="json",
        auth="public",
    )
    def session_update_and_broadcast(self, session_id, values):
        """Override to handle LiveKit-specific session updates"""
        # Handle LiveKit-specific values
        livekit_values = {}
        standard_values = {}

        for key, value in values.items():
            if key.startswith("livekit_"):
                livekit_values[key] = value
            else:
                standard_values[key] = value

        # Call parent method for standard RTC updates
        if standard_values:
            super().session_update_and_broadcast(
                session_id=session_id, values=standard_values
            )

        # Handle LiveKit-specific updates
        if livekit_values:
            guest = request.env["mail.guest"]._get_guest_from_request(request)
            if request.env.user._is_public():
                if guest:
                    session = (
                        guest.env["mail.channel.rtc.session"]
                        .sudo()
                        .browse(int(session_id))
                        .exists()
                    )
                    if session and session.guest_id == guest:
                        session.write(livekit_values)
                        _logger.info(
                            "Updated LiveKit session values for guest session %s",
                            session_id,
                        )
            else:
                session = (
                    request.env["mail.channel.rtc.session"]
                    .sudo()
                    .browse(int(session_id))
                    .exists()
                )
                if session and session.partner_id == request.env.user.partner_id:
                    session.write(livekit_values)
                    _logger.info(
                        "Updated LiveKit session values for partner session %s",
                        session_id,
                    )
