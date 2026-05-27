from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands, tasks
import sqlite3
import os
import io
import random
import datetime
import time
from contextlib import contextmanager
from PIL import Image, ImageDraw, ImageFont


BUSINESS_CHANNEL_ID = 1126516721952497756
DB_PATH = "economy.db"

import discord
from discord.ext import tasks
import random
import time

# 1. LOTTERY & DROP SETUP
# Run this in your setup_hook in main.py: self.lottery_loop.start()

@tasks.loop(hours=8)
async def lottery_loop(self):
    # This logic picks a winner from your lottery_participants table
    with get_db_cursor() as c:
        c.execute("SELECT user_id FROM lottery_participants")
        participants = [row[0] for row in c.fetchall()]
        if not participants: return
        
        winner_id = random.choice(participants)
        prize = random.randint(5000, 11000)
        
        # Pay the winner
        atomic_balance_update(c, winner_id, prize)
        c.execute("DELETE FROM lottery_participants") # Clear after drawing
        
        # Notify
        channel = self.bot.get_channel(BUSINESS_CHANNEL_ID)
        await channel.send(f"<a:wt_torofly:1480580890185826364> **LOTTERY DRAW:** <@{winner_id}> has won the Central Reserve Lottery! Payout: **A$ {prize:,}**")

# 2. CORPORATE RELIEF DROP (The /pick alternative)
# Add this counter logic inside your main.py message listener
activity_counter = 0

@tasks.loop(minutes=30)
async def relief_drop_loop(self):
    global activity_counter
    if activity_counter >= 100: # Threshold for active chat
        activity_counter = 0
        channel = self.bot.get_channel(BUSINESS_CHANNEL_ID)
        view = ReliefDropView()
        await channel.send(embed=discord.Embed(title="<:athenacoin:1503804322280902767> Corporate Relief Drop", description="The Central Reserve has taken money from mega corps to give payouts. Click below to claim!"), view=view)

class ReliefDropView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)
    
    @discord.ui.button(label="Claim Relief", style=discord.ButtonStyle.green, emoji="<a:happy_jumps:1504520522015178763>")
    async def claim(self, i: discord.Interaction, b: discord.ui.Button):
        amt = random.randint(1000, 2000)
        with get_db_cursor() as c:
            atomic_balance_update(c, i.user.id, amt)
        await i.response.send_message(f"Congrats! You got A$ {amt:,}!", ephemeral=False)
        self.stop()

@contextmanager
def get_db_cursor(db_path: str = DB_PATH):
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

CARD_TIERS = {
    "silver": {"threshold": 0, "file": "card_silver.png", "color": (255, 255, 255), "name": "Standard Silver", "multiplier": 1.0},
    "gold": {"threshold": 100000, "file": "card_gold.png", "color": (255, 255, 255), "name": "Gold Elite", "multiplier": 1.9},
    "crystal": {"threshold": 300000, "file": "card_crystal.png", "color": (255, 255, 255), "name": "Crystal Debit", "multiplier": 2.5},
    "plat_black": {"threshold": 600000, "file": "card_plat_black.png", "color": (214, 214, 214), "name": "Platinum Black", "multiplier": 3.5},
    "plat_pink": {"threshold": 600000, "file": "card_plat_pink.png", "color": (219, 120, 200), "name": "Platinum Chérie", "multiplier": 3.5},
    "signature": {"threshold": 1200000, "file": "card_signature.png", "color": (214, 214, 214), "name": "VISA Signature", "multiplier": 4.9},
    "signature_pink": {"threshold": 1200000, "file": "card_sigpink.png", "color": (255, 255, 255), "name": "VISA Chérie Signature", "multiplier": 5.3},
    "infinite": {"threshold": 3000000, "file": "card_infinite.png", "color": (214, 214, 214), "name": "VISA Infinite", "multiplier": 6.5},
    "world_debit": {"threshold": 4500000, "file": "card_worlddebit.png", "color": (214, 214, 214), "name": "VISA World Debit", "multiplier": 10.0}
}

TIER_THRESHOLDS = [
    (100000, "gold", "Gold Elite"),
    (300000, "crystal", "Crystal Debit"),
    (600000, "plat_black", "Platinum Black"),
    (1200000, "signature", "Signature"),
    (1200000, "signature_pink", "Signature Chérie"),
    (3000000, "infinite", "Infinite"),
    (4500000, "world_debit", "World Debit"),
]

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

def log_transaction(cursor, user_id: int, amount: int, tx_type: str, description: str):
    cursor.execute(
        "INSERT INTO transactions (user_id, amount, type, description) VALUES (?, ?, ?, ?)",
        (user_id, amount, tx_type.upper(), description)
    )

