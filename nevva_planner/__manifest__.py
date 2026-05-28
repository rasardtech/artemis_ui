{
    "name": "NEVVA Planner Integration",
    "version": "17.0.2.2.1",
    "summary": "CRM lead'den NEVVA 3D mutfak planner'ını açar + tasarım sekmesi",
    "description": """
NEVVA Planner Integration (Full)
================================

Bir CRM fırsatında (crm.lead) "NEVVA Planner" butonu ekler. Satış temsilcisi
butona basınca NEVVA planner **Odoo içinde full-screen client action** olarak
açılır (v1.6.0+); tasarım bitince NEVVA, projeyi XMLRPC ile doğrudan bu
Odoo'da bir teklif (sale.order) olarak oluşturur ve fiyatlandırmayı Odoo'nun
kendi fiyat listesi yapar. "Envoyer" sonrası action otomatik kapanır, sale.order
form view'da güncel kayıt yüklenir.

Teklifte (sale.order) "NEVVA Tasarım" sekmesi:
  - AI render + 3D ekran görüntüsü önizlemesi
  - Planner / AR / AI render butonları (planner butonu Odoo içinde açılır)
  - Proje JSON verisi (yeniden yüklenebilir)

NOT: Bu sürüm Python + JS içerir → Odoo.sh'de Git push (addons) veya
Apps → Import Module ile kurulur.

Kurulum:
  1. Bu modülü Apps'ten yükleyin.
  2. Settings → NEVVA Planner: NEVVA URL + Inbound Secret girin.
     (Secret, NEVVA .env'deki ODOO_INBOUND_SECRET ile aynı olmalı.)
  3. NEVVA tarafında nginx CSP frame-ancestors'a Odoo origin'i ekleyin
     (örn. 'https://*.odoo.com' veya 'https://odoo.electro-cuisine.be'),
     aksi halde browser iframe'i bloklar.
""",
    "category": "Sales/CRM",
    "author": "Electro & Cuisine",
    "license": "LGPL-3",
    "depends": ["crm", "sale", "sale_crm", "web"],
    "data": [
        "security/ir.model.access.csv",
        "views/res_config_settings_views.xml",
        "views/res_partner_views.xml",
        "views/crm_lead_views.xml",
        "views/sale_order_views.xml",
        "views/nevva_sale_snapshot_views.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "nevva_planner/static/src/js/planner_action.js",
            "nevva_planner/static/src/xml/planner_action.xml",
            "nevva_planner/static/src/css/planner.css",
        ],
    },
    "application": False,
    "installable": True,
}
