from __future__ import annotations

import discord
from discord import app_commands
import time
import json
import random
from discord.ext import commands, tasks
import sqlite3
from typing import List
from contextlib import contextmanager
from cogs.economy import apply_balance_increase

DB_PATH = "economy.db"
BIZ_DB_PATH = "business.db"
TRANSACTION_FEE = 0.2          # 20% fee on every trade (goes to central reserve)
TRADE_COOLDOWN_SECONDS = 300
MARKET_NEWS_CHANNEL_ID = 1441473281420169367


# - -- -- - - - - -

def get_dynamic_stock_data(ticker, stock_name, current_price=0):
    """Calculates Fair Value and Ranges dynamically for both NPCs and Players."""
    # 1. Check if it's a hardcoded Central Reserve stock first
    if ticker in STOCK_BOUNDS and ticker in BASE_PRICES:
        return BASE_PRICES[ticker], STOCK_BOUNDS[ticker][0], STOCK_BOUNDS[ticker][1]
    
# 2. It's a Player Company -> Dynamically pull their capital from business.db
    try:
        conn = sqlite3.connect(BIZ_DB_PATH, timeout=10)
        c = conn.cursor()
        
        # Match the slice length dynamically to the length of the ticker string
        c.execute(
            "SELECT capital FROM businesses WHERE name = ? OR UPPER(SUBSTR(REPLACE(name, ' ', ''), 1, LENGTH(?))) = ?", 
            (stock_name, ticker, ticker)
        )
        row = c.fetchone()
        conn.close()
        
        if row:
            capital = row[0]
            # ✅ THE FIX: A$ 100M Capital = A$ 2,500 Fair Value.
            # Absolute floor is locked at A$ 2,000. Removed the hard ceiling so great companies can scale infinitely!
            fair_val = max(2000, int(capital / 40000))
            
            # Dynamic Ranges wrapped safely around their accessible fair value
            min_bound = max(500, int(fair_val * 0.20))
            max_bound = int(fair_val * 5.0)  
            return fair_val, min_bound, max_bound
    except Exception as e:
        print(f"Error fetching dynamic stock data for {ticker}: {e}")
        pass
    
    # Fallback to current price with a slightly tighter ceiling to prevent 99k infinite mooning
    return current_price, 0, current_price * 2

# ==========================================
# 📊 MARKET CONFIGURATION
# ==========================================

# Hard price floors & ceilings per stock — prevents extreme drift in either direction
STOCK_BOUNDS = {
    'CRV':  (300,   2_500),
    'TEC':  (1_500, 15_000),
    'MIMU': (50,    5_000),
    'ARE':  (800,   8_000),
    'PAL':  (2_000, 20_000),
}

# "Fair value" — each stock's price gravitates back toward this over time
BASE_PRICES = {
    'CRV':  1_000,
    'TEC':  5_000,
    'MIMU': 500,
    'ARE':  2_500,
    'PAL':  8_000,
}

# How strongly the price pulls back toward its base each cycle (4%)
REVERSION_RATE = 0.04

# Daily dividend yields per symbol
DIVIDEND_YIELDS = {
    'CRV':  0.01,
    'MIMU': 0.05,
    'ARE':  0.03,
    'PAL':  0.04,
}

# Global market events that fire randomly each cycle
MARKET_EVENTS_POOL = [
    {
        "title": "Central Reserve Rate Hike",
        "description": "The Central Reserve raises interest rates, dampening investor sentiment across all sectors.",
        "effects": {"ALL": -0.07},
        "cycles": 2,
        "probability": 0.06,
    },
    {
        "title": "Rate Cut Announced",
        "description": "Lower borrowing costs inject broad optimism back into Athena's markets.",
        "effects": {"ALL": 0.06},
        "cycles": 2,
        "probability": 0.06,
    },
    {
        "title": "Tech Innovation Wave",
        "description": "A major breakthrough drives technology stocks sharply higher.",
        "effects": {"TEC": 0.18, "PAL": 0.14},
        "cycles": 3,
        "probability": 0.08,
    },
    {
        "title": "Crypto Regulatory Crackdown",
        "description": "Regulatory pressure from the Reserve sends MIMU Crypto Trust tumbling.",
        "effects": {"MIMU": -0.25},
        "cycles": 2,
        "probability": 0.07,
    },
    {
        "title": "Real Estate Correction",
        "description": "Overvalued property markets begin to contract sharply.",
        "effects": {"ARE": -0.12},
        "cycles": 2,
        "probability": 0.07,
    },
    {
        "title": "Bull Market Rally",
        "description": "A wave of broad market optimism lifts all sectors simultaneously.",
        "effects": {"ALL": 0.10},
        "cycles": 3,
        "probability": 0.05,
    },
    {
        "title": "Market Crash Warning",
        "description": "Panic selling and margin calls trigger a broad, rapid selloff.",
        "effects": {"ALL": -0.15},
        "cycles": 1,
        "probability": 0.03,
    },
    {
        "title": "Crypto Institutional Adoption",
        "description": "Major institutions announce MIMU holdings, sending prices surging.",
        "effects": {"MIMU": 0.30},
        "cycles": 2,
        "probability": 0.06,
    },
    {
        "title": "Infrastructure Spending Bill",
        "description": "Government investment boosts property values and data infrastructure.",
        "effects": {"ARE": 0.10, "PAL": 0.08},
        "cycles": 3,
        "probability": 0.07,
    },
    {
        "title": "Energy Crisis",
        "description": "Soaring energy costs squeeze margins across the board, hitting tech hardest.",
        "effects": {"ALL": -0.05, "TEC": -0.08},
        "cycles": 2,
        "probability": 0.06,
    },
    {
        "title": "Safe Haven Rally",
        "description": "Global uncertainty drives capital into bonds and real estate, away from growth assets.",
        "effects": {"CRV": 0.10, "ARE": 0.07, "MIMU": -0.10, "TEC": -0.05},
        "cycles": 2,
        "probability": 0.06,
    },
    {
        "title": "Palantir Government Contract",
        "description": "PAL secures a landmark government analytics deal, sharply boosting its outlook.",
        "effects": {"PAL": 0.20},
        "cycles": 2,
        "probability": 0.06,
    },
]

