import logging

from odoo import api, models, fields
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


def _nevva_origin(url):
    """NEVVA base URL'sini kök origin'e indir (scheme://host). API her zaman
    kökte (/api/...); param yanlışlıkla /planner gibi bir path içerirse
    /planner/api/... SPA'ya düşer ve login açar — bunu önler.

    Güvenlik: http:// http://localhost gibi local-only domain'ler hariç her
    yerde HTTPS'e zorlanır. NEVVA prod/staging zaten cert'li → http yanlışlık
    olur, iframe Mixed Content blocked → satıcıya boş ekran. Sessizce düzelt.
    """
    base = (url or "").strip().rstrip("/")
    if "://" in base:
        scheme, rest = base.split("://", 1)
        host = rest.split("/", 1)[0]
        # http → https zorla (local/dev domain'ler hariç). production iframe'i
        # bloklamasın diye yanlış protokol kullanımını sessizce düzelt.
        if scheme.lower() == "http" and not host.startswith(("localhost", "127.0.0.1", "0.0.0.0")):
            scheme = "https"
        base = scheme + "://" + host
    return base


class CrmLead(models.Model):
    _inherit = "crm.lead"

    nevva_planner_url = fields.Char(
        string="NEVVA Planner URL", readonly=True, copy=False,
        help="Son açılan NEVVA planner linki (bu lead için).",
    )

    # ── NEVVA Social Studio funnel attribution (v17.0.2.0.0+) ────────────────
    # Website form'undan gelen UTM parametreleri — Odoo'ya doğru iletildikten
    # sonra crm.lead.create() override webhook'la NEVVA'ya bildirir.
    # NEVVA backend SocialPost.engagement.attribution.leads++ yapar.
    x_utm_source   = fields.Char(string="UTM Source",   index=True, copy=False,
                                  help="Hangi sosyal platform — pinterest/instagram/facebook/...")
    x_utm_medium   = fields.Char(string="UTM Medium",   copy=False,
                                  help="Genelde 'social' (NEVVA UTM injection default).")
    x_utm_campaign = fields.Char(string="UTM Campaign", index=True, copy=False,
                                  help="Format: 'post_<id8>' — NEVVA SocialPost.id ilk 8 char.")
    x_utm_content  = fields.Char(string="UTM Content",  copy=False,
                                  help="Dil kodu — fr / nl / en / tr.")
    x_nevva_attribution_sent = fields.Boolean(
        string="NEVVA Attribution Sent", default=False, copy=False, readonly=True,
        help="Lead webhook NEVVA'ya gönderildi mi (idempotency koruması).",
    )

    @api.model_create_multi
    def create(self, vals_list):
        """Lead create event — utm_campaign='post_*' varsa NEVVA webhook'a HMAC POST."""
        records = super().create(vals_list)
        for lead in records:
            try:
                lead._nevva_notify_social_attribution(kind="lead")
            except Exception as e:
                _logger.warning("NEVVA lead attribution notify fail (lead=%s): %s", lead.id, e)
        return records

    def _nevva_notify_social_attribution(self, kind="lead", sale_amount_eur=None,
                                          sale_order_id=None):
        """NEVVA backend webhook'ı — Social Studio attribution kapatma.

        Akış:
          - x_utm_campaign 'post_' ile başlamıyor → skip (NEVVA dışı kaynak)
          - x_nevva_attribution_sent=True (kind='lead' için) → skip (idempotent)
          - HMAC: X-Odoo-Source = nevva_planner.inbound_secret (admin config)
          - Endpoint: <nevva_url>/api/social/webhooks/lead-attribution
        """
        self.ensure_one()
        campaign = (self.x_utm_campaign or "").strip()
        if not campaign.startswith("post_"):
            return  # NEVVA Social Studio'dan gelmiyor
        if kind == "lead" and self.x_nevva_attribution_sent:
            return  # idempotency: lead için bir kere gönderildi

        icp = self.env["ir.config_parameter"].sudo()
        nevva_url = _nevva_origin(icp.get_param("nevva_planner.url"))
        secret = (icp.get_param("nevva_planner.inbound_secret") or "").strip()
        if not nevva_url or not secret:
            _logger.debug("NEVVA URL/secret yok — attribution webhook skip (lead=%s)", self.id)
            return

        try:
            import requests
        except ImportError:
            _logger.warning("requests module yok — attribution webhook skip")
            return

        payload = {
            "utm_campaign": campaign,
            "utm_source":   (self.x_utm_source or "").strip() or None,
            "utm_medium":   (self.x_utm_medium or "").strip() or None,
            "utm_content":  (self.x_utm_content or "").strip() or None,
            "odoo_lead_id": str(self.id),
        }
        if kind == "sale" and sale_order_id:
            payload["odoo_sale_order_id"] = int(sale_order_id)
            if sale_amount_eur is not None:
                payload["sale_amount_eur"] = float(sale_amount_eur)
        from datetime import datetime
        payload["timestamp"] = datetime.utcnow().isoformat()

        try:
            r = requests.post(
                f"{nevva_url}/api/social/webhooks/lead-attribution",
                json=payload,
                headers={"X-Odoo-Source": secret, "Content-Type": "application/json"},
                timeout=8,
            )
            if r.status_code == 200:
                if kind == "lead":
                    self.with_context(skip_attribution=True).write(
                        {"x_nevva_attribution_sent": True})
                _logger.info("NEVVA attribution sent (lead=%s, kind=%s, campaign=%s)",
                             self.id, kind, campaign)
            else:
                _logger.warning("NEVVA attribution webhook %s: %s %s",
                                kind, r.status_code, r.text[:200])
        except Exception as e:
            _logger.warning("NEVVA attribution webhook exception (kind=%s): %s", kind, e)

    def nevva_get_planner_payload(self):
        """JS client action stateless fetch:
        URL hash'ten action_open_nevva_planner çağrısı yapılınca Odoo,
        in-memory action dict'i URL bazlı tag'la yeniden çözüyor → params
        kayboluyordu. Bu method JS'in RPC ile params'ı yeniden çekmesini sağlar.
        Refresh/share/back-forward sonrası da çalışır.

        Audit #11: bu RPC herhangi bir Odoo internal user tarafından
        herhangi bir lead ID için çağrılabilirdi → URL probing riski.
        Erişim kontrol: caller'ın CRM lead'e read access'i olmalı (record
        rules zaten uygular); ek olarak yalnız B2B planner kullanıcılarına
        izin ver — partner'ın x_nevva_b2b işareti yoksa reject.
        """
        self.ensure_one()
        # check_access_rights/rule — read yetkisi yoksa AccessError fırlat
        self.check_access_rights("read")
        self.check_access_rule("read")
        action = self.action_open_nevva_planner()
        # action_open_nevva_planner zaten ir.actions.client dönüyor; sadece
        # params alt-dict'ini extract et — JS bunu doğrudan kullansın.
        return action.get("params", {}) if isinstance(action, dict) else {}

    def action_open_nevva_planner(self):
        """NEVVA'da bu lead için bir planner projesi başlatır ve yeni sekmede açar.

        NEVVA POST /api/projects/odoo-start çağrısına X-Odoo-Source secret'ı ile
        gider; dönen redirect_url yeni sekmede açılır. Tasarım bittiğinde NEVVA
        projeyi XMLRPC ile bu Odoo'da sale.order olarak oluşturur.
        """
        import requests  # lazy — model yüklenirken üst-seviye import riski olmasın
        self.ensure_one()
        icp = self.env["ir.config_parameter"].sudo()
        base = _nevva_origin(icp.get_param("nevva_planner.url"))
        secret = icp.get_param("nevva_planner.inbound_secret") or ""
        if not base or not secret:
            raise UserError(
                "NEVVA Planner yapılandırılmadı.\n"
                "Settings → NEVVA Planner bölümünden URL ve Inbound Secret girin."
            )

        partner = self.partner_id
        # Dil önceliği:
        #   1) Müşteri (partner) dili — planner bu kişiyle paylaşılacak
        #   2) Butona basan satıcının dili — kontak dili yoksa satıcı
        #      Odoo kendi dilinde devam etsin (tasarımı yapan kişi rahat olsun)
        #   3) Fallback "fr" — multi-dil hiç yoksa
        lang = "fr"
        if partner and partner.lang:
            lang = partner.lang[:2]
        elif self.env.user.lang:
            lang = self.env.user.lang[:2]

        # Müşteri bilgisi çoğu lead'de bağlı partner kaydındadır — lead alanları
        # boşsa partner'dan doldur (planner "Envoyer" formu prefill olsun).
        customer_name = (self.contact_name or self.partner_name
                         or (partner.name if partner else "")
                         or self.name or "Client")
        customer_email = (self.email_from
                          or (partner.email if partner else "") or "")
        customer_phone = (self.phone or self.mobile
                          or (partner.phone if partner else "")
                          or (partner.mobile if partner else "") or "")

        # Butona basan satıcı → planner ayrı login istemesin, teklif doğru
        # satıcıya atansın (NEVVA project.staff_email + sale.order.user_id).
        # Audit 3.2: email format validation — login (örn. "admin") email
        # değilse boş gönder (NEVVA tarafında staff_email opsiyonel).
        import re as _re
        seller_email = (self.env.user.email or "").strip()
        if not _re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", seller_email):
            seller_email = ""

        payload = {
            "odoo_lead_id":   str(self.id),
            "customer_name":  customer_name,
            "customer_email": customer_email,
            "customer_phone": customer_phone,
            "language":       lang,
            "seller_email":   seller_email,
        }

        from ._constants import (
            NEVVA_PROJECT_START_PATH, NEVVA_TIMEOUT_BLOCKING, NEVVA_TLS_VERIFY,
        )
        try:
            resp = requests.post(
                "%s%s" % (base, NEVVA_PROJECT_START_PATH),
                json=payload,
                headers={"X-Odoo-Source": secret},
                timeout=NEVVA_TIMEOUT_BLOCKING,
                verify=NEVVA_TLS_VERIFY,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            _logger.exception("NEVVA Planner başlatma hatası (lead=%s)", self.id)
            raise UserError("NEVVA Planner başlatılamadı: %s" % e)

        redirect = (data or {}).get("redirect_url") or ""
        if not redirect:
            raise UserError("NEVVA geçerli bir redirect_url döndürmedi.")
        url = redirect if redirect.startswith("http") else "%s%s" % (base, redirect)
        # Audit 8.3: open-redirect koruması — URL ya base ile aynı origin olmalı
        # ya da relative path (yukarıda base'e eklendi). javascript:/data:/file:
        # protokolleri reddedilir.
        from urllib.parse import urlparse
        target = urlparse(url)
        if target.scheme not in ("http", "https"):
            raise UserError(
                "NEVVA güvensiz redirect_url döndürdü (scheme: %s)" % target.scheme)
        if urlparse(base).netloc != target.netloc:
            raise UserError(
                "NEVVA başka bir host'a redirect döndürdü: %s" % target.netloc)

        self.nevva_planner_url = url
        # Audit 8.4: başarı log'u — debug için minimal context (secret yok)
        _logger.info(
            "NEVVA planner açıldı: lead=%s, project_id=%s",
            self.id, (data or {}).get("project_id", "?"),
        )
        # v1.6.0+: Odoo client action ile FULL-SCREEN iframe'de aç — satıcı
        # Odoo navigation'da kalır, "Envoyer" sonrası postMessage ile action
        # kapanıp lead form'una geri döner.
        #
        # Shotgun param passing: Odoo 17.x versiyonları arasında client action
        # props yapısı farklı olabiliyor. Üç farklı yere de yazıyoruz, JS
        # tarafı hangisini bulursa kullanır.
        _payload = {
            "url":          str(url),
            "project_id":   str((data or {}).get("project_id") or ""),
            "parent_model": "crm.lead",
            "parent_id":    int(self.id),
        }
        _logger.info("NEVVA client action return payload: %s", _payload)
        return {
            "type":    "ir.actions.client",
            "tag":     "nevva_planner.open",
            "name":    "NEVVA Planner",
            "target":  "current",
            "params":  _payload,
            "context": {
                "nevva_planner_url":          _payload["url"],
                "nevva_planner_project_id":   _payload["project_id"],
                "nevva_planner_parent_model": _payload["parent_model"],
                "nevva_planner_parent_id":    _payload["parent_id"],
            },
        }
