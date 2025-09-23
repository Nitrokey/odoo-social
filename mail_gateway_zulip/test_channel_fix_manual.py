#!/usr/bin/env python3
"""
Manual test script to verify Zulip channel visibility fix.
Run this in Odoo shell: python odoo-bin shell -d your_database --addons-path=your_addons_path
Then: exec(open('mail_gateway_zulip/test_channel_fix_manual.py').read())
"""

import logging

_logger = logging.getLogger(__name__)

def test_channel_visibility_fix():
    """Test the Zulip channel visibility fix"""
    print("=== TESTING ZULIP CHANNEL VISIBILITY FIX ===")
    
    # Get environment
    env = globals().get('env')
    if not env:
        print("ERROR: This script must be run in Odoo shell")
        return False
    
    try:
        # 1. Test the _get_channel_vals method returns correct channel_type
        print("\n1. Testing _get_channel_vals method...")
        
        # Create a test gateway (or use existing one)
        gateway = env["mail.gateway"].search([("gateway_type", "=", "zulip")], limit=1)
        if not gateway:
            print("Creating test Zulip gateway...")
            gateway = env["mail.gateway"].create({
                "name": "Test Zulip Gateway",
                "gateway_type": "zulip",
                "token": "test_token_123",
                "zulip_server_url": "https://test.zulipchat.com",
                "zulip_bot_email": "bot@test.zulipchat.com",
                "zulip_api_key": "test_api_key_123",
            })
        
        # Get the Zulip service
        zulip_service = env["mail.gateway.zulip"]
        
        # Test channel values creation
        token = "general#test-topic"
        channel_vals = zulip_service._get_channel_vals(gateway, token, {})
        
        print(f"Channel values: {channel_vals}")
        
        # Check if channel_type is 'channel' (not 'gateway')
        if channel_vals.get("channel_type") == "channel":
            print("✅ PASS: New channels will have channel_type = 'channel'")
        else:
            print(f"❌ FAIL: Expected channel_type = 'channel', got {channel_vals.get('channel_type')}")
            return False
        
        # 2. Test existing gateway channels
        print("\n2. Checking existing Zulip gateway channels...")
        
        existing_channels = env["mail.channel"].search([
            ("gateway_id.gateway_type", "=", "zulip"),
            ("gateway_channel_token", "!=", False)
        ])
        
        print(f"Found {len(existing_channels)} existing Zulip gateway channels")
        
        gateway_type_channels = existing_channels.filtered(lambda c: c.channel_type == "gateway")
        channel_type_channels = existing_channels.filtered(lambda c: c.channel_type == "channel")
        
        print(f"  - {len(gateway_type_channels)} with channel_type = 'gateway' (INVISIBLE in Discuss)")
        print(f"  - {len(channel_type_channels)} with channel_type = 'channel' (VISIBLE in Discuss)")
        
        if gateway_type_channels:
            print("\n⚠️  Found channels that need fixing:")
            for channel in gateway_type_channels[:5]:  # Show first 5
                print(f"    - {channel.name} (token: {channel.gateway_channel_token})")
            if len(gateway_type_channels) > 5:
                print(f"    ... and {len(gateway_type_channels) - 5} more")
        
        # 3. Test the migration logic (simulation)
        print("\n3. Testing migration logic...")
        
        if gateway_type_channels:
            print("Simulating migration fix...")
            # Don't actually fix them, just show what would happen
            print(f"Migration would fix {len(gateway_type_channels)} channels")
            print("To actually fix them, run the module upgrade or execute:")
            print("UPDATE mail_channel SET channel_type = 'channel' WHERE gateway_id IN (SELECT id FROM mail_gateway WHERE gateway_type = 'zulip') AND channel_type = 'gateway';")
        else:
            print("✅ No channels need migration (all are already visible)")
        
        # 4. Test token parsing
        print("\n4. Testing token parsing...")
        
        test_cases = [
            ("general#announcements", ("general", "announcements")),
            ("development", ("development", "general")),
            ("support#urgent-issues", ("support", "urgent-issues"))
        ]
        
        for token, expected in test_cases:
            result = zulip_service._parse_channel_token(token)
            if result == expected:
                print(f"✅ PASS: {token} -> {result}")
            else:
                print(f"❌ FAIL: {token} -> {result}, expected {expected}")
                return False
        
        print("\n=== TEST SUMMARY ===")
        print("✅ Channel visibility fix is working correctly")
        print("✅ New channels will be visible in Discuss")
        
        if gateway_type_channels:
            print(f"⚠️  {len(gateway_type_channels)} existing channels need migration")
            print("   Run module upgrade to fix them automatically")
        else:
            print("✅ All existing channels are already visible")
        
        return True
        
    except Exception as e:
        print(f"❌ ERROR during testing: {str(e)}")
        import traceback
        traceback.print_exc()
        return False

# Run the test
if __name__ == "__main__":
    test_channel_visibility_fix()
else:
    # When executed in Odoo shell
    test_channel_visibility_fix()
