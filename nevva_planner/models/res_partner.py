from odoo import fields, models


class ResPartner(models.Model):
    _inherit = "res.partner"

    x_nevva_b2b = fields.Boolean(
        string="B2B Planner erişimi",
        help="İşaretli ise bu kontak NEVVA planner B2B moduna kendi e-posta + "
             "Odoo parolası ile giriş yapabilir. İşaretsiz hesaplar Odoo'da "
             "doğrulansa bile B2B planner'a alınmaz.",
        index=True,
        default=False,
        # Audit 1.6: Yetki yükseltme önlemi — yalnızca satış yöneticileri B2B
        # erişimi verebilir. Sıradan satış elemanı/intern kontağı kendi
        # işaretleyemez. Read herkese açık (kontak panelinde durum görünür).
        groups="sales_team.group_sale_manager",
    )