async def apply_balance_increase(user_id: int, amount: int, channel: discord.TextChannel = None, tx_type: str = "credit"):
    with get_db_cursor() as cursor:
        cursor.execute("INSERT OR IGNORE INTO wallets (user_id, balance, active_card, highest_balance) VALUES (?, 0, 'silver', 0)", (user_id,))
        
        max_retries = 3
        for attempt in range(max_retries):
            if atomic_balance_update(cursor, user_id, amount):
                log_transaction(cursor, user_id, amount, tx_type, f"Auto-credit: {tx_type}")
                
                cursor.execute("SELECT highest_balance, active_card FROM wallets WHERE user_id = ?", (user_id,))
                row = cursor.fetchone()
                if row is None: break
                
                highest, current_card = row
                current_card = (current_card or "silver").strip()
                new_card = current_card
                unlocked_name = None
                
                # FIX: Removed 'break' so it correctly catches the HIGHEST tier crossed
                for threshold, tier_key, tier_name in TIER_THRESHOLDS:
                    if (highest - amount) < threshold <= highest:
                        if tier_key != new_card:
                            new_card = tier_key
                            unlocked_name = tier_name
                
                if new_card != current_card:
                    cursor.execute("UPDATE wallets SET active_card = ? WHERE user_id = ?", (new_card, user_id))
                    log_transaction(cursor, user_id, 0, "UPGRADE", f"Card upgraded to {unlocked_name}")
                
                cursor.execute("SELECT balance FROM wallets WHERE user_id = ?", (user_id,))
                final_bal = cursor.fetchone()[0]
                break
        else:
            print(f"Balance update failed for user {user_id} after {max_retries} attempts")
            return None, None, None

    if unlocked_name and channel:
        embed = discord.Embed(title="꒰ა Rich Person Detected ⸝⸝", color=0xffffff)
        embed.description = f"<@{user_id}>, your earnings pushed your balance to **A$ {final_bal:,}**.\nYou have unlocked and automatically equipped the **{unlocked_name}** card!"
        try:
            await channel.send(embed=embed)
        except:
            pass

    return final_bal, new_card, unlocked_name

