# Copyright 2025 Nitrokey GmbH
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from odoo import fields, models


class ZulipTestWizard(models.TransientModel):
    _name = "mail.gateway.zulip.test.wizard"
    _description = "Zulip Connection Test Results"

    gateway_id = fields.Many2one(
        "mail.gateway",
        string="Gateway",
        required=True,
        readonly=True,
    )
    test_results = fields.Text(
        readonly=True,
    )
    connection_successful = fields.Boolean(
        readonly=True,
    )

    def action_close(self):
        """Close the wizard"""
        return {"type": "ir.actions.act_window_close"}
