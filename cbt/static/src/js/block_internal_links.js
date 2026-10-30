/** @odoo-module **/

import { registry } from "@web/core/registry";

/**
 * Block record-opening "internal links" for everyone inside the CBT app.
 *
 * Two kinds of links are neutralised:
 *   1. many2one / many2many record links (clicking the value to open the
 *      linked record's form);
 *   2. breadcrumb items (clicking a breadcrumb to jump to a parent record).
 *
 * The block is implemented with a capture-phase click listener on ``document``
 * so it is tolerant to the internal changes of the different field/component
 * implementations across releases: any click landing on a many2one link or a
 * breadcrumb is stopped before the component handler runs.
 *
 * It is only active when the session belongs to the CBT app: either the
 * ``cbt_managed`` flag is set (managed users) or a CBT menu/action is being
 * displayed (see cbt_home_action_id / body data attribute set by the client).
 */
const BLOCKED_SELECTORS = [
    // many2one / many2many record links in form & list views
    ".o_field_many2one .o_form_uri",
    ".o_field_many2one input ~ .o_form_uri",
    ".o_field_widget.o_field_many2one .o_external_button",
    ".o_field_many2many .o_form_uri",
    // clickable list cell links to related records
    ".o_list_table .o_field_many2one a",
    // breadcrumbs
    ".o_breadcrumb .o_last_breadcrumb_item",
    ".o_breadcrumb a",
    ".o_control_panel .breadcrumb a",
    ".o_control_panel .breadcrumb-item a",
];

function isCbtSession() {
    const info = (typeof odoo !== "undefined" && odoo.__session_info__) || {};
    if (info.cbt_managed || info.cbt_home_action_id) {
        return true;
    }
    // Fallback: detect a CBT action / menu currently displayed.
    return Boolean(
        document.body &&
            (document.body.dataset.cbtBlockLinks === "1" ||
                document.querySelector(".o_menu_brand[data-cbt-brand='1']"))
    );
}

const CbtBlockInternalLinks = {
    start() {
        if (!isCbtSession()) {
            return {};
        }
        const selector = BLOCKED_SELECTORS.join(",");
        const blocker = (ev) => {
            const target = ev.target;
            if (!target || !target.closest) {
                return;
            }
            const hit = target.closest(selector);
            if (!hit) {
                return;
            }
            ev.preventDefault();
            ev.stopPropagation();
            // Swallow the click entirely: no navigation to the target record.
            return false;
        };
        document.addEventListener("click", blocker, true);
        document.addEventListener("auxclick", blocker, true);
        return {
            stop() {
                document.removeEventListener("click", blocker, true);
                document.removeEventListener("auxclick", blocker, true);
            },
        };
    },
};

registry.category("services").add("cbt_block_internal_links", CbtBlockInternalLinks);
