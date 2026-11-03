/** @odoo-module **/

import { registry } from "@web/core/registry";

/**
 * Managed CBT users are scoped to the CBT application only: they must not be
 * able to reach the Odoo Apps dashboard.  The server exposes ``cbt_managed``
 * and ``cbt_home_action_id`` in the session info (see models/ir_http.py).
 *
 * - The app switcher toggle is hidden with CSS.
 * - If a managed user lands on a page without an action (i.e. the Apps
 *   dashboard), the client reacts by opening the configured CBT home action.
 */
const CbtNavigation = {
    dependencies: ["action"],

    start(env, { action }) {
        const info = (odoo && odoo.__session_info__) || {};
        if (!info.cbt_managed) {
            return {};
        }

        // 1. Hide the app switcher (belt and braces with the CSS rule).
        if (!document.getElementById("cbt_hide_apps_menu")) {
            const style = document.createElement("style");
            style.setAttribute("id", "cbt_hide_apps_menu");
            style.textContent = `
                .o_navbar_apps_menu,
                .o_apps_menu_toggle,
                .o_menu_toggle {
                    display: none !important;
                }
            `;
            document.head.appendChild(style);
        }

        // 2. Pin the user to the CBT home action.  Whenever the current
        //    action is empty (the app dashboard), load the home action.
        const homeId = info.cbt_home_action_id;
        if (homeId) {
            let loading = false;
            const enforceHome = async () => {
                if (loading) {
                    return;
                }
                const controller = action.currentController;
                if (controller && controller.action && controller.action.type) {
                    return;
                }
                loading = true;
                try {
                    await action.doAction(homeId, { clearBreadcrumbs: true });
                } finally {
                    loading = false;
                }
            };
            // Run once after boot and on every navbar/action reset.
            setTimeout(enforceHome, 0);
            env.bus.addEventListener("ACTION_MANAGER:UI-UPDATED", () => {
                setTimeout(enforceHome, 0);
            });
        }

        return {};
    },
};

registry.category("services").add("cbt_navigation", CbtNavigation);
