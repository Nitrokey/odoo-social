/** @odoo-module **/

import {registerInstancePatchModel} from "@mail/model/model_core";
import {registry} from "@web/core/registry";

/**
 * LiveKit Messaging Model Patch
 *
 * This patches the core messaging model to intercept RTC session initialization
 * and ensure LiveKit parameters from join call responses are passed to the RTC model.
 */

registerInstancePatchModel(
  "mail.messaging",
  "mail_livekit/static/src/models/messaging_livekit.js",
  {
    /**
     * Store LiveKit configuration from join call responses
     */
    _created() {
      this._super();
      this.livekitJoinCallData = null;
      console.log("LiveKit messaging model patch applied");

      // Patch the RPC service to intercept join call responses
      this._patchRpcService();
    },

    /**
     * Patch the RPC service to intercept join call responses
     */
    _patchRpcService() {
      const rpcService = this.env.services.rpc;
      if (rpcService && !rpcService._livekitPatched) {
        const originalRpc = rpcService.rpc || rpcService;
        const self = this;

        // Create wrapper function
        const livekitRpcWrapper = async function (route, params, settings) {
          // More robust logging
          try {
            console.log(
              "LiveKit messaging: RPC call intercepted - Route:",
              JSON.stringify(route),
              "Type:",
              typeof route,
              "Params:",
              params
            );
          } catch (e) {
            console.log(
              "LiveKit messaging: RPC call intercepted - Route (stringify failed):",
              route,
              "Type:",
              typeof route
            );
          }

          // Call original RPC
          const result = await originalRpc.call(this, route, params, settings);

          // Check all possible route formats for join_call
          let isJoinCall = false;
          let isRtcRelated = false;
          let routeString = "";

          if (typeof route === "string") {
            routeString = route;
            isJoinCall = route.includes("join_call");
            isRtcRelated = route.includes("rtc") || route.includes("call");
          } else if (route && typeof route === "object") {
            // Route is an object - check the route property specifically
            routeString =
              route.route || route.url || route.path || JSON.stringify(route);
            isJoinCall = routeString.includes("join_call");
            isRtcRelated = routeString.includes("rtc") || routeString.includes("call");

            // Also check if it's a model-based call that might be RTC related
            if (
              route.model &&
              (route.model.includes("rtc") || route.model.includes("channel"))
            ) {
              isRtcRelated = true;
            }
          } else {
            routeString = String(route);
            isJoinCall = routeString.includes("join_call");
            isRtcRelated = routeString.includes("rtc") || routeString.includes("call");
          }

          console.log(
            "LiveKit messaging: Route analysis - String:",
            routeString,
            "IsJoinCall:",
            isJoinCall,
            "IsRtcRelated:",
            isRtcRelated
          );

          // Enhanced logging for join_call debugging
          if (isJoinCall) {
            console.log("LiveKit messaging: *** FOUND JOIN_CALL ***", {
              route: route,
              routeString: routeString,
              result: result,
              hasLivekitEnabled: result && result.hasOwnProperty("livekitEnabled"),
              livekitEnabledValue: result && result.livekitEnabled,
              resultKeys: result ? Object.keys(result) : "no result",
            });

            // Check if this has LiveKit data
            if (result && result.livekitEnabled) {
              console.log("LiveKit messaging: *** FOUND LIVEKIT DATA ***", result);

              // Process LiveKit data immediately
              await self._handleLiveKitData(result);
            } else {
              console.log(
                "LiveKit messaging: join_call response does not have LiveKit data enabled"
              );
            }
          } else if (isRtcRelated) {
            // Log ALL RTC-related calls for debugging
            console.log("LiveKit messaging: *** RTC RELATED ROUTE ***", {
              route: route,
              routeString: routeString,
              resultKeys: result ? Object.keys(result) : "no result",
              result: result,
            });
          }

          return result;
        };

        // Replace the RPC method
        if (rpcService.rpc) {
          rpcService.rpc = livekitRpcWrapper;
        } else {
          // Copy all properties to maintain RPC service functionality
          Object.setPrototypeOf(livekitRpcWrapper, Object.getPrototypeOf(rpcService));
          Object.getOwnPropertyNames(rpcService).forEach((prop) => {
            if (prop !== "length" && prop !== "name" && prop !== "prototype") {
              livekitRpcWrapper[prop] = rpcService[prop];
            }
          });
          this.env.services.rpc = livekitRpcWrapper;
        }

        rpcService._livekitPatched = true;
        console.log("LiveKit messaging: RPC service patched successfully");
      }
    },

    /**
     * Handle LiveKit data and store it globally for RTC model access
     */
    async _handleLiveKitData(data) {
      if (data && data.livekitEnabled) {
        console.log("LiveKit messaging: Processing LiveKit data", data);

        // Store LiveKit data globally so RTC model can access it
        window.livekitJoinCallData = {
          sessionId: data.sessionId,
          livekitEnabled: data.livekitEnabled,
          livekitServerUrl: data.livekitServerUrl,
          livekitRoomName: data.livekitRoomName,
          livekitAccessToken: data.livekitAccessToken,
          livekitParticipantIdentity: data.livekitParticipantIdentity,
          timestamp: Date.now(), // Add timestamp to ensure freshness
        };

        console.log(
          "LiveKit messaging: Stored LiveKit data globally",
          window.livekitJoinCallData
        );

        // Also store in messaging model for reference
        this.livekitJoinCallData = window.livekitJoinCallData;
      }
    },

    /**
     * Override. Remove focused participant video to trigger video re-attachment.
     */
    toggleFocusedRtcSession(sessionId) {
      this._super(...arguments);
      let exVideo = false;
      let focusedRtcSession = this.focusedRtcSession;
      if (focusedRtcSession && focusedRtcSession.partner) {
        exVideo = document.querySelector(`video[data-participant='partner_${this.focusedRtcSession.partner.id}']`);
      } else if (focusedRtcSession && focusedRtcSession.guest) {
        exVideo = document.querySelector(`video[data-participant='guest_${this.focusedRtcSession.guest.id}']`);
      }
      if (exVideo) {
        exVideo.remove();
      }
    },
  }
);

console.log("LiveKit messaging model patch registered");
