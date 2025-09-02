/** @odoo-module **/

import {registerMessagingComponent} from "@mail/utils/messaging_component";

const {Component} = owl;

class GatewayFollowerView extends Component {
    /**
     * @override
     */
    setup() {
        super.setup();
        // Simplified setup for Odoo 15.0 compatibility
    }

    get composerGatewayFollower() {
        return this.props.record;
    }

    onChangeGatewayChannel(ev) {
        if (this.props.record && this.props.record.update) {
            this.props.record.update({
                channel: parseInt(ev.target.options[ev.target.selectedIndex].value, 10),
            });
        }
    }
}

Object.assign(GatewayFollowerView, {
    props: {record: Object},
    template: "mail_gateway.GatewayFollowerView",
});

registerMessagingComponent(GatewayFollowerView);
