import logging

from odoo import models, fields
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


def _nevva_origin(url):
    """NEVVA base URL'sini kök origin'e indir (scheme://host). API her zaman
    kökte (/api/...); param yanlışlıkla /planner gibi bir path içerirse
    /planner/api/... SPA'ya düşer ve login açar — bunu önler."""
    base = (url or "").strip().rstrip("/")
    if "://" in base:
        scheme, rest = base.split("://", 1)
        base = scheme + "://" + rest.split("/", 1)[0]
    return base


class CrmLead(models.Model):
    _inherit = "crm.lead"

    nevva_planner_url = fields.Char(
        string="NEVVA Planner URL", readonly=True, copy=False,
        help="Son açılan NEVVA planner linki (bu lead için).",
    )

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
        return {
            "type": "ir.actions.client",
            "tag":  "nevva_planner.open",
            "name": "NEVVA Planner",
            "params": {
                "url":          url,
                "project_id":   (data or {}).get("project_id"),
                "parent_model": "crm.lead",
                "parent_id":    self.id,
            },
        }
