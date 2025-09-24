# Copyright 2025 Nitrokey GmbH
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """Fix existing Zulip gateway channels to be visible in Discuss"""
    _logger.info("=== FIXING ZULIP GATEWAY CHANNEL VISIBILITY ===")
    
    # Find all channels created by Zulip gateways that have channel_type = 'gateway'
    cr.execute("""
        SELECT mc.id, mc.name, mc.gateway_channel_token, mg.name as gateway_name
        FROM mail_channel mc
        JOIN mail_gateway mg ON mc.gateway_id = mg.id
        WHERE mg.gateway_type = 'zulip'
        AND mc.channel_type = 'gateway'
        AND mc.gateway_channel_token IS NOT NULL
    """)
    
    channels_to_fix = cr.fetchall()
    
    if not channels_to_fix:
        _logger.info("No Zulip gateway channels found that need fixing")
        return
    
    _logger.info("Found %d Zulip gateway channels to fix", len(channels_to_fix))
    
    # Update channel_type from 'gateway' to 'channel' to make them visible in Discuss
    channel_ids = [str(channel[0]) for channel in channels_to_fix]
    
    cr.execute(f"""
        UPDATE mail_channel 
        SET channel_type = 'channel'
        WHERE id IN ({','.join(channel_ids)})
        AND channel_type = 'gateway'
    """)
    
    updated_count = cr.rowcount
    _logger.info("Updated %d Zulip gateway channels to be visible in Discuss", updated_count)
    
    # Log details of fixed channels
    for channel_id, channel_name, token, gateway_name in channels_to_fix:
        _logger.info("Fixed channel: %s (token: %s, gateway: %s)", 
                    channel_name, token, gateway_name)
    
    _logger.info("=== ZULIP GATEWAY CHANNEL VISIBILITY FIX COMPLETED ===")
