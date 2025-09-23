{
    "name": "Mail Zulip Gateway",
    "summary": """
        Set a gateway for Zulip""",
    "version": "15.0.1.0.0",
    "license": "AGPL-3",
    "author": "Nitrokey, Odoo Community Association (OCA)",
    "website": "https://github.com/OCA/social",
    "depends": ["mail_gateway"],
    "data": [
        "security/ir.model.access.csv",
        "data/cron.xml",
        "views/mail_gateway.xml",
        "views/zulip_channel_mapping.xml",
        "views/zulip_test_wizard_views.xml",
    ],
    "external_dependencies": {"python": ["zulip", "html2text"]},
    "assets": {
        "web.assets_backend": [
            "mail_gateway_zulip/static/src/css/zulip_quotes.css",
        ],
        "mail.assets_messaging": [
            "mail_gateway_zulip/static/src/models/**/*.js",
            "mail_gateway_zulip/static/src/components/**/*.xml",
            "mail_gateway_zulip/static/src/css/zulip_quotes.css",
        ],
    },
}
