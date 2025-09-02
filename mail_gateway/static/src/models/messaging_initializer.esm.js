/** @odoo-module **/

import {registerPatch} from "@mail/model/model_core";

registerPatch({
    name: "MessagingInitializer",
    recordMethods: {
        async _init({gateways}) {
            await this._super(...arguments);
            const discuss = this.messaging.discuss;
            if (gateways && gateways.length > 0) {
                // For Odoo 15.0, we need to handle gateway integration differently
                // Store gateway info for later use
                this.messaging.gatewayData = gateways;

                // Try to integrate with discuss sidebar if available
                if (discuss && this.messaging.models.DiscussSidebarCategory) {
                    this.messaging.executeGracefully(
                        gateways.map((gatewayData) => () => {
                            try {
                                this.messaging.models.DiscussSidebarCategory.insert({
                                    discussAsGateways: discuss,
                                    gateway: gatewayData,
                                    gateway_id: gatewayData.id,
                                });
                            } catch (error) {
                                console.warn(
                                    "Gateway sidebar integration failed:",
                                    error
                                );
                            }
                        })
                    );
                }
            }
        },
    },
});
