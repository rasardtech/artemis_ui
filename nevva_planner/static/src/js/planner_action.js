/** @odoo-module **/

/**
 * NEVVA Planner — Odoo client action (full screen iframe).
 *
 * Akış:
 *   1. crm.lead / sale.order butonu Python tarafında `ir.actions.client`
 *      döner: { tag: 'nevva_planner.open', params: { url, project_id, parent_model, parent_id } }
 *   2. Bu OWL component action'ı render eder: full-screen iframe + üst
 *      navigation bar Odoo'da kalır.
 *   3. Planner içinde satıcı "Envoyer" basınca planner-ui parent'a
 *      `postMessage({ type: 'nevva:envoyer_done', sale_order_id })` gönderir.
 *   4. Burada onMessage handler: orijin doğrulanır, action kapatılır,
 *      parent record (lead/SO) reload edilir → satıcı Odoo'da güncel kaydı görür.
 *
 * Güvenlik:
 *   - postMessage origin check: yalnız iframe'in geldiği origin'i kabul et.
 *   - Iframe URL'i Python tarafından HMAC-signed (sale.order için) veya
 *     tek-kullanımlık token'lı (crm.lead için) — JS asla secret görmez.
 */
import { Component, useState, onMounted, onWillUnmount, useRef } from "@odoo/owl";
import { registry } from "@web/core/registry";

class NevvaPlannerAction extends Component {
    static template = "nevva_planner.PlannerAction";
    static props = ["*"];

    setup() {
        // Odoo 17.x versiyonları arasında client action props yapısı değişiyor.
        // 6 farklı path'den URL'i ara: action.params, props.params, action.context
        // (nevva_planner_url key'i ile), props.context, action.kwargs, root props.
        // Python tarafı da hem params hem context'e yazıyor → bir tanesi tutar.
        const p = this.props || {};
        const action = p.action || {};
        const ctx = action.context || p.context || {};

        const url =
            (action.params && action.params.url) ||
            (p.params && p.params.url) ||
            ctx.nevva_planner_url ||
            p.url ||
            "";
        const projectId =
            (action.params && action.params.project_id) ||
            (p.params && p.params.project_id) ||
            ctx.nevva_planner_project_id ||
            null;
        const parentModel =
            (action.params && action.params.parent_model) ||
            (p.params && p.params.parent_model) ||
            ctx.nevva_planner_parent_model ||
            null;
        const parentId =
            (action.params && action.params.parent_id) ||
            (p.params && p.params.parent_id) ||
            ctx.nevva_planner_parent_id ||
            null;

        // eslint-disable-next-line no-console
        console.log("[NEVVA Planner action] props =", this.props,
                    "resolved url =", url, "project =", projectId);

        this.state = useState({
            url: url,
            loading: !!url,
            error: null,
        });
        this.parentModel = parentModel;
        this.parentId    = parentId;
        this.expectedOrigin = this._origin(url);
        // params reference for error fallback
        const params = { url, project_id: projectId, parent_model: parentModel, parent_id: parentId };

        this.iframeRef = useRef("iframe");
        this._onMessage = this._onMessage.bind(this);

        onMounted(() => {
            window.addEventListener("message", this._onMessage);
        });
        onWillUnmount(() => {
            window.removeEventListener("message", this._onMessage);
        });

        if (!params.url) {
            // Telefondan console açılamıyor → debug bilgisini doğrudan
            // ekrana yaz. Hangi prop path'inde ne var, JSON olarak göster.
            let debugInfo = "";
            try {
                debugInfo = JSON.stringify({
                    has_props: !!this.props,
                    has_props_action: !!(this.props && this.props.action),
                    has_props_params: !!(this.props && this.props.params),
                    action_keys: this.props && this.props.action
                        ? Object.keys(this.props.action) : [],
                    props_keys: this.props ? Object.keys(this.props) : [],
                    action_params: this.props && this.props.action
                        ? this.props.action.params : null,
                    props_params: this.props ? this.props.params : null,
                }, null, 2);
            } catch (e) {
                debugInfo = "JSON stringify failed: " + e.message;
            }
            this.state.error = "Planner URL eksik. Debug:\n" + debugInfo;
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
        // Yalnız iframe'imizden gelen mesajları kabul et — başka origin'ler
        // (extensions, dev tools, vb.) bypass'lamasın.
        if (!this.expectedOrigin || event.origin !== this.expectedOrigin) {
            return;
        }
        const data = event.data || {};
        if (data.type === "nevva:envoyer_done") {
            // Planner kaydı Odoo'ya gönderdi → action'ı kapat, parent record'u reload et.
            await this._closeAndRefresh(data);
        } else if (data.type === "nevva:planner_ready") {
            // Planner SPA mount oldu — loading state'i temizle (iframe load
            // event'inden daha güvenilir; SPA route yüklenmesi geciktirebilir).
            this.state.loading = false;
        } else if (data.type === "nevva:close_request") {
            // Planner içinden kullanıcı "kapat" istedi (örn. iptal).
            this._close();
        }
    }

    async _closeAndRefresh(data) {
        const actionService = this.env.services.action;
        // Önce action'ı kapat — breadcrumb'tan parent form'a döner.
        try {
            await actionService.doAction({ type: "ir.actions.act_window_close" });
        } catch (_) { /* zaten kapalıysa sessiz geç */ }

        // Parent record varsa onu form view'da yeniden aç → güncel sale.order
        // alanları (lines, attachments, status) görünür.
        if (this.parentModel && this.parentId) {
            try {
                await actionService.doAction({
                    type: "ir.actions.act_window",
                    res_model: this.parentModel,
                    res_id: this.parentId,
                    views: [[false, "form"]],
                    target: "current",
                });
            } catch (e) {
                // Refresh fail — sessiz, breadcrumb zaten parent'a döndü.
                console.warn("NEVVA: parent refresh atlandı", e);
            }
        }

        // Sale order numarası geldiyse bildirim göster.
        if (data.sale_order_name) {
            const notif = this.env.services.notification;
            if (notif) {
                notif.add(
                    `Sipariş güncellendi: ${data.sale_order_name}`,
                    { type: "success", sticky: false },
                );
            }
        }
    }

    _close() {
        this.env.services.action.doAction({ type: "ir.actions.act_window_close" });
    }
}

registry.category("actions").add("nevva_planner.open", NevvaPlannerAction);
