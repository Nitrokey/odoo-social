/** @odoo-module **/

import {registry} from "@web/core/registry";

/**
 * LiveKit Service
 *
 * This service provides a wrapper around the LiveKit JavaScript SDK
 * and handles the integration with Odoo's RTC system.
 */
export const livekitService = {
  dependencies: [],

  start(env, {}) {
    return new LiveKitService();
  },
};

class LiveKitService {
  constructor() {
    this.room = null;
    this.localParticipant = null;
    this.isConnected = false;
    this.serverUrl = null;
    this.accessToken = null;
    this.roomName = null;
    this.participantIdentity = null;

    // Event handlers
    this.onParticipantConnected = null;
    this.onParticipantDisconnected = null;
    this.onTrackSubscribed = null;
    this.onTrackUnsubscribed = null;
    this.onConnectionStateChanged = null;
    this.onDataReceived = null;

    // Check if LiveKit SDK is available
    this.isLiveKitAvailable = typeof window.LivekitClient !== "undefined";

    if (!this.isLiveKitAvailable) {
      console.warn("LiveKit SDK not found. Please include the LiveKit JavaScript SDK.");
    }
  }

  /**
   * Initialize the LiveKit connection
   * @param {Object} config - Configuration object
   * @param {string} config.serverUrl - LiveKit server URL
   * @param {string} config.accessToken - JWT access token
   * @param {string} config.roomName - Room name
   * @param {string} config.participantIdentity - Participant identity
   */
  initialize(config) {
    var self = this;
    if (!this.isLiveKitAvailable) {
      throw new Error("LiveKit SDK is not available");
    }

    this.serverUrl = config.serverUrl;
    this.accessToken = config.accessToken;
    this.roomName = config.roomName;
    this.participantIdentity = config.participantIdentity;

    return new Promise(function (resolve, reject) {
      try {
        // Create room instance
        self.room = new window.LivekitClient.Room({
          // Room options
          adaptiveStream: true,
          dynacast: true,
          videoCaptureDefaults: {
            resolution: window.LivekitClient.VideoPresets.h720.resolution,
          },
        });

        // Set up event listeners
        self._setupEventListeners();

        // Connect to the room
        self.room
          .connect(self.serverUrl, self.accessToken)
          .then(function () {
            self.isConnected = true;
            self.localParticipant = self.room.localParticipant;
            console.log("Connected to LiveKit room:", self.roomName);
            resolve(true);
          })
          .catch(function (error) {
            console.error("Failed to connect to LiveKit room:", error);
            reject(error);
          });
      } catch (error) {
        console.error("Failed to connect to LiveKit room:", error);
        reject(error);
      }
    });
  }

  /**
   * Disconnect from the LiveKit room
   */
  disconnect() {
    var self = this;
    if (this.room && this.isConnected) {
      return new Promise(function (resolve) {
        try {
          self.room
            .disconnect()
            .then(function () {
              self.isConnected = false;
              self.room = null;
              self.localParticipant = null;
              console.log("Disconnected from LiveKit room");
              resolve();
            })
            .catch(function (error) {
              console.error("Error disconnecting from LiveKit room:", error);
              resolve();
            });
        } catch (error) {
          console.error("Error disconnecting from LiveKit room:", error);
          resolve();
        }
      });
    }
    return Promise.resolve();
  }

  /**
   * Enable/disable camera
   * @param {boolean} enabled - Whether to enable camera
   */
  setCameraEnabled(enabled) {
    var self = this;
    if (!this.localParticipant) return Promise.resolve(false);

    return new Promise(function (resolve) {
      try {
        self.localParticipant
          .setCameraEnabled(enabled)
          .then(function () {
            resolve(true);
          })
          .catch(function (error) {
            console.error("Error toggling camera:", error);
            resolve(false);
          });
      } catch (error) {
        console.error("Error toggling camera:", error);
        resolve(false);
      }
    });
  }

