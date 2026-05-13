import discord
from discord import app_commands
import time 
from discord.ext import commands, tasks
import sqlite3
import random
from typing import List
from contextlib import contextmanager

DB_PATH = "economy.db"

# ==========================================
# 🗄️ SAFE DATABASE CONTEXT MANAGER
# ==========================================
@contextmanager
def get_db_cursor():
    """Context manager for safe, atomic DB operations with WAL mode"""
    conn = sqlite3.connect(DB_PATH, timeout=20, isolation_level=None)
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
    """Atomically updates balance with optimistic locking. Returns True on success."""
    cursor.execute("SELECT balance FROM wallets WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    
    if row is None:
        cursor.execute("INSERT OR IGNORE INTO wallets (user_id, balance, active_card, highest_balance) VALUES (?, 0, 'silver', 0)", (user_id,))
        cursor.execute("UPDATE wallets SET balance = balance + ? WHERE user_id = ?", (delta, user_id))
        return True
    
    old_balance = row[0] or 0
    new_balance = old_balance + delta
    cursor.execute("UPDATE wallets SET balance = ? WHERE user_id = ? AND balance = ?", (new_balance, user_id, old_balance))
    return cursor.rowcount > 0

def log_transaction(cursor, user_id: int, amount: int, tx_type: str, description: str):
    """Logs every balance change for audit trails"""
    cursor.execute(
        "INSERT INTO transactions (user_id, amount, type, description) VALUES (?, ?, ?, ?)",
        (user_id, amount, tx_type.upper(), description)
    )

# ✅ FIX: Clean thresholds (NO TRAILING SPACES)
TIER_THRESHOLDS = [
    (100_000, "gold", "Gold Elite"),
    (300_000, "crystal", "Crystal Debit"),
    (600_000, "plat_black", "Platinum Black"),
]

def apply_tier_upgrade(cursor, user_id: int):
    """Checks highest_balance and upgrades active_card if threshold crossed"""
    cursor.execute("SELECT highest_balance, active_card FROM wallets WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    if not row: return
    
    highest = row[0] or 0
    current_card = (row[1] or "silver").strip()  # ✅ FIX: strip whitespace
    new_card = current_card
    
    if highest >= 600_000: new_card = "plat_black"
    elif highest >= 300_000: new_card = "crystal"
    elif highest >= 100_000: new_card = "gold"
    
    if new_card != current_card and not (current_card == "plat_pink" and new_card == "plat_black"):
        cursor.execute("UPDATE wallets SET active_card = ? WHERE user_id = ?", (new_card, user_id))
        log_transaction(cursor, user_id, 0, "CARD_UPGRADE", f"Auto-upgraded to {new_card}")

# ==========================================
# 📖 THE BEGINNER'S GUIDE UI
# ==========================================
class InvestGuideView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="How to Trade?", style=discord.ButtonStyle.secondary, emoji="<a:wt_toronerd:1480580983593111602>")
    async def guide_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(title="Athena Trading for Beginners", color=0xffffff)
        embed.description = (
            "Welcome to Wall Street! Here is how you can build your wealth:\n\n"
            "**1. Buy Low, Sell High**\n"
            "Stock prices naturally go <:stockup_athena:1503776772850712616> UP or <:stockdown_athena:1503776838789501171> DOWN every 2 hours. Buy shares when they are cheap (especially during a market crash!). Sell them when the price is high to secure your profit.\n\n"
            "**2. Passive Income (Dividends)**\n"
            "Just by holding shares, you get paid! Every 24 hours, the Central Reserve automatically deposits a percentage of your total asset value directly into your wallet. (e.g., MIMU pays 5% daily!).\n\n"
            "**3. The Strategy**\n"
            "Use `/invest market` to spot cheap assets. Buy the dip with `/invest buy`. Check your `/invest portfolio` to track your Green 🟩 and Red 🟥 returns!"
        )
        embed.set_footer(text="Powered by Palantir")
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
                symbol TEXT PRIMARY KEY, name TEXT, price INTEGER, volatility INTEGER, trend TEXT
            )''')
            
            cursor.execute('''CREATE TABLE IF NOT EXISTS portfolio (
                user_id INTEGER, symbol TEXT, shares INTEGER, 
                average_buy_price REAL DEFAULT 0, UNIQUE(user_id, symbol)
            )''')

                        # Cycle tracker for rent guard
            cursor.execute('''CREATE TABLE IF NOT EXISTS cycle_tracker (
                key TEXT PRIMARY KEY,
                last_run REAL
            )''')
            
            # Ensure transactions table exists (in case economy.py hasn't run yet)
            cursor.execute('''CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER,
                amount INTEGER, type TEXT, description TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )''')
            
            # Inject default stocks if missing
            new_stocks = [
                ('CRV', 'Central Reserve Bonds', 1000, 3, '➖ FLAT'),
                ('TEC', 'Athena Tech Sector', 5000, 15, '➖ FLAT'),
                ('MIMU', 'Mimu Crypto Trust', 500, 45, '➖ FLAT'),
                ('ARE', 'Athena Real Estate', 2500, 10, ' FLAT'),
                ('PAL', 'Palantir Analytics', 8000, 25, '➖ FLAT')
            ]
            cursor.executemany("INSERT OR IGNORE INTO stocks (symbol, name, price, volatility, trend) VALUES (?, ?, ?, ?, ?)", new_stocks)

    # ==========================================
    # 📉 AUTOMATED BACKGROUND TASKS
    # ==========================================
    @tasks.loop(hours=2)
    async def market_fluctuation(self):
        with get_db_cursor() as cursor:
            cursor.execute("SELECT symbol, price, volatility FROM stocks")
            stocks = cursor.fetchall()
            
            for sym, price, vol in stocks:
                change = random.uniform(-vol, vol) / 100.0
                new_price = max(10, int(price + (price * change))) 
                trend = "<:stockup_athena:1503776772850712616> UP" if new_price > price else "<:stockdown_athena:1503776838789501171> DOWN" if new_price < price else "➖ FLAT"
                cursor.execute("UPDATE stocks SET price = ?, trend = ? WHERE symbol = ?", (new_price, trend, sym))

    @tasks.loop(hours=24)
    async def dividend_payouts(self):
        with get_db_cursor() as cursor:
# ---- GUARD: only run once per real 24h ----
            now = time.time()
            cursor.execute("SELECT last_run FROM cycle_tracker WHERE key = 'last_div_cycle'")
            row = cursor.fetchone()
            if row and (now - row[0]) < 86400:
                return  # already paid today
            cursor.execute("INSERT OR REPLACE INTO cycle_tracker (key, last_run) VALUES ('last_div_cycle', ?)", (now,))
        # ---- END GUARD ----

            cursor.execute("SELECT p.user_id, p.shares, s.price, p.symbol FROM portfolio p JOIN stocks s ON p.symbol = s.symbol")
            holdings = cursor.fetchall()

            user_payouts = {}
            for uid, shares, price, sym in holdings:
                yield_rate = {"CRV": 0.01, "MIMU": 0.05, "ARE": 0.03, "PAL": 0.04}.get(sym, 0.02)
                payout = int((shares * price) * yield_rate)
                if payout > 0:
                    user_payouts[uid] = user_payouts.get(uid, 0) + payout

            for uid, amount in user_payouts.items():
                max_retries = 3
                for _ in range(max_retries):
                    if atomic_balance_update(cursor, uid, amount):
                        log_transaction(cursor, uid, amount, "DIVIDEND", "Daily portfolio yield")
                        break
                apply_tier_upgrade(cursor, uid)

    # ==========================================
    # 🔍 AUTOCOMPLETE FUNCTIONS
    # ==========================================
    async def stock_autocomplete(self, interaction: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
        with get_db_cursor() as cursor:
            cursor.execute("SELECT symbol, name FROM stocks")
            stocks = cursor.fetchall()
        
        choices = [
            app_commands.Choice(name=f"{name} ({sym})", value=sym)
            for sym, name in stocks if current.lower() in sym.lower() or current.lower() in name.lower()
        ]
        return choices[:25] 

    async def portfolio_autocomplete(self, interaction: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
        with get_db_cursor() as cursor:
            cursor.execute("SELECT symbol FROM portfolio WHERE user_id = ?", (interaction.user.id,))
            owned = [r[0] for r in cursor.fetchall()]
        
        choices = [
            app_commands.Choice(name=sym, value=sym)
            for sym in owned if current.lower() in sym.lower()
        ]
        return choices[:25]

    # ==========================================
    # 📈 USER COMMANDS
    # ==========================================
    invest_group = app_commands.Group(name="invest", description="Wall Street Investment & Portfolio commands")

    @invest_group.command(name="market", description="View the current stock market prices and dividend yields")
    async def market(self, interaction: discord.Interaction):
        with get_db_cursor() as cursor:
            cursor.execute("SELECT symbol, name, price, trend, volatility FROM stocks")
            stocks = cursor.fetchall()

        embed = discord.Embed(title="꒰ა Athena Stock Exchange  ⸝⸝", color=0xffffff, description="*Prices fluctuate naturally every 2 hours based on asset volatility. Dividends are paid every 24H.*")
        for sym, name, price, trend, vol in stocks:
            risk = " Low" if vol <= 5 else " Med" if vol <= 20 else " High"
            div = {"CRV": "1%", "MIMU": "5%", "ARE": "3%", "PAL": "4%"}.get(sym, "2%")
            
            embed.add_field(
                name=f"<:stockmarket:1503803868415529152> {name} ({sym})", 
                value=f"**Price:** A$ {price:,} <:athenacoin:1503804322280902767>\n**Trend:** {trend}\n**Risk:** {risk} Volatility\n**Daily Yield:** {div}", 
                inline=False
            )
        
        await interaction.response.send_message(embed=embed, view=InvestGuideView())

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
            cursor.execute("UPDATE stocks SET price = ?, trend = 'UP' WHERE symbol = ?", (new_price, symbol))

        embed = discord.Embed(title="ა ﹒chérie  ⸝⸝", color=0xffffff)
        embed.description = f"<a:wt_torolove:1480580899430203484> **Market Manipulation Successful**\nForced **{symbol}** up by A$ {version:,}. New Price: **A$ {new_price:,}**."
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @invest_group.command(name="buy", description="Buy shares of a company")
    @app_commands.autocomplete(symbol=stock_autocomplete)
    async def buy(self, interaction: discord.Interaction, symbol: str, shares: int):
        if shares <= 0: return await interaction.response.send_message("❌ Invalid amount.", ephemeral=True)
        sym = symbol.upper()
        
        with get_db_cursor() as cursor:
            cursor.execute("SELECT price, name FROM stocks WHERE symbol = ?", (sym,))
            stock = cursor.fetchone()
            
            if not stock:
                return await interaction.response.send_message("❌ Invalid symbol. Please select one from the dropdown.", ephemeral=True)
                
            current_price = stock[0]
            total_cost = current_price * shares
            
            cursor.execute("SELECT balance FROM wallets WHERE user_id = ?", (interaction.user.id,))
            bal = cursor.fetchone()
            if not bal or bal[0] < total_cost:
                return await interaction.response.send_message(f"❌ Insufficient Capital. You need **A$ {total_cost:,}** to buy {shares:,} shares.", ephemeral=True)
                
            cursor.execute("SELECT shares, average_buy_price FROM portfolio WHERE user_id = ? AND symbol = ?", (interaction.user.id, sym))
            existing_pos = cursor.fetchone()
            
            if existing_pos:
                old_shares, old_avg = existing_pos[0], existing_pos[1]
                new_total_shares = old_shares + shares
                new_avg_price = ((old_shares * old_avg) + (shares * current_price)) / new_total_shares
            else:
                new_total_shares = shares
                new_avg_price = current_price

            # ✅ FIX: Atomic balance update
            if not atomic_balance_update(cursor, interaction.user.id, -total_cost):
                return await interaction.response.send_message("❌ Balance updated by another process. Please try again.", ephemeral=True)
                
            log_transaction(cursor, interaction.user.id, -total_cost, "BUY_STOCK", f"Purchased {shares} {sym} @ A$ {current_price:,}")
            
            cursor.execute('''INSERT INTO portfolio (user_id, symbol, shares, average_buy_price) 
                              VALUES (?, ?, ?, ?) 
                              ON CONFLICT(user_id, symbol) 
                              DO UPDATE SET shares = shares + ?, average_buy_price = ?''', 
                              (interaction.user.id, sym, new_total_shares, new_avg_price, shares, new_avg_price))
        
        await interaction.response.send_message(f"<:stockmarket1:1503803937000521971> **Trade Executed!**\nBought **{shares:,}** shares of **{stock[1]}** for **A$ {total_cost:,}**.\n*(Average Cost Basis: A$ {new_avg_price:,.2f} per share)*")

    @invest_group.command(name="sell", description="Sell your owned shares")
    @app_commands.autocomplete(symbol=portfolio_autocomplete)
    async def sell(self, interaction: discord.Interaction, symbol: str, shares: int):
        if shares <= 0: return await interaction.response.send_message("❌ Invalid amount.", ephemeral=True)
        sym = symbol.upper()
        
        with get_db_cursor() as cursor:
            cursor.execute("SELECT shares, average_buy_price FROM portfolio WHERE user_id = ? AND symbol = ?", (interaction.user.id, sym))
            owned = cursor.fetchone()
            
            if not owned or owned[0] < shares:
                return await interaction.response.send_message(f"❌ You don't own {shares:,} shares of {sym}.", ephemeral=True)
                
            cursor.execute("SELECT price, name FROM stocks WHERE symbol = ?", (sym,))
            stock = cursor.fetchone()
            
            current_price = stock[0]
            total_value = current_price * shares
            
            avg_buy_price = owned[1]
            cost_basis = avg_buy_price * shares
            profit = total_value - cost_basis
            profit_str = f"+ A$ {profit:,.2f}" if profit >= 0 else f"- A$ {abs(profit):,.2f}"
            
            cursor.execute("UPDATE portfolio SET shares = shares - ? WHERE user_id = ? AND symbol = ?", (shares, interaction.user.id, sym))
            cursor.execute("DELETE FROM portfolio WHERE user_id = ? AND symbol = ? AND shares <= 0", (interaction.user.id, sym))
            
            # ✅ FIX: Atomic balance update
            atomic_balance_update(cursor, interaction.user.id, total_value)
            log_transaction(cursor, interaction.user.id, total_value, "SELL_STOCK", f"Sold {shares} {sym} @ A$ {current_price:,}")
            
            # Check for tier upgrade on profit
            apply_tier_upgrade(cursor, interaction.user.id)

        await interaction.response.send_message(f"<:stockmarket1:1503803937000521971> **Trade Executed!**\nSold **{shares:,}** shares of **{stock[1]}** for **A$ {total_value:,}**.\n**Trade P/L:** `{profit_str}`")

    @invest_group.command(name="portfolio", description="View your investments and real-time performance")
    async def portfolio(self, interaction: discord.Interaction):
        with get_db_cursor() as cursor:
            cursor.execute('''SELECT p.symbol, p.shares, p.average_buy_price, s.price, s.name 
                              FROM portfolio p JOIN stocks s ON p.symbol = s.symbol 
                              WHERE p.user_id = ?''', (interaction.user.id,))
            holdings = cursor.fetchall()

        if not holdings: 
            return await interaction.response.send_message("Your portfolio is currently empty. Run `/invest market` to view available assets!", ephemeral=True)

        embed = discord.Embed(title=f"꒰ა {interaction.user.name}'s Investment Portfolio  ⸝⸝", color=0xffffff)
        
        total_net_worth = 0
        total_cost_basis = 0
        
        for sym, shares, avg_buy, current_price, name in holdings:
            value = shares * current_price
            cost = shares * avg_buy
            
            total_net_worth += value
            total_cost_basis += cost
            
            pl_amount = value - cost
            pl_percent = ((current_price - avg_buy) / avg_buy) * 100 if avg_buy > 0 else 0
            
            if pl_amount > 0:
                marker = "<:stockup_athena:1503776772850712616> "
                pl_str = f"+A$ {pl_amount:,.0f} (+{pl_percent:.1f}%)"
            elif pl_amount < 0:
                marker = "<:stockdown_athena:1503776838789501171> "
                pl_str = f"-A$ {abs(pl_amount):,.0f} ({pl_percent:.1f}%)"
            else:
                marker = "⬜"
                pl_str = f"A$ 0.00 (0.0%)"

            desc = (
                f"**Shares Owned:** {shares:,}\n"
                f"**Avg Cost:** A$ {avg_buy:,.0f} | **Current:** A$ {current_price:,}\n"
                f"**Market Value:** A$ {value:,} <:athenacoin:1503804322280902767>\n"
                f"**Return:** {marker}`{pl_str}`\n\n"
            )
            embed.add_field(name=f"{name} ({sym})", value=desc, inline=False)
            
        total_pl = total_net_worth - total_cost_basis
        health_emoji = "<:stockup_athena:1503776772850712616> " if total_pl >= 0 else "<:stockdown_athena:1503776838789501171> "
        embed.description = f"**Total Asset Value:** A$ {total_net_worth:,.0f}\n**Net P/L:** {health_emoji}`A$ {total_pl:,.0f}`"
        
        await interaction.response.send_message(embed=embed, view=InvestGuideView())

async def setup(bot):
    await bot.add_cog(Investments(bot))