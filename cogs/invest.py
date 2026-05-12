import discord
from discord import app_commands
from discord.ext import commands, tasks
import sqlite3
import random
from typing import List

DB_PATH = "economy.db"

def get_db_connection():
    # Adding a 20-second timeout gives tasks time to wait for a lock to release
    conn = sqlite3.connect(DB_PATH, timeout=20, isolation_level=None)
    # This line is the magic fix for "database is locked"
    conn.execute('PRAGMA journal_mode=WAL;') 
    conn.execute('PRAGMA temp_store = MEMORY;')
    conn.execute('PRAGMA synchronous = NORMAL;')
    return conn


# ==========================================
# 📖 THE BEGINNER'S GUIDE UI
# ==========================================
class InvestGuideView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="How to Trade?", style=discord.ButtonStyle.secondary, emoji="<a:wt_toronerd:1480580983593111602>")
    async def guide_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(title="📈 Athena Trading for Beginners", color=0x2b2d31)
        embed.description = (
            "Welcome to Wall Street! Here is how you can build your wealth:\n\n"
            "**1. Buy Low, Sell High**\n"
            "Stock prices naturally go 📈 UP or 📉 DOWN every 2 hours. Buy shares when they are cheap (especially during a market crash!). Sell them when the price is high to secure your profit.\n\n"
            "**2. Passive Income (Dividends)**\n"
            "Just by holding shares, you get paid! Every 24 hours, the Central Reserve automatically deposits a percentage of your total asset value directly into your wallet. (e.g., MIMU pays 5% daily!).\n\n"
            "**3. The Strategy**\n"
            "Use `/invest market` to spot cheap assets. Buy the dip with `/invest buy`. Check your `/invest portfolio` to track your Green 🟩 and Red 🟥 returns!"
        )
        embed.set_footer(text="Powered by Palantir")
        await interaction.response.send_message(embed=embed, ephemeral=True)


