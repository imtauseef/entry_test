/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { ListController } from "@web/views/list/list_controller";
import { FormController } from "@web/views/form/form_controller";

function isActionMenuHidden() {
    return Boolean(
        this.props.context && this.props.context.cbt_hide_action_menu
    );
}

patch(ListController.prototype, {
    get actionMenuItems() {
        if (isActionMenuHidden.call(this)) {
            return { action: [], print: [] };
        }
        return super.actionMenuItems;
    },
});

patch(FormController.prototype, {
    get actionMenuItems() {
        if (isActionMenuHidden.call(this)) {
            return { action: [], print: [] };
        }
        return super.actionMenuItems;
    },
});
