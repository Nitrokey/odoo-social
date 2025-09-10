import time

try:
    import jwt
except ImportError:
    # PyJWT package provides the jwt module
    import PyJWT as jwt

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class MailLiveKitServer(models.Model):
    _name = "mail.livekit.server"
    _description = "LiveKit Server Configuration"
    _rec_name = "name"

    name = fields.Char("Name", required=True, default="LiveKit Server")
    server_url = fields.Char(
        "Server URL",
        required=True,
        help="LiveKit server URL (e.g., wss://your-livekit-server.com)",
    )
    api_key = fields.Char("API Key", required=True, help="LiveKit API key")
    api_secret = fields.Char("API Secret", required=True, help="LiveKit API secret")
    active = fields.Boolean("Active", default=True)

    @api.constrains("server_url")
    def _check_server_url(self):
        for record in self:
            if record.server_url and not (
                record.server_url.startswith("ws://")
                or record.server_url.startswith("wss://")
            ):
                raise ValidationError(_("Server URL must start with ws:// or wss://"))

    def generate_access_token(
        self, room_name, participant_identity, participant_name=None, permissions=None
    ):
        """Generate LiveKit access token for a participant to join a room"""
        self.ensure_one()

        if not permissions:
            permissions = {
                "canPublish": True,
                "canSubscribe": True,
                "canPublishData": True,
            }

        # Token payload
        now = int(time.time())
        payload = {
            "iss": self.api_key,
            "sub": participant_identity,
            "iat": now,
            "exp": now + 3600,  # Token expires in 1 hour
            "video": {
                "room": room_name,
                "roomJoin": True,
                "canPublish": permissions.get("canPublish", True),
                "canSubscribe": permissions.get("canSubscribe", True),
                "canPublishData": permissions.get("canPublishData", True),
            },
        }

        if participant_name:
            payload["name"] = participant_name

        # Generate JWT token
        token = jwt.encode(payload, self.api_secret, algorithm="HS256")
        return token

    @api.model
    def get_default_server(self):
        """Get the default active LiveKit server"""
        server = self.search([("active", "=", True)], limit=1)
        if not server:
            raise ValidationError(
                _(
                    "No active LiveKit server configured. Please configure a LiveKit server first."
                )
            )
        return server

    @api.model
    def _get_default_server(self):
        """Helper to get or create default server configuration (returns None if none configured)"""
        return self.search([("active", "=", True)], limit=1)

    def test_connection(self):
        """Test connection to LiveKit server"""
        self.ensure_one()

        try:
            # Test 1: Validate URL format
            if not self.server_url:
                raise ValidationError(_("Server URL is required"))

            if not (
                self.server_url.startswith("ws://")
                or self.server_url.startswith("wss://")
            ):
                raise ValidationError(_("Server URL must start with ws:// or wss://"))

            # Test 2: Validate API credentials
            if not self.api_key:
                raise ValidationError(_("API Key is required"))

            if not self.api_secret:
                raise ValidationError(_("API Secret is required"))

            # Test 3: Test token generation
            try:
                test_token = self.generate_access_token(
                    room_name="test_room",
                    participant_identity="test_participant",
                    participant_name="Test User",
                )
                if not test_token:
                    raise ValidationError(_("Failed to generate access token"))
            except Exception as e:
                raise ValidationError(_("Token generation failed: %s") % str(e))

            # Test 4: Basic URL accessibility (optional - requires requests)
            import ssl
            import urllib.error
            import urllib.request

            try:
                # Convert WebSocket URL to HTTP for basic connectivity test
                test_url = self.server_url.replace("ws://", "http://").replace(
                    "wss://", "https://"
                )

                # Create SSL context that doesn't verify certificates (for testing)
                ssl_context = ssl.create_default_context()
                ssl_context.check_hostname = False
                ssl_context.verify_mode = ssl.CERT_NONE

                # Test basic connectivity with timeout
                req = urllib.request.Request(
                    test_url, headers={"User-Agent": "Odoo-LiveKit-Test"}
                )

                try:
                    with urllib.request.urlopen(req, timeout=10, context=ssl_context):
                        # Any response (even 404) means the server is reachable
                        pass
                except urllib.error.HTTPError as e:
                    # HTTP errors are fine - it means the server is reachable
                    if e.code in [
                        404,
                        405,
                        403,
                    ]:  # Common responses from LiveKit servers
                        pass
                    else:
                        raise

            except Exception as url_error:
                # URL test failed, but this is not critical
                return {
                    "type": "ir.actions.client",
                    "tag": "display_notification",
                    "params": {
                        "title": _("Connection Test - Partial Success"),
                        "message": _(
                            "Configuration is valid and token generation works, "
                            "but server URL may not be accessible: %s"
                        )
                        % str(url_error),
                        "type": "warning",
                    },
                }

            # All tests passed
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": _("Connection Test - Success"),
                    "message": _(
                        "LiveKit server configuration is valid. URL is accessible "
                        "and token generation works correctly."
                    ),
                    "type": "success",
                },
            }

        except ValidationError as e:
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": _("Connection Test - Failed"),
                    "message": str(e),
                    "type": "danger",
                },
            }
        except Exception as e:
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": _("Connection Test - Error"),
                    "message": _("Unexpected error during test: %s") % str(e),
                    "type": "danger",
                },
            }
