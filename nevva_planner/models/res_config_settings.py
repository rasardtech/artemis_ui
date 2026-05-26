from odoo import models, fields
from odoo.exceptions import UserError


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    # ir.config_parameter ile saklanır → tek yerden okunur.
    nevva_url = fields.Char(
        string="NEVVA Planner URL",
        config_parameter="nevva_planner.url",
        help="Örn: https://planner.electro-cuisine.be",
    )
    nevva_inbound_secret = fields.Char(
        string="NEVVA Inbound Secret",
        config_parameter="nevva_planner.inbound_secret",
        help="NEVVA .env'deki ODOO_INBOUND_SECRET ile birebir aynı olmalı.",
        # Audit 1.2: secret form UI'da yalnızca system admin'e görünür.
        # NOT: ir.config_parameter kaydı kod erişimine açık kalır (Odoo
        # mimarisi); UI seviyesi yine de yetkisiz görüntülemeyi engeller.
        groups="base.group_system",
    )

    def action_test_nevva_connection(self):
        """NEVVA /health uç noktasına ping atar; sonucu bildirimle gösterir."""
        import requests  # lazy — registry yüklenirken üst-seviye import riski olmasın
        from .crm_lead import _nevva_origin
        self.ensure_one()
        base = _nevva_origin(self.nevva_url)
        if not base:
            raise UserError("Önce NEVVA URL girin ve kaydedin.")
        try:
            resp = requests.get("%s/health" % base, timeout=10)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            raise UserError("NEVVA'ya bağlanılamadı: %s" % e)
        status = (data or {}).get("status", "?")
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": "NEVVA bağlantısı",
                "message": "Bağlantı başarılı — durum: %s" % status,
                "type": "success",
                "sticky": False,
            },
        }
