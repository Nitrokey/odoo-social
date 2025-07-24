# Testing the Zulip Gateway Integration

This guide explains how to test the Odoo-Zulip integration.

## Prerequisites

1. **Install Dependencies**: Ensure the `zulip` Python package is installed
2. **Module Installation**: Install both `mail_gateway` and `mail_gateway_zulip` modules
3. **Zulip Setup**: Have a Zulip organization with bot credentials ready

## Step-by-Step Testing Process

### Phase 1: Basic Configuration Test

1. **Create Gateway Record**:

   - Go to Settings → Technical → Email → Gateway
   - Create new gateway with type "Zulip"
   - Fill in all required fields:
     - **Name**: "Test Zulip Gateway"
     - **Token**: "zulip-test-001" (any unique value)
     - **Gateway Type**: "Zulip"
     - **Webhook Key**: Generate random string (e.g., "webhook-test-123")
     - **Webhook Secret**: Generate random string (optional but recommended)
     - **Zulip Server URL**: Your Zulip URL (e.g., "https://your-org.zulipchat.com")
     - **Bot Email**: Your Zulip bot email
     - **API Key**: Your Zulip bot API key
   - Add yourself to Members
   - Save the record

2. **Test API Connection**:
   - Click "Integrate Webhook" button
   - Check if status changes to "Integrated"
   - Look for success/error messages in Odoo logs

### Phase 2: Manual Test Channel Creation

Since gateway channels are normally created automatically, for testing you can create
them manually using the Odoo shell or through database operations.

#### Method 1: Using Odoo Shell (Updated for 15.0)

```python
# Access Odoo shell
# python odoo-bin shell -d your_database

# Get your gateway
gateway = env['mail.gateway'].search([('gateway_type', '=', 'zulip')], limit=1)

# Create a test channel manually with proper Odoo 15.0 structure
from odoo import Command

test_channel = env['mail.channel'].create({
    'name': 'Zulip: general / test-topic',
    'channel_type': 'gateway',
    'gateway_id': gateway.id,
    'gateway_channel_token': 'general#test-topic',  # Format: stream#topic
    'company_id': gateway.company_id.id,
    'channel_last_seen_partner_ids': [
        Command.create({
            'partner_id': partner.id,
            'is_pinned': True,
        }) for partner in gateway.member_ids.partner_id
    ]
})

print(f"Created test channel: {test_channel.name} (ID: {test_channel.id})")

# Ensure you're a member
your_membership = env['mail.channel.partner'].search([
    ('channel_id', '=', test_channel.id),
    ('partner_id', '=', env.user.partner_id.id)
])
if not your_membership:
    env['mail.channel.partner'].create({
        'channel_id': test_channel.id,
        'partner_id': env.user.partner_id.id,
        'is_pinned': True,
    })
    print("Added yourself as channel member")

# Update user gateway associations
gateway._update_user_gateway_associations()
```

#### Method 2: Using the Gateway's Helper Method

```python
# In Odoo shell
gateway = env['mail.gateway'].search([('gateway_type', '=', 'zulip')], limit=1)
zulip_service = env['mail.gateway.zulip']

# Simulate creating a channel as if a message arrived
fake_update = {}  # Empty update object for testing
channel = zulip_service._get_channel(gateway, 'general#test-topic', fake_update, force_create=True)

print(f"Created channel: {channel.name}")
```

### Phase 3: Outbound Testing (Odoo → Zulip)

1. **Send Test Message**:

   - Go to Discuss app
   - Find your test channel (should appear in the channel list)
   - Post a message in the channel
   - Check if it appears in the corresponding Zulip stream/topic
   - Verify message content and formatting

2. **Check Logs**:
   - Monitor Odoo logs for any errors during message sending
   - Look for success messages indicating the message was sent to Zulip

### Phase 4: Testing Different Scenarios

1. **Filter Testing**:

   - Set stream filter to specific streams (e.g., "general, test")
   - Set topic filter to specific topics (e.g., "urgent, test-topic")
   - Test that filtering works as expected

2. **User Mapping**:

   - Test with different Zulip users
   - Verify that existing Odoo users are matched by email
   - Verify that unknown users are created as guests

3. **Channel Security**:
   - Enable "Has New Channel Security" in gateway settings
   - Test that new channels aren't auto-created when this is enabled

## Debugging Tips

1. **Check Odoo Logs**: Monitor for error messages during testing
2. **Verify Zulip Bot Permissions**: Ensure the bot can access the streams you're
   testing
3. **Network Connectivity**: Verify Odoo can reach your Zulip server
4. **Field Validation**: Double-check all configuration fields are correct

## Common Test Scenarios

### Test 1: Basic Message Flow

- Create test channel for "general#test"
- Send message from Odoo
- Verify it appears in Zulip's general stream, test topic

### Test 2: Stream Filtering

- Set stream filter to "general"
- Create channels for both "general#test" and "random#test"
- Only the general channel should work

### Test 3: User Creation

- Send message from Zulip user not in Odoo
- Verify guest user is created in Odoo
- Check that the guest has correct name and email

## Events API Testing (Auto-sync)

### Phase 5: Events API Configuration

1. **Enable Auto-sync**:

   - In gateway settings, check "Auto-sync Messages"
   - Save the gateway
   - This should automatically start the long-polling listener

