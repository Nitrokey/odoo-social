Mail LiveKit Integration
========================

This module replaces Odoo's native WebRTC implementation with LiveKit integration
for improved scalability and reliability of video and voice calls.

Features
--------

* LiveKit server integration for video/voice calls
* Maintains identical user interface and experience
* Improved scalability for large meetings
* Better connection reliability
* Advanced features like recording and streaming support

Requirements
------------

* LiveKit server deployment
* LiveKit Python SDK (livekit-api)
* PyJWT for token generation

Configuration
-------------

After installation, configure your LiveKit server settings:

1. Go to Settings > Technical > Discuss > LiveKit Servers

2. Create a new LiveKit server record with:
   - Name: A descriptive name for your server
   - Server URL: Your LiveKit server URL (e.g., wss://your-livekit-server.com/livekit/sfu)
   - API Key: Your LiveKit API key
   - API Secret: Your LiveKit API secret
   - Active: Check this box to enable the server

   You can configure multiple LiveKit servers for load balancing or different environments.
   The system will automatically use the first active server found.

3. Test your configuration using the "Test Connection" button to verify:
   - Server URL accessibility
   - API key and secret validity
   - Token generation functionality

Usage
-----

Once configured, all video and voice calls in Odoo Discuss will automatically
use LiveKit instead of the native WebRTC implementation. The user experience
remains identical.
