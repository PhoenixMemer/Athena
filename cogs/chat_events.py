import discord
from discord import app_commands
from discord.ext import commands, tasks
import random
import sqlite3
import time
from contextlib import contextmanager

DB_PATH = "economy.db"
GENERAL_CHANNEL_ID = 1126516721952497756  # ⚠️ REPLACE WITH YOUR ACTUAL GENERAL CHAT CHANNEL ID

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
    def __init__(self, amount: int):
        super().__init__(timeout=120)
        self.amount = amount
        self.claimed = False

    @discord.ui.button(label="Snatch the Bag!", style=discord.ButtonStyle.primary, emoji="<a:torosilly:1509258779617919086>")
    async def claim_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.claimed:
            return await interaction.response.send_message("Too slow! Someone already grabbed this.", ephemeral=True)
        
        self.claimed = True
        button.disabled = True
        button.label = "Claimed!"
        
        with get_db_cursor() as db:
            db.execute("INSERT OR IGNORE INTO wallets (user_id, balance, active_card, highest_balance) VALUES (?, 0, 'silver', 0)", (interaction.user.id,))
            atomic_balance_update(db, interaction.user.id, self.amount)
            
        try:
            await interaction.response.edit_message(view=self)
        except discord.HTTPException:
            pass
            
        await interaction.channel.send(f"<a:torosilly:1509258779617919086> **{interaction.user.mention}** snatched **A$ {self.amount:,}** from the drop!")

