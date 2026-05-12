# ==========================================
#  CENTRALIZED CONFIGURATION - NO TRAILING SPACES!
# ==========================================

DB_PATH = "economy.db"
BUSINESS_DB_PATH = "business.db"

# Card Tiers - CLEAN KEYS, NO TRAILING SPACES
CARD_TIERS = {
    "silver": {
        "multiplier": 1.0,
        "threshold": 0,
        "name": "Standard Silver",
        "file": "card_silver.png",
        "color": (255, 255, 255)
    },
    "gold": {
        "multiplier": 1.9,
        "threshold": 100_000,
        "name": "Gold Elite",
        "file": "card_gold.png",
        "color": (255, 255, 255)
    },
    "crystal": {
        "multiplier": 2.5,
        "threshold": 300_000,
        "name": "Crystal Debit",
        "file": "card_crystal.png",
        "color": (255, 255, 255)
    },
    "plat_black": {
        "multiplier": 4.5,
        "threshold": 600_000,
        "name": "Platinum Black",
        "file": "card_plat_black.png",
        "color": (255, 255, 255)
    },
    "plat_pink": {
        "multiplier": 4.5,
        "threshold": 600_000,
        "name": "Platinum Chérie",
        "file": "card_plat_pink.png",
        "color": (219, 120, 200)
    }
}

# Tier upgrade thresholds (for silent upgrades)
TIER_THRESHOLDS = [
    (100_000, "gold", "Gold Elite"),
    (300_000, "crystal", "Crystal Debit"),
    (600_000, "plat_black", "Platinum Black"),
]

# Cooldowns in seconds
COOLDOWNS = {
    "daily": 86_400,      # 24 hours
    "work": 3_600,        # 1 hour
    "heist": 10_800,      # 3 hours
}

# Daily payout base
DAILY_BASE_PAYOUT = 5_000

# Database settings
DB_TIMEOUT = 20

# Owner ID for admin commands
OWNER_ID = 743411894416834590

# Transaction types for logging
TX_TYPES = {
    "CREDIT": ["daily", "work", "heist_win", "stake_claim", "dividend", "transfer_in", "casino_win", "sell_stock"],
    "DEBIT": ["heist_loss", "loan_repayment", "stake_penalty", "transfer_out", "casino_loss", "buy_stock", "purchase"]
}