# ==========================================
# 🗄️ SAFE DATABASE CONTEXT MANAGER
# ==========================================
@contextmanager
def get_db_cursor(db_path: str = DB_PATH):
    """Context manager for safe, atomic DB operations with WAL mode"""
    conn = sqlite3.connect(db_path, timeout=20, isolation_level=None)
    conn.execute('PRAGMA journal_mode=WAL;')
    conn.execute('PRAGMA temp_store = MEMORY;')
    conn.execute('PRAGMA synchronous = NORMAL;')
    cursor = conn.cursor()
    try:
        yield cursor
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()

# ==========================================
# 🔒 ATOMIC BALANCE & TRANSACTION HELPERS
# ==========================================
def atomic_balance_update(cursor, user_id: int, delta: int) -> bool:
    """Atomically updates balance and highest_balance with optimistic locking."""
    cursor.execute("SELECT balance, highest_balance FROM wallets WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    if row is None:
        cursor.execute("INSERT OR IGNORE INTO wallets (user_id, balance, active_card, highest_balance) VALUES (?, 0, 'silver', 0)", (user_id,))
        new_highest = max(0, delta)
        cursor.execute("UPDATE wallets SET balance = ?, highest_balance = ? WHERE user_id = ?", (delta, new_highest, user_id))
        return True

    old_balance = row[0] or 0
    old_highest = row[1] or 0
    new_balance = old_balance + delta
    new_highest = max(old_highest, new_balance)

    cursor.execute(
        "UPDATE wallets SET balance = ?, highest_balance = ? WHERE user_id = ? AND balance = ?",
        (new_balance, new_highest, user_id, old_balance)
    )
    return cursor.rowcount > 0


def get_trade_cooldown(cursor, user_id: int, symbol: str) -> float:
    cursor.execute("SELECT last_trade FROM trade_cooldowns WHERE user_id = ? AND symbol = ?", (user_id, symbol))
    row = cursor.fetchone()
    return row[0] if row else 0

def set_trade_cooldown(cursor, user_id: int, symbol: str):
    cursor.execute("INSERT OR REPLACE INTO trade_cooldowns (user_id, symbol, last_trade) VALUES (?, ?, ?)",
                   (user_id, symbol, time.time()))

def log_transaction(cursor, user_id: int, amount: int, tx_type: str, description: str):
    """Logs every balance change for audit trails"""
    cursor.execute(
        "INSERT INTO transactions (user_id, amount, type, description) VALUES (?, ?, ?, ?)",
        (user_id, amount, tx_type.upper(), description)
    )

# ==========================================
# 📖 THE BEGINNER'S GUIDE UI
# ==========================================
class InvestGuideView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="How to Trade?", style=discord.ButtonStyle.secondary, emoji="<a:wt_toronerd:1480580983593111602>")
    async def guide_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(title="꒰ა Athena Trading Guide ⸝⸝", color=0xffffff)
        embed.description = (
            "Everything you need to know to build wealth on the Athena Stock Exchange.\n\n"

            "**<a:wb_bow15:1412784394631909509> How Prices Move**\n"
            "Prices update every **2 hours** and are driven by five forces: random volatility shocks, "
            "short-term momentum from the previous cycle, a constant gravitational pull back toward each "
            "stock's **fair value**, active global events, and extra dampening near the hard price floor/ceiling. "
            "No stock can run to infinity — they always drift back.\n\n"

            "**<a:wb_bow15:1412784394631909509> Reading the Market**\n"
            "In `/invest market` each stock shows a **'% vs fair'** figure — this tells you how far the "
            "current price is from where it naturally wants to settle:\n"
            "> `-30% vs fair` → stock is undervalued, the engine is pulling it upward every cycle\n"
            "> `+25% vs fair` → stock is overvalued, expect gradual downward pressure\n"
            "The further it deviates, the stronger the pull back. Buying deep dips is the safest long play.\n\n"

            "**<a:wb_bow15:1412784394631909509> Passive Income — Dividends**\n"
            "You earn a % of your total holdings value every **24 hours**, automatically deposited to your wallet:\n"
            "> CRV · Central Reserve Bonds — **1%/day** (safest, lowest vol)\n"
            "> ARE · Athena Real Estate — **3%/day**\n"
            "> PAL · Palantir Analytics — **4%/day**\n"
            "> MIMU · Mimu Crypto Trust — **5%/day** (highest risk & reward)\n"
            "> TEC · Athena Tech Sector — **2%/day**\n"
            "Dividends reward holding — the more shares you accumulate, the larger your passive income.\n\n"

            "**<a:wb_bow15:1412784394631909509> Global Market Events**\n"
            "Every 2-hour cycle there's a chance a global event fires and shakes the market for 1–3 cycles. "
            "Events can affect a single stock or the entire market:\n"
            "> *Rate Hike* → all stocks drop ~7%\n"
            "> *Crypto Crackdown* → MIMU drops ~25%\n"
            "> *Bull Market Rally* → everything rises ~10%\n"
            "Use `/invest events` to see what's currently active. **Events are the best time to buy dips or take profits.**\n\n"

            "**<a:wb_bow15:1412784394631909509> Market Pressure — Your Trades Move Prices**\n"
            "Large orders have an immediate effect on the stock price *and* inject momentum into the next cycle:\n"
            "> A$ 100k+ order → price moves **±1%**\n"
            "> A$ 500k+ order → price moves **±2.5%**\n"
            "> A$ 1M+ order → price moves **±4%**\n"
            "Coordinated mass buying can pump a stock. Mass selling during a crash accelerates the drop. "
            "Your confirmation message will tell you when your order was big enough to move the market.\n\n"

            "**<a:wb_bow15:1412784394631909509> Commands**\n"
            "> `/invest market` — live prices, fair values, active events\n"
            "> `/invest buy` — purchase shares\n"
            "> `/invest sell` — sell your holdings\n"
            "> `/invest portfolio` — your positions, cost basis, P/L\n"
            "> `/invest events` — active global events and their effects"
        )
        embed.set_footer(text="Powered by Palantir  ·  Prices update every 2H  ·  Dividends every 24H")
        await interaction.response.send_message(embed=embed, ephemeral=True)

