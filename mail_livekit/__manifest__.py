# -*- coding: utf-8 -*-
{
    "name": "Mail LiveKit Integration",
    "version": "15.0.1.0.0",
    "category": "Productivity/Discuss",
    "summary": "Replace Odoo WebRTC with LiveKit for video/voice calls",
    "readme": "README.rst",
    "author": "Nitrokey GmbH",
    "website": "https://www.nitrokey.com",
    "depends": ["mail", "base"],
    "data": [
        "security/ir.model.access.csv",
        "views/mail_livekit_server_views.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "mail_livekit/static/src/lib/livekit-client.umd.js",
            "mail_livekit/static/src/services/livekit_service.js",
            "mail_livekit/static/src/models/messaging_livekit.js",
            "mail_livekit/static/src/models/rtc_livekit.js",
            "mail_livekit/static/src/models/rtc_controller_livekit.js",
        ],
    },
    "external_dependencies": {
        "python": ["livekit-api", "PyJWT"],
    },
    "installable": True,
    "application": False,
    "auto_install": False,
    "license": "LGPL-3",
}
