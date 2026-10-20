/** @odoo-module **/

import { registry } from "@web/core/registry";

registry.category("actions").add("cbt_sync_participants", async (env) => {
    const result = await env.services.rpc("/web/dataset/call_kw", {
        model: "cbt.participant",
        method: "fetch_participant",
        args: [],
        kwargs: {},
    });
    if (result && result["status"] === "updated") {
        alert("Participants Synchronized!");
        window.location.reload();
    } else {
        console.error(result && result["error"]);
        alert(result && result["msg"]);
    }
});
