import discord
from discord import app_commands
from discord.ext import commands, tasks
import sqlite3
import os
import io
import random
import datetime
from PIL import Image, ImageDraw, ImageFont

CARD_TIERS = {
    "silver": {"threshold": 0, "file": "card_silver.png", "color": (255, 255, 255), "name": "Standard Silver"},
    "gold": {"threshold": 100000, "file": "card_gold.png", "color": (255, 255, 255), "name": "Gold Elite"},
    "plat_black": {"threshold": 600000, "file": "card_plat_black.png", "color": (255, 255, 255), "name": "Platinum Black"},
    "plat_pink": {"threshold": 600000, "file": "card_plat_pink.png", "color": (219, 120, 200), "name": "Platinum Chérie"}
}

# ==========================================
# 📖 THE STAKING GUIDE UI
# ==========================================
class StakingGuideView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="How does Staking work?", style=discord.ButtonStyle.secondary, emoji="<a:wt_toronerd:1480580983593111602>")
    async def guide_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(title="🏦 Athena Staking Guide", color=0xffffff)
        embed.description = (
            "**Staking** is a risk free way to grow your wealth over time.\n\n"
            "**1. Lock Your Funds**\n"
            "You deposit a set amount of A$ into the Central Reserve for a fixed period (3, 7, or 14 days). During this time, you cannot withdraw or wager this money.\n\n"
            "**2. Guaranteed Yield**\n"
            "Because you provided liquidity to the Reserve, you are paid a guaranteed high-interest yield when the lock period ends.\n"
            "• **3 Days:** +15% Yield\n"
            "• **7 Days:** +25% Yield\n"
            "• **14 Days:** +60% Yield\n\n"
            "**3. Claiming**\n"
            "Once the time is up, use `/stake claim` to receive your original deposit PLUS the interest directly into your wallet!"
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


class Economy(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db_path = "economy.db"
        self.setup_db()
        self.loan_debt_collector.start() 
        
    def setup_db(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Wallets Table
        cursor.execute('''CREATE TABLE IF NOT EXISTS wallets (
            user_id INTEGER PRIMARY KEY, balance INTEGER DEFAULT 0
        )''')
        try: cursor.execute("ALTER TABLE wallets ADD COLUMN active_card TEXT DEFAULT 'silver'")
        except: pass
        try: cursor.execute("ALTER TABLE wallets ADD COLUMN highest_balance INTEGER DEFAULT 0")
        except: pass
        
        # Loans Table
        cursor.execute('''CREATE TABLE IF NOT EXISTS loans (
            user_id INTEGER PRIMARY KEY, amount INTEGER, due_date REAL
        )''')
        
        # Stakes Table (NEW)
        cursor.execute('''CREATE TABLE IF NOT EXISTS stakes (
            user_id INTEGER PRIMARY KEY, amount INTEGER, unlock_time REAL, yield_rate REAL
        )''')
        
        # Exchange Rate Table
        cursor.execute('''CREATE TABLE IF NOT EXISTS config (
            id INTEGER PRIMARY KEY, mimu_rate INTEGER DEFAULT 100
        )''')
        cursor.execute("INSERT OR IGNORE INTO config (id, mimu_rate) VALUES (1, 100)")
        
        conn.commit()
        conn.close()

    def get_wallet_data(self, user_id: int):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT balance, active_card FROM wallets WHERE user_id = ?", (user_id,))
        result = cursor.fetchone()
        conn.close()
        if result: return result[0], (result[1] if result[1] else "silver")
        return 0, "silver"

    def get_rate(self) -> int:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT mimu_rate FROM config WHERE id = 1")
        result = cursor.fetchone()
        conn.close()
        return result[0] if result else 100

    async def generate_wallet_card(self, member: discord.Member, balance: int, requested_card: str) -> io.BytesIO:
        valid_card = requested_card
        if balance < CARD_TIERS[valid_card]["threshold"]:
            if balance >= 600000: valid_card = "plat_black" 
            elif balance >= 100000: valid_card = "gold"
            else: valid_card = "silver"

        card_info = CARD_TIERS[valid_card]
        img = Image.open(card_info["file"]).convert("RGBA")
        draw = ImageDraw.Draw(img)

        font_path = "card_font.ttf" if os.path.exists("card_font.ttf") else "cogs/card_font.ttf"
        try: font_main = ImageFont.truetype(font_path, 100)
        except IOError: font_main = ImageFont.load_default()

        draw.text((200, 930), member.name.upper()[:20], fill=card_info["color"], font=font_main)
        draw.text((1300, 930), f"A$ {balance:,}", fill=card_info["color"], font=font_main)

        buffer = io.BytesIO()
        img.save(buffer, format="PNG")
        buffer.seek(0)
        return buffer

    # ==========================================
    # 🏦 THE DEBT COLLECTOR (AUTO-LOAN TASK)
    # ==========================================
    @tasks.loop(minutes=30)
    async def loan_debt_collector(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        now = datetime.datetime.now().timestamp()
        
        cursor.execute("SELECT user_id, amount FROM loans WHERE due_date <= ?", (now,))
        overdue_loans = cursor.fetchall()

        for user_id, amount in overdue_loans:
            repayment = int(amount * 1.15) # 15% Interest Rate
            cursor.execute("UPDATE wallets SET balance = balance - ? WHERE user_id = ?", (repayment, user_id))
            cursor.execute("DELETE FROM loans WHERE user_id = ?", (user_id,))
            try:
                user = self.bot.get_user(user_id)
                if user: await user.send(f"🏦 **LOAN COLLECTION:** The Central Reserve has forcibly deducted your overdue loan of **A$ {repayment:,}** (including 15% interest) from your account. If you lacked the funds, your account is now in the negative.")
            except: pass
            
        conn.commit()
        conn.close()

    @loan_debt_collector.before_loop
    async def before_collector(self):
        await self.bot.wait_until_ready()


    # ==========================================
    # 💸 ECONOMY COMMANDS
    # ==========================================
    @app_commands.command(name="bal", description="Check your Athena Reserve wallet balance")
    async def balance(self, interaction: discord.Interaction):
        await interaction.response.defer() 
        bal, active_card = self.get_wallet_data(interaction.user.id)
        image_buffer = await self.generate_wallet_card(interaction.user, bal, active_card)
        await interaction.followup.send(file=discord.File(fp=image_buffer, filename="wallet.png"))

    @app_commands.command(name="setcard", description="Equip an unlocked debit card tier")
    @app_commands.choices(card_type=[
        app_commands.Choice(name="Standard Silver (0+ A$)", value="silver"),
        app_commands.Choice(name="Gold Elite (100k+ A$)", value="gold"),
        app_commands.Choice(name="Platinum Black (600k+ A$)", value="plat_black"),
        app_commands.Choice(name="Platinum Chérie (600k+ A$)", value="plat_pink"),
    ])
    async def setcard(self, interaction: discord.Interaction, card_type: app_commands.Choice[str]):
        bal, _ = self.get_wallet_data(interaction.user.id)
        if bal < CARD_TIERS[card_type.value]["threshold"]:
            return await interaction.response.send_message(f"❌ **Access Denied.** You need **A$ {CARD_TIERS[card_type.value]['threshold']:,}** to use this card.", ephemeral=True)
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("UPDATE wallets SET active_card = ? WHERE user_id = ?", (card_type.value, interaction.user.id))
        conn.commit()
        conn.close()
        
        embed = discord.Embed(title="💳 Card Updated", color=0xffffff)
        embed.description = f"You have equipped the **{CARD_TIERS[card_type.value]['name']}**.\nRun `/bal` to view it."
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="give", description="Transfer Athena Coins to another user")
    async def give(self, interaction: discord.Interaction, user: discord.Member, amount: int):
        if amount <= 0: return await interaction.response.send_message("❌ Invalid amount.", ephemeral=True)
        if user.id == interaction.user.id: return await interaction.response.send_message("❌ Cannot transfer to yourself.", ephemeral=True)

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT balance FROM wallets WHERE user_id = ?", (interaction.user.id,))
        bal = cursor.fetchone()
        if not bal or bal[0] < amount:
            conn.close()
            return await interaction.response.send_message("❌ Insufficient funds.", ephemeral=True)

        cursor.execute("UPDATE wallets SET balance = balance - ? WHERE user_id = ?", (amount, interaction.user.id))
        cursor.execute("INSERT INTO wallets (user_id, balance, active_card, highest_balance) VALUES (?, ?, 'silver', ?) ON CONFLICT(user_id) DO UPDATE SET balance = balance + ?, highest_balance = MAX(highest_balance, balance + ?)", (user.id, amount, amount, amount, amount))
        conn.commit()
        conn.close()
        
        embed = discord.Embed(title="💸 Wire Transfer", color=0xffffff)
        embed.description = f"Successfully transferred **A$ {amount:,}** to {user.mention}."
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="loan", description="Take a loan from the Central Reserve (Max 7 days)")
    @app_commands.describe(amount="Amount to borrow (Max A$ 100,000)", days="Days until repayment (1-7)")
    async def take_loan(self, interaction: discord.Interaction, amount: int, days: int):
        if not (100 <= amount <= 100000): return await interaction.response.send_message("❌ Borrow limit: A$ 100 to A$ 100,000.", ephemeral=True)
        if not (1 <= days <= 7): return await interaction.response.send_message("❌ Term limit: 1 to 7 days.", ephemeral=True)

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT amount FROM loans WHERE user_id = ?", (interaction.user.id,))
        if cursor.fetchone():
            conn.close()
            return await interaction.response.send_message("❌ You already have an active loan!", ephemeral=True)

        due_date = (datetime.datetime.now() + datetime.timedelta(days=days)).timestamp()
        cursor.execute("INSERT INTO loans (user_id, amount, due_date) VALUES (?, ?, ?)", (interaction.user.id, amount, due_date))
        cursor.execute("INSERT INTO wallets (user_id, balance, active_card, highest_balance) VALUES (?, ?, 'silver', ?) ON CONFLICT(user_id) DO UPDATE SET balance = balance + ?, highest_balance = MAX(highest_balance, balance + ?)", (interaction.user.id, amount, amount, amount, amount))
        conn.commit()
        conn.close()
        
        embed = discord.Embed(title="🏦 Loan Approved", color=0xffffff)
        embed.description = f"The Reserve credited **A$ {amount:,}** to your account.\n\n📅 **Due In:** {days} days\n💸 **Repayment:** A$ {int(amount*1.10):,} (15% Interest)\n*Note: This will be auto-deducted, even if it puts your account in the negative!*"
        await interaction.response.send_message(embed=embed)


    # ==========================================
    # 🏦 STAKING COMMANDS (NEW)
    # ==========================================
    stake_group = app_commands.Group(name="stake", description="Stake Athena Coins for guaranteed returns")

    @stake_group.command(name="deposit", description="Lock A$ in the Reserve for guaranteed interest")
    @app_commands.choices(duration=[
        app_commands.Choice(name="3 Days (+15% Yield)", value=3),
        app_commands.Choice(name="7 Days (+25% Yield)", value=7),
        app_commands.Choice(name="14 Days (+60% Yield)", value=14)
    ])
    async def stake_deposit(self, interaction: discord.Interaction, amount: int, duration: app_commands.Choice[int]):
        if amount < 100: return await interaction.response.send_message("❌ Minimum stake is A$ 100.", ephemeral=True)

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("SELECT amount FROM stakes WHERE user_id = ?", (interaction.user.id,))
        if cursor.fetchone():
            conn.close()
            return await interaction.response.send_message("❌ You already have an active stake! Use `/stake info` to check it.", ephemeral=True)

        cursor.execute("SELECT balance FROM wallets WHERE user_id = ?", (interaction.user.id,))
        bal = cursor.fetchone()
        if not bal or bal[0] < amount:
            conn.close()
            return await interaction.response.send_message("❌ Insufficient funds to stake.", ephemeral=True)

        yield_rates = {3: 0.15, 7: 0.25, 14: 0.60}
        rate = yield_rates[duration.value]
        unlock = (datetime.datetime.now() + datetime.timedelta(days=duration.value)).timestamp()

        cursor.execute("UPDATE wallets SET balance = balance - ? WHERE user_id = ?", (amount, interaction.user.id))
        cursor.execute("INSERT INTO stakes (user_id, amount, unlock_time, yield_rate) VALUES (?, ?, ?, ?)", (interaction.user.id, amount, unlock, rate))
        conn.commit()
        conn.close()

        embed = discord.Embed(title="Stake Deposited", color=0xffffff)
        embed.description = f"Successfully locked **A$ {amount:,}** for **{duration.value} days**.\n\nExpected Return: **A$ {int(amount + (amount*rate)):,}**"
        await interaction.response.send_message(embed=embed, view=StakingGuideView())

    @stake_group.command(name="info", description="Check your current active stake")
    async def stake_info(self, interaction: discord.Interaction):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT amount, unlock_time, yield_rate FROM stakes WHERE user_id = ?", (interaction.user.id,))
        row = cursor.fetchone()
        conn.close()

        if not row:
            return await interaction.response.send_message("💼 You have no active stakes. Use `/stake deposit` to start earning!", view=StakingGuideView(), ephemeral=True)

        amount, unlock, rate = row
        payout = int(amount + (amount * rate))
        now = datetime.datetime.now().timestamp()

        embed = discord.Embed(title="Active Stake", color=0xffffff)
        if now >= unlock:
            embed.description = f"**Status:** 🟢 Ready to Claim!\n**Deposit:** A$ {amount:,}\n**Payout:** A$ {payout:,}\n\n*Run `/stake claim` to withdraw your funds.*"
        else:
            time_left = unlock - now
            days, rem = divmod(time_left, 86400)
            hours, rem = divmod(rem, 3600)
            embed.description = f"**Status:** ⏳ Locked\n**Deposit:** A$ {amount:,}\n**Future Payout:** A$ {payout:,}\n**Time Remaining:** {int(days)}d {int(hours)}h"

        await interaction.response.send_message(embed=embed, view=StakingGuideView())

    @stake_group.command(name="claim", description="Claim a completed stake and collect your yield")
    async def stake_claim(self, interaction: discord.Interaction):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT amount, unlock_time, yield_rate FROM stakes WHERE user_id = ?", (interaction.user.id,))
        row = cursor.fetchone()

        if not row:
            conn.close()
            return await interaction.response.send_message("❌ You have no active stakes to claim.", ephemeral=True)

        amount, unlock, rate = row
        if datetime.datetime.now().timestamp() < unlock:
            conn.close()
            return await interaction.response.send_message("❌ Your stake is still locked! Use `/stake info` to check the remaining time.", ephemeral=True)

        payout = int(amount + (amount * rate))
        cursor.execute("DELETE FROM stakes WHERE user_id = ?", (interaction.user.id,))
        cursor.execute("UPDATE wallets SET balance = balance + ?, highest_balance = MAX(highest_balance, balance + ?) WHERE user_id = ?", (payout, payout, interaction.user.id))
        conn.commit()
        conn.close()

        embed = discord.Embed(title="🎉 Stake Claimed!", color=0xffd700) # Winning payout coloring
        embed.description = f"Your lock period is over.\n\n**Initial Deposit:** A$ {amount:,}\n**Interest Earned:** A$ {payout - amount:,}\n**Total Added:** A$ {payout:,}"
        await interaction.response.send_message(embed=embed)


    # ==========================================
    # 🧮 UTILITY COMMANDS
    # ==========================================
    @app_commands.command(name="exchange_rate", description="View the current Mimu to Athena exchange rate")
    async def view_rate(self, interaction: discord.Interaction):
        rate = self.get_rate()
        embed = discord.Embed(title="🏦 Athena Reserve Exchange Rate", color=0xffffff)
        embed.description = f"**Current Rate:** `1 Athena Coin` = `{rate} Mimu Coins`\n\n*Use `/convert` to calculate exactly how much your coins are worth!*"
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
            
        embed = discord.Embed(title="💱 Currency Calculator", color=0xffffff)
        await interaction.response.send_message(embed=embed)

    # ==========================================
    # 💼 INCOME & RISK COMMANDS (WITH COOLDOWNS)
    # ==========================================
    @app_commands.command(name="daily", description="Claim your daily Athena Reserve allowance")
    @app_commands.checks.cooldown(1, 86400) # 24 Hours
    async def daily(self, interaction: discord.Interaction):
        await interaction.response.defer() 
        payout = 5000
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("INSERT INTO wallets (user_id, balance, active_card, highest_balance) VALUES (?, ?, 'silver', ?) ON CONFLICT(user_id) DO UPDATE SET balance = balance + ?, highest_balance = MAX(highest_balance, balance + ?)", (interaction.user.id, payout, payout, payout, payout))
        conn.commit()
        conn.close()
        await interaction.followup.send(embed=discord.Embed(title="🎁 Daily Allowance", color=0xffd700, description=f"You claimed your daily **A$ {payout:,}**!"))

    @app_commands.command(name="work", description="Work a shift to earn some Athena Coins")
    @app_commands.checks.cooldown(1, 3600) # 1 Hour
    async def work(self, interaction: discord.Interaction):
        await interaction.response.defer() 
        payout = random.randint(300, 1500)
        jobs = ["hacked a mainframe", "delivered pizzas in the rain", "cleaned the Athena databases", "won a local coding tournament", "investigated a cyber breach"]
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("INSERT INTO wallets (user_id, balance, active_card, highest_balance) VALUES (?, ?, 'silver', ?) ON CONFLICT(user_id) DO UPDATE SET balance = balance + ?, highest_balance = MAX(highest_balance, balance + ?)", (interaction.user.id, payout, payout, payout, payout))
        conn.commit()
        conn.close()
        await interaction.followup.send(embed=discord.Embed(title="💼 Shift Completed", color=0x00ff00, description=f"You {random.choice(jobs)} and earned **A$ {payout:,}**!"))

    @app_commands.command(name="heist", description="Attempt a corporate heist for massive payouts. High Risk.")
    @app_commands.checks.cooldown(1, 10800) # 3 Hours
    async def heist(self, interaction: discord.Interaction):
        await interaction.response.defer()

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Ensure user exists in DB before deducting or adding
        cursor.execute("INSERT OR IGNORE INTO wallets (user_id, balance, active_card, highest_balance) VALUES (?, 0, 'silver', 0)", (interaction.user.id,))
        
        success = random.random() < 0.40 # 40% win chance
        
        if success:
            winnings = 10000
            cursor.execute("UPDATE wallets SET balance = balance + ?, highest_balance = MAX(highest_balance, balance + ?) WHERE user_id = ?", (winnings, winnings, interaction.user.id))
            embed = discord.Embed(title="Heist Successful!", color=0x00ff00)
            embed.description = f"You successfully breached a rival Megacorp's database and stole **A$ {winnings:,}**!"
        else:
            fine = 3000
            cursor.execute("UPDATE wallets SET balance = balance - ? WHERE user_id = ?", (fine, interaction.user.id))
            embed = discord.Embed(title="BUSTED!", color=0xff0000)
            embed.description = f"Athena Security caught you. You were fined **A$ {fine:,}**.\n*(This will put you in debt if you lack the funds!)*"
            
        conn.commit()
        conn.close()
        await interaction.followup.send(embed=embed)


    # Cooldown Error Handler
    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.CommandOnCooldown):
            hours, remainder = divmod(int(error.retry_after), 3600)
            minutes, seconds = divmod(remainder, 60)
            await interaction.response.send_message(f"⏳ **Cooldown Active:** You are exhausted! Try again in **{hours}h {minutes}m {seconds}s**.", ephemeral=True)
        else: print(error)


    # ==========================================
    # 🔒 ADMIN COMMANDS (STRICT PHOENIX ONLY LOCK)
    # ==========================================
    @app_commands.command(name="set_rate", description="ADMIN: Set the Mimu exchange rate")
    @app_commands.describe(new_rate="How many Mimu coins equal 1 Athena coin?")
    async def set_rate(self, interaction: discord.Interaction, new_rate: int):
        if interaction.user.id != 743411894416834590:
            return await interaction.response.send_message("❌ **Security Alert:** Access Denied.", ephemeral=True)

        if new_rate < 1:
            return await interaction.response.send_message("❌ Rate must be at least 1.", ephemeral=True)

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("UPDATE config SET mimu_rate = ? WHERE id = 1", (new_rate,))
        conn.commit()
        conn.close()
        await interaction.response.send_message(f"✅ **Exchange Rate Updated!**\nNew Rate: 1 Athena = {new_rate} Mimu.")

    @app_commands.command(name="mint", description="ADMIN: Print Athena coins and add them to a user's wallet")
    async def mint_coins(self, interaction: discord.Interaction, user: discord.Member, amount: int):
        if interaction.user.id != 743411894416834590:
            return await interaction.response.send_message("❌ **Security Alert:** Access Denied. Only Phoenix has access to the Reserve Printing Press.", ephemeral=True)
            
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("INSERT INTO wallets (user_id, balance, active_card, highest_balance) VALUES (?, ?, 'silver', ?) ON CONFLICT(user_id) DO UPDATE SET balance = balance + ?, highest_balance = MAX(highest_balance, balance + ?)", (user.id, amount, amount, amount, amount))
        cursor.execute("SELECT balance FROM wallets WHERE user_id = ?", (user.id,))
        bal = cursor.fetchone()[0]
        conn.commit()
        conn.close()
        
        embed = discord.Embed(title="🏦 Bank Transfer Successful", color=0xffffff)
        embed.description = f"Added {amount:,} coins to {user.mention}.\nNew Balance: **A$ {bal:,}**"
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="deduct", description="ADMIN: Forcefully seize Athena coins from a user's wallet")
    async def deduct_coins(self, interaction: discord.Interaction, user: discord.Member, amount: int):
        if interaction.user.id != 743411894416834590:
            return await interaction.response.send_message("❌ **Security Alert:** Access Denied. Only Phoenix can seize assets.", ephemeral=True)
            
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("INSERT OR IGNORE INTO wallets (user_id, balance, active_card, highest_balance) VALUES (?, 0, 'silver', 0)", (user.id,))
        cursor.execute("UPDATE wallets SET balance = balance - ? WHERE user_id = ?", (amount, user.id))
        
        cursor.execute("SELECT balance FROM wallets WHERE user_id = ?", (user.id,))
        bal = cursor.fetchone()[0]
        conn.commit()
        conn.close()
        
        embed = discord.Embed(title="🚨 Assets Seized", color=0xffffff)
        embed.description = f"Successfully deducted **A$ {amount:,}** from {user.mention}.\nNew Balance: **A$ {bal:,}**"
        await interaction.response.send_message(embed=embed)

async def setup(bot):
    await bot.add_cog(Economy(bot))