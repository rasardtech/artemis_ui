/** @odoo-module **/

/**
 * NEVVA Planner — Odoo client action (full screen iframe).
 *
 * Akış:
 *   1. crm.lead / sale.order butonu Python tarafında `ir.actions.client`
 *      döner: { tag: 'nevva_planner.open', params: { url, project_id, parent_model, parent_id } }
 *   2. Bu OWL component action'ı render eder: full-screen iframe + üst
 *      navigation bar Odoo'da kalır.
 *   3. Refresh-safe: params kayıpsa context'teki active_id+active_model'i okuyup
 *      Python'a RPC ile `nevva_get_planner_payload` çağrısı yapar — taze URL gelir.
 *   4. Planner içinde satıcı "Envoyer" basınca planner-ui parent'a
 *      `postMessage({ type: 'nevva:envoyer_done', sale_order_id })` gönderir.
 *   5. onMessage handler: orijin doğrulanır, action kapatılır, parent record reload edilir.
 */
import { Component, useState, onMounted, onWillUnmount, useRef } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

class NevvaPlannerAction extends Component {
    static template = "nevva_planner.PlannerAction";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.actionService = useService("action");
        this.notification = useService("notification");

        // İlk olarak in-memory params'tan oku (button click freshly opened ise dolu olur).
        // Birden fazla path dene — Odoo 17.x sürümleri arasında props yapısı tutarsız.
        const p = this.props || {};
        const action = p.action || {};
        const ctx = action.context || p.context || {};

        const initialUrl =
            (action.params && action.params.url) ||
            (p.params && p.params.url) ||
            ctx.nevva_planner_url ||
            p.url ||
            "";
        const initialProjectId =
            (action.params && action.params.project_id) ||
            ctx.nevva_planner_project_id ||
            null;
        const initialParentModel =
            (action.params && action.params.parent_model) ||
            ctx.nevva_planner_parent_model ||
            ctx.active_model ||  // CRM lead button → active_model = "crm.lead"
            null;
        const initialParentId =
            (action.params && action.params.parent_id) ||
            ctx.nevva_planner_parent_id ||
            ctx.active_id ||      // Odoo standart: button'a basınca active_id set'lenir
            null;

        this.state = useState({
            url: initialUrl,
            loading: true,
            error: null,
        });
        this.parentModel = initialParentModel;
        this.parentId    = initialParentId;
        this.expectedOrigin = this._origin(initialUrl);

        this.iframeRef = useRef("iframe");
        this._onMessage = this._onMessage.bind(this);

        onMounted(() => {
            window.addEventListener("message", this._onMessage);
            // URL boşsa stateless fetch — refresh/back-forward sonrası tek
            // hayatta kalan bilgi active_id+active_model. Backend'den tekrar al.
            if (!initialUrl) {
                this._fetchPayloadStateless();
            }
        });
        onWillUnmount(() => {
            window.removeEventListener("message", this._onMessage);
        });
    }

    async _fetchPayloadStateless() {
        // Context'teki active_id ile parent record'tan payload çek.
        const model = this.parentModel;
        const id = this.parentId;
        if (!model || !id) {
            this.state.loading = false;
            this.state.error =
                "Planner açılamadı: kayıt referansı eksik (active_id/active_model). " +
                "Bu sayfaya doğrudan navigasyon değil, CRM lead veya sale.order " +
                "formundaki 'NEVVA Planner' butonundan açın.";
            return;
        }
        try {
            const payload = await this.orm.call(model, "nevva_get_planner_payload", [[Number(id)]]);
            if (payload && payload.url) {
                this.state.url = payload.url;
                this.expectedOrigin = this._origin(payload.url);
                // parentModel/Id zaten doğru — payload'tan teyit et
                this.parentModel = payload.parent_model || this.parentModel;
                this.parentId    = payload.parent_id    || this.parentId;
            } else {
                this.state.loading = false;
                this.state.error =
                    "Planner URL alınamadı: backend boş payload döndü. " +
                    "NEVVA URL/Secret yapılandırılmamış olabilir " +
                    "(Settings → NEVVA Planner).";
            }
        } catch (e) {
            this.state.loading = false;
            const msg = (e && (e.message || e.data?.message)) || String(e);
            this.state.error =
                "Planner backend hatası: " + msg.slice(0, 300);
        }
    }

    _origin(url) {
        if (!url) return null;
        try { return new URL(url).origin; } catch (_) { return null; }
    }

    _onIframeLoad() {
        this.state.loading = false;
    }

    async _onMessage(event) {
        if (!this.expectedOrigin || event.origin !== this.expectedOrigin) {
            return;
        }
        const data = event.data || {};
        if (data.type === "nevva:envoyer_done") {
            await this._closeAndRefresh(data);
        } else if (data.type === "nevva:planner_ready") {
            this.state.loading = false;
        } else if (data.type === "nevva:close_request") {
            this._close();
        }
    }

    async _closeAndRefresh(data) {
        try {
            await this.actionService.doAction({ type: "ir.actions.act_window_close" });
        } catch (_) { /* zaten kapalı */ }

        if (this.parentModel && this.parentId) {
            try {
                await this.actionService.doAction({
                    type: "ir.actions.act_window",
                    res_model: this.parentModel,
                    res_id: Number(this.parentId),
                    views: [[false, "form"]],
                    target: "current",
                });
            } catch (e) {
                // sessiz
            }
        }
        if (data.sale_order_name) {
            this.notification.add(
                `Sipariş güncellendi: ${data.sale_order_name}`,
                { type: "success", sticky: false },
            );
        }
    }

    _close() {
        this.actionService.doAction({ type: "ir.actions.act_window_close" });
    }
}

registry.category("actions").add("nevva_planner.open", NevvaPlannerAction);
