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
            repayment = int(amount * 1.10) # 10% Interest Rate
            cursor.execute("UPDATE wallets SET balance = balance - ? WHERE user_id = ?", (repayment, user_id))
            cursor.execute("DELETE FROM loans WHERE user_id = ?", (user_id,))
            try:
                user = self.bot.get_user(user_id)
                if user: await user.send(f"🏦 **LOAN COLLECTION:** The Central Reserve has forcibly deducted your overdue loan of **A$ {repayment:,}** (including 10% interest) from your account. If you lacked the funds, your account is now in the negative.")
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
        await interaction.response.send_message(f"💳 **Card Equipped:** {CARD_TIERS[card_type.value]['name']}. Run `/bal`!")

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
        await interaction.response.send_message(f"💸 **Wire Transfer Complete!**\nYou sent **A$ {amount:,}** to {user.mention}.")

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
        embed.description = f"The Reserve credited **A$ {amount:,}** to your account.\n\n📅 **Due In:** {days} days\n💸 **Repayment:** A$ {int(amount*1.10):,} (10% Interest)\n*Note: This will be auto-deducted, even if it puts your account in the negative!*"
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
            
        embed = discord.Embed(title="💱 Currency Calculator", color=0xffffff, description=desc)
        await interaction.response.send_message(embed=embed)

    # ==========================================
    # 💼 INCOME COMMANDS (WITH COOLDOWNS)
    # ==========================================
    # ==========================================
    # 💼 INCOME COMMANDS (WITH COOLDOWNS)
    # ==========================================
    @app_commands.command(name="daily", description="Claim your daily Athena Reserve allowance")
    @app_commands.checks.cooldown(1, 86400) # 24 Hours
    async def daily(self, interaction: discord.Interaction):
        await interaction.response.defer() #homosexual men
        
        payout = 5000
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("INSERT INTO wallets (user_id, balance, active_card, highest_balance) VALUES (?, ?, 'silver', ?) ON CONFLICT(user_id) DO UPDATE SET balance = balance + ?, highest_balance = MAX(highest_balance, balance + ?)", (interaction.user.id, payout, payout, payout, payout))
        conn.commit()
        conn.close()
        await interaction.followup.send(embed=discord.Embed(title="🎁 Daily Allowance", color=0xffffff, description=f"You claimed your daily **A$ {payout:,}**!"))

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
        await interaction.followup.send(embed=discord.Embed(title="💼 Shift Completed", color=0xffffff, description=f"You {random.choice(jobs)} and earned **A$ {payout:,}**!"))

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
        await interaction.response.send_message(f"🏦 **Bank Transfer Successful**\nAdded {amount:,} coins to {user.mention}.\nNew Balance: **A$ {bal:,}**")

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
        
        await interaction.response.send_message(f"🚨 **Assets Seized**\nSuccessfully deducted **A$ {amount:,}** from {user.mention}.\nNew Balance: **A$ {bal:,}**")

async def setup(bot):
    await bot.add_cog(Economy(bot))