class StakingGuideView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="How does Staking work?", style=discord.ButtonStyle.secondary, emoji="🏦")
    async def guide_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(title="🏦 Athena Staking Guide", color=0xffffff)
        embed.description = (
            "**Staking** is a risk-free way to grow your wealth over time.\n\n"
            "**1. Lock Your Funds**\nYou deposit a set amount of A$ into the Central Reserve for a fixed period (3, 7, or 14 days).\n\n"
            "**2. Guaranteed Yield**\n• **3 Days:** +15% Yield\n• **7 Days:** +35% Yield\n• **14 Days:** +60% Yield\n\n"
            "**3. Claiming**\nOnce the time is up, use `/stake claim` to receive your original deposit PLUS the interest!"
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

class SimplePaginationView(discord.ui.View):
    def __init__(self, items, title, items_per_page=5):
        super().__init__(timeout=180)
        self.title = title
        self.items_per_page = items_per_page
        self.current_page = 0
        self.pages = [items[i:i + items_per_page] for i in range(0, len(items), items_per_page)] if items else [[]]
        self.max_pages = len(self.pages)
        self.update_buttons()

    def update_buttons(self):
        self.prev_button.disabled = self.current_page == 0
        self.next_button.disabled = self.current_page >= self.max_pages - 1

    def get_embed(self):
        embed = discord.Embed(title=self.title, color=0xffffff)
        if not self.pages[0]:
            embed.description = "No data available."
            return embed
        page_data = self.pages[self.current_page]
        embed.description = "".join(page_data)
        embed.set_footer(text=f"Page {self.current_page + 1}/{self.max_pages}")
        return embed

    @discord.ui.button(label="⬅", style=discord.ButtonStyle.secondary)
    async def prev_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page -= 1
        self.update_buttons()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    @discord.ui.button(label="➡", style=discord.ButtonStyle.secondary)
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page += 1
        self.update_buttons()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

class EarlyClaimView(discord.ui.View):
    def __init__(self, db_path, user_id, amount):
        super().__init__(timeout=60)
        self.db_path = db_path
        self.user_id = user_id
        self.amount = amount

    @discord.ui.button(label="Accept Penalty & Claim", style=discord.ButtonStyle.danger)
    async def confirm_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("❌ This is not your stake.", ephemeral=True)

        penalty_fee = int(self.amount * 0.15)
        payout = self.amount - penalty_fee

        with get_db_cursor() as cursor:
            cursor.execute("DELETE FROM stakes WHERE user_id = ?", (self.user_id,))
            atomic_balance_update(cursor, self.user_id, payout)
            log_transaction(cursor, self.user_id, payout, "STAKE_EARLY_CLAIM", f"Early withdrawal penalty: -A$ {penalty_fee:,}")

        for child in self.children:
            child.disabled = True

        embed = discord.Embed(title="꒰ა Early Savings Withdrawal ⸝⸝", color=0xffffff)
        embed.description = f"You broke your lock period early.\n\n**Initial Deposit:** A$ {self.amount:,}\n**Penalty Fee (15%):** -A$ {penalty_fee:,}\n**Total Returned:** A$ {payout:,}"
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("❌ This is not your stake.", ephemeral=True)
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(content="Canceled. Your stake remains safely locked.", embed=None, view=self)

class Economy(commands.Cog):
    def setup_db(self):
        with get_db_cursor() as cursor:
            cursor.execute('''CREATE TABLE IF NOT EXISTS wallets (
                user_id INTEGER PRIMARY KEY, balance INTEGER DEFAULT 0,
                active_card TEXT DEFAULT 'silver', highest_balance INTEGER DEFAULT 0,
                last_daily REAL DEFAULT 0
            )''')
            
            cursor.execute('''CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER,
                amount INTEGER, type TEXT, description TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )''')
            
            cursor.execute('''CREATE TABLE IF NOT EXISTS loans (
                user_id INTEGER PRIMARY KEY, amount INTEGER, due_date REAL
            )''')
            
            cursor.execute('''CREATE TABLE IF NOT EXISTS stakes (
                user_id INTEGER PRIMARY KEY, amount INTEGER, unlock_time REAL, yield_rate REAL
            )''')
            
            cursor.execute('''CREATE TABLE IF NOT EXISTS config (
                id INTEGER PRIMARY KEY, mimu_rate INTEGER DEFAULT 100
            )''')
            
            # FIX: Added the missing command_cooldowns table
            cursor.execute('''CREATE TABLE IF NOT EXISTS command_cooldowns (
                user_id INTEGER, command_name TEXT, last_used REAL,
                PRIMARY KEY (user_id, command_name)
            )''')
            
            cursor.execute("INSERT OR IGNORE INTO config (id, mimu_rate) VALUES (1, 100)")

    def get_wallet_data(self, user_id: int):
        with get_db_cursor() as cursor:
            cursor.execute("SELECT balance, active_card FROM wallets WHERE user_id = ?", (user_id,))
            result = cursor.fetchone()
            if result:
                bal = result[0] or 0
                card = (result[1] or "silver").strip()
                return bal, card
            return 0, "silver"

    def get_rate(self) -> int:
        with get_db_cursor() as cursor:
            cursor.execute("SELECT mimu_rate FROM config WHERE id = 1")
            result = cursor.fetchone()
            return result[0] if result else 100

    async def generate_wallet_card(self, member: discord.Member, balance: int, requested_card: str) -> io.BytesIO:
        valid_card = requested_card.strip() if requested_card else "silver"
        if balance < CARD_TIERS[valid_card]["threshold"]:
            if balance >= 4500000: valid_card = "world_debit"
            elif balance >= 3000000: valid_card = "infinite"
            elif balance >= 1200000: valid_card = "signature"
            elif balance >= 600000: valid_card = "plat_black"
            elif balance >= 300000: valid_card = "crystal"
            elif balance >= 100000: valid_card = "gold"
            else: valid_card = "silver"

        card_info = CARD_TIERS[valid_card]
        img = Image.open(card_info["file"]).convert("RGBA")
        draw = ImageDraw.Draw(img)

        font_path = "card_font.ttf" if os.path.exists("card_font.ttf") else "cogs/card_font.ttf"
        try:
            font_main = ImageFont.truetype(font_path, 100)
        except IOError:
            font_main = ImageFont.load_default()

        draw.text((200, 930), member.name.upper()[:20], fill=card_info["color"], font=font_main)
        draw.text((1300, 930), f"A$ {balance:,}", fill=card_info["color"], font=font_main)

        buffer = io.BytesIO()
        img.save(buffer, format="PNG")
        buffer.seek(0)
        return buffer

    @tasks.loop(minutes=30)
    async def loan_debt_collector(self):
        with get_db_cursor() as cursor:
            now = datetime.datetime.now().timestamp()
            cursor.execute("SELECT user_id, amount FROM loans WHERE due_date <= ?", (now,))
            overdue_loans = cursor.fetchall()

            for user_id, amount in overdue_loans:
                repayment = int(amount * 1.10)
                atomic_balance_update(cursor, user_id, -repayment)
                log_transaction(cursor, user_id, -repayment, "LOAN_COLLECTION", "Overdue loan auto-collected")
                cursor.execute("DELETE FROM loans WHERE user_id = ?", (user_id,))
                try:
                    user = self.bot.get_user(user_id)
                    if user:
                        await user.send(f"🏦 **LOAN COLLECTION:** Deducted **A$ {repayment:,}**.")
                except:
                    pass

    @tasks.loop(hours=48)
    async def debt_penalty_loop(self):
        with get_db_cursor() as cursor:
            cursor.execute("SELECT user_id, balance FROM wallets WHERE balance < 0")
            debtors = cursor.fetchall()
            for uid, bal in debtors:
                penalty = int(abs(bal) * 0.015)
                atomic_balance_update(cursor, uid, -penalty)
                log_transaction(cursor, uid, -penalty, "DEBT_PENALTY", "48h debt interest")

    @loan_debt_collector.before_loop
    @debt_penalty_loop.before_loop
    async def before_tasks(self):
        await self.bot.wait_until_ready()

    @commands.command(name="bal", aliases=["balance", "b"])
    async def prefix_bal(self, ctx: commands.Context):
        try:
            # Try to trigger the typing indicator and send the card
            async with ctx.typing():
                bal, active_card = self.get_wallet_data(ctx.author.id)
                image_buffer = await self.generate_wallet_card(ctx.author, bal, active_card)
                await ctx.send(file=discord.File(fp=image_buffer, filename="wallet.png"))
                
        except discord.Forbidden:
            # If the bot is blocked from typing/sending in that channel, try DMing the user instead
            try:
                await ctx.author.send("I don't have permission to type or send messages in that channel! Please ask a server admin to fix my permissions.")
            except discord.Forbidden:
                pass # The user has their DMs locked too, just fail silently without crashing the bot

    @tasks.loop(hours=8)
    async def run_lottery(self):
        with get_db_cursor() as c:
            c.execute("SELECT user_id FROM lottery")
            participants = c.fetchall()
            if not participants: return
            
            winner_id = random.choice(participants)[0]
            prize = random.randint(5000, 11000)
            
            # Pay the winner
            atomic_balance_update(c, winner_id, prize)
            # Clear the lottery
            c.execute("DELETE FROM lottery")
            
            channel = self.bot.get_channel(BUSINESS_CHANNEL_ID)
            await channel.send(f"<a:wt_torofly:1480580890185826364> **Central Reserve Lottery Winner!**\n<@{winner_id}> has won **A$ {prize:,}**!")

    @app_commands.command(name="lottery", description="Sign up for the 8-hour Central Reserve Lottery")
    async def lottery_signup(self, interaction: discord.Interaction):
        with get_db_cursor() as c:
            c.execute("INSERT OR IGNORE INTO lottery (user_id, timestamp) VALUES (?, ?)", (interaction.user.id, time.time()))
            await interaction.response.send_message("Congrats!! You've entered the Central Reserve Lottery!", ephemeral=True)

    @app_commands.command(name="rob", description="Attempt to rob another user. High risk, high reward.")
    async def rob(self, interaction: discord.Interaction, target: discord.Member):
        if target.id == interaction.user.id:
            return await interaction.response.send_message("You cannot rob yourself.", ephemeral=True)
        if target.bot:
            return await interaction.response.send_message("You cannot rob a bot.", ephemeral=True)
            
        with get_db_cursor() as cursor:
            now = time.time()
            cooldown_duration = 3600
            cursor.execute("SELECT last_used FROM command_cooldowns WHERE user_id = ? AND command_name = 'rob'", (interaction.user.id,))
            row = cursor.fetchone()
            
            if row and (now - row[0] < cooldown_duration):
                rem = int(cooldown_duration - (now - row[0]))
                minutes, seconds = divmod(rem, 60)
                return await interaction.response.send_message(
                    f"<a:wt_toronerd:1480580983593111602> Lay low! Try again in **{minutes}m {seconds}s**.", 
                    ephemeral=True
                )
            
            cursor.execute("SELECT balance FROM wallets WHERE user_id = ?", (interaction.user.id,))
            robber_bal = (cursor.fetchone() or [0])[0]
            if robber_bal < 500:
                return await interaction.response.send_message("❌ You need at least **A$ 500** to fund a robbery.", ephemeral=True)

            cursor.execute("SELECT balance FROM wallets WHERE user_id = ?", (target.id,))
            target_bal = (cursor.fetchone() or [0])[0]
            if target_bal < 1000:
                return await interaction.response.send_message(f"❌ **{target.name}** is broke.", ephemeral=True)

            cursor.execute("INSERT OR REPLACE INTO command_cooldowns (user_id, command_name, last_used) VALUES (?, 'rob', ?)", (interaction.user.id, now))

            if random.random() > 0.60: 
                # FIX: Added missing second argument to random.uniform
                stolen_amount = int(target_bal * random.uniform(0.05, 0.9)) 
                atomic_balance_update(cursor, target.id, -stolen_amount)
                atomic_balance_update(cursor, interaction.user.id, stolen_amount)
                log_transaction(cursor, interaction.user.id, stolen_amount, "ROB_SUCCESS", f"Robbed {target.name}")
                log_transaction(cursor, target.id, -stolen_amount, "ROBBED", f"Robbed by {interaction.user.name}")
                embed = discord.Embed(title="꒰ა The Heist was a Success! ⸝⸝", color=0xffffff)
                embed.description = f"You slipped past security and successfully robbed **{target.mention}**!\n\n**Stolen:** A$ {stolen_amount:,}"
                await interaction.response.send_message(embed=embed)
            else:
                fine = max(500, int(robber_bal * 0.20))
                atomic_balance_update(cursor, interaction.user.id, -fine)
                log_transaction(cursor, interaction.user.id, -fine, "ROB_FAIL", f"Caught trying to rob {target.name}")
                embed = discord.Embed(title="꒰ა Busted! ⸝⸝", color=0xffffff)
                embed.description = f"You were caught trying to rob **{target.mention}**!\n\nFined **A$ {fine:,}**."
                await interaction.response.send_message(embed=embed)

    @app_commands.command(name="statement", description="View your official Athena Bank transaction history")
    async def statement(self, interaction: discord.Interaction):
        await interaction.response.defer()
        history = []
        with get_db_cursor() as cursor:
            cursor.execute("SELECT amount, type, description, timestamp FROM transactions WHERE user_id = ? ORDER BY timestamp DESC LIMIT 50", (interaction.user.id,))
            history = cursor.fetchall()

        if not history:
            return await interaction.followup.send("<a:wt_toroconfused:1480580932367945918> You have no transaction history.")

        formatted_logs = []
        for amount, t_type, desc, ts in history:
            clean_time = ts.split(".")[0] if "." in ts else ts
            type_upper = t_type.upper() if t_type else ""
            is_credit = type_upper in ("CREDIT", "DAILY", "WORK", "HEIST_WIN", "STAKING_CLAIM",
                                        "DIVIDEND", "TRANSFER_IN", "CASINO_WIN", "SELL_STOCK",
                                        "RENT_INCOME", "LOAN_DISBURSED", "ROB_SUCCESS")

            if is_credit:
                icon = "<:income_athena:1503894488299343892>"
                amt_str = f"+A$ {abs(amount):,}"
            else:
                icon = "<:expense_athena:1503894540220760226>"
                amt_str = f"-A$ {abs(amount):,}"

            formatted_logs.append(f"{icon} **{amt_str}** | {desc}\n└─ *{clean_time}*\n\n")

        view = SimplePaginationView(formatted_logs, "Official Bank Statement", items_per_page=5)
        await interaction.followup.send(embed=view.get_embed(), view=view)

    @app_commands.command(name="setcard", description="Equip an unlocked debit card tier")
    @app_commands.choices(card_type=[
        app_commands.Choice(name="Standard Silver (0+ A$)", value="silver"),
        app_commands.Choice(name="Gold Elite (100k+ A$)", value="gold"),
        app_commands.Choice(name="Crystal Debit (300k+ A$)", value="crystal"),
        app_commands.Choice(name="Platinum Black (600k+ A$)", value="plat_black"),
        app_commands.Choice(name="Platinum Chérie (600k+ A$)", value="plat_pink"),
        app_commands.Choice(name="Signature (1.2m+ A$)", value="signature"),
        app_commands.Choice(name="Signature Chérie (1.2m+ A$)", value="signature_pink"),
        app_commands.Choice(name="Infinite (3.0m+ A$)", value="infinite"),
        app_commands.Choice(name="World Debit (4.5m+ A$)", value="world_debit")
    ])
    async def setcard(self, interaction: discord.Interaction, card_type: app_commands.Choice[str]):
        bal, _ = self.get_wallet_data(interaction.user.id)
        if bal < CARD_TIERS[card_type.value]["threshold"]:
            return await interaction.response.send_message(f"❌ **Access Denied.** You need **A$ {CARD_TIERS[card_type.value]['threshold']:,}** to use this card.", ephemeral=True)

        with get_db_cursor() as cursor:
            cursor.execute("UPDATE wallets SET active_card = ? WHERE user_id = ?", (card_type.value, interaction.user.id))
            log_transaction(cursor, interaction.user.id, 0, "CARD_CHANGE", f"Equipped {CARD_TIERS[card_type.value]['name']}")

        embed = discord.Embed(title="꒰ა New Card Equipped ⸝⸝", color=0xffffff)
        embed.description = f"You have equipped the **{CARD_TIERS[card_type.value]['name']}**.\nRun `/bal` to view it."
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="give", description="Transfer Athena Coins to another user")
    async def give(self, interaction: discord.Interaction, user: discord.Member, amount: int):
        if amount <= 0: return await interaction.response.send_message("❌ Invalid amount.", ephemeral=True)
        if user.id == interaction.user.id: return await interaction.response.send_message("❌ Cannot transfer to yourself.", ephemeral=True)

        with get_db_cursor() as cursor:
            cursor.execute("SELECT balance FROM wallets WHERE user_id = ?", (interaction.user.id,))
            bal = cursor.fetchone()
            if not bal or bal[0] < amount:
                return await interaction.response.send_message("❌ Insufficient funds.", ephemeral=True)

            cursor.execute("SELECT amount FROM loans WHERE user_id = ?", (interaction.user.id,))
            active_loan = cursor.fetchone()
            if active_loan:
                required_repayment = int(active_loan[0] * 1.10)
                if (bal[0] - amount) < required_repayment:
                    return await interaction.response.send_message(f"❌ Transfer Denied: Active loan requires minimum balance of **A$ {required_repayment:,}**.", ephemeral=True)

            atomic_balance_update(cursor, interaction.user.id, -amount)
            atomic_balance_update(cursor, user.id, amount)
            log_transaction(cursor, interaction.user.id, -amount, "TRANSFER_OUT", f"Sent to {user.name}")
            log_transaction(cursor, user.id, amount, "TRANSFER_IN", f"Received from {interaction.user.name}")

        embed = discord.Embed(title="꒰ა Wire Transfer ⸝⸝", color=0xffffff)
        embed.description = f"Successfully transferred **A$ {amount:,}** to {user.mention}."
        await interaction.response.send_message(embed=embed)


    

    @app_commands.command(name="loan", description="Take a loan from the Central Reserve (Max 7 days)")
    @app_commands.describe(amount="Amount to borrow (Max A$ 100,000)", days="Days until repayment (1-7)")
    async def take_loan(self, interaction: discord.Interaction, amount: int, days: int):
        if not (100 <= amount <= 100000): return await interaction.response.send_message("Borrow limit: A$ 100 to A$ 100,000.", ephemeral=True)
        if not (1 <= days <= 7): return await interaction.response.send_message("Term limit: 1 to 7 days.", ephemeral=True)

        with get_db_cursor() as cursor:
            cursor.execute("SELECT amount, due_date FROM loans WHERE user_id = ?", (interaction.user.id,))
            active_loan = cursor.fetchone()
            if active_loan:
                due_timestamp = active_loan[1]
                time_left = due_timestamp - datetime.datetime.now().timestamp()
                time_str = f"{int(time_left // 86400)}d {int((time_left % 86400) // 3600)}h" if time_left > 0 else "Overdue"
                return await interaction.response.send_message(f"Active loan! Repayment of **A$ {int(active_loan[0]*1.10):,}** due in: **{time_str}**.", ephemeral=False)

            due_date = (datetime.datetime.now() + datetime.timedelta(days=days)).timestamp()
            cursor.execute("INSERT INTO loans (user_id, amount, due_date) VALUES (?, ?, ?)", (interaction.user.id, amount, due_date))
            atomic_balance_update(cursor, interaction.user.id, amount)
            log_transaction(cursor, interaction.user.id, amount, "LOAN_DISBURSED", f"{days}-day loan @ 10%")

        embed = discord.Embed(title="꒰ა Loan Granted ⸝⸝", color=0xffffff)
        embed.description = f"Credited **A$ {amount:,}**.\n\n**Due In:** {days} days\n**Repayment:** A$ {int(amount*1.10):,} (10% Interest)"
        await interaction.response.send_message(embed=embed)

    stake_group = app_commands.Group(name="stake", description="Stake Athena Coins for guaranteed returns")

    @stake_group.command(name="deposit", description="Lock A$ in the Reserve for guaranteed interest")
    @app_commands.choices(duration=[
        app_commands.Choice(name="3 Days (+15% Yield)", value=3),
        app_commands.Choice(name="7 Days (+35% Yield)", value=7),
        app_commands.Choice(name="14 Days (+60% Yield)", value=14)
    ])
    async def stake_deposit(self, interaction: discord.Interaction, amount: int, duration: app_commands.Choice[int]):
        if amount < 100: return await interaction.response.send_message("❌ Minimum stake is A$ 100.", ephemeral=True)

        with get_db_cursor() as cursor:
            cursor.execute("SELECT amount FROM stakes WHERE user_id = ?", (interaction.user.id,))
            if cursor.fetchone():
                return await interaction.response.send_message("❌ You already have an active stake!", ephemeral=True)

            cursor.execute("SELECT balance FROM wallets WHERE user_id = ?", (interaction.user.id,))
            bal = cursor.fetchone()
            if not bal or bal[0] < amount:
                return await interaction.response.send_message("❌ Insufficient funds.", ephemeral=True)

            yield_rates = {3: 0.15, 7: 0.35, 14: 0.60}
            rate = yield_rates[duration.value]
            unlock = (datetime.datetime.now() + datetime.timedelta(days=duration.value)).timestamp()

            atomic_balance_update(cursor, interaction.user.id, -amount)
            cursor.execute("INSERT INTO stakes (user_id, amount, unlock_time, yield_rate) VALUES (?, ?, ?, ?)", (interaction.user.id, amount, unlock, rate))
            log_transaction(cursor, interaction.user.id, -amount, "STAKE_DEPOSIT", f"Locked for {duration.value} days")

        embed = discord.Embed(title="꒰ა Savings Deposited ⸝⸝", color=0xffffff)
        embed.description = f"Locked **A$ {amount:,}** for **{duration.value} days**.\n\nExpected Return: **A$ {int(amount + (amount*rate)):,}**"
        await interaction.response.send_message(embed=embed, view=StakingGuideView())

    @stake_group.command(name="info", description="Check your current active stake")
    async def stake_info(self, interaction: discord.Interaction):
        with get_db_cursor() as cursor:
            cursor.execute("SELECT amount, unlock_time, yield_rate FROM stakes WHERE user_id = ?", (interaction.user.id,))
            row = cursor.fetchone()

        if not row:
            return await interaction.response.send_message("You have no active stakes.", view=StakingGuideView(), ephemeral=True)

        amount, unlock, rate = row
        payout = int(amount + (amount * rate))
        now = datetime.datetime.now().timestamp()

        embed = discord.Embed(title="꒰ა Savings Fund ⸝⸝", color=0xffffff)
        if now >= unlock:
            embed.description = f"**Status:** 🟢 Ready to Claim!\n**Deposit:** A$ {amount:,}\n**Payout:** A$ {payout:,}"
        else:
            time_left = unlock - now
            days, rem = divmod(time_left, 86400)
            hours, rem = divmod(rem, 3600)
            embed.description = f"**Status:** ⏳ Locked\n**Deposit:** A$ {amount:,}\n**Payout:** A$ {payout:,}\n**Time:** {int(days)}d {int(hours)}h"

        await interaction.response.send_message(embed=embed, view=StakingGuideView())

    @stake_group.command(name="claim", description="Claim a completed stake and collect your yield")
    async def stake_claim(self, interaction: discord.Interaction):
        with get_db_cursor() as cursor:
            cursor.execute("SELECT amount, unlock_time, yield_rate FROM stakes WHERE user_id = ?", (interaction.user.id,))
            row = cursor.fetchone()

            if not row:
                return await interaction.response.send_message("❌ No stakes to claim.", ephemeral=True)

            amount, unlock, rate = row

            if datetime.datetime.now().timestamp() < unlock:
                time_left = unlock - datetime.datetime.now().timestamp()
                days_left = int(time_left // 86400)
                hours_left = int((time_left % 86400) // 3600)

                embed = discord.Embed(title="꒰ა Proceed w/ Caution! ⸝⸝", color=0xffffff)
                embed.description = (
                    f"Locked for another **{days_left}d {hours_left}h**.\n\n"
                    "Early withdrawal incurs a **15% penalty fee**.\n\n"
                    f"**Deposit:** A$ {amount:,}\n"
                    f"**Penalty Return:** A$ {int(amount - (amount * 0.15)):,}"
                )
                view = EarlyClaimView(self.db_path, interaction.user.id, amount)
                return await interaction.response.send_message(embed=embed, view=view, ephemeral=False)

            payout = int(amount + (amount * rate))
            cursor.execute("DELETE FROM stakes WHERE user_id = ?", (interaction.user.id,))
            atomic_balance_update(cursor, interaction.user.id, payout)
            log_transaction(cursor, interaction.user.id, payout, "STAKE_CLAIM", "Matured stake")

        embed = discord.Embed(title="꒰ა Savings Extracted ⸝⸝", color=0xffffff)
        embed.description = f"Lock period over! Granted **A$ {payout:,}**."
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="daily", description="Claim your daily Athena Reserve allowance")
    async def daily(self, interaction: discord.Interaction):
        await interaction.response.defer()
        base_payout = 6000

        _, active_card = self.get_wallet_data(interaction.user.id)
        mult = CARD_TIERS.get(active_card, CARD_TIERS["silver"])["multiplier"]
        payout = int(base_payout * mult)

        with get_db_cursor() as cursor:
            cursor.execute("SELECT last_daily FROM wallets WHERE user_id = ?", (interaction.user.id,))
            row = cursor.fetchone()
            now = time.time()

            if row and row[0] and (now - row[0] < 86400):
                rem = int(86400 - (now - row[0]))
                hours, rem = divmod(rem, 3600)
                mins, secs = divmod(rem, 60)
                return await interaction.followup.send(f"<a:wt_toronerd:1480580983593111602> Please wait **{hours}h {mins}m {secs}s**.")

            cursor.execute("UPDATE wallets SET last_daily = ? WHERE user_id = ?", (now, interaction.user.id))

        await apply_balance_increase(interaction.user.id, payout, interaction.channel, tx_type="daily")

        card_name = CARD_TIERS.get(active_card, CARD_TIERS["silver"])["name"]
        embed = discord.Embed(title="꒰ა Daily Reward ⸝⸝", color=0xffffff)
        embed.description = (
            f"<a:wt_torolove:1480580899430203484> **Daily Allowance Credited**\n\n"
            f"**Base:** A$ {base_payout:,}\n"
            f"**{card_name} Bonus:** +A$ {payout - base_payout:,}\n"
            f"**Total:** A$ {payout:,}"
        )
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="heist", description="Attempt a corporate heist for massive payouts. High Risk.")
    @app_commands.checks.cooldown(1, 10800)
    async def heist(self, interaction: discord.Interaction):
        await interaction.response.defer()

        with get_db_cursor() as cursor:
            success = random.random() < 0.40

            if success:
                winnings = 10000
            else:
                fine = 3000
                atomic_balance_update(cursor, interaction.user.id, -fine)
                log_transaction(cursor, interaction.user.id, -fine, "HEIST_FINE", "Caught by Security")
                embed = discord.Embed(title="꒰ა Busted! ⸝⸝", color=0xffffff)
                embed.description = f"Caught by Athena Security. Fined **A$ {fine:,}**."
                return await interaction.followup.send(embed=embed)

        if success:
            await apply_balance_increase(interaction.user.id, winnings, interaction.channel, tx_type="heist_win")
            embed = discord.Embed(title="꒰ა Heist Successful! ⸝⸝", color=0xffffff)
            embed.description = f"Stole **A$ {winnings:,}**!"
            await interaction.followup.send(embed=embed)

    @app_commands.command(name="set_rate", description="ADMIN: Set the Mimu exchange rate")
    async def set_rate(self, interaction: discord.Interaction, new_rate: int):
        if interaction.user.id != 743411894416834590:
            return await interaction.response.send_message("❌ Access Denied.", ephemeral=True)
        if new_rate < 1:
            return await interaction.response.send_message("❌ Rate must be at least 1.", ephemeral=True)

        with get_db_cursor() as cursor:
            cursor.execute("UPDATE config SET mimu_rate = ? WHERE id = 1", (new_rate,))
        await interaction.response.send_message(f"✅ Rate Updated: 1 Athena = {new_rate} Mimu.")

    @app_commands.command(name="mint", description="ADMIN: Print Athena coins")
    async def mint_coins(self, interaction: discord.Interaction, user: discord.Member, amount: int):
        if interaction.user.id != 743411894416834590:
            return await interaction.response.send_message("❌ Access Denied.", ephemeral=True)

        await apply_balance_increase(user.id, amount, tx_type="admin_mint")
        await interaction.response.send_message(f"✅ Minted {amount:,} to {user.mention}.")

    @app_commands.command(name="deduct", description="ADMIN: Forcefully seize Athena coins")
    async def deduct_coins(self, interaction: discord.Interaction, user: discord.Member, amount: int):
        if interaction.user.id != 743411894416834590:
            return await interaction.response.send_message("❌ Access Denied.", ephemeral=True)

        with get_db_cursor() as cursor:
            atomic_balance_update(cursor, user.id, -amount)
            log_transaction(cursor, user.id, -amount, "ADMIN_DEDUCT", f"Seized by {interaction.user.name}")
            cursor.execute("SELECT balance FROM wallets WHERE user_id = ?", (user.id,))
            bal = cursor.fetchone()[0]

        embed = discord.Embed(title="꒰ა Assets Seized ⸝⸝", color=0xffffff)
        embed.description = f"Seized **A$ {amount:,}** from {user.mention}.\nNew Balance: **A$ {bal:,}**"
        await interaction.response.send_message(embed=embed)

async def setup(bot):
    await bot.add_cog(Economy(bot))

