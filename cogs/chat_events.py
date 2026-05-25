import discord
from discord import app_commands
from discord.ext import commands, tasks
import random
import sqlite3
from contextlib import contextmanager

DB_PATH = "economy.db"
GENERAL_CHANNEL_ID = 1441473281420169367  # ⚠️ REPLACE WITH YOUR ACTUAL GENERAL CHAT CHANNEL ID

@contextmanager
def get_db_cursor():
    conn = sqlite3.connect(DB_PATH, timeout=20, isolation_level=None)
    conn.execute('PRAGMA journal_mode=WAL;')
    cursor = conn.cursor()
    try:
        yield cursor
        conn.commit()
    finally:
        conn.close()

class DropClaimView(discord.ui.View):
    def __init__(self, amount: int):
        super().__init__(timeout=120)
        self.amount = amount
        self.claimed = False

    @discord.ui.button(label="Claim It!", style=discord.ButtonStyle.primary, emoji="🎁")
    async def claim_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.claimed:
            return await interaction.response.send_message("Too slow! Someone already grabbed this.", ephemeral=False)
        
        self.claimed = True
        button.disabled = True
        button.label = "Claimed!"
        
        with get_db_cursor() as c:
            c.execute("INSERT OR IGNORE INTO wallets (user_id, balance) VALUES (?, 0)", (interaction.user.id,))
            c.execute("UPDATE wallets SET balance = balance + ? WHERE user_id = ?", (self.amount, interaction.user.id))
            
        await interaction.response.edit_message(view=self)
        await interaction.followup.send(f"<a:cu_yay:1381390747776843920> **{interaction.user.mention}** snatched **A$ {self.amount:,}** from the drop!", ephemeral=False)

class LotteryView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Buy Ticket (A$ 500)", style=discord.ButtonStyle.secondary, emoji="🎟️", custom_id="lottery_buy")
    async def buy_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        with get_db_cursor() as c:
            c.execute("SELECT balance FROM wallets WHERE user_id = ?", (interaction.user.id,))
            bal = c.fetchone()
            if not bal or bal[0] < 500:
                return await interaction.response.send_message("❌ You need at least A$ 500 to buy a ticket.", ephemeral=True)
            
            c.execute("SELECT 1 FROM lottery_tickets WHERE user_id = ?", (interaction.user.id,))
            if c.fetchone():
                return await interaction.response.send_message("❌ You already bought a ticket for this draw!", ephemeral=True)

            c.execute("UPDATE wallets SET balance = balance - 500 WHERE user_id = ?", (interaction.user.id,))
            c.execute("INSERT OR IGNORE INTO lottery_tickets (user_id) VALUES (?)", (interaction.user.id,))
            
        await interaction.response.send_message("🎟️ **Ticket Purchased!** You are entered into the next draw.", ephemeral=True)

class ChatEvents(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.drop_loop.start()
        self.lottery_draw.start()
        
    def cog_unload(self):
        self.drop_loop.cancel()
        self.lottery_draw.cancel()

    @tasks.loop(minutes=20)
    async def drop_loop(self):
        channel = self.bot.get_channel(GENERAL_CHANNEL_ID)
        if not channel: return
        
        # Only drop if the chat has been active in the last 10 minutes
        recent = False
        async for msg in channel.history(limit=1):
            if (discord.utils.utcnow() - msg.created_at).total_seconds() < 600:
                recent = True
        
        if not recent: return
        
        amount = random.randint(900, 1200)
        view = DropClaimView(amount)
        await channel.send(f"<a:s_yellow:1405216230733779065> **A wild cash drop appeared!** First to click gets **A$ {amount:,}**!", view=view)

    @tasks.loop(hours=5)
    async def lottery_draw(self):
        channel = self.bot.get_channel(GENERAL_CHANNEL_ID)
        if not channel: return
        
        with get_db_cursor() as c:
            c.execute("CREATE TABLE IF NOT EXISTS lottery_tickets (user_id INTEGER PRIMARY KEY)")
            c.execute("SELECT user_id FROM lottery_tickets")
            tickets = c.fetchall()
            
            if not tickets:
                await channel.send("🎟️ **Lottery Draw:** No one bought tickets this round! The pot resets.")
                return
            
            winner_id = random.choice(tickets)[0]
            pot = len(tickets) * 500
            
            c.execute("INSERT OR IGNORE INTO wallets (user_id, balance) VALUES (?, 0)", (winner_id,))
            c.execute("UPDATE wallets SET balance = balance + ? WHERE user_id = ?", (pot, winner_id))
            c.execute("DELETE FROM lottery_tickets")
            
        winner = self.bot.get_user(winner_id)
        embed = discord.Embed(title="<a:cu_yay:1381390747776843920> Lottery Winner!", color=0xffffff)
        embed.description = f"**{winner.mention if winner else 'Unknown User'}** won the pot of **A$ {pot:,}**!"
        await channel.send(embed=embed, view=LotteryView())

    @drop_loop.before_loop
    @lottery_draw.before_loop
    async def before_tasks(self):
        await self.bot.wait_until_ready()

    @app_commands.command(name="pick", description="Scavenge the general chat for hidden drops")
    @app_commands.checks.cooldown(1, 3600)
    async def pick(self, interaction: discord.Interaction):
        amount = random.randint(800, 1300)
        with get_db_cursor() as c:
            c.execute("INSERT OR IGNORE INTO wallets (user_id, balance) VALUES (?, 0)", (interaction.user.id,))
            c.execute("UPDATE wallets SET balance = balance + ? WHERE user_id = ?", (amount, interaction.user.id))
            
        embed = discord.Embed(title="<a:wt_torocellphone:1503815758730366976> Scavenging...", color=0xffffff)
        embed.description = f"You searched the couches and found **A$ {amount:,}**!"
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @pick.error
    async def pick_error(self, interaction: discord.Interaction, error):
        if isinstance(error, app_commands.CommandOnCooldown):
            await interaction.response.send_message(f"You've already scavenged recently. Try again in **{int(error.retry_after // 60)}m**.", ephemeral=True)

async def setup(bot):
    await bot.add_cog(ChatEvents(bot))