# Copyright 2024 Dixmit
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

{
    "name": "Mail Zulip Gateway",
    "summary": """
        Set a gateway for Zulip""",
    "version": "15.0.1.0.0",
    "license": "AGPL-3",
    "author": "Nitrokey, Odoo Community Association (OCA)",
    "website": "https://github.com/OCA/social",
    "depends": ["mail_gateway"],
    "data": ["views/mail_gateway.xml"],
    "external_dependencies": {"python": ["zulip"]},
    "assets": {
        "mail.assets_messaging": [
            "mail_gateway_zulip/static/src/models/**/*.js",
            "mail_gateway_zulip/static/src/components/**/*.xml",
        ],
    },
}
