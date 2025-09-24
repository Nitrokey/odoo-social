# Copyright 2025 Nitrokey GmbH
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).
from odoo import api, fields, models, tools


class MailGateway(models.Model):
    _name = "mail.gateway"
    _description = "Mail Gateway"

    name = fields.Char(
        required=True,
        help="Descriptive name for this gateway (e.g., 'Company Zulip', "
        "'Development Team Chat')",
    )
    token = fields.Char(
        required=True,
        help="Internal Odoo identifier for this gateway. Use any unique value "
        "(e.g., 'zulip-gateway-1'). This is not a secret and is different "
        "from API keys.",
    )
    gateway_type = fields.Selection(
        [],
        required=True,
        default=False,
        help="Type of messaging platform this gateway connects to "
        "(Zulip, Telegram, etc.)",
    )
    webhook_key = fields.Char(
        help="Unique identifier used in the webhook URL. Generate a secure "
        "random string (32-64 characters). This becomes part of the URL that "
        "the external platform calls: /gateway/{type}/{webhook_key}/update"
    )
    webhook_secret = fields.Char(
        help="Optional security token to verify webhook authenticity. Highly "
        "recommended for production. Generate a secure random string and "
        "configure it in your external platform's webhook settings to "
        "prevent unauthorized webhook calls."
    )
    integrated_webhook_state = fields.Selection(
        [("pending", "Pending"), ("integrated", "Integrated")],
        readonly=True,
        help="Current webhook integration status. 'Pending' means webhook is "
        "configured but not yet active. 'Integrated' means webhook is active "
        "and receiving messages.",
    )
    can_set_webhook = fields.Boolean(
        compute="_compute_webhook_checks",
        help="Indicates whether the webhook can be activated. Requires both "
        "webhook key and webhook user to be configured.",
    )
    webhook_url = fields.Char(
        compute="_compute_webhook_url",
        help="Complete webhook URL that should be configured in your external "
        "platform. Copy this URL to your platform's webhook settings.",
    )
    has_new_channel_security = fields.Boolean(
        help="When enabled, prevents automatic creation of new channels. "
        "Messages from unknown streams/topics will be ignored instead of "
        "creating new channels. Useful for controlling which content appears "
        "in Odoo."
    )
    webhook_user_id = fields.Many2one(
        "res.users",
        default=lambda self: self.env.ref("base.user_root"),
        help="Odoo user account that will be used to create messages received "
        "from the external platform. This user's permissions determine what "
        "actions can be performed.",
    )
    member_ids = fields.Many2many(
        "res.users",
        help="Odoo users who have access to channels created by this gateway. "
        "Only these users will see and can participate in gateway channels.",
    )
    company_id = fields.Many2one(
        "res.company",
        default=lambda self: self.env.company.id,
        help="Company this gateway belongs to. In multi-company setups, "
        "determines which company's channels and users can access this "
        "gateway.",
    )

    _sql_constraints = [
        ("mail_gateway_token", "unique(token)", "Token must be unique"),
        (
            "mail_gateway_webhook_key",
            "unique(webhook_key)",
            "Webhook Key must be unique",
        ),
    ]

    @api.depends("webhook_key")
    def _compute_webhook_url(self):
        for record in self:
            record.webhook_url = record._get_webhook_url()

    def _get_channel_id(self, chat_token):
        return (
            self.env["mail.channel"]
            .search(
                [
                    ("gateway_channel_token", "=", str(chat_token)),
                    ("gateway_id", "=", self.id),
                ],
                limit=1,
            )
            .id
        )

    def _get_webhook_url(self):
        return "%s/gateway/%s/%s/update" % (
            self.webhook_url
            or self.env["ir.config_parameter"].get_param("web.base.url"),
            self.gateway_type,
            self.webhook_key,
        )

    def _can_set_webhook(self):
        return self.webhook_key and self.webhook_user_id

    @api.depends("gateway_type")
    def _compute_webhook_checks(self):
        for record in self:
            record.can_set_webhook = record._can_set_webhook()

    def set_webhook(self):
        self.ensure_one()
        if self.can_set_webhook:
            self.env["mail.gateway.%s" % self.gateway_type]._set_webhook(self)

    def remove_webhook(self):
        self.ensure_one()
        self.env["mail.gateway.%s" % self.gateway_type]._remove_webhook(self)

    def update_webhook(self):
        self.ensure_one()
        self.remove_webhook()
        self.set_webhook()

    def write(self, vals):
        res = super(MailGateway, self).write(vals)
        if (
            "webhook_key" in vals
            or "integrated_webhook_state" in vals
            or "webhook_secret" in vals
            or "webhook_user_id" in vals
        ):
            self.clear_caches()

        # Update user-gateway associations when members change
        if "member_ids" in vals:
            self._update_user_gateway_associations()

        return res

    def _update_user_gateway_associations(self):
        """Update the gateway_ids field on users when gateway members change"""
        for gateway in self:
            # Add this gateway to all member users
            for user in gateway.member_ids:
                if gateway not in user.gateway_ids:
                    user.gateway_ids = [(4, gateway.id)]

            # Remove this gateway from users who are no longer members
            all_users_with_gateway = self.env["res.users"].search(
                [("gateway_ids", "in", gateway.id)]
            )
            users_to_remove = all_users_with_gateway - gateway.member_ids
            for user in users_to_remove:
                user.gateway_ids = [(3, gateway.id)]

    @api.model_create_multi
    def create(self, mvals):
        res = super(MailGateway, self).create(mvals)
        self.clear_caches()
        # Update user-gateway associations for new gateways
        res._update_user_gateway_associations()
        return res

    @api.model
    @tools.ormcache()
    def _get_gateway_map(self, state="integrated", gateway_type=False):
        result = {}
        for record in self.sudo().search(
            [
                ("integrated_webhook_state", "=", state),
                ("gateway_type", "=", gateway_type),
            ]
        ):
            result[record.webhook_key] = record._get_gateway_data()
        return result

    def _get_gateway_data(self):
        return {
            "id": self.id,
            "company_id": self.company_id.id,
            "webhook_secret": self.webhook_secret,
            "webhook_user_id": self.webhook_user_id.id,
        }

    @api.model
    def _get_gateway(self, key, state="integrated", gateway_type=False):
        # We are using cache in order to avoid an exploit
        if not key:
            return False
        return self._get_gateway_map(state=state, gateway_type=gateway_type).get(
            key, False
        )

    def gateway_info(self):
        return [record._gateway_info() for record in self]

    def _gateway_info(self):
        return {
            "id": self.id,
            "name": self.name,
            "type": self.gateway_type,
        }
