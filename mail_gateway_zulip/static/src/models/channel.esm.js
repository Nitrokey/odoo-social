/** @odoo-module **/

import {registerPatch} from "@mail/model/model_core";

registerPatch({
    name: "Channel",
    recordMethods: {
        /**
         * @override
         */
        _generateAvatarGateway() {
            if (this.gateway && this.gateway.type === "zulip") {
                // Return a simple Zulip-style avatar or icon
                return false; // Use default for now
            }
            return this._super(...arguments);
        },
    },
});
