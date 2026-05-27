import base64
import logging

from odoo import models, fields, api
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class SaleOrder(models.Model):
    _inherit = "sale.order"

    nevva_project_id = fields.Char(
        string="NEVVA Project ID", readonly=True, copy=False, index=True,
        help="Bu teklifi oluşturan NEVVA planner projesinin kimliği.",
    )
    nevva_planner_url = fields.Char(
        string="NEVVA Planner URL", readonly=True, copy=False,
        help="Tasarımı NEVVA planner'da açmak için link.",
    )
    nevva_ar_url = fields.Char(
        string="NEVVA AR / 3D URL", readonly=True, copy=False,
        help="Müşterinin telefonunda AR (artırılmış gerçeklik) görünümü linki.",
    )
    nevva_render_url = fields.Char(
        string="NEVVA AI Render URL", readonly=True, copy=False,
        help="Foto-realistik AI render görselinin orijinal linki.",
    )
    nevva_render_image = fields.Image(
        string="AI Render", readonly=True, copy=False,
        help="Tasarımın foto-realistik AI render önizlemesi.",
    )
    nevva_screenshot = fields.Image(
        string="3D Görünüm", readonly=True, copy=False,
        help="NEVVA planner 3D sahnesinin ekran görüntüsü.",
    )
    nevva_project_json = fields.Text(
        string="NEVVA Proje Verisi (JSON)", readonly=True, copy=False,
        help="Planner'da yeniden yüklenebilir tam proje verisi.",
    )
    nevva_project_json_file = fields.Binary(
        string="Proje Verisi (JSON dosyası)", copy=False, attachment=False,
        compute="_compute_nevva_project_json_file",
        help="Proje JSON'unu dosya olarak indir.",
    )
    nevva_project_json_filename = fields.Char(
        compute="_compute_nevva_project_json_file",
    )
    nevva_pdf = fields.Binary(
        string="Commande PDF", readonly=True, copy=False, attachment=False,
        help="NEVVA fiş/teknik döküm PDF'i — sekmede satır içi görüntülenir.",
    )
    nevva_pdf_filename = fields.Char(
        string="PDF Dosya Adı", readonly=True, copy=False,
    )
    nevva_pending = fields.Boolean(
        string="NEVVA: Bekleyen Değişiklik", readonly=True, copy=False, default=False,
        help="Müşteri/temsilci tasarımı NEVVA Planner'da değiştirdi ama henüz "
             "Odoo'ya göndermedi. Bu tekliftekiler güncel olmayabilir.",
    )
    nevva_installation_breakdown = fields.Text(
        string="Montaj Puanı Kırılımı", readonly=True, copy=False,
        help="Bu teklifin montaj puanı hangi modül/panel/extra'lardan toplandı? "
             "NEVVA gönderiminde otomatik üretilir; satıcı bu kırılıma bakıp "
             "müşteriye fiyat itirazlarında savunma yapar.",
    )

    @api.depends("nevva_project_json", "nevva_project_id")
    def _compute_nevva_project_json_file(self):
        for order in self:
            data = order.nevva_project_json
            if data:
                order.nevva_project_json_file = base64.b64encode(
                    data.encode("utf-8"))
                ref = order.nevva_project_id or str(order.id or "projet")
                order.nevva_project_json_filename = "nevva_%s.json" % ref[:32]
            else:
                order.nevva_project_json_file = False
                order.nevva_project_json_filename = False

    def nevva_get_planner_payload(self):
        """JS client action stateless fetch — bkz crm_lead.nevva_get_planner_payload."""
        self.ensure_one()
        action = self.action_open_nevva_planner_so()
        return action.get("params", {}) if isinstance(action, dict) else {}

    def action_open_nevva_planner_so(self):
        """Bu teklifin tasarımını NEVVA planner'da Odoo içinde (v1.6.0+) full-screen
        client action olarak açar.

        /api/odoo/reopen?project_id=...&ts=...&sig=... — HMAC-signed URL
        (audit 1.1): secret URL'de görünmez, yalnızca tek seferlik imza
        gönderilir, 5 dakika içinde geçerlidir. Browser history / proxy log
        sızıntı yüzeyi minimize edilir.

        project_id URL-encode edilir (audit 1.4)."""
        import hashlib
        import hmac as _hmac
        import time as _time
        from urllib.parse import urlencode
        self.ensure_one()
        project_id = self.nevva_project_id or self.client_order_ref or ""
        if project_id:
            from .crm_lead import _nevva_origin
            icp = self.env["ir.config_parameter"].sudo()
            base = _nevva_origin(icp.get_param("nevva_planner.url"))
            secret = (icp.get_param("nevva_planner.inbound_secret") or "").strip()
            if base and secret:
                ts = int(_time.time())
                sig = _hmac.new(
                    secret.encode(),
                    ("%s:%d" % (project_id, ts)).encode(),
                    hashlib.sha256,
                ).hexdigest()[:32]
                query = urlencode({
                    "project_id": project_id, "ts": ts, "sig": sig,
                })
                url = "%s/api/odoo/reopen?%s" % (base, query)
                # Client action ile Odoo içinde aç (yeni sekme yerine).
                # Shotgun: params + context her ikisine yaz, JS hangisini
                # bulursa kullanır (Odoo 17.x props uyumluluğu).
                _payload = {
                    "url":          str(url),
                    "project_id":   str(project_id),
                    "parent_model": "sale.order",
                    "parent_id":    int(self.id),
                }
                _logger.info("NEVVA client action return payload (SO): %s", _payload)
                return {
                    "type":    "ir.actions.client",
                    "tag":     "nevva_planner.open",
                    "name":    "NEVVA Planner — %s" % (self.name or ""),
                    "target":  "current",
                    "params":  _payload,
                    "context": {
                        "nevva_planner_url":          _payload["url"],
                        "nevva_planner_project_id":   _payload["project_id"],
                        "nevva_planner_parent_model": _payload["parent_model"],
                        "nevva_planner_parent_id":    _payload["parent_id"],
                    },
                }
        # Geriye dönük: proje id yoksa kaydedilmiş URL'i dene (eski sekme akışı).
        return self._nevva_open_url(self.nevva_planner_url, "NEVVA planner")

    def action_open_nevva_ar(self):
        """AR / 3D görünümünü yeni sekmede açar."""
        return self._nevva_open_url(self.nevva_ar_url, "AR görünümü")

    def action_open_nevva_render(self):
        """AI render görselini yeni sekmede açar."""
        return self._nevva_open_url(self.nevva_render_url, "AI render")

    def _nevva_open_url(self, url, label):
        self.ensure_one()
        if not url:
            raise UserError("Bu teklife bağlı bir %s linki yok." % label)
        return {"type": "ir.actions.act_url", "url": url, "target": "new"}

    def write(self, vals):
        res = super().write(vals)
        # Durum değişince NEVVA'ya bildir (commit sonrası, transaction'ı bloklamadan).
        if vals.get("state"):
            for order in self:
                if order.nevva_project_id:
                    order._nevva_notify_state(order.nevva_project_id, vals["state"])
        return res

    def _nevva_notify_state(self, project_id, state):
        icp = self.env["ir.config_parameter"].sudo()
        from .crm_lead import _nevva_origin
        base = _nevva_origin(icp.get_param("nevva_planner.url"))
        secret = icp.get_param("nevva_planner.inbound_secret") or ""
        if not base or not secret:
            return

        order_id = self.id
        from ._constants import (
            NEVVA_SALE_STATE_PATH, NEVVA_TIMEOUT_NOTIFY, NEVVA_TLS_VERIFY,
        )

        def _do():
            import requests  # lazy
            try:
                resp = requests.post(
                    "%s%s" % (base, NEVVA_SALE_STATE_PATH),
                    json={"project_id": project_id, "state": state},
                    headers={"X-Odoo-Source": secret},
                    timeout=NEVVA_TIMEOUT_NOTIFY,
                    verify=NEVVA_TLS_VERIFY,
                )
                resp.raise_for_status()
                # Audit 8.4: başarı log'u (debug için minimal context)
                _logger.info(
                    "NEVVA sale-state bildirildi: order=%s, project=%s, state=%s",
                    order_id, project_id, state,
                )
            except Exception:
                # Audit 2.1: context'li warning — manuel takip / cron retry için.
                # Sessizce yutmak yerine order_id + project_id + state log'lanır.
                _logger.warning(
                    "NEVVA sale-state bildirimi başarısız: order=%s, project=%s, "
                    "state=%s — NEVVA'da durum güncel olmayabilir, manuel kontrol",
                    order_id, project_id, state, exc_info=True,
                )

        # Odoo 16+ — transaction commit edilince çalışır (write'ı bloklamaz/rollback'lemez)
        self.env.cr.postcommit.add(_do)


