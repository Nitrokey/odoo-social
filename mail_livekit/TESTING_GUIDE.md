# LiveKit Integration Testing Guide

This guide provides step-by-step instructions to verify that the LiveKit integration is
working correctly in your Odoo 15.0 installation.

## Prerequisites

1. **Module Installation**: Ensure the `mail_livekit` module is installed and activated
2. **LiveKit Server**: Have a LiveKit server running and accessible
3. **Configuration**: LiveKit server configured in Odoo (Settings > Technical >
   Discuss > LiveKit Servers)

## Testing Steps

### 1. Verify Module Installation

```bash
# Check if module is installed
docker-compose exec odoo odoo shell -d your_database_name
>>> env['ir.module.module'].search([('name', '=', 'mail_livekit')])
# Should return a record with state='installed'
```

### 2. Verify LiveKit Server Configuration

1. Go to **Settings > Technical > Discuss > LiveKit Servers**
2. Ensure you have at least one active LiveKit server configured
3. Test the connection using the "Test Connection" button

#### Using the Test Connection Feature

The LiveKit server configuration includes a built-in test feature:

- **From Form View**: Click the "Test Connection" button in the header when editing a
  server
- **From List View**: Click the "Test" button (plug icon) next to any server in the list

The test will verify:

- ✅ **URL Format**: Ensures the server URL starts with ws:// or wss://
- ✅ **Required Fields**: Checks that all required fields are filled
- ✅ **Token Generation**: Tests JWT token creation with your API credentials
- ✅ **Server Accessibility**: Attempts to connect to the server URL

**Test Results:**

- **Success**: Green notification - server is fully configured and accessible
- **Partial Success**: Orange notification - configuration is valid but server may not
  be reachable
- **Failed**: Red notification - configuration errors that need to be fixed

### 3. Browser Console Testing

Open your browser's developer console (F12) and watch for LiveKit-related logs when
starting a video call:

#### Expected Log Messages (Success):

```
LiveKit enabled by backend, configuring...
LiveKit configuration: {serverUrl: "...", roomName: "...", participantIdentity: "...", hasAccessToken: true}
LiveKit RTC model initialized
LiveKit connection state changed: connecting
LiveKit connection state changed: connected
```

#### Expected Log Messages (Fallback to WebRTC):

```
LiveKit not enabled by backend, using default WebRTC
```

### 4. Network Tab Verification

In browser developer tools, check the Network tab for:

1. **Join Call Request**: `POST /mail/rtc/channel/join_call`

   - Response should include `livekitEnabled: true` if LiveKit is configured
   - Should include `livekitServerUrl`, `livekitRoomName`, `livekitAccessToken`

2. **LiveKit SDK Loading**: Look for requests to LiveKit CDN
   - `https://unpkg.com/livekit-client@latest/dist/livekit-client.umd.js`

### 5. Functional Testing

#### Test 1: Audio Call

1. Open a channel/conversation
2. Click the audio call button
3. **Expected**: Console shows LiveKit initialization messages
4. **Expected**: Connection established to LiveKit server (not WebRTC)

#### Test 2: Video Call

1. Open a channel/conversation
2. Click the video call button
3. **Expected**: Console shows LiveKit initialization messages
4. **Expected**: Camera permission requested
5. **Expected**: Video stream appears using LiveKit

#### Test 3: Multi-participant Call

1. Have two users join the same channel
2. Start a video call from one user
3. Join the call from the second user
4. **Expected**: Both users see each other's video/audio via LiveKit

### 6. Backend Log Verification

Check Odoo server logs for LiveKit-related messages:

```bash
# Watch Odoo logs
docker-compose logs -f odoo | grep -i livekit
```

#### Expected Log Messages:

```
INFO your_db mail_livekit.controllers.discuss: LiveKit join call request for channel 123
INFO your_db mail_livekit.controllers.discuss: Added LiveKit data to join call response for channel 123
```

### 7. Database Verification

Check that LiveKit sessions are being created:

```sql
-- Check LiveKit server configuration
SELECT id, name, server_url, active FROM mail_livekit_server;

-- Check RTC sessions with LiveKit data
SELECT id, channel_id, partner_id, livekit_room_name, livekit_participant_identity
FROM mail_channel_rtc_session
WHERE livekit_access_token IS NOT NULL;
```

## Troubleshooting

### Issue: "LiveKit not enabled by backend"

**Possible Causes:**

1. No LiveKit server configured
2. LiveKit server is inactive
3. Channel doesn't have a LiveKit server assigned

**Solutions:**

1. Configure a LiveKit server in Settings > Technical > Discuss > LiveKit Servers
2. Ensure the server is marked as "Active"
3. Check that the channel has access to the LiveKit server

### Issue: "LiveKit SDK is not available"

**Possible Causes:**

1. CDN blocked or unavailable
2. Network connectivity issues
3. Content Security Policy blocking external scripts

**Solutions:**

1. Check browser console for network errors
2. Verify CDN accessibility: https://unpkg.com/livekit-client@latest/
3. Check CSP headers allow external script loading

### Issue: "Failed to connect to LiveKit room"

**Possible Causes:**

1. Invalid LiveKit server URL
2. Incorrect API key/secret
3. Network connectivity to LiveKit server
4. Invalid access token

**Solutions:**

1. Verify LiveKit server URL is accessible
2. Check API key and secret configuration
3. Test LiveKit server connectivity directly
4. Verify token generation is working

### Issue: WebRTC Still Being Used

**Possible Causes:**

1. JavaScript not loading properly
2. RTC model not being patched
3. Backend not sending LiveKit configuration

**Solutions:**

1. Clear browser cache and reload
2. Check browser console for JavaScript errors
3. Verify module assets are loaded correctly
4. Check network tab for join_call response content

## Performance Testing

### Load Testing

1. Create multiple concurrent video calls
2. Monitor server resources (CPU, memory, network)
3. Check LiveKit server performance metrics

### Quality Testing

1. Test video/audio quality compared to WebRTC
2. Test connection stability over time
3. Test reconnection after network interruptions

## Success Criteria

✅ **LiveKit is working correctly if:**

1. Console shows "LiveKit enabled by backend, configuring..."
2. Network requests go to LiveKit server (not STUN/TURN servers)
3. Video/audio streams work between participants
4. LiveKit server shows active rooms and participants
5. No WebRTC-related network traffic during calls

❌ **LiveKit is NOT working if:**

1. Console shows "LiveKit not enabled by backend"
2. Network requests still go to STUN/TURN servers
3. Calls fall back to default WebRTC implementation
4. LiveKit server shows no activity during calls

## Additional Resources

- **LiveKit Documentation**: https://docs.livekit.io/
- **LiveKit Client SDK**: https://github.com/livekit/client-sdk-js
- **Odoo RTC Documentation**:
  https://www.odoo.com/documentation/15.0/developer/reference/frontend/services.html#rtc

## Support

If you encounter issues:

1. Check the browser console for error messages
2. Review Odoo server logs for backend errors
3. Verify LiveKit server is running and accessible
4. Test with a minimal LiveKit client to isolate issues