  /**
   * Enable/disable microphone
   * @param {boolean} enabled - Whether to enable microphone
   */
  setMicrophoneEnabled(enabled) {
    var self = this;
    if (!this.localParticipant) return Promise.resolve(false);

    return new Promise(function (resolve) {
      try {
        self.localParticipant
          .setMicrophoneEnabled(enabled)
          .then(function () {
            resolve(true);
          })
          .catch(function (error) {
            console.error("Error toggling microphone:", error);
            resolve(false);
          });
      } catch (error) {
        console.error("Error toggling microphone:", error);
        resolve(false);
      }
    });
  }

  /**
   * Enable/disable screen sharing
   * @param {boolean} enabled - Whether to enable screen sharing
   */
  setScreenShareEnabled(enabled) {
    var self = this;
    if (!this.localParticipant) return Promise.resolve(false);

    return new Promise(function (resolve) {
      try {
        self.localParticipant
          .setScreenShareEnabled(enabled)
          .then(function () {
            resolve(true);
          })
          .catch(function (error) {
            console.error("Error toggling screen share:", error);
            resolve(false);
          });
      } catch (error) {
        console.error("Error toggling screen share:", error);
        resolve(false);
      }
    });
  }

  /**
   * Send data to other participants
   * @param {string|Uint8Array} data - Data to send
   * @param {Array} participantIdentities - Target participant identities (optional)
   */
  sendData(data, participantIdentities) {
    var self = this;
    participantIdentities = participantIdentities || null;
    if (!this.localParticipant) return Promise.resolve(false);

    return new Promise(function (resolve) {
      try {
        var encoder = new TextEncoder();
        var dataToSend = typeof data === "string" ? encoder.encode(data) : data;

        self.localParticipant
          .publishData(dataToSend, {
            reliable: true,
            destinationIdentities: participantIdentities,
          })
          .then(function () {
            resolve(true);
          })
          .catch(function (error) {
            console.error("Error sending data:", error);
            resolve(false);
          });
      } catch (error) {
        console.error("Error sending data:", error);
        resolve(false);
      }
    });
  }

  /**
   * Get list of remote participants
   */
  getRemoteParticipants() {
    if (!this.room) return [];

    return Array.from(this.room.remoteParticipants.values()).map(function (
      participant
    ) {
      return {
        identity: participant.identity,
        name: participant.name,
        isCameraEnabled: participant.isCameraEnabled,
        isMicrophoneEnabled: participant.isMicrophoneEnabled,
        isScreenShareEnabled: participant.isScreenShareEnabled,
        connectionQuality: participant.connectionQuality,
      };
    });
  }

  /**
   * Get local participant info
   */
  getLocalParticipant() {
    if (!this.localParticipant) return null;

    return {
      identity: this.localParticipant.identity,
      name: this.localParticipant.name,
      isCameraEnabled: this.localParticipant.isCameraEnabled,
      isMicrophoneEnabled: this.localParticipant.isMicrophoneEnabled,
      isScreenShareEnabled: this.localParticipant.isScreenShareEnabled,
    };
  }

  /**
   * Attach video track to HTML element
   * @param {HTMLElement} element - HTML element to attach video to
   * @param {string} participantIdentity - Participant identity
   * @param {string} trackSource - Track source ('camera' or 'screen_share')
   */
  attachVideoTrack(element, participantIdentity, trackSource) {
    trackSource = trackSource || "camera";
    if (!this.room) return false;

    try {
      var participant = null;
      if (participantIdentity === this.localParticipant.identity) {
        participant = this.localParticipant;
      } else {
        participant = this.room.remoteParticipants.get(participantIdentity);
      }

      if (!participant) return false;

      var trackPublication = null;
      if (trackSource === "screen_share") {
        trackPublication = participant.getTrackPublication(
          window.LivekitClient.Track.Source.ScreenShare
        );
      } else {
        trackPublication = participant.getTrackPublication(
          window.LivekitClient.Track.Source.Camera
        );
      }

      if (trackPublication && trackPublication.track) {
        trackPublication.track.attach(element);
        return true;
      }
      return false;
    } catch (error) {
      console.error("Error attaching video track:", error);
      return false;
    }
  }

