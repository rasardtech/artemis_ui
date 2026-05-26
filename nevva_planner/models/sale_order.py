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

    def action_open_nevva_planner_so(self):
        """Bu teklifin tasarımını NEVVA planner'da yeni sekmede açar.

        /api/odoo/reopen?project_id=...&ts=...&sig=... — HMAC-signed URL
        (audit 1.1): secret URL'de görünmez, yalnızca tek seferlik imza
        gönderilir, 5 dakika içinde geçerlidir. Browser history / proxy log
        sızıntı yüzeyi minimize edilir.

        project_id URL-encode edilir (audit 1.4)."""
        import hashlib
        import hmac as _hmac
        import time as _time
        from urllib.parse import urlencode, quote
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
                return {
                    "type": "ir.actions.act_url",
                    "url": "%s/api/odoo/reopen?%s" % (base, query),
                    "target": "new",
                }
        # Geriye dönük: proje id yoksa kaydedilmiş URL'i dene.
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

        def _do():
            import requests  # lazy
            try:
                requests.post(
                    "%s/api/odoo/sale-state" % base,
                    json={"project_id": project_id, "state": state},
                    headers={"X-Odoo-Source": secret},
                    timeout=10,
                )
            except Exception:
                _logger.warning("NEVVA sale-state bildirimi başarısız", exc_info=True)

        # Odoo 16+ — transaction commit edilince çalışır (write'ı bloklamaz/rollback'lemez)
        self.env.cr.postcommit.add(_do)
