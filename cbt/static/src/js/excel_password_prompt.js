/** @odoo-module **/

import { Component, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

class CbtExcelPasswordPrompt extends Component {
    static template = "cbt.ExcelPasswordPrompt";
    static props = ["*"];

    setup() {
        this.action = useService("action");
        this.state = useState({
            odooPassword: "",
            workbookPassword: "",
            confirmWorkbookPassword: "",
            error: "",
            busy: false,
        });
        this.params = this.props.action.params;
    }

    async submit(event) {
        event.preventDefault();
        if (this.state.busy) {
            return;
        }
        this.state.error = "";
        if (this.params.operation === "export") {
            if (this.state.workbookPassword.length < 12) {
                this.state.error =
                    "The workbook password must contain at least 12 characters.";
                return;
            }
            if (this.state.workbookPassword !==
                    this.state.confirmWorkbookPassword) {
                this.state.error = "The workbook passwords do not match.";
                return;
            }
        }

        this.state.busy = true;
        try {
            const response = await fetch("/cbt/excel/execute", {
                method: "POST",
                credentials: "same-origin",
                cache: "no-store",
                referrerPolicy: "same-origin",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    model: this.params.model,
                    method: this.params.method,
                    res_id: this.params.res_id,
                    context: this.params.context || {},
                    odoo_password: this.state.odooPassword,
                    workbook_password: this.state.workbookPassword,
                }),
            });
            const payload = await response.json();
            if (!response.ok || payload.error) {
                throw new Error(payload.error || "The Excel operation failed.");
            }
            this.clearPasswords();
            await this.action.doAction(payload.result);
        } catch (error) {
            this.clearPasswords();
            this.state.error = error.data?.arguments?.[0] ||
                error.data?.message || error.message ||
                "The Excel operation could not be completed.";
        } finally {
            this.state.busy = false;
        }
    }

    clearPasswords() {
        this.state.odooPassword = "";
        this.state.workbookPassword = "";
        this.state.confirmWorkbookPassword = "";
    }

    cancel() {
        this.action.doAction({ type: "ir.actions.act_window_close" });
    }
}

registry.category("actions").add(
    "cbt_excel_password_prompt", CbtExcelPasswordPrompt);