  /**
   * Detach video track from HTML element
   * @param {HTMLElement} element - HTML element to detach video from
   */
  detachVideoTrack(element) {
    try {
      // Remove all video elements from the container
      var videoElements = element.querySelectorAll("video");
      videoElements.forEach(function (video) {
        video.remove();
      });
      return true;
    } catch (error) {
      console.error("Error detaching video track:", error);
      return false;
    }
  }

  /**
   * Set up event listeners for LiveKit room events
   */
  _setupEventListeners() {
    var self = this;
    if (!this.room) return;

    // Participant connected
    this.room.on(
      window.LivekitClient.RoomEvent.ParticipantConnected,
      function (participant) {
        console.log("Participant connected:", participant.identity);
        if (self.onParticipantConnected) {
          self.onParticipantConnected(participant);
        }
      }
    );

    // Participant disconnected
    this.room.on(
      window.LivekitClient.RoomEvent.ParticipantDisconnected,
      function (participant) {
        console.log("Participant disconnected:", participant.identity);
        if (self.onParticipantDisconnected) {
          self.onParticipantDisconnected(participant);
        }
      }
    );

    // Track subscribed
    this.room.on(
      window.LivekitClient.RoomEvent.TrackSubscribed,
      function (track, publication, participant) {
        console.log("Track subscribed:", track.kind, "from", participant.identity);
        if (self.onTrackSubscribed) {
          self.onTrackSubscribed(track, publication, participant);
        }
      }
    );

    // Track unsubscribed
    this.room.on(
      window.LivekitClient.RoomEvent.TrackUnsubscribed,
      function (track, publication, participant) {
        console.log("Track unsubscribed:", track.kind, "from", participant.identity);
        if (self.onTrackUnsubscribed) {
          self.onTrackUnsubscribed(track, publication, participant);
        }
      }
    );

    // Connection state changed
    this.room.on(
      window.LivekitClient.RoomEvent.ConnectionStateChanged,
      function (state) {
        console.log("Connection state changed:", state);
        if (self.onConnectionStateChanged) {
          self.onConnectionStateChanged(state);
        }
      }
    );

    // Data received
    this.room.on(
      window.LivekitClient.RoomEvent.DataReceived,
      function (payload, participant) {
        var decoder = new TextDecoder();
        var data = decoder.decode(payload);
        console.log(
          "Data received from",
          participant ? participant.identity : "unknown",
          ":",
          data
        );
        if (self.onDataReceived) {
          self.onDataReceived(data, participant);
        }
      }
    );

    // Local track published (for screen sharing detection)
    this.room.on(
      window.LivekitClient.RoomEvent.LocalTrackPublished,
      function (publication, participant) {
        console.log(
          "Local track published:",
          publication.source,
          publication.kind,
          "from",
          participant.identity
        );
        // This event is handled directly by the RTC model's event listeners
      }
    );

    // Local track unpublished (for screen sharing detection)
    this.room.on(
      window.LivekitClient.RoomEvent.LocalTrackUnpublished,
      function (publication, participant) {
        console.log(
          "Local track unpublished:",
          publication.source,
          publication.kind,
          "from",
          participant.identity
        );
        // This event is handled directly by the RTC model's event listeners
      }
    );

    // Disconnected
    this.room.on(window.LivekitClient.RoomEvent.Disconnected, function (reason) {
      console.log("Disconnected from room:", reason);
      self.isConnected = false;
    });
  }

  /**
   * Check if LiveKit SDK is available
   */
  static isAvailable() {
    return typeof window.LivekitClient !== "undefined";
  }
}

registry.category("services").add("livekit_service", livekitService);
