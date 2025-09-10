/** @odoo-module **/

import {registerInstancePatchModel} from "@mail/model/model_core";
import {attr} from "@mail/model/model_field";

/**
 * LiveKit RTC Model
 *
 * This patches the core RTC model to integrate with LiveKit
 * instead of the default WebRTC implementation.
 */

registerInstancePatchModel(
  "mail.rtc",
  "mail_livekit/static/src/models/rtc_livekit.js",
  {
    /**
     * @override
     */
    _created() {
      this._super();

      console.log("LiveKit RTC model patch applied - _created called");

      // LiveKit-specific fields
      this.livekitService = null;
      this.livekitServerUrl = null;
      this.livekitRoomName = null;
      this.livekitAccessToken = null;
      this.livekitParticipantIdentity = null;
      this.livekitEnabled = false;
      this.livekitDeafened = false; // Track deafen state
      this.livekitMuteStateBeforeDeafen = null; // Track original mute state before deafen
      this.livekitDeafenOperationInProgress = false; // Prevent concurrent deafen operations

      // Video track registry for persistence across view changes
      this.activeVideoTracks = new Map(); // participantIdentity -> { track, participant }
      this.activeAudioTracks = new Map(); // participantIdentity -> { track, participant }
      this.domObserver = null; // MutationObserver for DOM changes
      this.reattachmentInterval = null; // Periodic check for missing videos

      // Local screen share tracking
      this.localScreenShareTrack = null; // Track local screen share
      this.localScreenShareElement = null; // Video element for local screen share
      this.originalLocalVideoElement = null; // Store original local video element when screen sharing

      // Remote screen share tracking
      this.remoteScreenShareTracks = new Map(); // participantIdentity -> { track, participant, screenShareElement, originalVideoElement }
    },

    /**
     * Initialize LiveKit service
     */
    async _initializeLiveKit() {
      if (!this.livekitEnabled) {
        console.log("LiveKit RTC: _initializeLiveKit called but LiveKit not enabled");
        return Promise.resolve();
      }

      console.log("LiveKit RTC: _initializeLiveKit starting");

      try {
        // Check if env and services are available
        console.log("LiveKit RTC: Checking env.services availability", {
          hasEnv: !!this.env,
          hasServices: !!(this.env && this.env.services),
          availableServices:
            this.env && this.env.services
              ? Object.keys(this.env.services)
              : "no services",
        });

        // Try to get LiveKit service from env.services first
        this.livekitService = this.env.services.livekit_service;

        // If not found, try to get it directly from the registry
        if (!this.livekitService) {
          console.log(
            "LiveKit RTC: Service not found in env.services, trying registry"
          );
          try {
            const {registry} = require("@web/core/registry");
            const serviceRegistry = registry.category("services");
            const livekitServiceDef = serviceRegistry.get("livekit_service", null);
            if (livekitServiceDef) {
              console.log(
                "LiveKit RTC: Found service definition in registry, starting service"
              );
              this.livekitService = livekitServiceDef.start(this.env, {});
            }
          } catch (error) {
            console.log("LiveKit RTC: Could not access registry:", error);
          }
        }

        console.log("LiveKit RTC: Retrieved livekit_service", {
          hasLivekitService: !!this.livekitService,
          isLiveKitAvailable: this.livekitService
            ? this.livekitService.isLiveKitAvailable
            : "service not found",
          windowLivekitClient: typeof window.LivekitClient,
        });

        if (!this.livekitService) {
          console.error("LiveKit service not found in env.services or registry");

          // As a last resort, try to create the service directly if the SDK is available
          if (typeof window.LivekitClient !== "undefined") {
            console.log("LiveKit RTC: Creating service directly as fallback");
            // Import the service class directly
            try {
              const livekitServiceModule = await import(
                "@mail_livekit/services/livekit_service"
              );
              if (livekitServiceModule && livekitServiceModule.livekitService) {
                this.livekitService = livekitServiceModule.livekitService.start(
                  this.env,
                  {}
                );
                console.log("LiveKit RTC: Successfully created service as fallback");
              }
            } catch (importError) {
              console.error(
                "LiveKit RTC: Could not import service directly:",
                importError
              );
            }
          }

          if (!this.livekitService) {
            throw new Error("LiveKit service not found and could not be created");
          }
        }

        if (!this.livekitService.isLiveKitAvailable) {
          console.error(
            "LiveKit SDK is not available - isLiveKitAvailable returned false"
          );
          console.error("LiveKit service details:", {
            service: this.livekitService,
            methods: Object.getOwnPropertyNames(this.livekitService),
            windowLiveKit: typeof window.LivekitClient,
          });
          throw new Error("LiveKit SDK is not available");
        }

        // Set up event handlers
        console.log("LiveKit RTC: Setting up event handlers");
        this._setupLiveKitEventHandlers();

        console.log("LiveKit RTC model initialized successfully");
      } catch (error) {
        console.error("Failed to initialize LiveKit:", error);
        throw error;
      }
    },

    /**
     * Connect to LiveKit room
     */
    async _connectToLiveKitRoom(enableVideo = true) {
      if (!this.livekitService || !this.livekitAccessToken) {
        console.error("LiveKit service or access token not available");
        return false;
      }

      const config = {
        serverUrl: this.livekitServerUrl,
        accessToken: this.livekitAccessToken,
        roomName: this.livekitRoomName,
        participantIdentity: this.livekitParticipantIdentity,
      };

      try {
        console.log("LiveKit: Connecting to room with config:", {
          serverUrl: config.serverUrl,
          roomName: config.roomName,
          participantIdentity: config.participantIdentity,
          enableVideo: enableVideo,
        });

        await this.livekitService.initialize(config);

        // Set up local track event handlers AFTER room is connected
        console.log("LiveKit: Setting up local track event handlers after connection");
        this._setupLocalTrackEventHandlers();

        // Enable local media based on call type
        console.log(
          `LiveKit: Enabling local media - Video: ${enableVideo}, Audio: true`
        );
        try {
          // Always enable microphone for both voice and video calls
          await this.livekitService.setMicrophoneEnabled(true);

          // Only enable camera for video calls
          if (enableVideo) {
            await this.livekitService.setCameraEnabled(true);
            console.log("LiveKit: Video call - camera enabled");
          } else {
            await this.livekitService.setCameraEnabled(false);
            console.log("LiveKit: Voice call - camera disabled");
          }

          console.log("LiveKit: Local media configured successfully");
        } catch (mediaError) {
          console.warn("LiveKit: Could not configure local media:", mediaError);
          // Continue anyway - the connection is still valid
        }

        this._updateRtcSessionState();
        return true;
      } catch (error) {
        console.error("Failed to connect to LiveKit room:", error);
        return false;
      }
    },

    /**
     * Disconnect from LiveKit room
     */
    async _disconnectFromLiveKitRoom() {
      if (this.livekitService) {
        try {
          await this.livekitService.disconnect();
          this._updateRtcSessionState();
        } catch (error) {
          console.error("Error disconnecting from LiveKit:", error);
        }
      }
    },

    /**
     * Set up LiveKit event handlers
     */
    _setupLiveKitEventHandlers() {
      if (!this.livekitService) return;

      // Participant connected
      this.livekitService.onParticipantConnected = (participant) => {
        this._onLiveKitParticipantConnected(participant);
      };

      // Participant disconnected
      this.livekitService.onParticipantDisconnected = (participant) => {
        this._onLiveKitParticipantDisconnected(participant);
      };

      // Track subscribed
      this.livekitService.onTrackSubscribed = (track, publication, participant) => {
        this._onLiveKitTrackSubscribed(track, publication, participant);
      };

      // Track unsubscribed
      this.livekitService.onTrackUnsubscribed = (track, publication, participant) => {
        this._onLiveKitTrackUnsubscribed(track, publication, participant);
      };

      // Connection state changed
      this.livekitService.onConnectionStateChanged = (state) => {
        this._onLiveKitConnectionStateChanged(state);
      };

      // Data received
      this.livekitService.onDataReceived = (data, participant) => {
        this._onLiveKitDataReceived(data, participant);
      };

      // Note: Local track event handlers are set up after room connection in _connectToLiveKitRoom()
    },

    /**
     * Set up event handlers for local track management (screen sharing)
     */
    _setupLocalTrackEventHandlers() {
      console.log("🖥️ LiveKit: Setting up local track event handlers");

      if (!this.livekitService) {
        console.error(
          "🖥️ LiveKit: Cannot setup local track handlers - no livekitService"
        );
        return;
      }

      if (!this.livekitService.room) {
        console.error("🖥️ LiveKit: Cannot setup local track handlers - no room");
        return;
      }

      const room = this.livekitService.room;
      console.log("🖥️ LiveKit: Room available for event handlers:", {
        roomName: room.name,
        state: room.state,
        hasLocalParticipant: !!room.localParticipant,
      });

      // Listen for local track published events
      room.on(
        window.LivekitClient.RoomEvent.LocalTrackPublished,
        (publication, participant) => {
          console.log("🖥️ LiveKit: ===== LOCAL TRACK PUBLISHED EVENT =====");
          console.log("🖥️ LiveKit: Publication details:", {
            source: publication.source,
            kind: publication.kind,
            trackSid: publication.trackSid,
            trackName: publication.trackName,
            isEnabled: publication.isEnabled,
            isMuted: publication.isMuted,
            hasTrack: !!publication.track,
          });
          console.log("🖥️ LiveKit: Participant details:", {
            identity: participant?.identity,
            isLocal: participant === room.localParticipant,
          });

          if (
            publication.source === window.LivekitClient.Track.Source.ScreenShare &&
            publication.kind === "video"
          ) {
            console.log("🖥️ LiveKit: ✅ SCREEN SHARE TRACK DETECTED - Processing...");

            if (publication.track) {
              console.log("🖥️ LiveKit: Track object available, calling handler");
              this._handleLocalScreenSharePublished(publication.track);
            } else {
              console.error("🖥️ LiveKit: ❌ No track object in publication!");
              this._addDebugIndicator(
                "Screen share published but no track object",
                "error"
              );
            }
          } else {
            console.log("🖥️ LiveKit: Not a screen share track, ignoring");
          }
          console.log("🖥️ LiveKit: ===== END LOCAL TRACK PUBLISHED EVENT =====");
        }
      );

      // Listen for local track unpublished events
      room.on(
        window.LivekitClient.RoomEvent.LocalTrackUnpublished,
        (publication, participant) => {
          console.log("🖥️ LiveKit: ===== LOCAL TRACK UNPUBLISHED EVENT =====");
          console.log("🖥️ LiveKit: Publication details:", {
            source: publication.source,
            kind: publication.kind,
            trackSid: publication.trackSid,
          });

          if (
            publication.source === window.LivekitClient.Track.Source.ScreenShare &&
            publication.kind === "video"
          ) {
            console.log(
              "🖥️ LiveKit: ✅ SCREEN SHARE TRACK UNPUBLISHED - Processing..."
            );
            this._handleLocalScreenShareUnpublished();
          }
          console.log("🖥️ LiveKit: ===== END LOCAL TRACK UNPUBLISHED EVENT =====");
        }
      );

      // Add additional debugging for room events
      room.on(
        window.LivekitClient.RoomEvent.TrackPublished,
        (publication, participant) => {
          if (
            participant === room.localParticipant &&
            publication.source === window.LivekitClient.Track.Source.ScreenShare
          ) {
            console.log(
              "🖥️ LiveKit: TrackPublished event for local screen share (alternative event)"
            );
          }
        }
      );

      console.log("🖥️ LiveKit: Local track event handlers setup complete");
    },

    /**
     * Handle local screen share track published
     */
    _handleLocalScreenSharePublished(track) {
      console.log("🖥️ LiveKit: ===== HANDLING LOCAL SCREEN SHARE PUBLISHED =====");

      try {
        // Store the screen share track
        this.localScreenShareTrack = track;
        console.log("🖥️ LiveKit: Stored screen share track");

        // Try multiple times with increasing delays to find container
        this._attemptScreenShareDisplay(track, 0);

        this._addDebugIndicator("Local screen share started", "success");
      } catch (error) {
        console.error(
          "🖥️ LiveKit: Error handling local screen share published:",
          error
        );
        this._addDebugIndicator(`Screen share error: ${error.message}`, "error");
      }

      console.log("🖥️ LiveKit: ===== END HANDLING LOCAL SCREEN SHARE PUBLISHED =====");
    },

    /**
     * Attempt to display screen share with retry logic
     */
    _attemptScreenShareDisplay(track, attemptNumber) {
      const maxAttempts = 5;
      const delays = [0, 100, 500, 1000, 2000]; // Progressive delays

      console.log(
        `🖥️ LiveKit: Screen share display attempt ${attemptNumber + 1}/${maxAttempts}`
      );

      // Find the local participant's video container
      const localContainer = this._findLocalParticipantContainer();

      if (localContainer) {
        console.log(
          "🖥️ LiveKit: ✅ Found local participant container, displaying screen share"
        );
        this._displayLocalScreenShare(track, localContainer);
        return; // Success - exit retry loop
      }

      // If we haven't found the container and have more attempts left
      if (attemptNumber < maxAttempts - 1) {
        const nextDelay = delays[attemptNumber + 1];
        console.log(
          `🖥️ LiveKit: ⏳ Container not found, retrying in ${nextDelay}ms (attempt ${
            attemptNumber + 2
          }/${maxAttempts})`
        );

        setTimeout(() => {
          this._attemptScreenShareDisplay(track, attemptNumber + 1);
        }, nextDelay);
      } else {
        // All attempts failed - use fallback
        console.warn(
          "🖥️ LiveKit: ❌ All attempts failed to find local participant container"
        );
        console.log("🖥️ LiveKit: Using fallback floating screen share display");
        this._createFallbackScreenShareDisplay(track);
      }
    },

    /**
     * Handle local screen share track unpublished
     */
    _handleLocalScreenShareUnpublished() {
      console.log("🖥️ LiveKit: Handling local screen share unpublished");

      try {
        // Remove the local screen share display
        this._hideLocalScreenShare();

        // Clear the stored track
        this.localScreenShareTrack = null;

        this._addDebugIndicator("Local screen share stopped", "info");
      } catch (error) {
        console.error(
          "🖥️ LiveKit: Error handling local screen share unpublished:",
          error
        );
      }
    },

    /**
     * Display local screen share in the presenter's participant container
     */
    _displayLocalScreenShare(track, container) {
      console.log("🖥️ LiveKit: Displaying local screen share");

      try {
        // Find the existing local video element (camera)
        const existingVideo = container.querySelector("video.o_RtcVideo");

        if (existingVideo) {
          // Store reference to original video element
          this.originalLocalVideoElement = existingVideo;
          // Hide the camera video (don't remove it, just hide it)
          existingVideo.style.display = "none";
          console.log("🖥️ LiveKit: Hidden original camera video");
        }

        // Create screen share video element
        const screenShareElement = document.createElement("video");
        screenShareElement.className = "o_RtcVideo livekit-local-screenshare";
        screenShareElement.autoplay = true;
        screenShareElement.playsInline = true;
        screenShareElement.muted = true; // Local screen share should be muted
        screenShareElement.setAttribute("data-participant", "local-screenshare");
        screenShareElement.setAttribute("data-track-source", "screen_share");

        // Attach the screen share track
        track.attach(screenShareElement);

        // Insert the screen share video element
        if (existingVideo) {
          // Insert after the hidden camera video
          existingVideo.parentNode.insertBefore(
            screenShareElement,
            existingVideo.nextSibling
          );
        } else {
          // Insert at the beginning of the container
          container.insertBefore(screenShareElement, container.firstChild);
        }

        // Store reference to screen share element
        this.localScreenShareElement = screenShareElement;

        console.log("🖥️ LiveKit: Successfully displayed local screen share");

        // Verify screen share is displaying
        setTimeout(() => {
          console.log("🖥️ Screen share element state:", {
            videoWidth: screenShareElement.videoWidth,
            videoHeight: screenShareElement.videoHeight,
            readyState: screenShareElement.readyState,
            paused: screenShareElement.paused,
          });
        }, 1000);
      } catch (error) {
        console.error("🖥️ LiveKit: Error displaying local screen share:", error);
        throw error;
      }
    },

    /**
     * Hide local screen share and restore camera video
     */
    _hideLocalScreenShare() {
      console.log("🖥️ LiveKit: Hiding local screen share");

      try {
        // Remove screen share video element
        if (this.localScreenShareElement) {
          this.localScreenShareElement.remove();
          this.localScreenShareElement = null;
          console.log("🖥️ LiveKit: Removed screen share video element");
        }

        // Restore original camera video
        if (this.originalLocalVideoElement) {
          this.originalLocalVideoElement.style.display = "";
          this.originalLocalVideoElement = null;
          console.log("🖥️ LiveKit: Restored original camera video");
        }
      } catch (error) {
        console.error("🖥️ LiveKit: Error hiding local screen share:", error);
      }
    },

    /**
     * Find the local participant's container
     */
    _findLocalParticipantContainer() {
      console.log("🖥️ LiveKit: ===== FINDING LOCAL PARTICIPANT CONTAINER =====");

      // Look for participant cards that have a video element (local participant usually has camera)
      const participantCards = document.querySelectorAll(
        ".o_RtcCallParticipantCard_container"
      );
      console.log(
        `🖥️ LiveKit: Found ${participantCards.length} participant card containers`
      );

      // Log details of each container for debugging
      participantCards.forEach((card, index) => {
        const videoElement = card.querySelector("video.o_RtcVideo");
        const hasVideo = !!videoElement;
        const isMuted = videoElement ? videoElement.muted : "no video";
        const participant = videoElement
          ? videoElement.getAttribute("data-participant")
          : "no video";
        const hasAvatar = !!card.querySelector(".o_RtcCallParticipantCard_avatarFrame");

        console.log(`🖥️ LiveKit: Container ${index}:`, {
          hasVideo,
          isMuted,
          participant,
          hasAvatar,
          containerHTML: card.innerHTML.substring(0, 150) + "...",
        });
      });

      // Strategy 1: Look for muted video (most reliable for local participant)
      for (const card of participantCards) {
        const videoElement = card.querySelector("video.o_RtcVideo");
        if (videoElement && videoElement.muted === true) {
          console.log(
            "🖥️ LiveKit: ✅ Found local participant container (Strategy 1: has muted video)"
          );
          return card;
        }
      }

      // Strategy 2: Look for video with local participant data attribute
      for (const card of participantCards) {
        const videoElement = card.querySelector("video.o_RtcVideo");
        if (videoElement) {
          const participant = videoElement.getAttribute("data-participant");
          if (
            participant &&
            (participant.includes("local") ||
              participant === this.livekitParticipantIdentity)
          ) {
            console.log(
              "🖥️ LiveKit: ✅ Found local participant container (Strategy 2: participant identity match)"
            );
            return card;
          }
        }
      }

      // Strategy 3: Look for the first participant card with video (fallback)
      for (const card of participantCards) {
        const videoElement = card.querySelector("video.o_RtcVideo");
        if (videoElement) {
          console.log(
            "🖥️ LiveKit: ⚠️ Using first participant container with video as local (Strategy 3: fallback)"
          );
          return card;
        }
      }

      // Strategy 4: If no video containers found, try to find any container and wait
      if (participantCards.length > 0) {
        console.log(
          "🖥️ LiveKit: ⚠️ No video containers found, using first available container (Strategy 4: desperate fallback)"
        );
        return participantCards[0];
      }

      console.error("🖥️ LiveKit: ❌ Could not find any participant container");
      console.log("🖥️ LiveKit: ===== END FINDING LOCAL PARTICIPANT CONTAINER =====");
      return null;
    },

    /**
     * Create fallback floating screen share display
     */
    _createFallbackScreenShareDisplay(track) {
      console.log(
        "🖥️ LiveKit: ===== CREATING FALLBACK FLOATING SCREEN SHARE DISPLAY ====="
      );

      try {
        // Remove any existing fallback display first
        const existingFallback = document.querySelector(
          ".livekit-local-screenshare-fallback"
        );
        if (existingFallback) {
          console.log("🖥️ LiveKit: Removing existing fallback display");
          existingFallback.remove();
        }

        const screenShareElement = document.createElement("video");
        screenShareElement.className = "o_RtcVideo livekit-local-screenshare-fallback";
        screenShareElement.autoplay = true;
        screenShareElement.playsInline = true;
        screenShareElement.muted = true;
        screenShareElement.setAttribute(
          "data-participant",
          "local-screenshare-fallback"
        );
        screenShareElement.setAttribute("data-track-source", "screen_share_fallback");

        // Enhanced styling for floating display
        screenShareElement.style.position = "fixed";
        screenShareElement.style.top = "60px";
        screenShareElement.style.right = "20px";
        screenShareElement.style.width = "400px";
        screenShareElement.style.height = "250px";
        screenShareElement.style.border = "4px solid #00ff00";
        screenShareElement.style.zIndex = "99999";
        screenShareElement.style.backgroundColor = "black";
        screenShareElement.style.borderRadius = "12px";
        screenShareElement.style.boxShadow = "0 8px 32px rgba(0, 255, 0, 0.3)";
        screenShareElement.style.cursor = "move";

        // Create container for label and controls
        const container = document.createElement("div");
        container.style.position = "relative";
        container.style.width = "100%";
        container.style.height = "100%";

        // Add a prominent label
        const label = document.createElement("div");
        label.textContent = "🖥️ Your Screen Share (Fallback Display)";
        label.style.position = "absolute";
        label.style.top = "-35px";
        label.style.left = "0";
        label.style.right = "0";
        label.style.color = "white";
        label.style.fontSize = "14px";
        label.style.fontWeight = "bold";
        label.style.backgroundColor = "#00ff00";
        label.style.padding = "6px 12px";
        label.style.borderRadius = "8px 8px 0 0";
        label.style.textAlign = "center";
        label.style.textShadow = "1px 1px 2px rgba(0,0,0,0.8)";

        // Add close button
        const closeButton = document.createElement("button");
        closeButton.textContent = "×";
        closeButton.style.position = "absolute";
        closeButton.style.top = "-35px";
        closeButton.style.right = "5px";
        closeButton.style.width = "25px";
        closeButton.style.height = "25px";
        closeButton.style.backgroundColor = "#ff4444";
        closeButton.style.color = "white";
        closeButton.style.border = "none";
        closeButton.style.borderRadius = "50%";
        closeButton.style.cursor = "pointer";
        closeButton.style.fontSize = "16px";
        closeButton.style.fontWeight = "bold";
        closeButton.style.zIndex = "100000";

        closeButton.onclick = () => {
          console.log("🖥️ LiveKit: User closed fallback screen share display");
          this._hideLocalScreenShare();
        };

        // Add status indicator
        const statusIndicator = document.createElement("div");
        statusIndicator.textContent = "🔴 LIVE";
        statusIndicator.style.position = "absolute";
        statusIndicator.style.top = "10px";
        statusIndicator.style.left = "10px";
        statusIndicator.style.backgroundColor = "rgba(255, 0, 0, 0.8)";
        statusIndicator.style.color = "white";
        statusIndicator.style.padding = "4px 8px";
        statusIndicator.style.borderRadius = "4px";
        statusIndicator.style.fontSize = "12px";
        statusIndicator.style.fontWeight = "bold";
        statusIndicator.style.zIndex = "100001";

        // Attach the track to the video element
        console.log("🖥️ LiveKit: Attaching track to fallback video element");
        track.attach(screenShareElement);

        // Assemble the components
        container.appendChild(screenShareElement);
        container.appendChild(label);
        container.appendChild(closeButton);
        container.appendChild(statusIndicator);

        // Add to document body
        document.body.appendChild(container);

        // Store reference to the container (not just the video element)
        this.localScreenShareElement = container;

        // Make it draggable
        this._makeDraggable(container);

        console.log(
          "🖥️ LiveKit: ✅ Created enhanced fallback floating screen share display"
        );
        this._addDebugIndicator(
          "Created enhanced floating screen share display",
          "success"
        );

        // Verify the video is working after a short delay
        setTimeout(() => {
          console.log("🖥️ LiveKit: Fallback screen share element state:", {
            videoWidth: screenShareElement.videoWidth,
            videoHeight: screenShareElement.videoHeight,
            readyState: screenShareElement.readyState,
            paused: screenShareElement.paused,
            hasVideoTrack: !!screenShareElement.srcObject,
          });

          if (screenShareElement.videoWidth > 0 && screenShareElement.videoHeight > 0) {
            console.log(
              "🖥️ LiveKit: ✅ Fallback screen share is displaying video successfully"
            );
            this._addDebugIndicator("Fallback screen share working!", "success");
          } else {
            console.warn(
              "🖥️ LiveKit: ⚠️ Fallback screen share may not be displaying video properly"
            );
            this._addDebugIndicator("Fallback screen share may have issues", "warning");
          }
        }, 2000);
      } catch (error) {
        console.error(
          "🖥️ LiveKit: ❌ Error creating fallback screen share display:",
          error
        );
        this._addDebugIndicator(`Fallback display error: ${error.message}`, "error");
      }

      console.log(
        "🖥️ LiveKit: ===== END CREATING FALLBACK FLOATING SCREEN SHARE DISPLAY ====="
      );
    },

    /**
     * Make an element draggable
     */
    _makeDraggable(element) {
      let isDragging = false;
      let currentX;
      let currentY;
      let initialX;
      let initialY;
      let xOffset = 0;
      let yOffset = 0;

      element.addEventListener("mousedown", (e) => {
        if (e.target.tagName === "BUTTON") return; // Don't drag when clicking buttons

        initialX = e.clientX - xOffset;
        initialY = e.clientY - yOffset;

        if (e.target === element || e.target.tagName === "DIV") {
          isDragging = true;
          element.style.cursor = "grabbing";
        }
      });

      document.addEventListener("mousemove", (e) => {
        if (isDragging) {
          e.preventDefault();
          currentX = e.clientX - initialX;
          currentY = e.clientY - initialY;

          xOffset = currentX;
          yOffset = currentY;

          element.style.transform = `translate3d(${currentX}px, ${currentY}px, 0)`;
        }
      });

      document.addEventListener("mouseup", () => {
        initialX = currentX;
        initialY = currentY;
        isDragging = false;
        element.style.cursor = "move";
      });
    },

    /**
     * Handle LiveKit participant connected
     */
    _onLiveKitParticipantConnected(participant) {
      console.log("LiveKit participant connected:", participant.identity);

      // Update RTC session state to reflect new participant
      this._updateRtcSessionState();
    },

    /**
     * Handle LiveKit participant disconnected
     */
    _onLiveKitParticipantDisconnected(participant) {
      console.log("LiveKit participant disconnected:", participant.identity);

      // Clean up video elements for this participant
      this._detachParticipantVideo(participant.identity);

      // Update RTC session state
      this._updateRtcSessionState();
    },

    /**
     * Handle LiveKit track subscribed
     */
    _onLiveKitTrackSubscribed(track, publication, participant) {
      console.log(
        `🎥 LiveKit ${track.kind} track subscribed from:`,
        participant.identity
      );
      console.log("🎥 Track details:", {
        kind: track.kind,
        source: track.source,
        publicationSource: publication.source,
        enabled: track.enabled,
        muted: track.muted,
        participant: participant.identity,
        publication: publication,
      });

      if (track.kind === "video") {
        // Check if this is a screen share track
        if (publication.source === window.LivekitClient.Track.Source.ScreenShare) {
          console.log(
            "🖥️ LiveKit: Remote screen share track detected from:",
            participant.identity
          );
          this._handleRemoteScreenSharePublished(track, publication, participant);
        } else {
          // Handle regular camera video
          console.log(
            "🎥 LiveKit: Regular camera track detected from:",
            participant.identity
          );

          // Store video track in registry for persistence
          this.activeVideoTracks.set(participant.identity, {track, participant});
          console.log(
            "🎥 LiveKit: Stored video track in registry for participant:",
            participant.identity
          );

          console.log("🎥 LiveKit: Attempting to attach remote video track");
          this._attachRemoteVideoTrack(track, participant);
        }
      } else if (track.kind === "audio") {
        // Store audio track in registry for persistence
        this.activeAudioTracks.set(participant.identity, {track, participant});
        console.log(
          "🔊 LiveKit: Stored audio track in registry for participant:",
          participant.identity
        );

        console.log("🔊 LiveKit: Attempting to attach remote audio track");
        this._attachRemoteAudioTrack(track, participant);
      }

      // Start DOM monitoring if not already started
      this._startDOMMonitoring();

      // Update RTC session state
      this._updateRtcSessionState();
    },

    /**
     * Handle remote screen share track published
     */
    _handleRemoteScreenSharePublished(track, publication, participant) {
      console.log("🖥️ LiveKit: ===== HANDLING REMOTE SCREEN SHARE PUBLISHED =====");
      console.log("🖥️ LiveKit: Remote screen share from:", participant.identity);

      try {
        // Find the participant's existing video container
        const participantContainer = this._findParticipantContainerByIdentity(
          participant.identity
        );

        if (participantContainer) {
          console.log(
            "🖥️ LiveKit: Found participant container for screen share replacement"
          );

          // Find the existing camera video element
          const existingVideo = participantContainer.querySelector("video.o_RtcVideo");

          if (existingVideo) {
            console.log(
              "🖥️ LiveKit: Found existing camera video, replacing with screen share"
            );

            // Store reference to original video element
            const screenShareData = {
              track: track,
              participant: participant,
              screenShareElement: null,
              originalVideoElement: existingVideo,
            };

            // Hide the camera video (don't remove it, just hide it)
            existingVideo.style.display = "none";
            console.log(
              "🖥️ LiveKit: Hidden original camera video for participant:",
              participant.identity
            );

            // Create screen share video element
            const screenShareElement = document.createElement("video");
            screenShareElement.className = "o_RtcVideo livekit-remote-screenshare";
            screenShareElement.autoplay = true;
            screenShareElement.playsInline = true;
            screenShareElement.muted = false; // Remote screen share should not be muted
            screenShareElement.setAttribute("data-participant", participant.identity);
            screenShareElement.setAttribute("data-track-source", "screen_share");
            screenShareElement.setAttribute("data-track-type", "remote-screenshare");

            // Attach the screen share track
            track.attach(screenShareElement);

            // Insert the screen share video element after the hidden camera video
            existingVideo.parentNode.insertBefore(
              screenShareElement,
              existingVideo.nextSibling
            );

            // Store reference to screen share element
            screenShareData.screenShareElement = screenShareElement;

            // Store in remote screen share tracking
            this.remoteScreenShareTracks.set(participant.identity, screenShareData);

            console.log(
              "🖥️ LiveKit: Successfully replaced camera with remote screen share for:",
              participant.identity
            );
            this._addDebugIndicator(
              `Screen share from ${participant.identity} replacing camera`,
              "success"
            );

            // Verify screen share is displaying
            setTimeout(() => {
              console.log("🖥️ Remote screen share element state:", {
                participant: participant.identity,
                videoWidth: screenShareElement.videoWidth,
                videoHeight: screenShareElement.videoHeight,
                readyState: screenShareElement.readyState,
                paused: screenShareElement.paused,
              });
            }, 1000);
          } else {
            console.warn(
              "🖥️ LiveKit: No existing camera video found for participant:",
              participant.identity
            );
            // Fallback: treat as regular video track
            this._attachRemoteVideoTrack(track, participant);
          }
        } else {
          console.warn(
            "🖥️ LiveKit: No participant container found for screen share from:",
            participant.identity
          );
          // Fallback: create floating screen share display
          this._createRemoteScreenShareFallback(track, participant);
        }
      } catch (error) {
        console.error(
          "🖥️ LiveKit: Error handling remote screen share published:",
          error
        );
        this._addDebugIndicator(`Remote screen share error: ${error.message}`, "error");
      }

      console.log("🖥️ LiveKit: ===== END HANDLING REMOTE SCREEN SHARE PUBLISHED =====");
    },

    /**
     * Handle remote screen share track unpublished
     */
    _handleRemoteScreenShareUnpublished(participant) {
      console.log(
        "🖥️ LiveKit: Handling remote screen share unpublished from:",
        participant.identity
      );

      try {
        const screenShareData = this.remoteScreenShareTracks.get(participant.identity);

        if (screenShareData) {
          console.log("🖥️ LiveKit: Found screen share data, restoring camera video");

          // Remove screen share video element
          if (screenShareData.screenShareElement) {
            screenShareData.screenShareElement.remove();
            console.log("🖥️ LiveKit: Removed remote screen share video element");
          }

          // Restore original camera video
          if (screenShareData.originalVideoElement) {
            screenShareData.originalVideoElement.style.display = "";
            console.log(
              "🖥️ LiveKit: Restored original camera video for:",
              participant.identity
            );
          }

          // Remove from tracking
          this.remoteScreenShareTracks.delete(participant.identity);

          this._addDebugIndicator(
            `Screen share from ${participant.identity} ended, camera restored`,
            "info"
          );
        } else {
          console.warn(
            "🖥️ LiveKit: No screen share data found for participant:",
            participant.identity
          );
        }
      } catch (error) {
        console.error(
          "🖥️ LiveKit: Error handling remote screen share unpublished:",
          error
        );
      }
    },

    /**
     * Find participant container by identity (for existing participants with video)
     */
    _findParticipantContainerByIdentity(participantIdentity) {
      console.log(
        "🖥️ LiveKit: Finding participant container for:",
        participantIdentity
      );

      // Look for participant cards that have a video element with matching participant identity
      const participantCards = document.querySelectorAll(
        ".o_RtcCallParticipantCard_container"
      );

      for (const card of participantCards) {
        const videoElement = card.querySelector("video.o_RtcVideo");
        if (videoElement) {
          const videoParticipant = videoElement.getAttribute("data-participant");
          if (videoParticipant === participantIdentity) {
            console.log(
              "🖥️ LiveKit: Found participant container for:",
              participantIdentity
            );
            return card;
          }
        }
      }

      console.warn(
        "🖥️ LiveKit: No participant container found for:",
        participantIdentity
      );
      return null;
    },

    /**
     * Create fallback floating display for remote screen share
     */
    _createRemoteScreenShareFallback(track, participant) {
      console.log(
        "🖥️ LiveKit: Creating fallback floating display for remote screen share from:",
        participant.identity
      );

      try {
        // Create screen share video element
        const screenShareElement = document.createElement("video");
        screenShareElement.className = "o_RtcVideo livekit-remote-screenshare-fallback";
        screenShareElement.autoplay = true;
        screenShareElement.playsInline = true;
        screenShareElement.muted = false;
        screenShareElement.setAttribute("data-participant", participant.identity);
        screenShareElement.setAttribute("data-track-source", "screen_share_fallback");

        // Enhanced styling for floating display
        screenShareElement.style.position = "fixed";
        screenShareElement.style.top = "120px";
        screenShareElement.style.right = "20px";
        screenShareElement.style.width = "400px";
        screenShareElement.style.height = "250px";
        screenShareElement.style.border = "4px solid #ff6600";
        screenShareElement.style.zIndex = "99998";
        screenShareElement.style.backgroundColor = "black";
        screenShareElement.style.borderRadius = "12px";
        screenShareElement.style.boxShadow = "0 8px 32px rgba(255, 102, 0, 0.3)";
        screenShareElement.style.cursor = "move";

        // Create container for label and controls
        const container = document.createElement("div");
        container.style.position = "relative";
        container.style.width = "100%";
        container.style.height = "100%";

        // Add a prominent label
        const label = document.createElement("div");
        label.textContent = `🖥️ ${participant.identity}'s Screen Share`;
        label.style.position = "absolute";
        label.style.top = "-35px";
        label.style.left = "0";
        label.style.right = "0";
        label.style.color = "white";
        label.style.fontSize = "14px";
        label.style.fontWeight = "bold";
        label.style.backgroundColor = "#ff6600";
        label.style.padding = "6px 12px";
        label.style.borderRadius = "8px 8px 0 0";
        label.style.textAlign = "center";
        label.style.textShadow = "1px 1px 2px rgba(0,0,0,0.8)";

        // Add close button
        const closeButton = document.createElement("button");
        closeButton.textContent = "×";
        closeButton.style.position = "absolute";
        closeButton.style.top = "-35px";
        closeButton.style.right = "5px";
        closeButton.style.width = "25px";
        closeButton.style.height = "25px";
        closeButton.style.backgroundColor = "#ff4444";
        closeButton.style.color = "white";
        closeButton.style.border = "none";
        closeButton.style.borderRadius = "50%";
        closeButton.style.cursor = "pointer";
        closeButton.style.fontSize = "16px";
        closeButton.style.fontWeight = "bold";
        closeButton.style.zIndex = "100000";

        closeButton.onclick = () => {
          console.log("🖥️ LiveKit: User closed remote screen share fallback display");
          container.remove();
          this.remoteScreenShareTracks.delete(participant.identity);
        };

        // Attach the track to the video element
        track.attach(screenShareElement);

        // Assemble the components
        container.appendChild(screenShareElement);
        container.appendChild(label);
        container.appendChild(closeButton);

        // Add to document body
        document.body.appendChild(container);

        // Store in remote screen share tracking
        this.remoteScreenShareTracks.set(participant.identity, {
          track: track,
          participant: participant,
          screenShareElement: container,
          originalVideoElement: null,
        });

        // Make it draggable
        this._makeDraggable(container);

        console.log(
          "🖥️ LiveKit: Created fallback floating remote screen share display"
        );
        this._addDebugIndicator(
          `Fallback screen share from ${participant.identity}`,
          "warning"
        );
      } catch (error) {
        console.error(
          "🖥️ LiveKit: Error creating remote screen share fallback:",
          error
        );
      }
    },

    /**
     * Handle LiveKit track unsubscribed
     */
    _onLiveKitTrackUnsubscribed(track, publication, participant) {
      console.log(
        `LiveKit ${track.kind} track unsubscribed from:`,
        participant.identity
      );
      console.log("🎥 Track unsubscribed details:", {
        kind: track.kind,
        source: track.source,
        publicationSource: publication.source,
        participant: participant.identity,
      });

      if (track.kind === "video") {
        // Check if this is a screen share track being unsubscribed
        if (publication.source === window.LivekitClient.Track.Source.ScreenShare) {
          console.log(
            "🖥️ LiveKit: Remote screen share track unsubscribed from:",
            participant.identity
          );
          this._handleRemoteScreenShareUnpublished(participant);
        } else {
          // Handle regular camera video unsubscription
          console.log(
            "🎥 LiveKit: Regular camera track unsubscribed from:",
            participant.identity
          );

          // Remove from video track registry
          this.activeVideoTracks.delete(participant.identity);
          console.log(
            "🎥 LiveKit: Removed video track from registry for participant:",
            participant.identity
          );

          this._detachParticipantVideo(participant.identity);
        }
      } else if (track.kind === "audio") {
        // Remove from audio track registry
        this.activeAudioTracks.delete(participant.identity);
        console.log(
          "🔊 LiveKit: Removed audio track from registry for participant:",
          participant.identity
        );
      }

      // Update RTC session state
      this._updateRtcSessionState();
    },

    /**
     * Handle LiveKit connection state changed
     */
    _onLiveKitConnectionStateChanged(state) {
      console.log("LiveKit connection state changed:", state);
    },

    /**
     * Handle LiveKit data received
     */
    _onLiveKitDataReceived(data, participant) {
      console.log("LiveKit data received from:", participant?.identity, data);
    },

    /**
     * Attach remote video track to Odoo's participant card
     */
    _attachRemoteVideoTrack(track, participant) {
      console.log(
        "🎥 LiveKit: Attaching remote video track for participant:",
        participant.identity
      );
      console.log("🎥 Track state:", {
        enabled: track.enabled,
        muted: track.muted,
        readyState: track.readyState,
        kind: track.kind,
      });

      try {
        // Add visual debugging indicator
        this._addDebugIndicator(
          `Attempting to attach video for ${participant.identity}`
        );

        // Try multiple strategies to find and attach video
        let success = false;

        // Strategy 1: Find specific participant container
        console.log("🎥 Strategy 1: Finding specific participant container");
        const participantContainer = this._findParticipantContainer(
          participant.identity
        );

        if (participantContainer) {
          success = this._attachVideoToContainer(
            track,
            participant,
            participantContainer,
            "Strategy 1"
          );
        }

        // Strategy 2: If strategy 1 failed, try with delay (DOM might not be ready)
        if (!success) {
          console.log("🎥 Strategy 2: Retrying with delay");
          setTimeout(() => {
            const delayedContainer = this._findParticipantContainer(
              participant.identity
            );
            if (delayedContainer) {
              this._attachVideoToContainer(
                track,
                participant,
                delayedContainer,
                "Strategy 2 (delayed)"
              );
            } else {
              this._tryFallbackAttachment(track, participant);
            }
          }, 500);
        }

        // Strategy 3: Try all containers without video as immediate fallback
        if (!success) {
          console.log("🎥 Strategy 3: Trying all containers without video");
          const allContainers = this._findParticipantCardContainers();
          for (let i = 0; i < allContainers.length; i++) {
            const container = allContainers[i];
            if (!container.querySelector("video.o_RtcVideo")) {
              console.log(`🎥 Trying container ${i} as fallback`);
              success = this._attachVideoToContainer(
                track,
                participant,
                container,
                `Strategy 3 (container ${i})`
              );
              if (success) break;
            }
          }
        }

        if (!success) {
          console.error("🎥 All strategies failed - video attachment unsuccessful");
          this._logDOMState();
        }
      } catch (error) {
        console.error("🎥 LiveKit: Error attaching remote video track:", error);
        this._addDebugIndicator(`Error attaching video: ${error.message}`, "error");
      }
    },

    /**
     * Attach video to a specific container
     */
    _attachVideoToContainer(track, participant, container, strategy) {
      try {
        console.log(
          `🎥 ${strategy}: Found participant container, creating video element`
        );

        // Create video element with Odoo's styling
        const videoElement = document.createElement("video");
        videoElement.className = "o_RtcVideo"; // Use Odoo's video class
        videoElement.autoplay = true;
        videoElement.playsInline = true;
        videoElement.muted = false; // Remote video should not be muted
        videoElement.setAttribute("data-participant", participant.identity);
        videoElement.setAttribute("data-strategy", strategy);

        // Remove debugging styles since video is working
        // videoElement.style.border = '2px solid red';
        // videoElement.style.minWidth = '100px';
        // videoElement.style.minHeight = '100px';

        // Attach the LiveKit track to the video element
        track.attach(videoElement);

        // Hide the avatar frame (it shows "Not connected" message)
        const avatarFrame = container.querySelector(
          ".o_RtcCallParticipantCard_avatarFrame"
        );
        if (avatarFrame) {
          avatarFrame.style.display = "none";
          console.log(`🎥 ${strategy}: Hidden avatar frame for participant`);
        }

        // Hide the connection state overlay (shows "Not connected: sending initial RTC offer")
        const overlayTop = container.querySelector(
          ".o_RtcCallParticipantCard_overlayTop"
        );
        if (overlayTop) {
          overlayTop.style.display = "none";
          console.log(`🎥 ${strategy}: Hidden connection state overlay`);
        }

        // Insert the video element at the beginning of the container
        container.insertBefore(videoElement, container.firstChild);

        console.log(
          `🎥 ${strategy}: Successfully attached remote video track to participant card`
        );
        this._addDebugIndicator(
          `Video attached successfully using ${strategy}`,
          "success"
        );

        // Verify video is playing
        setTimeout(() => {
          console.log(`🎥 Video element state after attachment:`, {
            videoWidth: videoElement.videoWidth,
            videoHeight: videoElement.videoHeight,
            readyState: videoElement.readyState,
            paused: videoElement.paused,
            muted: videoElement.muted,
          });
        }, 1000);

        return true;
      } catch (error) {
        console.error(`🎥 ${strategy}: Error in _attachVideoToContainer:`, error);
        return false;
      }
    },

    /**
     * Try fallback attachment strategies
     */
    _tryFallbackAttachment(track, participant) {
      console.log("🎥 Fallback: Trying alternative attachment methods");

      // Fallback 1: Create a floating video element
      try {
        const videoElement = document.createElement("video");
        videoElement.className = "o_RtcVideo livekit-debug-video";
        videoElement.autoplay = true;
        videoElement.playsInline = true;
        videoElement.muted = false;
        videoElement.setAttribute("data-participant", participant.identity);

        // Style for debugging
        videoElement.style.position = "fixed";
        videoElement.style.top = "10px";
        videoElement.style.right = "10px";
        videoElement.style.width = "200px";
        videoElement.style.height = "150px";
        videoElement.style.border = "3px solid blue";
        videoElement.style.zIndex = "9999";
        videoElement.style.backgroundColor = "black";

        track.attach(videoElement);
        document.body.appendChild(videoElement);

        console.log("🎥 Fallback: Created floating debug video element");
        this._addDebugIndicator("Created floating debug video", "warning");
      } catch (error) {
        console.error("🎥 Fallback attachment also failed:", error);
      }
    },

    /**
     * Add visual debugging indicator
     */
    _addDebugIndicator(message, type = "info") {
      const indicator = document.createElement("div");
      indicator.className = `livekit-debug-indicator livekit-debug-${type}`;
      indicator.textContent = `LiveKit: ${message}`;
      indicator.style.position = "fixed";
      indicator.style.top = "50px";
      indicator.style.left = "10px";
      indicator.style.padding = "5px 10px";
      indicator.style.backgroundColor =
        type === "error"
          ? "red"
          : type === "success"
          ? "green"
          : type === "warning"
          ? "orange"
          : "blue";
      indicator.style.color = "white";
      indicator.style.fontSize = "12px";
      indicator.style.zIndex = "10000";
      indicator.style.borderRadius = "3px";

      document.body.appendChild(indicator);

      // Remove after 5 seconds
      setTimeout(() => {
        if (indicator.parentNode) {
          indicator.parentNode.removeChild(indicator);
        }
      }, 5000);
    },

    /**
     * Log current DOM state for debugging
     */
    _logDOMState() {
      console.log("🎥 Current DOM state:");

      // Log all participant containers
      const allContainers = document.querySelectorAll(
        ".o_RtcCallParticipantCard_container"
      );
      console.log(`🎥 Found ${allContainers.length} participant card containers:`);

      allContainers.forEach((container, index) => {
        const hasVideo = !!container.querySelector("video.o_RtcVideo");
        const hasAvatar = !!container.querySelector(
          ".o_RtcCallParticipantCard_avatarFrame"
        );
        const hasOverlay = !!container.querySelector(
          ".o_RtcCallParticipantCard_overlayTop"
        );

        console.log(`🎥 Container ${index}:`, {
          hasVideo,
          hasAvatar,
          hasOverlay,
          innerHTML: container.innerHTML.substring(0, 200) + "...",
        });
      });

      // Log all existing video elements
      const allVideos = document.querySelectorAll("video");
      console.log(`🎥 Found ${allVideos.length} video elements in DOM:`);
      allVideos.forEach((video, index) => {
        console.log(`🎥 Video ${index}:`, {
          className: video.className,
          participant: video.getAttribute("data-participant"),
          strategy: video.getAttribute("data-strategy"),
          videoWidth: video.videoWidth,
          videoHeight: video.videoHeight,
          readyState: video.readyState,
        });
      });
    },

    /**
     * Attach remote audio track
     */
    _attachRemoteAudioTrack(track, participant) {
      console.log(
        "🔊 LiveKit: Attaching remote audio track for participant:",
        participant.identity
      );

      try {
        // Create audio element for remote audio
        const audioElement = document.createElement("audio");
        audioElement.autoplay = true;
        audioElement.setAttribute("data-participant", participant.identity);
        audioElement.className = "livekit-remote-audio";

        // Apply current deafen state
        if (this.livekitDeafened) {
          audioElement.volume = 0;
          console.log("🔊 LiveKit: Applied deafen state to new audio track");
        }

        // Attach the track to the audio element
        track.attach(audioElement);

        // Add to document body (audio doesn't need to be visible)
        document.body.appendChild(audioElement);

        console.log("🔊 LiveKit: Successfully attached remote audio track");
      } catch (error) {
        console.error("🔊 LiveKit: Error attaching remote audio track:", error);
      }
    },

    /**
     * Detach video for a specific participant
     */
    _detachParticipantVideo(participantIdentity) {
      console.log("LiveKit: Detaching video for participant:", participantIdentity);

      try {
        // Find and remove video elements for this participant
        const videoElements = document.querySelectorAll(
          `video[data-participant="${participantIdentity}"]`
        );
        const audioElements = document.querySelectorAll(
          `audio[data-participant="${participantIdentity}"]`
        );

        videoElements.forEach((element) => {
          element.remove();
        });

        audioElements.forEach((element) => {
          element.remove();
        });

        console.log(
          "LiveKit: Cleaned up media elements for participant:",
          participantIdentity
        );
      } catch (error) {
        console.error("LiveKit: Error detaching participant video:", error);
      }
    },

    /**
     * Find Odoo's participant card containers for video attachment
     */
    _findParticipantCardContainers() {
      // Look for Odoo's participant card containers
      const containers = document.querySelectorAll(
        ".o_RtcCallParticipantCard_container"
      );
      console.log(`LiveKit: Found ${containers.length} participant card containers`);
      return Array.from(containers);
    },

    /**
     * Find the specific participant card container for a given participant
     */
    _findParticipantContainer(participantIdentity) {
      // Look for participant cards that don't already have a video element (remote participants)
      const participantCards = document.querySelectorAll(
        ".o_RtcCallParticipantCard_container"
      );

      for (const card of participantCards) {
        // Skip cards that already have a video element (local participant)
        if (card.querySelector("video.o_RtcVideo")) {
          continue;
        }

        // Check if this card has an avatar (indicating it's waiting for video)
        const avatarFrame = card.querySelector(".o_RtcCallParticipantCard_avatarFrame");
        if (avatarFrame) {
          console.log(
            `LiveKit: Found participant card without video for participant: ${participantIdentity}`
          );
          return card;
        }
      }

      console.warn(
        `LiveKit: No suitable participant card found for: ${participantIdentity}`
      );
      return null;
    },

    /**
     * Update RTC session state
     */
    _updateRtcSessionState() {
      if (this.currentRtcSession && this.livekitService) {
        const localParticipant = this.livekitService.getLocalParticipant();
        if (localParticipant) {
          const newState = {
            isCameraOn: localParticipant.isCameraEnabled,
            isMuted: !localParticipant.isMicrophoneEnabled,
            isScreenSharingOn: localParticipant.isScreenShareEnabled,
          };

          console.log("🔄 LiveKit: Updating RTC session state:", newState);

          this.currentRtcSession.update(newState);

          // Add visual indicator for state changes
          this._addDebugIndicator(
            `State: Mic=${!newState.isMuted ? "ON" : "OFF"}, Cam=${
              newState.isCameraOn ? "ON" : "OFF"
            }`,
            "info"
          );
        }
      }
    },

    /**
     * Override toggleMicrophone to use LiveKit service with deafen dependency
     */
    async toggleMicrophone() {
      console.log("🎤 LiveKit: toggleMicrophone called");

      if (this.livekitEnabled && this.livekitService) {
        try {
          const localParticipant = this.livekitService.getLocalParticipant();
          if (localParticipant) {
            const currentState = localParticipant.isMicrophoneEnabled;
            const newState = !currentState;

            // Check deafen dependency: cannot unmute while deafened
            if (newState === true && this.livekitDeafened) {
              console.log(
                "🎤 LiveKit: Cannot unmute while deafened - ignoring toggle request"
              );
              this._addDebugIndicator("Cannot unmute while deafened", "warning");
              return; // Do nothing - prevent unmuting while deafened
            }

            console.log(
              `🎤 LiveKit: Toggling microphone from ${currentState} to ${newState}`
            );

            await this.livekitService.setMicrophoneEnabled(newState);

            // Update RTC session state
            this._updateRtcSessionState();

            console.log(`🎤 LiveKit: Microphone toggled successfully to ${newState}`);
          } else {
            console.warn(
              "🎤 LiveKit: No local participant found for microphone toggle"
            );
          }
        } catch (error) {
          console.error("🎤 LiveKit: Error toggling microphone:", error);
          // Fallback to parent method if LiveKit fails
          return this._super();
        }
      } else {
        console.log("🎤 LiveKit: Not enabled, using parent toggleMicrophone");
        return this._super();
      }
    },

    /**
     * Override toggleCamera to use LiveKit service
     */
    async toggleCamera() {
      console.log("📹 LiveKit: toggleCamera called");

      if (this.livekitEnabled && this.livekitService) {
        try {
          const localParticipant = this.livekitService.getLocalParticipant();
          if (localParticipant) {
            const currentState = localParticipant.isCameraEnabled;
            const newState = !currentState;

            console.log(
              `📹 LiveKit: Toggling camera from ${currentState} to ${newState}`
            );

            await this.livekitService.setCameraEnabled(newState);

            // Update RTC session state
            this._updateRtcSessionState();

            console.log(`📹 LiveKit: Camera toggled successfully to ${newState}`);
          } else {
            console.warn("📹 LiveKit: No local participant found for camera toggle");
          }
        } catch (error) {
          console.error("📹 LiveKit: Error toggling camera:", error);
          // Fallback to parent method if LiveKit fails
          return this._super();
        }
      } else {
        console.log("📹 LiveKit: Not enabled, using parent toggleCamera");
        return this._super();
      }
    },

    /**
     * Override setMicrophoneEnabled to use LiveKit service with deafen dependency
     */
    async setMicrophoneEnabled(enabled) {
      console.log(`🎤 LiveKit: setMicrophoneEnabled called with ${enabled}`);

      if (this.livekitEnabled && this.livekitService) {
        try {
          // Check deafen dependency: cannot unmute while deafened
          if (enabled === true && this.livekitDeafened) {
            console.log(
              "🎤 LiveKit: Cannot unmute while deafened - ignoring setMicrophoneEnabled request"
            );
            this._addDebugIndicator("Cannot unmute while deafened", "warning");
            return; // Do nothing - prevent unmuting while deafened
          }

          await this.livekitService.setMicrophoneEnabled(enabled);

          // Update RTC session state
          this._updateRtcSessionState();

          console.log(`🎤 LiveKit: Microphone set to ${enabled} successfully`);
        } catch (error) {
          console.error("🎤 LiveKit: Error setting microphone state:", error);
          // Fallback to parent method if LiveKit fails
          return this._super(enabled);
        }
      } else {
        console.log("🎤 LiveKit: Not enabled, using parent setMicrophoneEnabled");
        return this._super(enabled);
      }
    },

    /**
     * Override setCameraEnabled to use LiveKit service
     */
    async setCameraEnabled(enabled) {
      console.log(`📹 LiveKit: setCameraEnabled called with ${enabled}`);

      if (this.livekitEnabled && this.livekitService) {
        try {
          await this.livekitService.setCameraEnabled(enabled);

          // Update RTC session state
          this._updateRtcSessionState();

          console.log(`📹 LiveKit: Camera set to ${enabled} successfully`);
        } catch (error) {
          console.error("📹 LiveKit: Error setting camera state:", error);
          // Fallback to parent method if LiveKit fails
          return this._super(enabled);
        }
      } else {
        console.log("📹 LiveKit: Not enabled, using parent setCameraEnabled");
        return this._super(enabled);
      }
    },

    /**
     * Override toggleScreenShare to use LiveKit service
     */
    async toggleScreenShare() {
      console.log("🖥️ LiveKit: ===== TOGGLE SCREEN SHARE CALLED =====");

      if (this.livekitEnabled && this.livekitService) {
        try {
          const localParticipant = this.livekitService.getLocalParticipant();
          if (localParticipant) {
            const currentState = localParticipant.isScreenShareEnabled;
            const newState = !currentState;

            console.log(
              `🖥️ LiveKit: Toggling screen share from ${currentState} to ${newState}`
            );
            console.log(`🖥️ LiveKit: Current room state:`, {
              roomName: this.livekitService.room?.name,
              roomState: this.livekitService.room?.state,
              localParticipantIdentity: localParticipant.identity,
              hasEventHandlers: !!this.livekitService.room?._events,
            });

            // Add immediate debugging for screen share start
            if (newState) {
              console.log("🖥️ LiveKit: STARTING SCREEN SHARE - Setting up debugging");
              this._debugScreenShareStart();
            }

            await this.livekitService.setScreenShareEnabled(newState);

            // Update RTC session state
            this._updateRtcSessionState();

            console.log(`🖥️ LiveKit: Screen share toggled successfully to ${newState}`);

            // Add post-toggle debugging
            if (newState) {
              setTimeout(() => {
                this._debugScreenShareStatus();
              }, 1000);
            }
          } else {
            console.warn(
              "🖥️ LiveKit: No local participant found for screen share toggle"
            );
          }
        } catch (error) {
          console.error("🖥️ LiveKit: Error toggling screen share:", error);
          // Fallback to parent method if LiveKit fails
          return this._super();
        }
      } else {
        console.log("🖥️ LiveKit: Not enabled, using parent toggleScreenShare");
        return this._super();
      }

      console.log("🖥️ LiveKit: ===== END TOGGLE SCREEN SHARE =====");
    },

    /**
     * Debug screen share start process
     */
    _debugScreenShareStart() {
      console.log("🔍 LiveKit: ===== DEBUGGING SCREEN SHARE START =====");

      // Check if event handlers are properly set up
      const room = this.livekitService?.room;
      if (room) {
        console.log("🔍 LiveKit: Room event handlers:", {
          hasRoom: !!room,
          roomEvents: room._events ? Object.keys(room._events) : "no events",
          localTrackPublishedHandlers: room._events?.localTrackPublished?.length || 0,
          localTrackUnpublishedHandlers:
            room._events?.localTrackUnpublished?.length || 0,
        });
      }

      // Check current DOM state
      const participantCards = document.querySelectorAll(
        ".o_RtcCallParticipantCard_container"
      );
      console.log(
        `🔍 LiveKit: Found ${participantCards.length} participant cards before screen share`
      );

      // Check current screen share state
      console.log("🔍 LiveKit: Current screen share tracking:", {
        localScreenShareTrack: !!this.localScreenShareTrack,
        localScreenShareElement: !!this.localScreenShareElement,
        originalLocalVideoElement: !!this.originalLocalVideoElement,
      });

      console.log("🔍 LiveKit: ===== END DEBUGGING SCREEN SHARE START =====");
    },

    /**
     * Debug screen share status after toggle
     */
    _debugScreenShareStatus() {
      console.log("🔍 LiveKit: ===== DEBUGGING SCREEN SHARE STATUS =====");

      const localParticipant = this.livekitService?.getLocalParticipant();
      if (localParticipant) {
        console.log("🔍 LiveKit: Local participant screen share state:", {
          isScreenShareEnabled: localParticipant.isScreenShareEnabled,
          trackPublications: localParticipant.trackPublications?.size || 0,
        });

        // Check for screen share publications
        if (localParticipant.trackPublications) {
          const publications = Array.from(localParticipant.trackPublications.values());
          const screenSharePubs = publications.filter(
            (pub) => pub.source === window.LivekitClient?.Track?.Source?.ScreenShare
          );
          console.log(
            `🔍 LiveKit: Found ${screenSharePubs.length} screen share publications:`,
            screenSharePubs
          );
        }
      }

      // Check if our screen share display was created
      console.log("🔍 LiveKit: Screen share display status:", {
        localScreenShareTrack: !!this.localScreenShareTrack,
        localScreenShareElement: !!this.localScreenShareElement,
        fallbackDisplayExists: !!document.querySelector(
          ".livekit-local-screenshare-fallback"
        ),
        regularDisplayExists: !!document.querySelector(".livekit-local-screenshare"),
      });

      // Check for any screen share video elements
      const screenShareVideos = document.querySelectorAll(
        'video[data-track-source*="screen"]'
      );
      console.log(
        `🔍 LiveKit: Found ${screenShareVideos.length} screen share video elements in DOM`
      );

      console.log("🔍 LiveKit: ===== END DEBUGGING SCREEN SHARE STATUS =====");
    },

    /**
     * Override toggleDeafen to use LiveKit remote audio control with proper locking
     */
    async toggleDeafen() {
      console.log("🔇 LiveKit: toggleDeafen called");

      if (this.livekitEnabled) {
        // Check if another deafen operation is in progress
        if (this.livekitDeafenOperationInProgress) {
          console.log(
            "🔇 LiveKit: Deafen operation already in progress, ignoring request"
          );
          this._addDebugIndicator("Deafen operation in progress, ignoring", "warning");
          return;
        }

        try {
          // Lock the operation
          this.livekitDeafenOperationInProgress = true;

          const currentState = this.livekitDeafened;
          const newState = !currentState;

          console.log(
            `🔇 LiveKit: Toggling deafen from ${currentState} to ${newState}`
          );

          await this._setDeafenState(newState);

          console.log(`🔇 LiveKit: Deafen toggled successfully to ${newState}`);

          // Return early to prevent any parent method calls
          return;
        } catch (error) {
          console.error("🔇 LiveKit: Error toggling deafen:", error);
          // Don't fallback to parent method - just log the error
          this._addDebugIndicator(`Deafen toggle failed: ${error.message}`, "error");
          return;
        } finally {
          // Always unlock the operation
          this.livekitDeafenOperationInProgress = false;
        }
      } else {
        console.log("🔇 LiveKit: Not enabled, using parent toggleDeafen");
        return this._super();
      }
    },

    /**
     * Override setDeafened to use LiveKit remote audio control with proper locking
     */
    async setDeafened(deafened) {
      console.log(`🔇 LiveKit: setDeafened called with ${deafened}`);

      if (this.livekitEnabled) {
        // Check if another deafen operation is in progress
        if (this.livekitDeafenOperationInProgress) {
          console.log(
            "🔇 LiveKit: Deafen operation already in progress, ignoring setDeafened request"
          );
          this._addDebugIndicator("Deafen operation in progress, ignoring", "warning");
          return;
        }

        try {
          // Lock the operation
          this.livekitDeafenOperationInProgress = true;

          await this._setDeafenState(deafened);
          console.log(`🔇 LiveKit: Deafen set to ${deafened} successfully`);

          // Return early to prevent any parent method calls
          return;
        } catch (error) {
          console.error("🔇 LiveKit: Error setting deafen state:", error);
          // Don't fallback to parent method - just log the error
          this._addDebugIndicator(`Set deafen failed: ${error.message}`, "error");
          return;
        } finally {
          // Always unlock the operation
          this.livekitDeafenOperationInProgress = false;
        }
      } else {
        console.log("🔇 LiveKit: Not enabled, using parent setDeafened");
        return this._super(deafened);
      }
    },

    /**
     * Set deafen state for LiveKit (controls remote audio volume AND preserves mute state)
     */
    async _setDeafenState(deafened) {
      console.log(`🔇 LiveKit: ===== DEAFEN STATE CHANGE START =====`);
      console.log(`🔇 LiveKit: Setting deafen state to ${deafened}`);
      console.log(`🔇 LiveKit: Current livekitDeafened state: ${this.livekitDeafened}`);
      console.log(
        `🔇 LiveKit: Current saved mute state: ${this.livekitMuteStateBeforeDeafen}`
      );

      // CORRECT DEPENDENT BEHAVIOR: Preserve original mute state
      if (this.livekitService) {
        try {
          const localParticipant = this.livekitService.getLocalParticipant();
          if (localParticipant) {
            const currentMicState = localParticipant.isMicrophoneEnabled;
            console.log(
              `🔇 LiveKit: Current microphone state from LiveKit: ${currentMicState}`
            );

            if (deafened) {
              // When enabling deafen: save current mute state and ensure microphone is muted
              console.log(
                `🔇 LiveKit: ENABLING DEAFEN - Current mic state: ${currentMicState}`
              );

              // Save the current state BEFORE making any changes
              this.livekitMuteStateBeforeDeafen = currentMicState;
              console.log(
                `🔇 LiveKit: Saved original mute state: ${this.livekitMuteStateBeforeDeafen}`
              );

              // Check if microphone is currently enabled (unmuted)
              if (currentMicState === true) {
                console.log(
                  `🔇 LiveKit: Microphone is UNMUTED, need to mute it for deafen`
                );
                await this.livekitService.setMicrophoneEnabled(false);
                console.log(
                  `🔇 LiveKit: Called setMicrophoneEnabled(false) - microphone should now be muted`
                );
              } else {
                console.log(
                  `🔇 LiveKit: Microphone is already MUTED, no change needed`
                );
                console.log(
                  `🔇 LiveKit: NOT calling setMicrophoneEnabled() - preserving muted state`
                );
              }
            } else {
              // When disabling deafen: restore the original mute state
              console.log(`🔇 LiveKit: DISABLING DEAFEN`);
              const originalState = this.livekitMuteStateBeforeDeafen;
              console.log(
                `🔇 LiveKit: Original saved state to restore: ${originalState}`
              );

              if (originalState !== null) {
                console.log(
                  `🔇 LiveKit: Restoring microphone to original state: ${originalState}`
                );
                await this.livekitService.setMicrophoneEnabled(originalState);
                console.log(
                  `🔇 LiveKit: Called setMicrophoneEnabled(${originalState})`
                );
                this.livekitMuteStateBeforeDeafen = null; // Clear saved state
                console.log(`🔇 LiveKit: Cleared saved state`);
              } else {
                console.log(`🔇 LiveKit: No saved state found, defaulting to unmute`);
                await this.livekitService.setMicrophoneEnabled(true);
                console.log(
                  `🔇 LiveKit: Called setMicrophoneEnabled(true) as fallback`
                );
              }
            }

            // Verify the final state
            const finalMicState =
              this.livekitService.getLocalParticipant()?.isMicrophoneEnabled;
            console.log(
              `🔇 LiveKit: FINAL microphone state after operation: ${finalMicState}`
            );

            // Update RTC session state to reflect changes
            console.log(`🔇 LiveKit: Updating RTC session state...`);
            this._updateRtcSessionState();
            console.log(`🔇 LiveKit: RTC session state updated`);
          }
        } catch (error) {
          console.error(`🔇 LiveKit: ERROR during microphone control:`, error);
          console.error(`🔇 LiveKit: Error stack:`, error.stack);
        }
      }

      // Update our internal deafen state
      console.log(
        `🔇 LiveKit: Setting internal livekitDeafened from ${this.livekitDeafened} to ${deafened}`
      );
      this.livekitDeafened = deafened;

      // Also update Odoo's RTC session state for UI synchronization
      if (this.currentRtcSession) {
        console.log(
          `🔇 LiveKit: Updating RTC session isDeaf from ${this.currentRtcSession.isDeaf} to ${deafened}`
        );
        this.currentRtcSession.update({isDeaf: deafened});
        console.log(`🔇 LiveKit: RTC session isDeaf updated for UI synchronization`);
      } else {
        console.warn(`🔇 LiveKit: No currentRtcSession available for UI state update`);
      }

      // Control all remote audio elements
      const remoteAudioElements = document.querySelectorAll(
        "audio.livekit-remote-audio"
      );
      console.log(
        `🔇 LiveKit: Found ${remoteAudioElements.length} remote audio elements to control`
      );

      remoteAudioElements.forEach((audioElement, index) => {
        const participant = audioElement.getAttribute("data-participant");
        const oldVolume = audioElement.volume;
        if (deafened) {
          audioElement.volume = 0;
          console.log(
            `🔇 LiveKit: Set audio volume to 0 for participant ${participant} (was ${oldVolume})`
          );
        } else {
          audioElement.volume = 1;
          console.log(
            `🔇 LiveKit: Set audio volume to 1 for participant ${participant} (was ${oldVolume})`
          );
        }
      });

      // Add visual indicator for deafen state
      const micState = this.livekitService
        ? this.livekitService.getLocalParticipant()?.isMicrophoneEnabled
          ? "UNMUTED"
          : "MUTED"
        : "UNKNOWN";
      console.log(
        `🔇 LiveKit: Final state summary - Deafen: ${
          deafened ? "ON" : "OFF"
        }, Mic: ${micState}`
      );
      this._addDebugIndicator(
        `Deafen: ${deafened ? "ON" : "OFF"} (Mic: ${micState})`,
        deafened ? "warning" : "info"
      );

      console.log(`🔇 LiveKit: ===== DEAFEN STATE CHANGE END =====`);
      return Promise.resolve();
    },

    /**
     * Override initSession to handle LiveKit initialization
     */
    async initSession(params) {
      console.log("🚀 LiveKit RTC model initSession called with params:", params);

      const {
        currentSessionId,
        iceServers,
        startWithAudio,
        startWithVideo,
        videoType = "user-video",
        livekitEnabled,
        livekitServerUrl,
        livekitRoomName,
        livekitAccessToken,
        livekitParticipantIdentity,
      } = params;

      // Add visual debugging indicator for session start
      this._addDebugIndicator("Starting RTC session initialization", "info");

      // Check for globally stored LiveKit data first
      let livekitData = null;
      if (window.livekitJoinCallData) {
        // Check if the data is fresh (within last 30 seconds) and matches current session
        const dataAge = Date.now() - window.livekitJoinCallData.timestamp;
        if (
          dataAge < 30000 &&
          window.livekitJoinCallData.sessionId === currentSessionId
        ) {
          livekitData = window.livekitJoinCallData;
          console.log(
            "🚀 LiveKit RTC: Using globally stored LiveKit data",
            livekitData
          );
          this._addDebugIndicator("Using globally stored LiveKit data", "info");
        } else {
          console.log(
            "🚀 LiveKit RTC: Global LiveKit data is stale or for different session",
            {
              dataAge: dataAge,
              globalSessionId: window.livekitJoinCallData.sessionId,
              currentSessionId: currentSessionId,
            }
          );
        }
      } else {
        console.log("🚀 LiveKit RTC: No global LiveKit data found");
      }

      // Store LiveKit configuration and state before calling parent
      let shouldUseLiveKit = false;
      let livekitConfig = null;

      if (livekitEnabled || (livekitData && livekitData.livekitEnabled)) {
        shouldUseLiveKit = true;
        livekitConfig = {
          livekitServerUrl:
            livekitServerUrl || (livekitData && livekitData.livekitServerUrl),
          livekitRoomName:
            livekitRoomName || (livekitData && livekitData.livekitRoomName),
          livekitAccessToken:
            livekitAccessToken || (livekitData && livekitData.livekitAccessToken),
          livekitParticipantIdentity:
            livekitParticipantIdentity ||
            (livekitData && livekitData.livekitParticipantIdentity),
        };

        console.log("🚀 LiveKit configuration received:", {
          source: livekitEnabled ? "params" : "global",
          serverUrl: livekitConfig.livekitServerUrl,
          roomName: livekitConfig.livekitRoomName,
          participantIdentity: livekitConfig.livekitParticipantIdentity,
          hasAccessToken: !!livekitConfig.livekitAccessToken,
        });
        this._addDebugIndicator(
          `LiveKit enabled - ${livekitEnabled ? "from params" : "from global data"}`,
          "success"
        );
      } else {
        console.log("🚀 LiveKit not enabled - no params or global data available");
        this._addDebugIndicator("LiveKit not enabled - using WebRTC", "warning");
      }

      // Call parent method first
      console.log("🚀 LiveKit RTC: Calling parent _super method");
      try {
        await this._super({
          currentSessionId,
          iceServers,
          startWithAudio,
          startWithVideo,
          videoType,
        });
        console.log("🚀 LiveKit RTC: Parent _super method completed successfully");
      } catch (error) {
        console.error("🚀 LiveKit RTC: Parent _super method failed:", error);
        this._addDebugIndicator(`Parent method failed: ${error.message}`, "error");
        throw error;
      }

      // Restore LiveKit configuration after parent method (which might have reset it)
      if (shouldUseLiveKit && livekitConfig) {
        console.log(
          "🚀 LiveKit RTC: Restoring LiveKit configuration after parent method"
        );
        this.livekitEnabled = true;
        this.livekitServerUrl = livekitConfig.livekitServerUrl;
        this.livekitRoomName = livekitConfig.livekitRoomName;
        this.livekitAccessToken = livekitConfig.livekitAccessToken;
        this.livekitParticipantIdentity = livekitConfig.livekitParticipantIdentity;

        console.log(
          "🚀 LiveKit RTC: Configuration restored, livekitEnabled =",
          this.livekitEnabled
        );
      }

      // Initialize LiveKit if enabled
      if (this.livekitEnabled) {
        console.log("🚀 LiveKit enabled, initializing LiveKit session");
        this._addDebugIndicator("Initializing LiveKit session", "info");

        try {
          console.log("🚀 LiveKit RTC: Step 1 - Calling _initializeLiveKit()");
          await this._initializeLiveKit();
          console.log("🚀 LiveKit RTC: Step 1 completed - LiveKit initialized");

          console.log("🚀 LiveKit RTC: Step 2 - Calling _connectToLiveKitRoom()");
          const connected = await this._connectToLiveKitRoom(startWithVideo);
          console.log(
            "🚀 LiveKit RTC: Step 2 completed - Connection result:",
            connected
          );

          if (connected) {
            console.log("🚀 LiveKit RTC: Successfully connected to LiveKit room");
            this._addDebugIndicator(
              "Successfully connected to LiveKit room",
              "success"
            );

            // Log current participants and tracks
            setTimeout(() => {
              this._logLiveKitRoomState();
            }, 1000);

            // Clear global data after successful use
            if (window.livekitJoinCallData) {
              console.log("🚀 LiveKit RTC: Clearing used global LiveKit data");
              window.livekitJoinCallData = null;
            }
          } else {
            console.warn(
              "🚀 LiveKit RTC: Failed to connect to LiveKit room, but no error thrown"
            );
            this._addDebugIndicator("Failed to connect to LiveKit room", "error");
          }
        } catch (error) {
          console.error("🚀 Failed to initialize LiveKit session:", error);
          console.error("🚀 Error details:", {
            message: error.message,
            stack: error.stack,
            livekitService: !!this.livekitService,
            serverUrl: this.livekitServerUrl,
            accessToken: this.livekitAccessToken ? "present" : "missing",
          });
          this._addDebugIndicator(
            `LiveKit initialization failed: ${error.message}`,
            "error"
          );
          this.livekitEnabled = false;
        }
      } else {
        console.log("🚀 LiveKit RTC: LiveKit not enabled, using standard WebRTC");
      }
    },

    /**
     * Log current LiveKit room state for debugging
     */
    _logLiveKitRoomState() {
      if (!this.livekitService || !this.livekitService.room) {
        console.log("🚀 No LiveKit room to log state for");
        return;
      }

      try {
        const room = this.livekitService.room;
        const localParticipant = room.localParticipant;

        // Safely get remote participants with null checks
        let remoteParticipants = [];
        if (
          room.remoteParticipants &&
          typeof room.remoteParticipants.values === "function"
        ) {
          remoteParticipants = Array.from(room.remoteParticipants.values());
        } else if (room.remoteParticipants && room.remoteParticipants instanceof Map) {
          remoteParticipants = Array.from(room.remoteParticipants.values());
        } else if (room.remoteParticipants) {
          // Fallback: try to convert to array if it's an object
          remoteParticipants = Object.values(room.remoteParticipants);
        }

        console.log("🚀 LiveKit Room State:", {
          roomName: room.name || "unknown",
          connectionState: room.state || "unknown",
          localParticipant: localParticipant
            ? {
                identity: localParticipant.identity || "unknown",
                isCameraEnabled: localParticipant.isCameraEnabled || false,
                isMicrophoneEnabled: localParticipant.isMicrophoneEnabled || false,
                trackPublications: localParticipant.trackPublications
                  ? localParticipant.trackPublications.size
                  : 0,
              }
            : null,
          remoteParticipantsCount: remoteParticipants.length,
          remoteParticipants: remoteParticipants.map((p) => {
            if (!p) return {identity: "null participant"};

            // Safely get video track publications
            let videoTracks = [];
            try {
              if (
                p.videoTrackPublications &&
                typeof p.videoTrackPublications.values === "function"
              ) {
                videoTracks = Array.from(p.videoTrackPublications.values()).map(
                  (pub) => ({
                    source: pub.source || "unknown",
                    subscribed: pub.isSubscribed || false,
                    enabled: pub.isEnabled || false,
                    muted: pub.isMuted || false,
                  })
                );
              }
            } catch (videoError) {
              console.warn(
                "🚀 Error getting video tracks for participant:",
                p.identity,
                videoError
              );
            }

            return {
              identity: p.identity || "unknown",
              isCameraEnabled: p.isCameraEnabled || false,
              isMicrophoneEnabled: p.isMicrophoneEnabled || false,
              trackPublications: p.trackPublications ? p.trackPublications.size : 0,
              videoTracks: videoTracks,
            };
          }),
        });

        // Also log DOM state
        this._logDOMState();
      } catch (error) {
        console.error("🚀 Error logging LiveKit room state:", error);
        console.error("🚀 Room object:", this.livekitService.room);
      }
    },

    /**
     * Start DOM monitoring for participant card changes
     */
    _startDOMMonitoring() {
      if (this.domObserver || this.reattachmentInterval) {
        console.log("🔍 LiveKit: DOM monitoring already started");
        return;
      }

      console.log("🔍 LiveKit: Starting DOM monitoring for video re-attachment");

      // Set up MutationObserver to detect DOM changes
      this.domObserver = new MutationObserver((mutations) => {
        let shouldCheckReattachment = false;

        mutations.forEach((mutation) => {
          // Check if participant cards were added or removed
          if (mutation.type === "childList") {
            const addedNodes = Array.from(mutation.addedNodes);
            const removedNodes = Array.from(mutation.removedNodes);

            // Check if any participant cards were added
            const hasParticipantCards = [...addedNodes, ...removedNodes].some(
              (node) => {
                return (
                  node.nodeType === Node.ELEMENT_NODE &&
                  (node.classList?.contains("o_RtcCallParticipantCard_container") ||
                    node.querySelector?.(".o_RtcCallParticipantCard_container"))
                );
              }
            );

            if (hasParticipantCards) {
              console.log("🔍 LiveKit: Detected participant card DOM changes");
              shouldCheckReattachment = true;
            }
          }
        });

        if (shouldCheckReattachment) {
          // Debounce the re-attachment check
          setTimeout(() => {
            this._checkAndReattachVideos();
          }, 100);
        }
      });

      // Observe the entire document for changes
      this.domObserver.observe(document.body, {
        childList: true,
        subtree: true,
      });

      // Set up periodic check as backup
      this.reattachmentInterval = setInterval(() => {
        this._checkAndReattachVideos();
      }, 2000); // Check every 2 seconds

      console.log("🔍 LiveKit: DOM monitoring started successfully");
    },

    /**
     * Stop DOM monitoring
     */
    _stopDOMMonitoring() {
      if (this.domObserver) {
        this.domObserver.disconnect();
        this.domObserver = null;
        console.log("🔍 LiveKit: DOM observer stopped");
      }

      if (this.reattachmentInterval) {
        clearInterval(this.reattachmentInterval);
        this.reattachmentInterval = null;
        console.log("🔍 LiveKit: Reattachment interval stopped");
      }
    },

    /**
     * Check for missing videos and re-attach them
     */
    _checkAndReattachVideos() {
      if (!this.livekitEnabled || this.activeVideoTracks.size === 0) {
        return;
      }

      console.log("🔍 LiveKit: Checking for missing videos to re-attach");
      console.log(`🔍 LiveKit: Active video tracks: ${this.activeVideoTracks.size}`);

      // Check each active video track
      this.activeVideoTracks.forEach(({track, participant}, participantIdentity) => {
        // Check if video element exists for this participant
        const existingVideo = document.querySelector(
          `video[data-participant="${participantIdentity}"]`
        );

        if (!existingVideo) {
          console.log(
            `🔍 LiveKit: Missing video for participant ${participantIdentity}, attempting re-attachment`
          );
          this._addDebugIndicator(
            `Re-attaching video for ${participantIdentity}`,
            "warning"
          );

          // Try to re-attach the video
          this._reattachVideoTrack(track, participant);
        } else {
          // Video exists, but check if it's properly attached and playing
          const isAttached = existingVideo.srcObject || existingVideo.src;
          const isInDOM = document.body.contains(existingVideo);

          if (!isAttached || !isInDOM) {
            console.log(
              `🔍 LiveKit: Video element exists but not properly attached for ${participantIdentity}`
            );
            this._addDebugIndicator(
              `Re-attaching detached video for ${participantIdentity}`,
              "warning"
            );

            // Remove the broken video element and re-attach
            if (existingVideo.parentNode) {
              existingVideo.remove();
            }
            this._reattachVideoTrack(track, participant);
          }
        }
      });

      // Also check audio tracks
      this.activeAudioTracks.forEach(({track, participant}, participantIdentity) => {
        const existingAudio = document.querySelector(
          `audio[data-participant="${participantIdentity}"]`
        );

        if (!existingAudio) {
          console.log(
            `🔍 LiveKit: Missing audio for participant ${participantIdentity}, attempting re-attachment`
          );
          this._reattachAudioTrack(track, participant);
        }
      });
    },

    /**
     * Re-attach a video track to the DOM
     */
    _reattachVideoTrack(track, participant) {
      console.log(
        `🔄 LiveKit: Re-attaching video track for participant: ${participant.identity}`
      );

      try {
        // Use the same attachment logic as initial attachment
        let success = false;

        // Strategy 1: Find specific participant container
        const participantContainer = this._findParticipantContainer(
          participant.identity
        );

        if (participantContainer) {
          success = this._attachVideoToContainer(
            track,
            participant,
            participantContainer,
            "Re-attachment Strategy 1"
          );
        }

        // Strategy 2: Try with delay if failed
        if (!success) {
          setTimeout(() => {
            const delayedContainer = this._findParticipantContainer(
              participant.identity
            );
            if (delayedContainer) {
              this._attachVideoToContainer(
                track,
                participant,
                delayedContainer,
                "Re-attachment Strategy 2 (delayed)"
              );
            } else {
              // Strategy 3: Try all containers without video
              const allContainers = this._findParticipantCardContainers();
              for (let i = 0; i < allContainers.length; i++) {
                const container = allContainers[i];
                if (!container.querySelector("video.o_RtcVideo")) {
                  console.log(`🔄 Re-attachment: Trying container ${i} as fallback`);
                  const success = this._attachVideoToContainer(
                    track,
                    participant,
                    container,
                    `Re-attachment Strategy 3 (container ${i})`
                  );
                  if (success) break;
                }
              }
            }
          }, 500);
        }
      } catch (error) {
        console.error("🔄 LiveKit: Error re-attaching video track:", error);
        this._addDebugIndicator(`Error re-attaching video: ${error.message}`, "error");
      }
    },

    /**
     * Re-attach an audio track to the DOM
     */
    _reattachAudioTrack(track, participant) {
      console.log(
        `🔄 LiveKit: Re-attaching audio track for participant: ${participant.identity}`
      );

      try {
        // Create new audio element
        const audioElement = document.createElement("audio");
        audioElement.autoplay = true;
        audioElement.setAttribute("data-participant", participant.identity);
        audioElement.className = "livekit-remote-audio";

        // Apply current deafen state
        if (this.livekitDeafened) {
          audioElement.volume = 0;
          console.log("🔄 LiveKit: Applied deafen state to re-attached audio track");
        }

        // Attach the track to the audio element
        track.attach(audioElement);

        // Add to document body
        document.body.appendChild(audioElement);

        console.log("🔄 LiveKit: Successfully re-attached remote audio track");
      } catch (error) {
        console.error("🔄 LiveKit: Error re-attaching audio track:", error);
      }
    },

    /**
     * Override reset to clean up LiveKit resources
     */
    reset() {
      // Stop DOM monitoring
      this._stopDOMMonitoring();

      // Clean up local screen share
      this._hideLocalScreenShare();

      // Clean up remote screen shares
      this.remoteScreenShareTracks.forEach((screenShareData, participantIdentity) => {
        console.log(
          "🖥️ LiveKit: Cleaning up remote screen share for:",
          participantIdentity
        );

        // Remove screen share video element
        if (screenShareData.screenShareElement) {
          screenShareData.screenShareElement.remove();
        }

        // Restore original camera video if it exists
        if (screenShareData.originalVideoElement) {
          screenShareData.originalVideoElement.style.display = "";
        }
      });

      // Clear track registries
      this.activeVideoTracks.clear();
      this.activeAudioTracks.clear();
      this.remoteScreenShareTracks.clear();

      // Reset local screen share tracking
      this.localScreenShareTrack = null;
      this.localScreenShareElement = null;
      this.originalLocalVideoElement = null;

      if (this.livekitService) {
        this.livekitService.disconnect().catch(console.error);
      }

      this.livekitService = null;
      this.livekitServerUrl = null;
      this.livekitRoomName = null;
      this.livekitAccessToken = null;
      this.livekitParticipantIdentity = null;
      this.livekitEnabled = false;

      this._super();
    },

    /**
     * Override handleNotification to process LiveKit-specific notifications
     */
    async handleNotification(sender, content) {
      // If LiveKit is enabled, let LiveKit handle the notifications
      if (this.livekitEnabled) {
        console.log("LiveKit handling notification from:", sender);
        return;
      }

      // Otherwise, use parent WebRTC handling
      return this._super(sender, content);
    },

    /**
     * Manual test function for screen sharing display (for debugging)
     * Call this from browser console: window.livekitRtcModel.testScreenShareDisplay()
     */
    testScreenShareDisplay() {
      console.log("🧪 LiveKit: ===== MANUAL SCREEN SHARE DISPLAY TEST =====");

      if (!this.livekitEnabled) {
        console.error("🧪 LiveKit: Cannot test - LiveKit not enabled");
        return;
      }

      // Create a mock video track for testing
      const canvas = document.createElement("canvas");
      canvas.width = 640;
      canvas.height = 480;
      const ctx = canvas.getContext("2d");

      // Draw a test pattern
      ctx.fillStyle = "#00ff00";
      ctx.fillRect(0, 0, canvas.width, canvas.height);
      ctx.fillStyle = "#000000";
      ctx.font = "48px Arial";
      ctx.textAlign = "center";
      ctx.fillText("TEST SCREEN SHARE", canvas.width / 2, canvas.height / 2);
      ctx.fillText(
        new Date().toLocaleTimeString(),
        canvas.width / 2,
        canvas.height / 2 + 60
      );

      // Get a stream from the canvas
      const stream = canvas.captureStream(30);
      const videoTrack = stream.getVideoTracks()[0];

      // Create a mock LiveKit track object
      const mockTrack = {
        attach: (element) => {
          console.log("🧪 LiveKit: Attaching mock track to element");
          element.srcObject = stream;
          return element;
        },
        detach: (element) => {
          console.log("🧪 LiveKit: Detaching mock track from element");
          element.srcObject = null;
        },
        kind: "video",
        source: "screen_share",
      };

      console.log("🧪 LiveKit: Created mock screen share track, testing display...");

      // Test the screen share display logic
      try {
        this._handleLocalScreenSharePublished(mockTrack);
        console.log("🧪 LiveKit: Mock screen share display test completed");

        // Auto-cleanup after 10 seconds
        setTimeout(() => {
          console.log("🧪 LiveKit: Auto-cleaning up test screen share");
          this._handleLocalScreenShareUnpublished();
          videoTrack.stop();
        }, 10000);
      } catch (error) {
        console.error("🧪 LiveKit: Error in screen share display test:", error);
      }

      console.log("🧪 LiveKit: ===== END MANUAL SCREEN SHARE DISPLAY TEST =====");
    },
  }
);

// Make the RTC model globally accessible for debugging
if (typeof window !== "undefined") {
  window.addEventListener("DOMContentLoaded", () => {
    // Try to find and expose the LiveKit RTC model for debugging
    setTimeout(() => {
      try {
        const messagingService = window.odoo?.env?.services?.messaging;
        if (messagingService && messagingService.rtc) {
          window.livekitRtcModel = messagingService.rtc;
          console.log(
            "🔧 LiveKit: RTC model exposed as window.livekitRtcModel for debugging"
          );
          console.log(
            "🔧 LiveKit: You can test screen sharing with: window.livekitRtcModel.testScreenShareDisplay()"
          );
        }
      } catch (error) {
        console.log("🔧 LiveKit: Could not expose RTC model for debugging:", error);
      }
    }, 2000);
  });
}