class SaleOrderLine(models.Model):
    """Satıcı (sıradan kullanıcı) NEVVA'dan gelen sale.order satırlarını ELLE
    DÜZENLEYEMEZ — sadece görüntüleme; değişiklik için NEVVA planner'a dönüp
    'Envoyer' ile yeniden gönderir. Tek kanaldan akan veri = NEVVA ↔ Odoo
    tutarlılığı.

    Aktivasyon: `ir.config_parameter` 'nevva_planner.lock_sale_order_lines'
    True ise guard aktif; aksi halde tamamen bypass (default davranış). Yeni
    kurulumlar tarafından unintended UI bozulma yaşanmasın diye DEFAULT KAPALI.
    Admin Settings → NEVVA Planner → "Satır kilidi" toggle'ından açar.

    Aktifken bypass'lar:
      a) base.group_system (sistem yöneticisi) — acil düzeltme yetkisi
      b) context['nevva_sync'] == True — NEVVA backend XMLRPC çağrılarında
         set edilir; manuel UI bunu set edemez → tek-yön invariant korunur

    Etki: write / create / unlink üzerinde guard. Order satır-dışı alanlar
    (state, fiscal_position, vb.) etkilenmez."""
    _inherit = "sale.order.line"

    def _nevva_lock_enabled(self):
        """Config flag — admin açmadıysa guard tamamen kapalı."""
        try:
            param = self.env["ir.config_parameter"].sudo().get_param(
                "nevva_planner.lock_sale_order_lines", "False",
            )
            return str(param).lower() in ("1", "true", "yes")
        except Exception:
            return False

    def _nevva_should_skip(self):
        """True → guard atlanır. NEVVA backend context flag'i veya admin user."""
        if self.env.context.get("nevva_sync"):
            return True
        return self.env.user.has_group("base.group_system")

    def _nevva_locked_msg(self):
        return ("Bu satır NEVVA tasarımına bağlı bir teklife ait — doğrudan "
                "düzenlenemez. Değişiklik için NEVVA planner'da düzenleyip "
                "'Envoyer' ile yeniden gönderin. (Sadece yönetici doğrudan "
                "değiştirebilir.)")

    def write(self, vals):
        if self._nevva_lock_enabled() and not self._nevva_should_skip():
            for line in self:
                if line.order_id and line.order_id.nevva_project_id:
                    raise UserError(self._nevva_locked_msg())
        return super().write(vals)

    @api.model_create_multi
    def create(self, vals_list):
        if self._nevva_lock_enabled() and not self._nevva_should_skip():
            order_ids = {v.get("order_id") for v in vals_list if v.get("order_id")}
            if order_ids:
                nevva_orders = self.env["sale.order"].browse(list(order_ids)).filtered(
                    lambda o: o.nevva_project_id,
                )
                if nevva_orders:
                    raise UserError(self._nevva_locked_msg())
        return super().create(vals_list)

    def unlink(self):
        if self._nevva_lock_enabled() and not self._nevva_should_skip():
            for line in self:
                if line.order_id and line.order_id.nevva_project_id:
                    raise UserError(self._nevva_locked_msg())
        return super().unlink()
