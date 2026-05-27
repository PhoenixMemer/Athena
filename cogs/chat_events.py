import discord
from discord import app_commands
from discord.ext import commands, tasks
import random
import sqlite3
import time
from contextlib import contextmanager

DB_PATH = "economy.db"
GENERAL_CHANNEL_ID = 1441473281420169367  # ⚠️ REPLACE WITH YOUR ACTUAL GENERAL CHAT CHANNEL ID

@contextmanager
def get_db_cursor():
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

def atomic_balance_update(cursor, user_id: int, delta: int) -> bool:
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

class DropClaimView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)
        self.claimed_users = set()
        self.max_claims = 4

    @discord.ui.button(label="Snatch the Bag!", style=discord.ButtonStyle.green, emoji="<a:torosilly:1509258779617919086>")
    async def claim_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id in self.claimed_users:
            return await interaction.response.send_message("You already grabbed a cut from this bag!", ephemeral=True)
        
        if len(self.claimed_users) >= self.max_claims:
            return await interaction.response.send_message("The bag is empty! You were too slow <a:wt_torocryflail:1480580960566378711>", ephemeral=True)
        
        self.claimed_users.add(interaction.user.id)
        amount = random.randint(800, 2500)
        
        with get_db_cursor() as c:
            c.execute("INSERT OR IGNORE INTO wallets (user_id, balance, active_card, highest_balance) VALUES (?, 0, 'silver', 0)", (interaction.user.id,))
            atomic_balance_update(c, interaction.user.id, amount)
            
        if len(self.claimed_users) >= self.max_claims:
            button.disabled = True
            button.label = "Bag Empty!"
            try:
                await interaction.message.edit(view=self)
            except Exception:
                pass
                
        await interaction.response.send_message(f"<a:torosilly:1509258779617919086> **{interaction.user.mention}** snatched <:athenacoin:1503804322280902767> **A$ {amount:,}** from the drop!", ephemeral=False)

class ChatEvents(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.setup_db()
        self.drop_loop.start()
        self.lottery_draw.start()

    def cog_unload(self):
        self.drop_loop.cancel()
        self.lottery_draw.cancel()

    def setup_db(self):
        with get_db_cursor() as c:
            c.execute('''CREATE TABLE IF NOT EXISTS lottery_tickets (
                user_id INTEGER PRIMARY KEY,
                timestamp REAL
            )''')
            c.execute('''CREATE TABLE IF NOT EXISTS command_cooldowns (
                user_id INTEGER, 
                command_name TEXT, 
                last_used REAL,
                PRIMARY KEY (user_id, command_name)
            )''')

    @tasks.loop(minutes=15)
    async def drop_loop(self):
        channel = self.bot.get_channel(GENERAL_CHANNEL_ID)
        if not channel:
            return
        
        recent = False
        try:
            async for msg in channel.history(limit=1):
                if (discord.utils.utcnow() - msg.created_at).total_seconds() < 600:
                    recent = True
        except Exception:
            return
            
        if not recent:
            return
            
        embed = discord.Embed(
            title="꒰ა A Wild Cash Drop Appeared! ⸝⸝",
            description="A bag of unmarked bills just fell from an armored truck!",
            color=0xffffff
        )
        
        view = DropClaimView()
        await channel.send(embed=embed, view=view)

    @tasks.loop(hours=8)
    async def lottery_draw(self):
        channel = self.bot.get_channel(GENERAL_CHANNEL_ID)
        if not channel:
            return
            
        with get_db_cursor() as c:
            c.execute("SELECT user_id FROM lottery_tickets")
            tickets = c.fetchall()
            
            if not tickets:
                await channel.send("🎟️ **Lottery Draw:** No one bought tickets this round! The pot resets.")
                return
                
            winner_id = random.choice(tickets)[0]
            prize = random.randint(5000, 11000)
            
            c.execute("INSERT OR IGNORE INTO wallets (user_id, balance, active_card, highest_balance) VALUES (?, 0, 'silver', 0)", (winner_id,))
            atomic_balance_update(c, winner_id, prize)
            c.execute("DELETE FROM lottery_tickets")
            
        winner = self.bot.get_user(winner_id)
        mention = winner.mention if winner else f"User ID {winner_id}"
        
        embed = discord.Embed(
            title="🎟️ Lottery Winner!",
            description=f"**{mention}** won the Central Reserve Lottery!\n\n**Prize:** A$ {prize:,}",
            color=0xffffff
        )
        await channel.send(embed=embed)

    @drop_loop.before_loop
    @lottery_draw.before_loop
    async def before_tasks(self):
        await self.bot.wait_until_ready()

    @app_commands.command(name="pick", description="Scavenge the general chat for hidden drops")
    @app_commands.checks.cooldown(1, 3600)
    async def pick(self, interaction: discord.Interaction):
        amount = random.randint(800, 1300)
        with get_db_cursor() as c:
            c.execute("INSERT OR IGNORE INTO wallets (user_id, balance, active_card, highest_balance) VALUES (?, 0, 'silver', 0)", (interaction.user.id,))
            atomic_balance_update(c, interaction.user.id, amount)
            
        embed = discord.Embed(
            title="🔍 Scavenging...",
            description=f"You searched the couches and found **A$ {amount:,}**!",
            color=0xffffff
        )
        await interaction.response.send_message(embed=embed, ephemeral=False)

    @pick.error
    async def pick_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.CommandOnCooldown):
            minutes = int(error.retry_after // 60)
            seconds = int(error.retry_after % 60)
            await interaction.response.send_message(
                f"You've already scavenged recently. Try again in **{minutes}m {seconds}s**.", 
                ephemeral=True
            )

    @app_commands.command(name="buyticket", description="Buy a lottery ticket for the 8-hour draw")
    async def lottery_buy(self, interaction: discord.Interaction):
        with get_db_cursor() as c:
            c.execute("SELECT balance FROM wallets WHERE user_id = ?", (interaction.user.id,))
            bal_row = c.fetchone()
            bal = bal_row[0] if bal_row else 0
            
            if bal < 500:
                return await interaction.response.send_message("❌ You need at least A$ 500 to buy a ticket.", ephemeral=True)
                
            c.execute("SELECT 1 FROM lottery_tickets WHERE user_id = ?", (interaction.user.id,))
            if c.fetchone():
                return await interaction.response.send_message("❌ You already bought a ticket for this draw!", ephemeral=True)
                
            atomic_balance_update(c, interaction.user.id, -500)
            c.execute("INSERT OR REPLACE INTO lottery_tickets (user_id, timestamp) VALUES (?, ?)", (interaction.user.id, time.time()))
            
        await interaction.response.send_message("<a:torosilly:1509258779617919086> **Ticket Purchased!** You are entered into the next 8 hour draw!", ephemeral=True)

async def setup(bot):
    await bot.add_cog(ChatEvents(bot))