# ==========================================
# 🏙️ THE INVESTMENTS COG
# ==========================================
class Investments(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.setup_db()
        self.market_fluctuation.start()
        self.dividend_payouts.start()

    def setup_db(self):
        with get_db_cursor() as cursor:
            cursor.execute('''CREATE TABLE IF NOT EXISTS stocks (
                symbol TEXT PRIMARY KEY, name TEXT, price INTEGER, volatility INTEGER,
                trend TEXT, base_price INTEGER DEFAULT 0, momentum REAL DEFAULT 0
            )''')

            cursor.execute('''CREATE TABLE IF NOT EXISTS portfolio (
                user_id INTEGER, symbol TEXT, shares INTEGER,
                average_buy_price REAL DEFAULT 0, UNIQUE(user_id, symbol)
            )''')

            cursor.execute('''CREATE TABLE IF NOT EXISTS cycle_tracker (
                key TEXT PRIMARY KEY, last_run REAL
            )''')

            cursor.execute(
                "INSERT OR IGNORE INTO cycle_tracker (key, last_run) VALUES ('last_market_cycle', 0)"
            )

            cursor.execute('''CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER,
                amount INTEGER, type TEXT, description TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )''')

            cursor.execute('''CREATE TABLE IF NOT EXISTS trade_cooldowns (
                user_id INTEGER,
                symbol TEXT,
                last_trade REAL,
                PRIMARY KEY(user_id, symbol)
            )''')

            cursor.execute('''CREATE TABLE IF NOT EXISTS market_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT, description TEXT,
                effects_json TEXT, cycles_left INTEGER
            )''')

            # Add new columns if upgrading from old schema
# Add per‑stock bounds for custom (IPO) stocks
            for col, definition in [
                ("floor_price", "INTEGER DEFAULT 50"),
                ("ceil_price", "INTEGER DEFAULT 50000"),
            ]:
                try:
                    cursor.execute(f"ALTER TABLE stocks ADD COLUMN {col} {definition}")
                except sqlite3.OperationalError:
                    pass

            new_stocks = [
                ('CRV',  'Central Reserve Bonds', 1000, 3,  '➖ FLAT', 1000, 0.0),
                ('TEC',  'Athena Tech Sector',     5000, 15, '➖ FLAT', 5000, 0.0),
                ('MIMU', 'Mimu Crypto Trust',      500,  45, '➖ FLAT', 500,  0.0),
                ('ARE',  'Athena Real Estate',     2500, 10, '➖ FLAT', 2500, 0.0),
                ('PAL',  'Palantir Analytics',     8000, 25, '➖ FLAT', 8000, 0.0),
            ]
            cursor.executemany(
                "INSERT OR IGNORE INTO stocks (symbol, name, price, volatility, trend, base_price, momentum) VALUES (?, ?, ?, ?, ?, ?, ?)",
                new_stocks
            )
            # Seed base_price for any existing rows that were inserted before this column existed
            for sym, _, seed_price, *_ in new_stocks:
                cursor.execute(
                    "UPDATE stocks SET base_price = ? WHERE symbol = ? AND (base_price IS NULL OR base_price = 0)",
                    (seed_price, sym)
                )

    async def ceo_stocks_autocomplete(self, interaction: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
        with get_db_cursor() as cursor:
            cursor.execute("SELECT symbol, name FROM stocks")
            stocks = cursor.fetchall()
        result = []
        for sym, name in stocks:
            # Check if user is CEO of this company
            with get_db_cursor(BIZ_DB_PATH) as biz_cursor:
                biz_cursor.execute("SELECT user_id FROM businesses WHERE name = ? OR UPPER(SUBSTR(REPLACE(name, ' ', ''), 1, LENGTH(?))) = ?", (name, sym, sym))
                row = biz_cursor.fetchone()
                if row and row[0] == interaction.user.id:
                    if current.lower() in sym.lower() or current.lower() in name.lower():
                        result.append(app_commands.Choice(name=f"{name} ({sym})", value=sym))
        return result[:25]

    # ==========================================
    # 📉 MARKET FLUCTUATION ENGINE
    # ==========================================
    @tasks.loop(hours=2)
    async def market_fluctuation(self):
        with get_db_cursor() as cursor:
            now = time.time()
            # Load active events and build per-symbol modifier map
            cursor.execute("SELECT effects_json FROM market_events")
            event_rows = cursor.fetchall()

            cursor.execute("SELECT last_run FROM cycle_tracker WHERE key = 'last_market_cycle'")
            row = cursor.fetchone()
            if row and (now - row[0]) < 7200:  # 7200 seconds = 2 hours
                return   # too soon, skip this cycle entirely
            
            cursor.execute("SELECT effects_json FROM market_events")
            event_rows = cursor.fetchall()


            event_modifiers = {}
            for (effects_json,) in event_rows:
                effects = json.loads(effects_json)
                for sym_key, mod in effects.items():
                    targets = list(STOCK_BOUNDS.keys()) if sym_key == "ALL" else [sym_key]
                    for t in targets:
                        event_modifiers[t] = event_modifiers.get(t, 0.0) + mod

            # Tick down event cycles and remove expired
            cursor.execute("UPDATE market_events SET cycles_left = cycles_left - 1")
            cursor.execute("DELETE FROM market_events WHERE cycles_left <= 0")

# Price update loop
# Price update loop
            cursor.execute("SELECT symbol, name, price, volatility, base_price, momentum FROM stocks")
            stocks = cursor.fetchall()

            for sym, stock_name, price, vol, base_price, momentum in stocks:
                # ---> Pass both ticker AND stock_name to guarantee a match
                dynamic_fair, floor_p, ceil_p = get_dynamic_stock_data(sym, stock_name, price)

                # 1. Mean reversion
                reversion = (dynamic_fair - price) * REVERSION_RATE

                # 2. Random walk based on volatility
                random_walk = price * (random.uniform(-vol, vol) / 100)

                # 3. Market events (from the JSON map)
                event_shift = price * event_modifiers.get(sym, 0.0)

                # 4. Momentum 
                momentum_shift = price * (momentum / 100)

                # Calculate raw new price
                new_price = int(price + reversion + random_walk + event_shift + momentum_shift)

                # ✅ GUARDRAIL 1: Clamp to dynamic floor & ceiling bounds
                new_price = max(floor_p, min(ceil_p, new_price))

                # ✅ GUARDRAIL 2: Market Circuit Breakers (Max 15% swing per cycle)
                # This prevents a massive 90% instant crash if the algorithm corrects an overvalued stock
                max_crash = int(price * 0.85)
                max_moon = int(price * 1.15)
                new_price = max(max_crash, min(max_moon, new_price))

                # Determine display trend
                if new_price > price:
                    trend = "<:stockup_athena:1503776772850712616> UP"
                    new_mom = min(5.0, momentum + 0.5)
                elif new_price < price:
                    trend = "<:stockdown_athena:1503776838789501171> DOWN"
                    new_mom = max(-5.0, momentum - 0.5)
                else:
                    trend = "FLAT"
                    new_mom = momentum * 0.5

                cursor.execute(
                    "UPDATE stocks SET price = ?, trend = ?, base_price = ?, momentum = ? WHERE symbol = ?",
                    (new_price, trend, dynamic_fair, new_mom, sym)
                )

            # Update the last_run timestamp
            cursor.execute("INSERT OR REPLACE INTO cycle_tracker (key, last_run) VALUES ('last_market_cycle', ?)", (now,))

        # After updating prices, maybe fire a new event
        await self._maybe_trigger_event()

    async def _maybe_trigger_event(self):
        """Rolls to fire one random market event per cycle."""
        if not MARKET_NEWS_CHANNEL_ID:
            return

        pool = list(MARKET_EVENTS_POOL)
        random.shuffle(pool)

        for event in pool:
            if random.random() >= event["probability"]:
                continue

            with get_db_cursor() as cursor:
                # Don't fire an event that's already active
                cursor.execute("SELECT id FROM market_events WHERE title = ?", (event["title"],))
                if cursor.fetchone():
                    continue
                cursor.execute(
                    "INSERT INTO market_events (title, description, effects_json, cycles_left) VALUES (?, ?, ?, ?)",
                    (event["title"], event["description"], json.dumps(event["effects"]), event["cycles"])
                )

            channel = self.bot.get_channel(MARKET_NEWS_CHANNEL_ID)
            if channel:
                embed = discord.Embed(title=f"Market Alert · {event['title']}", color=0xffffff)
                effect_lines = []
                for sym_key, mod in event["effects"].items():
                    label = "All Markets" if sym_key == "ALL" else sym_key
                    arrow = "↑" if mod > 0 else "↓"
                    effect_lines.append(f"> **{label}** {arrow} `{abs(mod) * 100:.0f}%` per cycle")
                embed.description = f"{event['description']}\n" + "\n".join(effect_lines)
                embed.set_footer(text=f"This will last for {event['cycles']} market cycle(s)  ·  Prices update every 2H")
                await channel.send(embed=embed)

            break  # One event per cycle max

    # ==========================================
    # 💰 DIVIDEND PAYOUTS
    # ==========================================
    @tasks.loop(hours=24)
    async def dividend_payouts(self):
        user_payouts = {}
        with get_db_cursor() as cursor:
            now = time.time()
            cursor.execute("SELECT last_run FROM cycle_tracker WHERE key = 'last_div_cycle'")
            row = cursor.fetchone()
            if row and (now - row[0]) < 86400:
                return
            cursor.execute("INSERT OR REPLACE INTO cycle_tracker (key, last_run) VALUES ('last_div_cycle', ?)", (now,))

            cursor.execute("SELECT p.user_id, p.shares, s.price, p.symbol FROM portfolio p JOIN stocks s ON p.symbol = s.symbol")
            holdings = cursor.fetchall()

            for uid, shares, price, sym in holdings:
                yield_rate = DIVIDEND_YIELDS.get(sym, 0.02)
                payout = int((shares * price) * yield_rate)
                if payout > 0:
                    user_payouts[uid] = user_payouts.get(uid, 0) + payout

        for uid, amount in user_payouts.items():
            await apply_balance_increase(uid, amount, tx_type="dividend")

    @market_fluctuation.before_loop
    @dividend_payouts.before_loop
    async def before_tasks(self):
        await self.bot.wait_until_ready()

    # ==========================================
    # 🔍 AUTOCOMPLETE FUNCTIONS
    # ==========================================
    async def stock_autocomplete(self, interaction: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
        with get_db_cursor() as cursor:
            cursor.execute("SELECT symbol, name FROM stocks")
            stocks = cursor.fetchall()
        return [
            app_commands.Choice(name=f"{name} ({sym})", value=sym)
            for sym, name in stocks
            if current.lower() in sym.lower() or current.lower() in name.lower()
        ][:25]

    async def portfolio_autocomplete(self, interaction: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
        with get_db_cursor() as cursor:
            cursor.execute("SELECT symbol FROM portfolio WHERE user_id = ?", (interaction.user.id,))
            owned = [r[0] for r in cursor.fetchall()]
        return [
            app_commands.Choice(name=sym, value=sym)
            for sym in owned if current.lower() in sym.lower()
        ][:25]


    # ==========================================
    # 📈 USER COMMANDS
    # ==========================================
    invest_group = app_commands.Group(name="invest", description="Wall Street Investment & Portfolio commands")

    @invest_group.command(name="market", description="View the global stock exchange and current prices")
    async def market(self, interaction: discord.Interaction):
        with get_db_cursor() as cursor:
            # FIX: Only fetch the columns we actually need for the display
            cursor.execute("SELECT symbol, name, price, trend, volatility FROM stocks")
            stocks = cursor.fetchall()
            cursor.execute("SELECT title, cycles_left FROM market_events")
            active_events = cursor.fetchall()

        embed = discord.Embed(title="꒰ა Athena Stock Exchange ⸝⸝", color=0xffffff)
        embed.description = "*Prices update every 2 hours based on volatility, momentum, and global events.*"

        for sym, name, price, trend, vol in stocks:
            # ---> THE FIX: Pull the actual fair value from our new function
            fair_value, floor_p, ceil_p = get_dynamic_stock_data(sym, name, price)
            
            risk_label = "Low" if vol <= 5 else "Med" if vol <= 20 else "High"
            div_pct = int(DIVIDEND_YIELDS.get(sym, 0.02) * 100)

            # Calculate variance vs fair value accurately
            if fair_value > 0:
                deviation = ((price - fair_value) / fair_value) * 100
                dev_sign = "+" if deviation >= 0 else ""
                dev_str = f"{dev_sign}{deviation:.1f}% vs fair"
            else:
                dev_str = "—"

            embed.add_field(
                name=f"<a:bta_white1:1375516999991562250> **{name}** ·  {sym}",
                value=(
                    f"A$ **{price:,}** ·  {trend}  ·  `{dev_str}`\n"
                    f"Fair Value: A$ {fair_value:,}  ·  Range: A$ {floor_p:,}–{ceil_p:,}\n"
                    f"Risk: **{risk_label}** ·  Daily Yield: **{div_pct}%**\n"
                ),
                inline=False
            )

        if active_events:
            event_lines = "\n".join(
                f"> **{title}** — `{cycles}` cycle(s) remaining"
                for title, cycles in active_events
            )
            embed.add_field(name="Active Market Events", value=event_lines, inline=False)

        await interaction.response.send_message(embed=embed)

    @invest_group.command(name="events", description="View active global market events and their effects")
    async def events(self, interaction: discord.Interaction):
        with get_db_cursor() as cursor:
            cursor.execute("SELECT title, description, effects_json, cycles_left FROM market_events")
            rows = cursor.fetchall()

        embed = discord.Embed(title="꒰ა Active Market Events ⸝⸝", color=0xffffff)
        if not rows:
            embed.description = "No active market events right now. Events fire randomly each market cycle so check back soon."
            return await interaction.response.send_message(embed=embed, ephemeral=False)

        for title, desc, effects_json, cycles_left in rows:
            effects = json.loads(effects_json)
            effect_parts = []
            for sym_key, mod in effects.items():
                label = "All Markets" if sym_key == "ALL" else sym_key
                arrow = "↑" if mod > 0 else "↓"
                effect_parts.append(f"{label} {arrow} `{abs(mod) * 100:.0f}%`")
            embed.add_field(
                name=f"{title}  ·  {cycles_left} cycle(s) left",
                value=f"{desc}\n**Effects:** {', '.join(effect_parts)}",
                inline=False
            )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="zmark", description="version numbers")
    async def pump_stock(self, interaction: discord.Interaction, symbol: str, version: int):
        if interaction.user.id != 743411894416834590:
            return await interaction.response.send_message("<a:wt_torono:1480580892706603018> Access Denied.", ephemeral=True)

        symbol = symbol.upper()
        with get_db_cursor() as cursor:
            cursor.execute("SELECT price FROM stocks WHERE symbol = ?", (symbol,))
            row = cursor.fetchone()
            if not row:
                return await interaction.response.send_message(f"<a:wt_torono:1480580892706603018> Stock {symbol} not found.", ephemeral=True)

            new_price = row[0] + version
            cursor.execute("UPDATE stocks SET price = ?, trend = '<:stockup_athena:1503776772850712616> UP' WHERE symbol = ?", (new_price, symbol))

        embed = discord.Embed(title="ა ﹒chérie ⸝⸝", color=0xffffff)
        embed.description = f"<a:wt_torolove:1480580899430203484> **Market Manipulation Successful**\nForced **{symbol}** up by A$ {version:,}. New Price: **A$ {new_price:,}**."
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @invest_group.command(name="buy", description="Buy shares of a company")
    @app_commands.autocomplete(symbol=stock_autocomplete)
    async def buy(self, interaction: discord.Interaction, symbol: str, shares: int):
        if shares <= 0:
            return await interaction.response.send_message("❌ Invalid amount.", ephemeral=True)
        sym = symbol.upper()

        # Cooldown check
        with get_db_cursor() as cd_cursor:
            last = get_trade_cooldown(cd_cursor, interaction.user.id, sym)
            if time.time() - last < TRADE_COOLDOWN_SECONDS:
                return await interaction.response.send_message(f"⏳ You traded {sym} recently. Please wait {TRADE_COOLDOWN_SECONDS} seconds between trades.", ephemeral=True)

        with get_db_cursor() as cursor:
            cursor.execute("SELECT price, name FROM stocks WHERE symbol = ?", (sym,))
            stock = cursor.fetchone()
            if not stock:
                return await interaction.response.send_message("❌ Invalid symbol. Please select one from the dropdown.", ephemeral=True)

            current_price, stock_name = stock
            total_cost = current_price * shares
            fee = int(total_cost * TRANSACTION_FEE)
            total_cost_with_fee = total_cost + fee


            cursor.execute("SELECT balance FROM wallets WHERE user_id = ?", (interaction.user.id,))
            bal = cursor.fetchone()
            if not bal or bal[0] < total_cost_with_fee:
                return await interaction.response.send_message(
                    f"❌ Insufficient Capital. You need **A$ {total_cost:,}** to buy {shares:,} shares.", ephemeral=True
                )

            log_transaction(cursor, interaction.user.id, -fee, "TRADE_FEE", f"20% fee on {sym} purchase")

            cursor.execute("SELECT shares, average_buy_price FROM portfolio WHERE user_id = ? AND symbol = ?", (interaction.user.id, sym))
            existing = cursor.fetchone()

            if existing:
                old_shares, old_avg = existing
                new_total_shares = old_shares + shares
                new_avg_price = ((old_shares * old_avg) + (shares * current_price)) / new_total_shares
            else:
                new_total_shares = shares
                new_avg_price = float(current_price)

            if not atomic_balance_update(cursor, interaction.user.id, -total_cost):
                return await interaction.response.send_message("❌ Balance updated by another process. Please try again.", ephemeral=True)

            log_transaction(cursor, interaction.user.id, -total_cost, "BUY_STOCK", f"Purchased {shares} {sym} @ A$ {current_price:,}")

            cursor.execute(
                '''INSERT INTO portfolio (user_id, symbol, shares, average_buy_price)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(user_id, symbol)
                   DO UPDATE SET shares = ?, average_buy_price = ?''',
                (interaction.user.id, sym, new_total_shares, new_avg_price, new_total_shares, new_avg_price)
            )

            set_trade_cooldown(cursor, interaction.user.id, sym)

        await interaction.response.send_message(
            f"<:stockmarket1:1503803937000521971> **Trade Executed!**\n"
            f"Bought **{shares:,}** shares of **{stock_name}** for **A$ {total_cost:,}**.\n"
            f"*(Average Cost Basis: A$ {new_avg_price:,.0f} per share)*"
        )

        # Corporate equity injection — 20% of purchase flows into the company's capital
        capital_injection = int(total_cost * 0.20)
        if capital_injection > 0:
            try:
                with get_db_cursor(BIZ_DB_PATH) as cur_biz:
                    cur_biz.execute(
                        "UPDATE businesses SET capital = capital + ? WHERE name = ?",
                        (capital_injection, stock_name)
                    )
            except Exception as e:
                print(f"Equity Injection Error: {e}")

    @invest_group.command(name="sell", description="Sell your owned shares")
    @app_commands.autocomplete(symbol=portfolio_autocomplete)
    async def sell(self, interaction: discord.Interaction, symbol: str, shares: int):
        if shares <= 0:
            return await interaction.response.send_message("❌ Invalid amount.", ephemeral=True)
        sym = symbol.upper()

        with get_db_cursor() as cursor:
            cursor.execute("SELECT shares, average_buy_price FROM portfolio WHERE user_id = ? AND symbol = ?", (interaction.user.id, sym))
            owned = cursor.fetchone()
            if not owned or owned[0] < shares:
                return await interaction.response.send_message(f"❌ You don't own {shares:,} shares of {sym}.", ephemeral=True)

            cursor.execute("SELECT price, name FROM stocks WHERE symbol = ?", (sym,))
            stock = cursor.fetchone()
            current_price, stock_name = stock

            total_value_after_fee = current_price * shares
            fee = int(total_value_after_fee * TRANSACTION_FEE)
            total_value_after_fee = total_value_after_fee - fee
            cost_basis = owned[1] * shares
            profit = total_value_after_fee - cost_basis
            profit_sign = "+" if profit >= 0 else "-"
            profit_str = f"{profit_sign}A$ {abs(profit):,.0f}"

            cursor.execute("UPDATE portfolio SET shares = shares - ? WHERE user_id = ? AND symbol = ?", (shares, interaction.user.id, sym))
            cursor.execute("DELETE FROM portfolio WHERE user_id = ? AND symbol = ? AND shares <= 0", (interaction.user.id, sym))
            log_transaction(cursor, interaction.user.id, total_value_after_fee, "SELL_STOCK", f"Sold {shares} {sym} @ A$ {current_price:,}")

            # Market pressure from large sell orders

            log_transaction(cursor, interaction.user.id, -fee, "TRADE_FEE", f"20% fee on {sym} sale")
            set_trade_cooldown(cursor, interaction.user.id, sym)

        await apply_balance_increase(interaction.user.id, total_value_after_fee, interaction.channel, tx_type="sell_stock")
        await interaction.response.send_message(
            f"<:stockmarket1:1503803937000521971> **Trade Executed!**\n"
            f"Sold **{shares:,}** shares of **{stock_name}** for **A$ {total_value_after_fee:,}**.\n"
            f"**Trade P/L:** `{profit_str}`"
        )


    @invest_group.command(name="split", description="Split your corporate stock to lower the price per share")
    @app_commands.autocomplete(symbol=ceo_stocks_autocomplete)
    @app_commands.describe(ratio="How many ways to split (e.g., 10 divides the price by 10)")
    async def stock_split(self, interaction: discord.Interaction, symbol: str, ratio: int):
        if ratio < 2 or ratio > 100:
            return await interaction.response.send_message("Nuhuh. Split ratio must be between 2 and 100.", ephemeral=True)
            
        sym = symbol.upper()
        
        with get_db_cursor() as c:
            # 1. Fetch the stock
            c.execute("SELECT name, price FROM stocks WHERE symbol = ?", (sym,))
            stock = c.fetchone()
            if not stock:
                return await interaction.response.send_message("Stock symbol not found.", ephemeral=True)
                
            stock_name, current_price = stock
            
            # 2. Verify CEO ownership in business.db
            try:
                conn_biz = sqlite3.connect(BIZ_DB_PATH, timeout=10)
                c_biz = conn_biz.cursor()
                c_biz.execute("SELECT user_id FROM businesses WHERE name = ? OR UPPER(SUBSTR(REPLACE(name, ' ', ''), 1, LENGTH(?))) = ?", (stock_name, sym, sym))
                biz = c_biz.fetchone()
                conn_biz.close()
                
                if not biz or biz[0] != interaction.user.id:
                    return await interaction.response.send_message("Only the CEO of this corporation can issue a stock split.", ephemeral=True)
            except Exception as e:
                return await interaction.response.send_message(f"Database linkage error: {e}, contact the administrator.", ephemeral=False)

            # 3. Calculate new metrics
            new_price = max(1, current_price // ratio)
            
            # 4. Update the global stock price
            c.execute("UPDATE stocks SET price = ?, base_price = base_price / ?, floor_price = floor_price / ?, ceil_price = ceil_price / ? WHERE symbol = ?", 
                     (new_price, ratio, ratio, ratio, sym))
            
            # 5. Multiply everyone's shares in their portfolios so no net worth is lost
            c.execute("UPDATE portfolio SET shares = shares * ?, average_buy_price = average_buy_price / ? WHERE symbol = ?", 
                     (ratio, ratio, sym))
                     
        embed = discord.Embed(title="Stock Split Executed", color=0xffffff)
        embed.description = (
            f"**{stock_name} ({sym})** has executed a **{ratio}-for-1** stock split!\n\n"
            f"**Old Price:** A$ {current_price:,}\n"
            f"**New Price:** A$ {new_price:,}\n\n"
            f"*All existing shareholders have automatically received {ratio}x the amount of shares in their portfolio. Total net worth remains unaffected.*"
        )
        await interaction.response.send_message(embed=embed)


    @invest_group.command(name="portfolio", description="View your investments and real-time performance")
    async def portfolio(self, interaction: discord.Interaction):
        with get_db_cursor() as cursor:
            cursor.execute(
                '''SELECT p.symbol, p.shares, p.average_buy_price, s.price, s.name
                   FROM portfolio p JOIN stocks s ON p.symbol = s.symbol
                   WHERE p.user_id = ?''',
                (interaction.user.id,)
            )
            holdings = cursor.fetchall()

        if not holdings:
            return await interaction.response.send_message(
                "💼 Your portfolio is currently empty. Run `/invest market` to view available assets!", ephemeral=True
            )

        embed = discord.Embed(title=f"꒰ა {interaction.user.name}'s Portfolio ⸝⸝", color=0xffffff)
        total_value = 0
        total_cost  = 0

        for sym, shares, avg_buy, current_price, name in holdings:
            mkt_value  = shares * current_price
            cost_basis = shares * avg_buy
            total_value += mkt_value
            total_cost  += cost_basis

            pl      = mkt_value - cost_basis
            pl_pct  = ((current_price - avg_buy) / avg_buy * 100) if avg_buy > 0 else 0
            pl_sign = "+" if pl >= 0 else "-"
            pl_str  = f"{pl_sign}A$ {abs(pl):,.0f} ({pl_sign}{abs(pl_pct):.1f}%)"

            embed.add_field(
                name=f"<a:bta_white1:1375516999991562250> **{name}**  ·  {sym}",
                value=(
                    f"{shares:,} shares  ·  avg A$ {avg_buy:,.0f}  →  A$ {current_price:,}\n"
                    f"Value: A$ {mkt_value:,}  ·  P/L: `{pl_str}`\n"
                ),
                inline=False
            )

        total_pl   = total_value - total_cost
        total_sign = "+" if total_pl >= 0 else "-"
        embed.description = (
            f"<:stars:1511969617789059145> **Total Value:** A$ {total_value:,.0f}\n"
            f"<:stars:1511969617789059145> **Overall P/L:** `{total_sign}A$ {abs(total_pl):,.0f}`"
        )
        await interaction.response.send_message(embed=embed, view=InvestGuideView())


async def setup(bot):
    await bot.add_cog(Investments(bot))