2. **Check Listener Status**:

   - Look at "Event Listener Active" field
   - If it shows a grey box (unchecked), the listener isn't running
   - Use "Start Listener" button to manually start it

3. **Manual Listener Control**:
   - **Start Listener**: Click green "Start Listener" button
   - **Stop Listener**: Click orange "Stop Listener" button
   - **Test Connection**: Click "Test Connection" for diagnostics

### Phase 6: Message Sync Testing

1. **Send Test Message in Zulip**:

   - Go to your Zulip organization
   - Send a message in a monitored stream/topic
   - Message should appear in Odoo within 1-2 minutes (cron backup) or < 1 second
     (real-time listener)

2. **Check Recent Messages in Odoo Shell**:

```python
# Access Odoo shell
# python odoo-bin shell -d your_database

# Find your Zulip gateway
gateway = env['mail.gateway'].search([('gateway_type', '=', 'zulip')], limit=1)
print(f"Gateway: {gateway.name}")

# Check gateway channels
channels = env['mail.channel'].search([('gateway_id', '=', gateway.id)])
print(f"Found {len(channels)} Zulip channels:")
for channel in channels:
    print(f"  - {channel.name} (token: {channel.gateway_channel_token})")

# Check recent messages in all Zulip channels
print("\n=== RECENT MESSAGES ===")
recent_messages = env['mail.message'].search([
    ('res_id', 'in', channels.ids),
    ('model', '=', 'mail.channel'),
    ('gateway_type', '=', 'zulip')
], order='create_date desc', limit=10)

for msg in recent_messages:
    channel = env['mail.channel'].browse(msg.res_id)
    print(f"[{msg.create_date}] {channel.name}: {msg.body[:100]}...")
    print(f"  Author: {msg.author_id.name if msg.author_id else 'System'}")
    print(f"  Gateway Message ID: {msg.gateway_notification_ids.mapped('gateway_message_id')}")
    print()

# Check if any messages were received in the last hour
from datetime import datetime, timedelta
one_hour_ago = datetime.now() - timedelta(hours=1)
recent_count = env['mail.message'].search_count([
    ('res_id', 'in', channels.ids),
    ('model', '=', 'mail.channel'),
    ('gateway_type', '=', 'zulip'),
    ('create_date', '>=', one_hour_ago)
])
print(f"Messages received in last hour: {recent_count}")

# Check gateway status
print(f"\n=== GATEWAY STATUS ===")
print(f"Auto-sync enabled: {gateway.zulip_auto_sync}")
print(f"Listener active: {gateway.zulip_listener_active}")
print(f"Queue ID: {gateway.zulip_queue_id}")
print(f"Last Event ID: {gateway.zulip_last_event_id}")
```

3. **Check Cron Job Status**:

```python
# Check if the cron job is active
cron_job = env['ir.cron'].search([('name', '=', 'Zulip Events Polling')])
print(f"Cron job active: {cron_job.active}")
print(f"Next run: {cron_job.nextcall}")
print(f"Last run: {cron_job.lastcall}")

# Manually trigger the cron job for testing
if cron_job:
    cron_job.method_direct_trigger()
    print("Cron job triggered manually")
```

4. **Test Events API Directly**:

```python
# Test the Events API connection directly
zulip_service = env['mail.gateway.zulip']

# Run connection test
success = zulip_service.test_zulip_connection(gateway)
print(f"Connection test: {'PASSED' if success else 'FAILED'}")

# Run manual poll test
poll_success = zulip_service.manual_poll_test(gateway)
print(f"Poll test: {'PASSED' if poll_success else 'FAILED'}")

# Start auto-sync manually if needed
if gateway.zulip_auto_sync and not gateway.zulip_listener_active:
    zulip_service.start_auto_sync(gateway)
    print("Auto-sync started manually")
```

## Troubleshooting

### Common Issues:

- **Authentication Error**: Check bot email and API key
- **Network Error**: Verify Zulip server URL and network connectivity
- **Permission Error**: Ensure bot has access to the streams
- **Channel Not Found**: Verify gateway_channel_token format (stream#topic)
- **Listener Not Starting**: Use "Start Listener" button or check auto-sync is enabled
- **No Messages Received**: Check bot stream subscriptions and filters

### Events API Specific Issues:

- **Grey "Event Listener Active" Box**: Listener not running, click "Start Listener"
- **Queue Registration Fails**: Check bot permissions and API credentials
- **Messages Not Syncing**: Verify bot is subscribed to the streams you're testing
- **Filter Issues**: Check stream/topic filters aren't too restrictive

### Log Messages to Look For:

- "Zulip webhook set for gateway X" (success)
- "Message sent to Zulip: Y" (outbound success)
- "Error processing Zulip update" (inbound error)
- "Failed to set Zulip webhook" (configuration error)
- "Auto-sync started for gateway X" (listener started)
- "Successfully registered event queue" (Events API working)
- "Processed N events for gateway X" (messages being received)

### Debugging Steps:

1. **Check Connection**: Use "Test Connection" button first
2. **Verify Bot Subscriptions**: Ensure bot is subscribed to streams in Zulip
3. **Check Filters**: Verify stream/topic filters allow your test messages
4. **Monitor Logs**: Watch Odoo logs while sending test messages
5. **Manual Listener Start**: Use "Start Listener" button if auto-sync enabled but
   listener inactive
6. **Cron Job Backup**: Even if listener fails, cron job should sync messages every
   minute
