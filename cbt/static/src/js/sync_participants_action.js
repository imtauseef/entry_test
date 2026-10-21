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
        const created = (result.created || []).length;
        const updated = (result.updated || []).length;
        const archived = (result.archived || []).length;
        const skipped = result.skipped || [];
        let message = "Participants synchronized!\n"
            + `Created: ${created}\nUpdated: ${updated}\nArchived: ${archived}\n`
            + `Skipped: ${skipped.length}`;
        if (skipped.length) {
            message += "\n\nSkipped rows:\n" + skipped
                .map((row) => `${row.login || "(no login)"}: ${row.reason}`)
                .join("\n");
        }
        if (result.security_warning) {
            message += "\n\nSecurity warning:\n" + result.security_warning;
        }
        alert(message);
        window.location.reload();
    } else {
        console.error(result && result["error"]);
        alert(result && result["msg"]);
    }
});
