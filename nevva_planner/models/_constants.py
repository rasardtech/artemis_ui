"""Modül-seviyesi sabitler (audit 7.2 + 8.1).

Endpoint path'leri ve timeout değerleri tek yerde tutulur — NEVVA'da path
değişirse yalnızca burayı güncellemek yeter. Timeout'lar context'e göre
(blocking POST vs notification GET) ayrılır.
"""

# NEVVA HTTP endpoint path'leri (origin base ayrı eklenir)
NEVVA_HEALTH_PATH         = "/health"
NEVVA_PROJECT_START_PATH  = "/api/projects/odoo-start"
NEVVA_REOPEN_PATH         = "/api/odoo/reopen"
NEVVA_SALE_STATE_PATH     = "/api/odoo/sale-state"

# Timeout'lar (saniye)
#   Project creation kullanıcıyı bekletir — biraz daha cömert (20s).
#   Health check ve fire-and-forget notify daha kısa (10s) — UI engellemesin.
NEVVA_TIMEOUT_BLOCKING    = 20
NEVVA_TIMEOUT_NOTIFY      = 10

# requests'e açıkça verify=True veriyoruz — default da bu, ama audit 1.5
# için kod düzeyinde explicit görünür olsun.
NEVVA_TLS_VERIFY          = True
