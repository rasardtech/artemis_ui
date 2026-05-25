{
    "name": "NEVVA Planner Integration",
    "version": "17.0.1.2.3",
    "summary": "CRM lead'den NEVVA 3D mutfak planner'ını açar + tasarım sekmesi",
    "description": """
NEVVA Planner Integration (Full)
================================

Bir CRM fırsatında (crm.lead) "NEVVA Planner" butonu ekler. Satış temsilcisi
butona basınca NEVVA planner yeni sekmede açılır; tasarım bitince NEVVA, projeyi
XMLRPC ile doğrudan bu Odoo'da bir teklif (sale.order) olarak oluşturur ve
fiyatlandırmayı Odoo'nun kendi fiyat listesi yapar.

Teklifte (sale.order) "NEVVA Tasarım" sekmesi:
  - AI render + 3D ekran görüntüsü önizlemesi
  - Planner / AR / AI render butonları
  - Proje JSON verisi (yeniden yüklenebilir)

NOT: Bu sürüm Python içerir → Odoo.sh'de yalnızca Git ile kurulur. Web-upload
(Apps → Import Module) ile kurmak için Python'suz "lite" sürümü (nevva_link)
kullanın; o sürüm aynı verileri sipariş ekleri + not olarak gösterir.

Kurulum:
  1. Bu modülü Apps'ten yükleyin.
  2. Settings → NEVVA Planner: NEVVA URL + Inbound Secret girin.
     (Secret, NEVVA .env'deki ODOO_INBOUND_SECRET ile aynı olmalı.)
""",
    "category": "Sales/CRM",
    "author": "Electro & Cuisine",
    "license": "LGPL-3",
    "depends": ["crm", "sale", "sale_crm"],
    "data": [
        "views/res_config_settings_views.xml",
        "views/crm_lead_views.xml",
        "views/sale_order_views.xml",
    ],
    "application": False,
    "installable": True,
}