class Investments(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.setup_db()
        self.market_fluctuation.start() 
        self.dividend_payouts.start() 

    def setup_db(self):
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute('''CREATE TABLE IF NOT EXISTS stocks (
            symbol TEXT PRIMARY KEY, name TEXT, price INTEGER, volatility INTEGER, trend TEXT
        )''')
        
        cursor.execute('''CREATE TABLE IF NOT EXISTS portfolio (
            user_id INTEGER, symbol TEXT, shares INTEGER, average_buy_price REAL DEFAULT 0, UNIQUE(user_id, symbol)
        )''')
        
        try: cursor.execute("ALTER TABLE portfolio ADD COLUMN average_buy_price REAL DEFAULT 0")
        except: pass
        
        # Injects the new stocks (ARE and PAL) into your existing database!
        new_stocks = [
            ('CRV', 'Central Reserve Bonds', 1000, 3, '➖ FLAT'),  
            ('TEC', 'Athena Tech Sector', 5000, 15, '➖ FLAT'),    
            ('MIMU', 'Mimu Crypto Trust', 500, 45, '➖ FLAT'),
            ('ARE', 'Athena Real Estate', 2500, 10, '➖ FLAT'),
            ('PAL', 'Palantir Analytics', 8000, 25, '➖ FLAT')
        ]
        cursor.executemany("INSERT OR IGNORE INTO stocks (symbol, name, price, volatility, trend) VALUES (?, ?, ?, ?, ?)", new_stocks)
            
        conn.commit()
        conn.close()

    # ==========================================
    # 📉 AUTOMATED BACKGROUND TASKS
    # ==========================================
    @tasks.loop(hours=2)
    async def market_fluctuation(self):
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT symbol, price, volatility FROM stocks")
        stocks = cursor.fetchall()
        
        for sym, price, vol in stocks:
            change = random.uniform(-vol, vol) / 100.0
            new_price = max(10, int(price + (price * change))) 
            trend = "📈 UP" if new_price > price else "📉 DOWN" if new_price < price else "➖ FLAT"
            cursor.execute("UPDATE stocks SET price = ?, trend = ? WHERE symbol = ?", (new_price, trend, sym))
            
        conn.commit()
        conn.close()

    @tasks.loop(hours=24)
    async def dividend_payouts(self):
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("SELECT p.user_id, p.shares, s.price, p.symbol FROM portfolio p JOIN stocks s ON p.symbol = s.symbol")
        holdings = cursor.fetchall()

        user_payouts = {}
        for uid, shares, price, sym in holdings:
            yield_rate = 0.02 
            if sym == 'CRV': yield_rate = 0.01  
            elif sym == 'MIMU': yield_rate = 0.05 
            elif sym == 'ARE': yield_rate = 0.03
            elif sym == 'PAL': yield_rate = 0.04

            payout = int((shares * price) * yield_rate)
            user_payouts[uid] = user_payouts.get(uid, 0) + payout

        for uid, amount in user_payouts.items():
            if amount > 0:
                cursor.execute("INSERT OR IGNORE INTO wallets (user_id, balance) VALUES (?, 0)", (uid,))
                cursor.execute("UPDATE wallets SET balance = balance + ?, highest_balance = MAX(highest_balance, balance + ?) WHERE user_id = ?", (amount, amount, uid))
                
                # Silent card tier upgrade check
                cursor.execute("SELECT highest_balance, active_card FROM wallets WHERE user_id = ?", (uid,))
                row = cursor.fetchone()
                if row:
                    highest, current_card = row
                    new_card = current_card
                    for threshold, tier_key in [(100000,"gold"),(300000,"crystal"),(600000,"plat_black")]:
                        if highest >= threshold:
                            new_card = tier_key
                    if new_card != current_card:
                        cursor.execute("UPDATE wallets SET active_card = ? WHERE user_id = ?", (new_card, uid))

        conn.commit()
        conn.close()

    @market_fluctuation.before_loop
    @dividend_payouts.before_loop
    async def before_tasks(self):
        await self.bot.wait_until_ready()

    # ==========================================
    # 🔍 AUTOCOMPLETE FUNCTIONS
    # ==========================================
    async def stock_autocomplete(self, interaction: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT symbol, name FROM stocks")
        stocks = cursor.fetchall()
        conn.close()
        
        choices = [
            app_commands.Choice(name=f"{name} ({sym})", value=sym)
            for sym, name in stocks if current.lower() in sym.lower() or current.lower() in name.lower()
        ]
        return choices[:25] 

    async def portfolio_autocomplete(self, interaction: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT symbol FROM portfolio WHERE user_id = ?", (interaction.user.id,))
        owned = [r[0] for r in cursor.fetchall()]
        conn.close()
        
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
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT symbol, name, price, trend, volatility FROM stocks")
        stocks = cursor.fetchall()
        conn.close()

        embed = discord.Embed(title="📊 Athena Stock Exchange", color=0xffffff, description="*Prices fluctuate naturally every 2 hours based on asset volatility. Dividends are paid every 24H.*")
        for sym, name, price, trend, vol in stocks:
            risk = "🟢 Low" if vol <= 5 else "🟡 Med" if vol <= 20 else "🔴 High"
            div = "1%" if sym == "CRV" else "5%" if sym == "MIMU" else "3%" if sym == "ARE" else "4%" if sym == "PAL" else "2%"
            
            embed.add_field(
                name=f"{name} ({sym})", 
                value=f"**Price:** A$ {price:,}\n**Trend:** {trend}\n**Risk:** {risk} Volatility\n**Daily Yield:** {div}", 
                inline=False
            )
        
        await interaction.response.send_message(embed=embed, view=InvestGuideView())


    @app_commands.command(name="zmark", description="version numbers")
    async def pump_stock(self, interaction: discord.Interaction, symbol: str, version: int):
        # Locked strictly to your Discord ID!
        if interaction.user.id != 743411894416834590: 
            return await interaction.response.send_message("<a:wt_torono:1480580892706603018> Access Denied.", ephemeral=True)
            
        symbol = symbol.upper()
        conn = get_db_connection() # Or self.db_path depending on your invest.py setup
        cursor = conn.cursor()
        cursor.execute("SELECT price FROM stocks WHERE symbol = ?", (symbol,))
        row = cursor.fetchone()
        
        if not row:
            conn.close()
            return await interaction.response.send_message(f"<a:wt_torono:1480580892706603018> Stock {symbol} not found.", ephemeral=True)
            
        new_price = row[0] + version
        
        # Force the price up and artificially set the trend to UP
        cursor.execute("UPDATE stocks SET price = ?, trend = 'UP' WHERE symbol = ?", (new_price, symbol))
        conn.commit()
        conn.close()
        
        embed = discord.Embed(title="꒰ა ﹒chérie  ⸝⸝", color=0xffffff)
        embed.description = f"<a:wt_torolove:1480580899430203484> **Market Manipulation Successful**\nForced **{symbol}** up by A$ {version:,}. New Price: **A$ {new_price:,}**."
        await interaction.response.send_message(embed=embed, ephemeral=True)


    @invest_group.command(name="buy", description="Buy shares of a company")
    @app_commands.autocomplete(symbol=stock_autocomplete)
    async def buy(self, interaction: discord.Interaction, symbol: str, shares: int):
        if shares <= 0: return await interaction.response.send_message("❌ Invalid amount.", ephemeral=True)
        sym = symbol.upper()
        
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT price, name FROM stocks WHERE symbol = ?", (sym,))
        stock = cursor.fetchone()
        
        if not stock:
            conn.close()
            return await interaction.response.send_message("❌ Invalid symbol. Please select one from the dropdown.", ephemeral=True)
            
        current_price = stock[0]
        total_cost = current_price * shares
        
        cursor.execute("SELECT balance FROM wallets WHERE user_id = ?", (interaction.user.id,))
        bal = cursor.fetchone()
        if not bal or bal[0] < total_cost:
            conn.close()
            return await interaction.response.send_message(f"❌ Insufficient Capital. You need **A$ {total_cost:,}** to buy {shares:,} shares.", ephemeral=True)
            
        cursor.execute("SELECT shares, average_buy_price FROM portfolio WHERE user_id = ? AND symbol = ?", (interaction.user.id, sym))
        existing_pos = cursor.fetchone()
        
        if existing_pos:
            old_shares, old_avg = existing_pos[0], existing_pos[1]
            new_total_shares = old_shares + shares
            new_avg_price = ((old_shares * old_avg) + (shares * current_price)) / new_total_shares
        else:
            new_avg_price = current_price

        cursor.execute("UPDATE wallets SET balance = balance - ? WHERE user_id = ?", (total_cost, interaction.user.id))
        cursor.execute('''INSERT INTO portfolio (user_id, symbol, shares, average_buy_price) 
                          VALUES (?, ?, ?, ?) 
                          ON CONFLICT(user_id, symbol) 
                          DO UPDATE SET shares = shares + ?, average_buy_price = ?''', 
                          (interaction.user.id, sym, shares, new_avg_price, shares, new_avg_price))
        conn.commit()
        conn.close()
        
        await interaction.response.send_message(f"📈 **Trade Executed!**\nBought **{shares:,}** shares of **{stock[1]}** for **A$ {total_cost:,}**.\n*(Average Cost Basis: A$ {new_avg_price:,.2f} per share)*")

    @invest_group.command(name="sell", description="Sell your owned shares")
    @app_commands.autocomplete(symbol=portfolio_autocomplete)
    async def sell(self, interaction: discord.Interaction, symbol: str, shares: int):
        if shares <= 0: return await interaction.response.send_message("❌ Invalid amount.", ephemeral=True)
        sym = symbol.upper()
        
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT shares, average_buy_price FROM portfolio WHERE user_id = ? AND symbol = ?", (interaction.user.id, sym))
        owned = cursor.fetchone()
        
        if not owned or owned[0] < shares:
            conn.close()
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
        cursor.execute("UPDATE wallets SET balance = balance + ?, highest_balance = MAX(highest_balance, balance + ?) WHERE user_id = ?", (total_value, total_value, interaction.user.id))
        cursor.execute("DELETE FROM portfolio WHERE user_id = ? AND symbol = ? AND shares <= 0", (interaction.user.id, sym)) 
        conn.commit()
        conn.close()
        
        await interaction.response.send_message(f"📉 **Trade Executed!**\nSold **{shares:,}** shares of **{stock[1]}** for **A$ {total_value:,}**.\n**Trade P/L:** `{profit_str}`")

    @invest_group.command(name="portfolio", description="View your investments and real-time performance")
    async def portfolio(self, interaction: discord.Interaction):
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('''SELECT p.symbol, p.shares, p.average_buy_price, s.price, s.name 
                          FROM portfolio p JOIN stocks s ON p.symbol = s.symbol 
                          WHERE p.user_id = ?''', (interaction.user.id,))
        holdings = cursor.fetchall()
        conn.close()

        if not holdings: 
            return await interaction.response.send_message("💼 Your portfolio is currently empty. Run `/invest market` to view available assets!", ephemeral=True)

        embed = discord.Embed(title=f"💼 {interaction.user.name}'s Investment Portfolio", color=0xffffff)
        
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
                marker = "🟩"
                pl_str = f"+A$ {pl_amount:,.0f} (+{pl_percent:.1f}%)"
            elif pl_amount < 0:
                marker = "🟥"
                pl_str = f"-A$ {abs(pl_amount):,.0f} ({pl_percent:.1f}%)"
            else:
                marker = "⬜"
                pl_str = f"A$ 0.00 (0.0%)"

            desc = (
                f"**Shares Owned:** {shares:,}\n"
                f"**Avg Cost:** A$ {avg_buy:,.0f} | **Current:** A$ {current_price:,}\n"
                f"**Market Value:** A$ {value:,}\n"
                f"**Return:** {marker} `{pl_str}`"
            )
            embed.add_field(name=f"{name} ({sym})", value=desc, inline=False)
            
        total_pl = total_net_worth - total_cost_basis
        health_emoji = "📈" if total_pl >= 0 else "📉"
        embed.description = f"**Total Asset Value:** A$ {total_net_worth:,.0f}\n**Net P/L:** {health_emoji} `A$ {total_pl:,.0f}`"
        
        await interaction.response.send_message(embed=embed, view=InvestGuideView())

async def setup(bot): 
    await bot.add_cog(Investments(bot))