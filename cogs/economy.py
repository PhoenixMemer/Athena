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

DB_PATH = "economy.db"

# ==========================================
# ️ SAFE DATABASE CONTEXT MANAGER
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
# 📊 CARD TIERS (FIXED: NO TRAILING SPACES)
# ==========================================
CARD_TIERS = {
    "silver": {"threshold": 0, "file": "card_silver.png", "color": (255, 255, 255), "name": "Standard Silver", "multiplier": 1.0},
    "gold": {"threshold": 100000, "file": "card_gold.png", "color": (255, 255, 255), "name": "Gold Elite", "multiplier": 1.9},
    "crystal": {"threshold": 300000, "file": "card_crystal.png", "color": (255, 255, 255), "name": "Crystal Debit", "multiplier": 2.5},
    "plat_black": {"threshold": 600000, "file": "card_plat_black.png", "color": (214, 214, 214), "name": "Platinum Black", "multiplier": 3.5},
    "plat_pink": {"threshold": 600000, "file": "card_plat_pink.png", "color": (219, 120, 200), "name": "Platinum Chérie", "multiplier": 3.5},
    
    "signature": {"threshold": 1200000, "file": "card_signature.png", "color": (214, 214, 214), "name": "VISA Signature", "multiplier": 4.9},
    "infinite": {"threshold": 3000000, "file": "card_infinite.png", "color": (214, 214, 214), "name": "VISA Infinite", "multiplier": 5.3},
    "world_debit": {"threshold": 4500000, "file": "card_worlddebit.png", "color": (214, 214, 214), "name": "VISA World Debit", "multiplier": 5.7},
    "signature_pink": {"threshold": 1200000, "file": "card_sigpink.png", "color": (255, 255, 255), "name": "VISA Chérie Signature", "multiplier": 5.3}
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

async def apply_balance_increase(user_id: int, amount: int, channel: discord.TextChannel = None, tx_type: str = "credit"):
    """
    Adds amount to user's wallet with atomic update, transaction logging, 
    and automatic tier upgrades. Thread-safe and race-condition resistant.
    """
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
                for threshold, tier_key, tier_name in TIER_THRESHOLDS:
    # threshold crossed during this increment?
                    if (highest - amount) < threshold <= highest:
        # keep the highest tier
                        if tier_key != new_card:   # but don't downgrade (if we already got a higher one)
            # assign order numbers to compare (or rely on threshold ascending)
                            new_card = tier_key
                            unlocked_name = tier_name
                            break
                
                if new_card != current_card:
                    cursor.execute("UPDATE wallets SET active_card = ? WHERE user_id = ?", (new_card, user_id))
                    log_transaction(cursor, user_id, 0, "UPGRADE", f"Card upgraded to {tier_name}")
                
                cursor.execute("SELECT balance FROM wallets WHERE user_id = ?", (user_id,))
                final_bal = cursor.fetchone()[0]
                break
        else:
            print(f"Balance update failed for user {user_id} after {max_retries} attempts")
            return None, None, None

    if unlocked_name and channel:
        embed = discord.Embed(title="꒰ა Rich Person Detected  ⸝⸝", color=0xffffff)
        embed.description = f"<@{user_id}>, your earnings pushed your balance to **A$ {final_bal:,}**.\nYou have unlocked and automatically equipped the **{unlocked_name}** card!"
        await channel.send(embed=embed)
    
    return final_bal, new_card, unlocked_name

# ==========================================
# 🏛️ UI COMPONENTS
# ==========================================
class StakingGuideView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="How does Staking work?", style=discord.ButtonStyle.secondary)
    async def guide_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(title="<:athenacoin:1503804322280902767> Athena Staking Guide <:athenacoin:1503804322280902767>", color=0xffffff)
        embed.description = (
            "**Staking** is a risk-free way to grow your wealth over time.\n\n"
            "**1. Lock Your Funds**\nYou deposit a set amount of A$ into the Central Reserve for a fixed period (3, 7, or 14 days). During this time, you cannot withdraw or wager this money.\n\n"
            "**2. Guaranteed Yield**\nBecause you provided liquidity to the Reserve, you are paid a guaranteed high-interest yield when the lock period ends.\n"
            "• **3 Days:** +15% Yield\n"
            "• **7 Days:** +25% Yield\n"
            "• **14 Days:** +60% Yield\n\n"
            "**3. Claiming**\nOnce the time is up, use `/stake claim` to receive your original deposit PLUS the interest directly into your wallet!"
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

class SimplePaginationView(discord.ui.View):
    def __init__(self, items, title, items_per_page=5):
        super().__init__(timeout=180)
        self.title = title
        self.items_per_page = items_per_page
        self.current_page = 0
        
        # Pre-slice all pages ONCE (no repeated slicing)
        self.pages = [
            items[i:i + items_per_page] 
            for i in range(0, len(items), items_per_page)
        ] if items else [[]]
        
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

    @discord.ui.button(label="", emoji="<:w_arrowleft:1272235695137751162>", style=discord.ButtonStyle.secondary)
    async def prev_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page -= 1
        self.update_buttons()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    @discord.ui.button(label="", emoji="<:w_arrowright:1272235711721898005>", style=discord.ButtonStyle.secondary)
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

        embed = discord.Embed(title="꒰ა Early Savings Withdrawal  ⸝⸝", color=0xffffff)
        embed.description = f"You broke your lock period early tch tch.\n\n**Initial Deposit:** A$ {self.amount:,}\n**Penalty Fee (15%):** -A$ {penalty_fee:,}\n**Total Returned:** A$ {payout:,}"
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("❌ This is not your stake.", ephemeral=True)
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(content="Canceled. Your stake remains safely locked in the Reserve.", embed=None, view=self)

# ==========================================
# 🏙️ THE ECONOMY COG
# ==========================================
class Economy(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db_path = DB_PATH
        self.setup_db()
        self.loan_debt_collector.start()
        self.debt_penalty_loop.start()

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
            cursor.execute("INSERT OR IGNORE INTO config (id, mimu_rate) VALUES (1, 100)")

    def get_wallet_data(self, user_id: int):
        with get_db_cursor() as cursor:
            cursor.execute("SELECT balance, active_card FROM wallets WHERE user_id = ?", (user_id,))
            result = cursor.fetchone()
            if result:
                bal = result[0] or 0
                card = (result[1] or "silver").strip()  # ✅ FIX: strip whitespace
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
            if balance >= 600000: valid_card = "plat_black"
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
                        await user.send(f"🏦 **LOAN COLLECTION:** The Central Reserve has forcibly deducted your overdue loan of **A$ {repayment:,}** (including 10% interest) from your account.")
                except:
                    pass

    @tasks.loop(hours=48)
    async def debt_penalty_loop(self):
        """Compounds negative balances by 1.5% every 48 hours"""
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

    @app_commands.command(name="bal", description="Check your Athena Reserve wallet balance")
    async def balance(self, interaction: discord.Interaction):
        await interaction.response.defer()
        bal, active_card = self.get_wallet_data(interaction.user.id)
        image_buffer = await self.generate_wallet_card(interaction.user, bal, active_card)
        await interaction.followup.send(file=discord.File(fp=image_buffer, filename="wallet.png"))

    @commands.command(name="bal", aliases=["balance", "b"])
    async def prefix_bal(self, ctx: commands.Context):
        async with ctx.typing():
            bal, active_card = self.get_wallet_data(ctx.author.id)
            image_buffer = await self.generate_wallet_card(ctx.author, bal, active_card)
            await ctx.send(file=discord.File(fp=image_buffer, filename="wallet.png"))

    @app_commands.command(name="rob", description="Attempt to rob another user. High risk, high reward.")
    async def rob(self, interaction: discord.Interaction, target: discord.Member):
        if target.id == interaction.user.id:
            return await interaction.response.send_message("❌ You cannot rob yourself.", ephemeral=True)
        if target.bot:
            return await interaction.response.send_message("❌ You cannot rob a bot.", ephemeral=True)
            
        with get_db_cursor() as cursor:
            # 1. Create a persistent cooldown table automatically if it doesn't exist
            cursor.execute('''CREATE TABLE IF NOT EXISTS command_cooldowns (
                user_id INTEGER, command_name TEXT, last_used REAL,
                PRIMARY KEY (user_id, command_name)
            )''')
            
            # 2. Check Database Cooldown (1 hour = 3600 seconds)
            now = time.time()
            cooldown_duration = 3600
            cursor.execute("SELECT last_used FROM command_cooldowns WHERE user_id = ? AND command_name = 'rob'", (interaction.user.id,))
            row = cursor.fetchone()
            
            if row:
                last_used = row[0]
                if now - last_used < cooldown_duration:
                    rem = int(cooldown_duration - (now - last_used))
                    minutes, seconds = divmod(rem, 60)
                    return await interaction.response.send_message(
                        f"<a:wt_toronerd:1480580983593111602> Lay low! The cops are still looking for you. Try again in **{minutes}m {seconds}s**.", 
                        ephemeral=True
                    )
            
            # 3. Check robber's balance (Needs seed money)
            cursor.execute("SELECT balance FROM wallets WHERE user_id = ?", (interaction.user.id,))
            robber_bal = cursor.fetchone()
            robber_bal = robber_bal[0] if robber_bal else 0
            
            if robber_bal < 500:
                return await i.response.send_message("❌ You need at least **A$ 500** to fund a robbery attempt (bribes, getaway car, etc.).", ephemeral=True)

            # 4. Check target's balance
            cursor.execute("SELECT balance FROM wallets WHERE user_id = ?", (target.id,))
            target_bal = cursor.fetchone()
            target_bal = target_bal[0] if target_bal else 0
            
            if target_bal < 1000:
                return await interaction.response.send_message(f"❌ **{target.name}** is broke. They don't have enough money to be worth robbing.", ephemeral=True)

            # 5. Lock in the new cooldown timestamp right now before calculations run
            cursor.execute("INSERT OR REPLACE INTO command_cooldowns (user_id, command_name, last_used) VALUES (?, 'rob', ?)", (interaction.user.id, now))

            # 6. Robbery mechanics (40% success rate)
            success_chance = random.random()
            
            if success_chance > 0.60: 
                # SUCCESS
                stolen_amount = int(target_bal * random.uniform(0.05, 0.15)) # Steal 5% to 15%
                
                # Execute transfer
                atomic_balance_update(cursor, target.id, -stolen_amount)
                atomic_balance_update(cursor, interaction.user.id, stolen_amount)
                
                log_transaction(cursor, interaction.user.id, stolen_amount, "ROB_SUCCESS", f"Robbed {target.name}")
                log_transaction(cursor, target.id, -stolen_amount, "ROBBED", f"Robbed by {interaction.user.name}")
                
                embed = discord.Embed(title="꒰ა The Heist was a Success! ⸝⸝", color=0xffffff)
                embed.description = f"You slipped past security and successfully robbed **{target.mention}**!\n\n **Stolen:** <:athenacoin:1503804322280902767> A$ {stolen_amount:,} <:athenacoin:1503804322280902767>"
                await interaction.response.send_message(embed=embed)
            else:
                # FAIL
                fine = max(500, int(robber_bal * 0.10))
                
                atomic_balance_update(cursor, interaction.user.id, -fine)
                log_transaction(cursor, interaction.user.id, -fine, "ROB_FAIL", f"Caught trying to rob {target.name}")
                
                embed = discord.Embed(title="꒰ა Busted! ⸝⸝", color=0xffffff)
                embed.description = f"You were caught trying to rob **{target.mention}**!\n\nThe Athena Central Reserve fined you <:athenacoin:1503804322280902767> **A$ {fine:,}** <:athenacoin:1503804322280902767>."
                await interaction.response.send_message(embed=embed)

    # Custom Error Handler to show the cooldown countdown
    @rob.error
    async def rob_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.CommandOnCooldown):
            minutes, seconds = divmod(error.retry_after, 60)
            await interaction.response.send_message(f"<a:wt_toronerd:1480580983593111602> Lay low! The cops are still looking for you. Try again in **{int(minutes)}m {int(seconds)}s**.", ephemeral=True)
    
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

            # Determine if money was added or removed
            type_upper = t_type.upper() if t_type else ""
            is_credit = type_upper in ("CREDIT", "DAILY", "WORK", "HEIST_WIN", "STAKING_CLAIM",
                                       "DIVIDEND", "TRANSFER_IN", "CASINO_WIN", "SELL_STOCK",
                                       "RENT_INCOME", "LOAN_DISBURSED")

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

        embed = discord.Embed(title="꒰ა New Card Equipped  ⸝⸝", color=0xffffff)
        embed.description = f"You have equipped the **{CARD_TIERS[card_type.value]['name']}**.\nRun `/bal` to view it. Each card gives different perks!"
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="give", description="Transfer Athena Coins to another user")
    async def give(self, interaction: discord.Interaction, user: discord.Member, amount: int):
        if amount <= 0: return await interaction.response.send_message("❌ Invalid amount.", ephemeral=True)
        if user.id == interaction.user.id: return await interaction.response.send_message("❌ Cannot transfer to yourself.", ephemeral=True)

        with get_db_cursor() as cursor:
            cursor.execute("SELECT balance FROM wallets WHERE user_id = ?", (interaction.user.id,))
            bal = cursor.fetchone()
            if not bal or bal[0] < amount:
                return await interaction.response.send_message("❌ Insufficient funds, broke ahh", ephemeral=True)

            cursor.execute("SELECT amount FROM loans WHERE user_id = ?", (interaction.user.id,))
            active_loan = cursor.fetchone()
            if active_loan:
                required_repayment = int(active_loan[0] * 1.10)
                if (bal[0] - amount) < required_repayment:
                    return await interaction.response.send_message(f"❌ Transfer Denied: You have an active loan. You must maintain a balance of at least **A$ {required_repayment:,}** to cover your pending repayment.", ephemeral=True)

            atomic_balance_update(cursor, interaction.user.id, -amount)
            atomic_balance_update(cursor, user.id, amount)
            log_transaction(cursor, interaction.user.id, -amount, "TRANSFER_OUT", f"Sent to {user.name}")
            log_transaction(cursor, user.id, amount, "TRANSFER_IN", f"Received from {interaction.user.name}")

        embed = discord.Embed(title="꒰ა Wire Transfer  ⸝⸝", color=0xffffff)
        embed.description = f"Successfully transferred **A$ {amount:,} <:athenacoin:1503804322280902767>** to {user.mention} as a tax writeoff."
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="loan", description="Take a loan from the Central Reserve (Max 7 days)")
    @app_commands.describe(amount="Amount to borrow (Max A$ 100,000)", days="Days until repayment (1-7)")
    async def take_loan(self, interaction: discord.Interaction, amount: int, days: int):
        if not (100 <= amount <= 100000): return await interaction.response.send_message("Borrow limit: <:athenacoin:1503804322280902767> A$ 100 to <:athenacoin:1503804322280902767> A$ 100,000.", ephemeral=True)
        if not (1 <= days <= 7): return await interaction.response.send_message(" Term limit: 1 to 7 days.", ephemeral=True)

        with get_db_cursor() as cursor:
            cursor.execute("SELECT amount, due_date FROM loans WHERE user_id = ?", (interaction.user.id,))
            active_loan = cursor.fetchone()
            if active_loan:
                due_timestamp = active_loan[1]
                time_left = due_timestamp - datetime.datetime.now().timestamp()
                time_str = f"{int(time_left // 86400)} days and {int((time_left % 86400) // 3600)} hours" if time_left > 0 else "Overdue (Repayment pending)"
                return await interaction.response.send_message(f"You already have an active loan! Your repayment of **A$ {int(active_loan[0]*1.10):,} <:athenacoin:1503804322280902767>** is due in: **{time_str}**.", ephemeral=False)

            due_date = (datetime.datetime.now() + datetime.timedelta(days=days)).timestamp()
            cursor.execute("INSERT INTO loans (user_id, amount, due_date) VALUES (?, ?, ?)", (interaction.user.id, amount, due_date))
            atomic_balance_update(cursor, interaction.user.id, amount)
            log_transaction(cursor, interaction.user.id, amount, "LOAN_DISBURSED", f"{days}-day loan @ 10% interest")

        embed = discord.Embed(title="꒰ა Loan Granted  ⸝⸝", color=0xffffff)
        embed.description = f"After noticing high levels of broke in your account, the Athena Central Reserve has credited **A$ {amount:,} <:athenacoin:1503804322280902767>** into your account. Thank you for enlisting for this pyramid scheme.\n\n **Due In:** {days} days\n **Repayment:** A$ {int(amount*1.10):,} (10% Interest)\n*Note: This will be auto-deducted, even if it puts your account in the negative :3*"
        await interaction.response.send_message(embed=embed)

    # ==========================================
    # 🏦 STAKING COMMANDS
    # ==========================================
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
                return await interaction.response.send_message("❌ You already have an active stake! Use `/stake info` to check it.", ephemeral=True)

            cursor.execute("SELECT balance FROM wallets WHERE user_id = ?", (interaction.user.id,))
            bal = cursor.fetchone()
            if not bal or bal[0] < amount:
                return await interaction.response.send_message("❌ Insufficient funds to stake.", ephemeral=True)

            yield_rates = {3: 0.15, 7: 0.35, 14: 0.60}
            rate = yield_rates[duration.value]
            unlock = (datetime.datetime.now() + datetime.timedelta(days=duration.value)).timestamp()

            atomic_balance_update(cursor, interaction.user.id, -amount)
            cursor.execute("INSERT INTO stakes (user_id, amount, unlock_time, yield_rate) VALUES (?, ?, ?, ?)", (interaction.user.id, amount, unlock, rate))
            log_transaction(cursor, interaction.user.id, -amount, "STAKE_DEPOSIT", f"Locked for {duration.value} days @ {int(rate*100)}%")

        embed = discord.Embed(title="꒰ა Savings Amount Deposited  ⸝⸝", color=0xffffff)
        embed.description = f"You have successfully locked **A$ {amount:,} <:athenacoin:1503804322280902767>** for **{duration.value} days**.\n\nExpected Return: **A$ {int(amount + (amount*rate)):,}**"
        await interaction.response.send_message(embed=embed, view=StakingGuideView())

    @stake_group.command(name="info", description="Check your current active stake")
    async def stake_info(self, interaction: discord.Interaction):
        with get_db_cursor() as cursor:
            cursor.execute("SELECT amount, unlock_time, yield_rate FROM stakes WHERE user_id = ?", (interaction.user.id,))
            row = cursor.fetchone()

        if not row:
            return await interaction.response.send_message(" You have no active stakes. Use `/stake deposit` to start earning!", view=StakingGuideView(), ephemeral=True)

        amount, unlock, rate = row
        payout = int(amount + (amount * rate))
        now = datetime.datetime.now().timestamp()

        embed = discord.Embed(title="꒰ა Savings Fund  ⸝⸝", color=0xffffff)
        if now >= unlock:
            embed.description = f"**Status:** <a:wt_toroexclaim:1480581004317036624> Ready to Claim! Wahoo\n**Deposit:** A$ {amount:,} <:athenacoin:1503804322280902767>\n**Payout:** A$ {payout:,} <:athenacoin:1503804322280902767>\n\n*Run `/stake claim` to withdraw your funds.*"
        else:
            time_left = unlock - now
            days, rem = divmod(time_left, 86400)
            hours, rem = divmod(rem, 3600)
            embed.description = f"**Status:** <a:wt_torospin:1480580977867624540> Still Locked! Oopsie Poopsie\n**Deposit:** A$ {amount:,} <:athenacoin:1503804322280902767>\n**Future Payout:** A$ {payout:,} <:athenacoin:1503804322280902767>\n**Time Remaining:** {int(days)}d {int(hours)}h"

        await interaction.response.send_message(embed=embed, view=StakingGuideView())

    @stake_group.command(name="claim", description="Claim a completed stake and collect your yield")
    async def stake_claim(self, interaction: discord.Interaction):
        with get_db_cursor() as cursor:
            cursor.execute("SELECT amount, unlock_time, yield_rate FROM stakes WHERE user_id = ?", (interaction.user.id,))
            row = cursor.fetchone()

            if not row:
                return await interaction.response.send_message("❌ You have no active stakes to claim.", ephemeral=True)

            amount, unlock, rate = row

            if datetime.datetime.now().timestamp() < unlock:
                time_left = unlock - datetime.datetime.now().timestamp()
                days_left = int(time_left // 86400)
                hours_left = int((time_left % 86400) // 3600)

                embed = discord.Embed(title="꒰ა Proceed w/ Caution!  ⸝⸝", color=0xffffff)
                embed.description = (
                    f"Your stake is still locked for another **{days_left} days, {hours_left} hours**.\n\n"
                    "If you withdraw your stake early, you will forfeit all generated interest AND pay a 15% penalty fee on your initial deposit.\n\n"
                    f"**Initial Deposit:** A$ {amount:,} <:athenacoin:1503804322280902767>\n"
                    f"**Penalty Return:** A$ {int(amount - (amount * 0.15)):,} <:athenacoin:1503804322280902767>\n\n"
                    "Do you want to break the lock and claim early?"
                )
                view = EarlyClaimView(self.db_path, interaction.user.id, amount)
                return await interaction.response.send_message(embed=embed, view=view, ephemeral=False)

            payout = int(amount + (amount * rate))
            cursor.execute("DELETE FROM stakes WHERE user_id = ?", (interaction.user.id,))
            atomic_balance_update(cursor, interaction.user.id, payout)
            log_transaction(cursor, interaction.user.id, payout, "STAKE_CLAIM", f"Matured stake payout")

        embed = discord.Embed(title="꒰ა Savings Fund Extracted  ⸝⸝", color=0xffffff)
        embed.description = f"Your lock period is over! The Athena Central Reserve has granted you A$ {payout:,} <:athenacoin:1503804322280902767>. Reinvest for further profit!"
        await interaction.response.send_message(embed=embed)

    # ==========================================
    # 🧮 UTILITY COMMANDS
    # ==========================================
    @app_commands.command(name="exchange_rate", description="View the current Mimu to Athena exchange rate")
    async def view_rate(self, interaction: discord.Interaction):
        rate = self.get_rate()
        embed = discord.Embed(title="Athena Reserve Exchange Rate", color=0xffffff)
        embed.description = f"**Current Rate:** <:athenacoin:1503804322280902767> `1 Athena Coin` = <:p_coin:1376159513518018611> `{rate} Mimu Coins`\n\n*Use `/convert` to calculate exactly how much your coins are worth!*"
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="convert", description="Calculator: Convert between Mimu and Athena coins")
    @app_commands.choices(direction=[
        app_commands.Choice(name="Mimu ➔ Athena (Deposit)", value="to_athena"),
        app_commands.Choice(name="Athena ➔ Mimu (Withdraw)", value="to_mimu")
    ])
    async def convert_currency(self, interaction: discord.Interaction, amount: int, direction: app_commands.Choice[str]):
        rate = self.get_rate()
        if direction.value == "to_athena":
            result = amount / rate
            desc = f"**{amount:,} Mimu Coins** ÷ {rate} = **A$ {result:,.2f}**\n\n*Note: Mimu must be deducted from your account by staff to receive Athena coins.*"
        else:
            result = amount * rate
            desc = f"**A$ {amount:,}** × {rate} = **{result:,.2f} Mimu Coins**\n\n*Note: Athena coins will be deducted upon withdrawal.*"

        embed = discord.Embed(title=" Currency Calculator", color=0xffffff, description=desc)
        await interaction.response.send_message(embed=embed)

    # ==========================================
    # 💼 INCOME & RISK COMMANDS
    # ==========================================
    @app_commands.command(name="daily", description="Claim your daily Athena Reserve allowance")
    async def daily(self, interaction: discord.Interaction):
        await interaction.response.defer()
        base_payout = 6000

        # ✅ FIX: Strip whitespace and use clean CARD_TIERS
        _, active_card = self.get_wallet_data(interaction.user.id)
        active_card = active_card.strip() if active_card else "silver"
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

            cursor.execute("INSERT OR IGNORE INTO wallets (user_id, balance, active_card, highest_balance, last_daily) VALUES (?, 0, 'silver', 0, 0)", (interaction.user.id,))
            cursor.execute("UPDATE wallets SET last_daily = ? WHERE user_id = ?", (now, interaction.user.id))
            log_transaction(cursor, interaction.user.id, payout, "DAILY", f"Daily allowance ({active_card} {mult}x)")

        await apply_balance_increase(interaction.user.id, payout, interaction.channel, tx_type="daily")

        card_name = CARD_TIERS.get(active_card, CARD_TIERS["silver"])["name"]
        embed = discord.Embed(title="꒰ა Daily Reward  ⸝⸝", color=0xffffff)
        embed.description = (
            f"<a:wt_torolove:1480580899430203484> **Daily Allowance Credited**\n\n"
            f"Congratulations, you've received your daily payment of {payout:,} inclusive of your bonus from {card_name} <a:wt_torocellphone:1503815758730366976> Spend it wisely!"
        )
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="heist", description="Attempt a corporate heist for massive payouts. High Risk.")
    @app_commands.checks.cooldown(1, 10800)
    async def heist(self, interaction: discord.Interaction):
        await interaction.response.defer()

        with get_db_cursor() as cursor:
            cursor.execute("INSERT OR IGNORE INTO wallets (user_id, balance, active_card, highest_balance) VALUES (?, 0, 'silver', 0)", (interaction.user.id,))
            success = random.random() < 0.40

            if success:
                winnings = 10000
                atomic_balance_update(cursor, interaction.user.id, winnings)
                log_transaction(cursor, interaction.user.id, winnings, "HEIST_WIN", "Successful corporate breach")
                embed = discord.Embed(title="꒰ა You did it!  ⸝⸝", color=0xffffff)
                embed.description = f"<a:wt_torofly:1480580890185826364> You successfully breached the Athena Central Reserve's database and stole **A$ {winnings:,} <:athenacoin:1503804322280902767>!**"
            else:
                fine = 3000
                atomic_balance_update(cursor, interaction.user.id, -fine)
                log_transaction(cursor, interaction.user.id, -fine, "HEIST_FINE", "Caught by Athena Security")
                embed = discord.Embed(title="꒰ა You were caught!  ⸝⸝", color=0xffffff)
                embed.description = f"<a:wt_torocryflail:1480580960566378711> Athena Central Reserve security caught you. You were fined **A$ {fine:,} <:athenacoin:1503804322280902767>**.\n*(This will put you in debt if you lack the funds!)*"

        await interaction.followup.send(embed=embed)

    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.CommandOnCooldown):
            hours, remainder = divmod(int(error.retry_after), 3600)
            minutes, seconds = divmod(remainder, 60)
            await interaction.response.send_message(f"⏳ **Cooldown Active:** You are exhausted! Try again in **{hours}h {minutes}m {seconds}s**.", ephemeral=True)
        else:
            print(error)

    # ==========================================
    # 🔒 ADMIN COMMANDS
    # ==========================================
    @app_commands.command(name="set_rate", description="ADMIN: Set the Mimu exchange rate")
    @app_commands.describe(new_rate="How many Mimu coins equal 1 Athena coin?")
    async def set_rate(self, interaction: discord.Interaction, new_rate: int):
        if interaction.user.id != 743411894416834590:
            return await interaction.response.send_message("❌ **Security Alert:** Access Denied.", ephemeral=True)
        if new_rate < 1:
            return await interaction.response.send_message("❌ Rate must be at least 1.", ephemeral=True)

        with get_db_cursor() as cursor:
            cursor.execute("UPDATE config SET mimu_rate = ? WHERE id = 1", (new_rate,))
        await interaction.response.send_message(f"✅ **Exchange Rate Updated!**\nNew Rate: 1 Athena = {new_rate} Mimu.")

    @app_commands.command(name="mint", description="ADMIN: Print Athena coins and add them to a user's wallet")
    async def mint_coins(self, interaction: discord.Interaction, user: discord.Member, amount: int):
        if interaction.user.id != 743411894416834590:
            return await interaction.response.send_message("❌ **Security Alert:** Access Denied. Only Phoenix has access to the Reserve Printing Press.", ephemeral=True)

        with get_db_cursor() as cursor:
            atomic_balance_update(cursor, user.id, amount)
            log_transaction(cursor, user.id, amount, "ADMIN_MINT", f"Minted by {interaction.user.name}")
            cursor.execute("SELECT balance FROM wallets WHERE user_id = ?", (user.id,))
            bal = cursor.fetchone()[0]

        embed = discord.Embed(title="꒰ა Bank Transfer  ⸝⸝", color=0xffffff)
        embed.description = f"The Athena Central Reserve has blessed {user.mention} with {amount:,}.\n New Balance: **A$ {bal:,} <:athenacoin:1503804322280902767>**"
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="deduct", description="ADMIN: Forcefully seize Athena coins from a user's wallet")
    async def deduct_coins(self, interaction: discord.Interaction, user: discord.Member, amount: int):
        if interaction.user.id != 743411894416834590:
            return await interaction.response.send_message("❌ **Security Alert:** Access Denied. Only Phoenix can seize assets.", ephemeral=True)

        with get_db_cursor() as cursor:
            cursor.execute("INSERT OR IGNORE INTO wallets (user_id, balance, active_card, highest_balance) VALUES (?, 0, 'silver', 0)", (user.id,))
            atomic_balance_update(cursor, user.id, -amount)
            log_transaction(cursor, user.id, -amount, "ADMIN_DEDUCT", f"Seized by {interaction.user.name}")
            cursor.execute("SELECT balance FROM wallets WHERE user_id = ?", (user.id,))
            bal = cursor.fetchone()[0]

        embed = discord.Embed(title="꒰ა Assets Seized  ⸝⸝", color=0xffffff)
        embed.description = f"The Athena Central Reserve has seized **A$ {amount:,} <:athenacoin:1503804322280902767>** from {user.mention} for alleged involvement in the Russian-Ukrainian war. \nNew Balance: **A$ {bal:,}**"
        await interaction.response.send_message(embed=embed)

async def setup(bot):
    await bot.add_cog(Economy(bot))