class ChatEvents(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.setup_db()
        self.chat_loops.start()

    def cog_unload(self):
        self.chat_loops.cancel()

    def setup_db(self):
        with get_db_cursor() as c:
            c.execute('''CREATE TABLE IF NOT EXISTS lottery_tickets (
                user_id INTEGER PRIMARY KEY,
                timestamp REAL
            )''')
            c.execute('''CREATE TABLE IF NOT EXISTS chat_events_tracker (
                key TEXT PRIMARY KEY,
                value REAL DEFAULT 0
            )''')
            # Initialize tracker keys if they don't exist
            for key in ['last_cash_drop', 'last_lottery_draw', 'lottery_reminder_sent']:
                c.execute("INSERT OR IGNORE INTO chat_events_tracker (key, value) VALUES (?, 0)", (key,))

    def get_tracker(self, key: str) -> float:
        with get_db_cursor() as c:
            c.execute("SELECT value FROM chat_events_tracker WHERE key = ?", (key,))
            row = c.fetchone()
            return float(row[0]) if row else 0

    def set_tracker(self, key: str, value: float):
        with get_db_cursor() as c:
            c.execute("INSERT OR REPLACE INTO chat_events_tracker (key, value) VALUES (?, ?)", (key, value))

    async def is_chat_active(self, channel, seconds=600):
        """Checks if there was a non-bot message in the last X seconds (default 10 mins)"""
        try:
            async for msg in channel.history(limit=1):
                if not msg.author.bot and (discord.utils.utcnow() - msg.created_at).total_seconds() < seconds:
                    return True
        except Exception:
            pass
        return False

    @tasks.loop(minutes=5)
    async def chat_loops(self):
        channel = self.bot.get_channel(GENERAL_CHANNEL_ID)
        if not channel:
            return

        now = time.time()
        
        # ==========================================
        # 💰 CASH DROP LOGIC
        # ==========================================
        last_drop = self.get_tracker('last_cash_drop')
        time_since_drop = now - last_drop
        
        # Force drop if it's been over 2 hours, regardless of chat activity
        force_drop = time_since_drop > 7200  
        # Drop if chat is active and it's been at least 20 minutes
        active_drop = time_since_drop > 1200 and await self.is_chat_active(channel, 600) 
        
        if force_drop or active_drop:
            amount = random.randint(800, 2500)
            view = DropClaimView(amount)
            
            drop_embed = discord.Embed(
                title="꒰ა A Wild Cash Drop Appeared! ⸝⸝",
                description="A bag of unmarked bills just fell from an armored truck!",
                color=0xffffff
            )
            await channel.send(embed=drop_embed, view=view)
            self.set_tracker('last_cash_drop', now)

        # ==========================================
        # 🎟️ LOTTERY LOGIC (8 Hour Loop)
        # ==========================================
        last_draw = self.get_tracker('last_lottery_draw')
        time_since_draw = now - last_draw
        
        # If it's been 8 hours, draw the winner and reset
        if time_since_draw >= 28800: 
            with get_db_cursor() as c:
                c.execute("SELECT user_id FROM lottery_tickets")
                tickets = c.fetchall()
                
                if tickets:
                    winner_id = random.choice(tickets)[0]
                    pot = len(tickets) * 500
                    
                    c.execute("INSERT OR IGNORE INTO wallets (user_id, balance, active_card, highest_balance) VALUES (?, 0, 'silver', 0)", (winner_id,))
                    atomic_balance_update(c, winner_id, pot)
                    c.execute("DELETE FROM lottery_tickets")
                    
                    winner = self.bot.get_user(winner_id)
                    winner_mention = winner.mention if winner else f"User ID {winner_id}"
                    
                    win_embed = discord.Embed(
                        title="꒰ა Lottery Winner Drawn! ⸝⸝",
                        description=f"**{winner_mention}** won the pot of **A$ {pot:,}**!\n\nThe next lottery cycle has started.",
                        color=0xffd700
                    )
                    await channel.send(embed=win_embed)
                else:
                    await channel.send("🎟️ **Lottery Draw:** No one bought tickets this round! The pot resets.")
            
            # Reset draw timer and reminder flag
            self.set_tracker('last_lottery_draw', now)
            self.set_tracker('lottery_reminder_sent', 0)

        # ==========================================
        # 📢 LOTTERY REMINDER (Once per 8hr cycle)
        # ==========================================
        reminder_sent = self.get_tracker('lottery_reminder_sent')
        # Send reminder halfway through the cycle (after 4 hours) if not sent yet
        if time_since_draw >= 14400 and reminder_sent == 0:
            rem_embed = discord.Embed(
                title="꒰ა Lottery Reminder! ⸝⸝",
                description="Don't forget to buy your lottery tickets!\nUse `/lottery` to enter before the next draw.",
                color=0xffffff
            )
            await channel.send(embed=rem_embed)
            self.set_tracker('lottery_reminder_sent', 1)

    @chat_loops.before_loop
    async def before_chat_loops(self):
        await self.bot.wait_until_ready()

    @app_commands.command(name="pick", description="Scavenge the general chat for hidden drops")
    @app_commands.checks.cooldown(1, 3600)
    async def pick(self, interaction: discord.Interaction):
        amount = random.randint(800, 1300)
        with get_db_cursor() as db:
            db.execute("INSERT OR IGNORE INTO wallets (user_id, balance, active_card, highest_balance) VALUES (?, 0, 'silver', 0)", (interaction.user.id,))
            atomic_balance_update(db, interaction.user.id, amount)
            
        embed = discord.Embed(
            title="🔍 Scavenging...",
            description=f"You searched the couches and found **A$ {amount:,}**!",
            color=0xffffff
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @pick.error
    async def pick_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.CommandOnCooldown):
            minutes = int(error.retry_after // 60)
            seconds = int(error.retry_after % 60)
            await interaction.response.send_message(f"⏳ You've already scavenged recently. Try again in **{minutes}m {seconds}s**.", ephemeral=True)

    @app_commands.command(name="lottery", description="Buy a lottery ticket for the 8-hour draw (A$ 500)")
    async def lottery_buy(self, interaction: discord.Interaction):
        with get_db_cursor() as db:
            db.execute("SELECT balance FROM wallets WHERE user_id = ?", (interaction.user.id,))
            bal_row = db.fetchone()
            bal = bal_row[0] if bal_row else 0
            
            if bal < 500:
                return await interaction.response.send_message("❌ You need at least A$ 500 to buy a ticket.", ephemeral=True)
            
            db.execute("SELECT 1 FROM lottery_tickets WHERE user_id = ?", (interaction.user.id,))
            if db.fetchone():
                return await interaction.response.send_message("❌ You already bought a ticket for this draw!", ephemeral=True)

            atomic_balance_update(db, interaction.user.id, -500)
            db.execute("INSERT OR REPLACE INTO lottery_tickets (user_id, timestamp) VALUES (?, ?)", (interaction.user.id, time.time()))
            
        await interaction.response.send_message("🎟️ **Ticket Purchased!** You are entered into the next 8-hour draw.", ephemeral=True)

async def setup(bot):
    await bot.add_cog(ChatEvents(bot))