import discord
from discord import app_commands
from discord.ext import commands, tasks
import sqlite3
import random

DB_PATH = "economy.db"

class Investments(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.setup_db()
        self.market_fluctuation.start() # Starts the living market!

    def setup_db(self):
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('''CREATE TABLE IF NOT EXISTS stocks (
            symbol TEXT PRIMARY KEY, name TEXT, price INTEGER, volatility INTEGER, trend TEXT
        )''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS portfolio (
            user_id INTEGER, symbol TEXT, shares INTEGER, UNIQUE(user_id, symbol)
        )''')
        
        # Inject default market assets if the table is empty
        cursor.execute("SELECT COUNT(*) FROM stocks")
        if cursor.fetchone()[0] == 0:
            stocks = [
                ('CRV', 'Central Reserve Bonds', 1000, 3, '➖ FLAT'),  # Low risk/low reward
                ('TEC', 'Athena Tech Sector', 5000, 15, '➖ FLAT'),    # Medium risk
                ('MIMU', 'Mimu Crypto Trust', 500, 45, '➖ FLAT')     # Insane risk
            ]
            cursor.executemany("INSERT INTO stocks VALUES (?, ?, ?, ?, ?)", stocks)
        conn.commit()
        conn.close()

    @tasks.loop(hours=2)
    async def market_fluctuation(self):
        """Randomly alters stock prices every 2 hours based on their volatility."""
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT symbol, price, volatility FROM stocks")
        stocks = cursor.fetchall()
        
        for sym, price, vol in stocks:
            change = random.uniform(-vol, vol) / 100.0
            new_price = max(10, int(price + (price * change))) # Prevents dropping below 10
            trend = "📈 UP" if new_price > price else "📉 DOWN" if new_price < price else "➖ FLAT"
            cursor.execute("UPDATE stocks SET price = ?, trend = ? WHERE symbol = ?", (new_price, trend, sym))
            
        conn.commit()
        conn.close()

    @market_fluctuation.before_loop
    async def before_market(self):
        await self.bot.wait_until_ready()

    invest_group = app_commands.Group(name="invest", description="Wall Street Investment commands")

    @invest_group.command(name="market", description="View the current stock market prices")
    async def market(self, interaction: discord.Interaction):
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT symbol, name, price, trend, volatility FROM stocks")
        stocks = cursor.fetchall()
        conn.close()

        embed = discord.Embed(title="📊 Athena Stock Exchange", color=0x2b2d31, description="*Prices fluctuate naturally every 2 hours based on asset volatility.*")
        for sym, name, price, trend, vol in stocks:
            risk = "Low" if vol <= 5 else "Med" if vol <= 20 else "High"
            embed.add_field(name=f"{name} ({sym})", value=f"**Price:** A$ {price:,}\n**Trend:** {trend}\n**Risk:** {risk} Volatility", inline=False)
        
        await interaction.response.send_message(embed=embed)

    @invest_group.command(name="buy", description="Buy shares of an asset")
    async def buy(self, interaction: discord.Interaction, symbol: str, shares: int):
        if shares <= 0: return await interaction.response.send_message("❌ Invalid amount.", ephemeral=True)
        sym = symbol.upper()
        
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT price, name FROM stocks WHERE symbol = ?", (sym,))
        stock = cursor.fetchone()
        if not stock:
            conn.close()
            return await interaction.response.send_message("❌ Invalid symbol. Use `/invest market`.", ephemeral=True)
            
        total_cost = stock[0] * shares
        cursor.execute("SELECT balance FROM wallets WHERE user_id = ?", (interaction.user.id,))
        bal = cursor.fetchone()
        if not bal or bal[0] < total_cost:
            conn.close()
            return await interaction.response.send_message(f"❌ You need **A$ {total_cost:,}** to buy {shares} shares.", ephemeral=True)
            
        # Execute Trade
        cursor.execute("UPDATE wallets SET balance = balance - ? WHERE user_id = ?", (total_cost, interaction.user.id))
        cursor.execute("INSERT INTO portfolio (user_id, symbol, shares) VALUES (?, ?, ?) ON CONFLICT(user_id, symbol) DO UPDATE SET shares = shares + ?", (interaction.user.id, sym, shares, shares))
        conn.commit()
        conn.close()
        await interaction.response.send_message(f"📈 **Trade Executed!**\nBought **{shares:,}** shares of **{stock[1]}** for **A$ {total_cost:,}**.")

    @invest_group.command(name="sell", description="Sell your shares")
    async def sell(self, interaction: discord.Interaction, symbol: str, shares: int):
        if shares <= 0: return await interaction.response.send_message("❌ Invalid amount.", ephemeral=True)
        sym = symbol.upper()
        
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT shares FROM portfolio WHERE user_id = ? AND symbol = ?", (interaction.user.id, sym))
        owned = cursor.fetchone()
        if not owned or owned[0] < shares:
            conn.close()
            return await interaction.response.send_message(f"❌ You don't own {shares} shares of {sym}.", ephemeral=True)
            
        cursor.execute("SELECT price, name FROM stocks WHERE symbol = ?", (sym,))
        stock = cursor.fetchone()
        total_value = stock[0] * shares
        
        # Execute Trade
        cursor.execute("UPDATE portfolio SET shares = shares - ? WHERE user_id = ? AND symbol = ?", (shares, interaction.user.id, sym))
        cursor.execute("UPDATE wallets SET balance = balance + ?, highest_balance = MAX(highest_balance, balance + ?) WHERE user_id = ?", (total_value, total_value, interaction.user.id))
        cursor.execute("DELETE FROM portfolio WHERE shares <= 0") # Cleanup
        conn.commit()
        conn.close()
        await interaction.response.send_message(f"📉 **Trade Executed!**\nSold **{shares:,}** shares of **{stock[1]}** for **A$ {total_value:,}**.")

    @invest_group.command(name="portfolio", description="View your current investments")
    async def portfolio(self, interaction: discord.Interaction):
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('''SELECT p.symbol, p.shares, s.price, s.name 
                          FROM portfolio p JOIN stocks s ON p.symbol = s.symbol 
                          WHERE p.user_id = ?''', (interaction.user.id,))
        holdings = cursor.fetchall()
        conn.close()

        if not holdings: return await interaction.response.send_message("💼 Your portfolio is empty. Run `/invest market`!", ephemeral=True)

        embed = discord.Embed(title=f"💼 {interaction.user.name}'s Portfolio", color=0x2b2d31)
        total_net_worth = 0
        for sym, shares, price, name in holdings:
            value = shares * price
            total_net_worth += value
            embed.add_field(name=f"{name} ({sym})", value=f"**Shares:** {shares:,}\n**Current Value:** A$ {value:,}", inline=False)
            
        embed.description = f"**Total Asset Value:** A$ {total_net_worth:,}"
        await interaction.response.send_message(embed=embed)

async def setup(bot): await bot.add_cog(Investments(bot))