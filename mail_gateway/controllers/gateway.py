# Copyright 2025 Nitrokey GmbH
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl).

import json
import logging

from odoo.http import Controller, request, route

_logger = logging.getLogger(__name__)


class GatewayController(Controller):
    @route(
        "/gateway/<string:usage>/<string:token>/update",
        type="http",
        auth="public",
        methods=["GET", "POST"],
        csrf=False,
    )
    def post_update_http(self, usage, token, *args, **kwargs):
        return self._handle_update(usage, token, *args, **kwargs)

    @route(
        "/gateway/<string:usage>/<string:token>/update/json",
        type="json",
        auth="public",
        methods=["POST"],
        csrf=False,
    )
    def post_update_json(self, usage, token, *args, **kwargs):
        return self._handle_update(usage, token, *args, **kwargs)

    def _handle_update(self, usage, token, *args, **kwargs):
        if request.httprequest.method == "GET":
            bot_data = request.env["mail.gateway"]._get_gateway(
                token, gateway_type=usage, state="pending"
            )
            if not bot_data:
                return request.make_response(
                    json.dumps({}),
                    [
                        ("Content-Type", "application/json"),
                    ],
                )
            return (
                request.env["mail.gateway.%s" % usage]
                .with_user(bot_data["webhook_user_id"])
                .with_company(bot_data["company_id"])
                ._receive_get_update(bot_data, request, **kwargs)
            )
        bot_data = request.env["mail.gateway"]._get_gateway(
            token, gateway_type=usage, state="integrated"
        )
        if not bot_data:
            _logger.warning(
                "Gateway was not found for token %s with usage %s", token, usage
            )
            return request.make_response(
                json.dumps({}),
                [
                    ("Content-Type", "application/json"),
                ],
            )
        # Parse webhook data from request
        webhook_data = self._parse_webhook_data()
        _logger.info("=== WEBHOOK DEBUG START ===")
        _logger.info("Token: %s, Usage: %s", token, usage)
        _logger.info(
            "Webhook data parsed: %s",
            json.dumps(webhook_data) if webhook_data else "EMPTY",
        )
        _logger.info("Bot data: %s", bot_data)

        dispatcher = (
            request.env["mail.gateway.%s" % usage]
            .with_user(bot_data["webhook_user_id"])
            .with_context(no_gateway_notification=True)
        )

        _logger.info("Dispatcher created: %s", dispatcher)

        # Test verification
        verification_result = dispatcher._verify_update(bot_data, webhook_data)
        _logger.info("Verification result: %s", verification_result)

        if not verification_result:
            _logger.warning(
                "Message could not be verified for token %s with usage %s", token, usage
            )
            _logger.info("=== WEBHOOK DEBUG END (VERIFICATION FAILED) ===")
            return self._make_response({})

        _logger.info("Verification passed, processing message...")
        gateway = dispatcher.env["mail.gateway"].browse(bot_data["id"])
        _logger.info("Gateway object: %s (ID: %s)", gateway.name, gateway.id)

        try:
            result = dispatcher._receive_update(gateway, webhook_data)
            _logger.info("Message processing result: %s", result)
        except Exception as e:
            _logger.error("Error in _receive_update: %s", str(e))
            _logger.error("Exception details:", exc_info=True)

        _logger.info("=== WEBHOOK DEBUG END (SUCCESS) ===")
        return self._make_response({})

    def _parse_webhook_data(self):
        """Parse webhook data from request, handling multiple formats"""
        # Handle JSON requests (from JSON route)
        if hasattr(request, "jsonrequest") and request.jsonrequest:
            return request.jsonrequest

        # Handle HTTP requests with JSON body
        try:
            raw_data = request.httprequest.get_data()
            if raw_data:
                return json.loads(
                    raw_data.decode(request.httprequest.charset or "utf-8")
                )
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            _logger.debug("Failed to parse JSON from request body: %s", str(e))

        # Handle form data
        form_data = dict(request.httprequest.form)
        if form_data:
            # Check for payload field (common webhook pattern)
            if "payload" in form_data:
                try:
                    return json.loads(form_data["payload"])
                except json.JSONDecodeError as e:
                    _logger.debug("Failed to parse JSON from payload field: %s", str(e))
            return form_data

        # Return empty dict if no data found
        return {}

    def _make_response(self, data):
        """Create appropriate response based on request type"""
        if hasattr(request, "jsonrequest") and request.jsonrequest:
            # JSON route - return data directly
            return data
        else:
            # HTTP route - return HTTP response
            return request.make_response(
                json.dumps(data),
                [
                    ("Content-Type", "application/json"),
                ],
            )
