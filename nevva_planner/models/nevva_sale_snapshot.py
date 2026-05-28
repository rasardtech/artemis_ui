# -*- coding: utf-8 -*-
"""nevva.sale.snapshot — sale.order'ın geçmiş Envoyer versiyonlarını saklar.

Her Envoyer (NEVVA Planner'dan sale.order güncelleme) öncesi, NEVVA backend
mevcut state'i bu modele bir satır olarak kaydeder. Satıcı sale.order
form'undaki "NEVVA Geçmişi" smart button'a tıklayınca kanban popup'ta tüm
snapshot'lar sipariş satırı kartı gibi listelenir (tarih + render thumbnail
+ gönderen + toplam). Kartı açınca form view: büyük render + lines tablosu
+ eski PDF/JSON ek dosyaları.

NEVVA backend create yolu: XMLRPC ile `nevva.sale.snapshot.create(...)`.
Storage cap: env NEVVA_SO_SNAPSHOT_CAP (default 10) per sale.order.
"""
from odoo import fields, models
from odoo.exceptions import UserError


class NevvaSaleSnapshot(models.Model):
    _name = "nevva.sale.snapshot"
    _description = "NEVVA Sale Order Snapshot — Envoyer öncesi tasarım arşivi"
    _order = "created_at desc"
    _rec_name = "display_name"

    sale_order_id = fields.Many2one(
        "sale.order", string="Sipariş", required=True, ondelete="cascade",
        index=True,
    )
    # created_at — Odoo'nun standart create_date'i yerine NEVVA backend
    # tarafından set'lenen UTC timestamp (XMLRPC create payload'ında verilir).
    created_at = fields.Datetime(
        string="Snapshot Tarihi", required=True, default=fields.Datetime.now,
        index=True,
    )
    sender_email = fields.Char(
        string="Gönderen",
        help="Envoyer'a basan satıcının email'i (NEVVA tarafından "
             "current_user_obj.email veya project.staff_email'den çözülür)."
    )
    language = fields.Char(
        string="Dil", size=8,
        help="Snapshot oluştuğunda satıcının res.users.lang kısa kodu ('fr','en',...). "
             "Form view'da satır tablosu kolon başlıklarını bu dile göre gösterir.",
    )

    # Tutarlar (Envoyer öncesi snapshot anındaki)
    amount_untaxed = fields.Float(string="HT Tutar", digits=(16, 2))
    amount_total   = fields.Float(string="TTC Tutar", digits=(16, 2))
    currency_name  = fields.Char(string="Para Birimi", size=8)

    # Eski sale.order.line satırlarının JSON snapshot'ı — form view'da HTML
    # tabloya dönüştürülür. Format: [{"name":"...","qty":1.0,"unit":245.0,"subtotal":245.0}]
    lines_data = fields.Text(string="Satırlar JSON")

    # Eski dosyalar — ir.attachment referansları. Snapshot satırı silinince
    # attachment'lar da silinir (set_null değil restrict yok — basit cascade).
    render_attachment_id = fields.Many2one(
        "ir.attachment", string="Eski Render", ondelete="set null",
        help="Envoyer öncesi nevva_render_image alanından arşivlenen PNG.",
    )
    render_url = fields.Char(string="Eski Render URL")
    pdf_attachment_id = fields.Many2one(
        "ir.attachment", string="Eski BOM PDF", ondelete="set null",
    )
    json_attachment_id = fields.Many2one(
        "ir.attachment", string="Eski Proje JSON", ondelete="set null",
    )
    screenshot_attachment_id = fields.Many2one(
        "ir.attachment", string="Eski Ekran Görüntüsü", ondelete="set null",
    )

    # Display ve kanban için computed alanlar
    display_name = fields.Char(compute="_compute_display_name", store=True)
    render_thumbnail_url = fields.Char(compute="_compute_thumbnail_url")
    # Form view'da büyük render önizleme. Odoo 17 form arch'ta <img t-att-src>
    # (owl direktifi) YASAK → render'ı Html alanı + widget="html" ile gösteririz
    # (lines_html ile aynı desen, sanitize=False img tag'ini korur).
    render_html = fields.Html(string="Render", compute="_compute_render_html",
                              sanitize=False)
    line_count = fields.Integer(string="Satır Sayısı",
                                compute="_compute_line_count")
    lines_html = fields.Html(string="Satırlar Tablosu",
                             compute="_compute_lines_html", sanitize=False)

    def _compute_display_name(self):
        for rec in self:
            ts = rec.created_at.strftime("%Y-%m-%d %H:%M") if rec.created_at else ""
            sender = (rec.sender_email or "system").split("@")[0]
            rec.display_name = "%s · %s" % (ts, sender)

    def _compute_thumbnail_url(self):
        # Kanban kartında <img t-att-src="record.render_thumbnail_url.raw_value"/>
        # ile gösterilir (t-if attachment var diye gate'li). Attachment yoksa False —
        # eski placeholder.svg dosyası mevcut değildi (404 önlenir).
        for rec in self:
            rec.render_thumbnail_url = (
                "/web/image/%d" % rec.render_attachment_id.id
                if rec.render_attachment_id else False
            )

    # ── İndirme aksiyonları (form popup butonları) ──────────────────────────
    def _download_attachment(self, attachment, label):
        self.ensure_one()
        if not attachment:
            raise UserError("Bu sürümde %s yok." % label)
        return {
            "type": "ir.actions.act_url",
            "url": "/web/content/%d?download=true" % attachment.id,
            "target": "new",
        }

    def action_download_pdf(self):
        return self._download_attachment(self.pdf_attachment_id, "BOM PDF")

    def action_download_json(self):
        return self._download_attachment(self.json_attachment_id, "proje JSON")

    def action_download_render(self):
        return self._download_attachment(self.render_attachment_id, "render görseli")

    def action_open_planner_for_restore(self):
        """Güvenli "geri dön": teklifin NEVVA planner'ını aç. Satıcı planner'daki
        Sürüm Geçmişi'nden (her Envoyer otomatik snapshot'lanır) eski sürüme
        tam-sadakatle + undo'lu restore eder, sonra tekrar Envoyer'lar. Odoo
        siparişini doğrudan EZMEZ (ürünler planner'da doğru çözülür → güvenli)."""
        self.ensure_one()
        if not self.sale_order_id:
            raise UserError("Bu snapshot bir siparişe bağlı değil.")
        return self.sale_order_id.action_open_nevva_planner_so()

    def _compute_render_html(self):
        for rec in self:
            if rec.render_attachment_id:
                rec.render_html = (
                    "<img src='/web/image/%d' "
                    "style='max-width:600px;border:1px solid #e5e7eb;border-radius:8px' "
                    "alt='Eski render'/>" % rec.render_attachment_id.id
                )
            else:
                rec.render_html = False

    def _compute_line_count(self):
        import json as _json
        for rec in self:
            try:
                data = _json.loads(rec.lines_data or "[]")
                rec.line_count = len(data) if isinstance(data, list) else 0
            except Exception:
                rec.line_count = 0

    def _compute_lines_html(self):
        """lines_data JSON'unu form view'da HTML tablo olarak göster."""
        import json as _json
        # Per-language column headers (sender'ın diline göre)
        i18n = {
            "fr": {"product": "Produit", "qty": "Qté", "unit": "Prix unit.",
                   "total": "Sous-total", "empty": "(aucune ligne)"},
            "en": {"product": "Product", "qty": "Qty", "unit": "Unit price",
                   "total": "Subtotal", "empty": "(no lines)"},
            "nl": {"product": "Product", "qty": "Aantal", "unit": "Eenheidsprijs",
                   "total": "Subtotaal", "empty": "(geen regels)"},
            "tr": {"product": "Ürün", "qty": "Adet", "unit": "Birim",
                   "total": "Tutar", "empty": "(satır yok)"},
        }
        for rec in self:
            lang = (rec.language or "fr").lower()
            tx = i18n.get(lang, i18n["fr"])
            try:
                rows = _json.loads(rec.lines_data or "[]")
            except Exception:
                rows = []
            if not rows:
                rec.lines_html = (
                    "<p style='color:#999;font-style:italic;padding:8px'>%s</p>" % tx["empty"]
                )
                continue
            def _esc(s):
                return (str(s) if s is not None else "").replace("&", "&amp;").replace(
                    "<", "&lt;").replace(">", "&gt;")
            rows_html = "".join([
                "<tr>"
                "<td style='padding:6px 10px;border:1px solid #e5e7eb'>%s</td>"
                "<td style='padding:6px 10px;border:1px solid #e5e7eb;text-align:right'>%.2f</td>"
                "<td style='padding:6px 10px;border:1px solid #e5e7eb;text-align:right'>%.2f</td>"
                "<td style='padding:6px 10px;border:1px solid #e5e7eb;text-align:right'>%.2f</td>"
                "</tr>" % (
                    _esc(r.get("name", ""))[:120],
                    float(r.get("qty") or 0),
                    float(r.get("unit") or 0),
                    float(r.get("subtotal") or 0),
                )
                for r in rows if isinstance(r, dict)
            ])
            rec.lines_html = (
                "<table style='border-collapse:collapse;font-size:13px;width:100%%'>"
                "<thead><tr style='background:#f5f5f5'>"
                "<th style='padding:6px 10px;border:1px solid #e5e7eb;text-align:left'>%s</th>"
                "<th style='padding:6px 10px;border:1px solid #e5e7eb'>%s</th>"
                "<th style='padding:6px 10px;border:1px solid #e5e7eb'>%s</th>"
                "<th style='padding:6px 10px;border:1px solid #e5e7eb'>%s</th>"
                "</tr></thead>"
                "<tbody>%s</tbody>"
                "</table>" % (tx["product"], tx["qty"], tx["unit"], tx["total"], rows_html)
            )
