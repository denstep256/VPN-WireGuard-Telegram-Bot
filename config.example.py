"""Copy this file to config.py and replace all placeholder values."""

TOKEN = "TELEGRAM_BOT_TOKEN"
DB_URL_USERS = "sqlite+aiosqlite:///db.sqlite3"
PAYMENT_TOKEN = "YOOKASSA_PROVIDER_TOKEN"
ADMIN_ID = "123456789"

# Directory for generated WireGuard client configurations.
DIR_CONF = "app/auth"

# A Telegram invoice must not become cheaper than this after bonuses.
MIN_PAY_RUB = 50

# WireGuard Easy integration. TLS certificate verification is disabled because
# the target installation uses a self-signed certificate.
WG_MAX_CLIENTS = 60
WG_REQUEST_TIMEOUT_SECONDS = 15

# Prices in whole RUB.
one_mounth_price = 299
one_mounth_fake_price = 399
six_mounth_price = 1499
six_mounth_fake_price = 2394
twelve_mounth_price = 2499
twelve_mounth_fake_price = 4788
