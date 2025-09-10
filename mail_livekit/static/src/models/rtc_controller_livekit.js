/** @odoo-module **/

import {registerInstancePatchModel} from "@mail/model/model_core";

/**
 * LiveKit RTC Controller Model Patch
 *
 * This patches the RTC controller to intercept deafen button clicks
 * and route them directly to our LiveKit implementation, bypassing
 * the original Odoo deafen logic that causes race conditions.
 */

registerInstancePatchModel(
  "mail.rtc_controller",
  "mail_livekit/static/src/models/rtc_controller_livekit.js",
  {
    /**
     * Override onClickDeafen to bypass original Odoo logic for LiveKit calls
     * @param {MouseEvent} ev
     */
    async onClickDeafen(ev) {
      console.log("🔇 LiveKit RTC Controller: onClickDeafen intercepted");

      // Check if this is a LiveKit call
      if (this.messaging.rtc && this.messaging.rtc.livekitEnabled) {
        console.log("🔇 LiveKit RTC Controller: Routing to LiveKit deafen logic");

        try {
          // Call our LiveKit deafen method directly, bypassing the original RTC session logic
          await this.messaging.rtc.toggleDeafen();
          console.log(
            "🔇 LiveKit RTC Controller: LiveKit deafen completed successfully"
          );
        } catch (error) {
          console.error("🔇 LiveKit RTC Controller: Error in LiveKit deafen:", error);
        }
      } else {
        // For non-LiveKit calls, use the original behavior
        console.log("🔇 LiveKit RTC Controller: Using original Odoo deafen logic");
        await this._super(ev);
      }
    },
  }
);
