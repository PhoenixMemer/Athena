import discord
from discord import app_commands
from discord.ext import commands
import sqlite3
import os
import io
from PIL import Image, ImageDraw, ImageFont

# --- THE CARD TIER DICTIONARY ---
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
        
    def setup_db(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS wallets (
                user_id INTEGER PRIMARY KEY,
                balance INTEGER DEFAULT 0
            )
        ''')
        
        # Safely upgrade existing database
        try: cursor.execute("ALTER TABLE wallets ADD COLUMN active_card TEXT DEFAULT 'silver'")
        except sqlite3.OperationalError: pass
            
        try: cursor.execute("ALTER TABLE wallets ADD COLUMN highest_balance INTEGER DEFAULT 0")
        except sqlite3.OperationalError: pass
            
        # Exchange Rate Table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS config (
                id INTEGER PRIMARY KEY,
                mimu_rate INTEGER DEFAULT 100
            )
        ''')
        cursor.execute("INSERT OR IGNORE INTO config (id, mimu_rate) VALUES (1, 100)")
            
        conn.commit()
        conn.close()

    def get_wallet_data(self, user_id: int):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT balance, active_card FROM wallets WHERE user_id = ?", (user_id,))
        result = cursor.fetchone()
        conn.close()
        
        if result:
            card = result[1] if result[1] else "silver"
            return result[0], card
        return 0, "silver"

    def get_rate(self) -> int:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT mimu_rate FROM config WHERE id = 1")
        rate = cursor.fetchone()[0]
        conn.close()
        return rate

    def add_balance(self, user_id: int, amount: int):
        """Used by the mint command to add money and track all-time highs"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("INSERT INTO wallets (user_id, balance, active_card, highest_balance) VALUES (?, ?, 'silver', ?) ON CONFLICT(user_id) DO UPDATE SET balance = balance + ?", (user_id, amount, max(0, amount), amount))
        # Ensure highest_balance updates if the mint pushes them to a new all-time high
        cursor.execute("UPDATE wallets SET highest_balance = MAX(highest_balance, balance) WHERE user_id = ?", (user_id,))
        conn.commit()
        conn.close()

    async def generate_wallet_card(self, member: discord.Member, balance: int, requested_card: str) -> io.BytesIO:
        # --- STRICT AUTO-DOWNGRADE CHECK ---
        valid_card = requested_card
        if balance < CARD_TIERS[valid_card]["threshold"]:
            if balance >= 600000: valid_card = "plat_black" 
            elif balance >= 100000: valid_card = "gold"
            else: valid_card = "silver"

        card_info = CARD_TIERS[valid_card]
        
        img = Image.open(card_info["file"]).convert("RGBA")
        draw = ImageDraw.Draw(img)

        font_path = "card_font.ttf"
        if not os.path.exists(font_path): font_path = "cogs/card_font.ttf"

        try: font_main = ImageFont.truetype(font_path, 100)
        except IOError: font_main = ImageFont.load_default()

        # Dynamic Color specific to the Tier
        draw.text((200, 930), member.name.upper()[:20], fill=card_info["color"], font=font_main)
        draw.text((1300, 930), f"A$ {balance:,}", fill=card_info["color"], font=font_main)

        buffer = io.BytesIO()
        img.save(buffer, format="PNG")
        buffer.seek(0)
        return buffer

    # ==========================================
    # USER COMMANDS
    # ==========================================

    @app_commands.command(name="bal", description="Check your Athena Reserve wallet balance")
    async def balance(self, interaction: discord.Interaction):
        await interaction.response.defer() 
        bal, active_card = self.get_wallet_data(interaction.user.id)
        
        try:
            image_buffer = await self.generate_wallet_card(interaction.user, bal, active_card)
            file = discord.File(fp=image_buffer, filename="wallet.png")
            await interaction.followup.send(file=file)
        except Exception as e:
            await interaction.followup.send(f"⚠️ Error: Make sure your 4 card images are uploaded and named correctly! ({e})")

    @app_commands.command(name="setcard", description="Equip an unlocked debit card tier")
    @app_commands.choices(card_type=[
        app_commands.Choice(name="Standard Silver (0+ A$)", value="silver"),
        app_commands.Choice(name="Gold Elite (100k+ A$)", value="gold"),
        app_commands.Choice(name="Platinum Black (600k+ A$)", value="plat_black"),
        app_commands.Choice(name="Platinum Chérie (600k+ A$)", value="plat_pink"),
    ])
    async def setcard(self, interaction: discord.Interaction, card_type: app_commands.Choice[str]):
        bal, _ = self.get_wallet_data(interaction.user.id)
        selected = card_type.value
        threshold = CARD_TIERS[selected]["threshold"]

        if bal < threshold:
            await interaction.response.send_message(f"❌ **Access Denied.** You need a current balance of **A$ {threshold:,}** to use the {CARD_TIERS[selected]['name']}. (Your Balance: A$ {bal:,})", ephemeral=True)
            return

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("UPDATE wallets SET active_card = ? WHERE user_id = ?", (selected, interaction.user.id))
        conn.commit()
        conn.close()

        await interaction.response.send_message(f"💳 **Card Updated!** You have equipped the **{CARD_TIERS[selected]['name']}**.\nRun `/bal` to see it!")

    @app_commands.command(name="exchange_rate", description="View the current Mimu to Athena exchange rate")
    async def view_rate(self, interaction: discord.Interaction):
        rate = self.get_rate()
        embed = discord.Embed(title="🏦 Athena Reserve Exchange Rate", color=0xffffff)
        embed.description = f"**Current Rate:** `1 Athena Coin` = `{rate} Mimu Coins`\n\n*Ping the developer to request a currency exchange.*"
        await interaction.response.send_message(embed=embed)


    # ==========================================
    # ADMIN COMMANDS (STRICT PHOENIX ONLY LOCK)
    # ==========================================

    @app_commands.command(name="set_rate", description="Set the Mimu exchange rate")
    @app_commands.describe(new_rate="How many Mimu coins equal 1 Athena coin?")
    async def set_rate(self, interaction: discord.Interaction, new_rate: int):
        # STRIPPED 'administrator' bypass. ONLY ID 743411894416834590 works.
        if interaction.user.id != 743411894416834590:
            await interaction.response.send_message("❌ **Security Alert:** Access Denied. Only Phoenix can alter the central exchange rate.", ephemeral=True)
            return

        if new_rate < 1:
            await interaction.response.send_message("❌ Rate must be at least 1.", ephemeral=True)
            return

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("UPDATE config SET mimu_rate = ? WHERE id = 1", (new_rate,))
        conn.commit()
        conn.close()

        await interaction.response.send_message(f"✅ **Exchange Rate Updated!**\nNew Rate: 1 Athena = {new_rate} Mimu.")

    @app_commands.command(name="mint", description="Print Athena coins and add them to a user's wallet")
    async def mint_coins(self, interaction: discord.Interaction, user: discord.Member, amount: int):
        # STRIPPED 'administrator' bypass. ONLY ID 743411894416834590 works.
        if interaction.user.id != 743411894416834590:
            return await interaction.response.send_message("❌ **Security Alert:** Access Denied. Only Phoenix has access to the Reserve Printing Press.", ephemeral=True)
            
        self.add_balance(user.id, amount)
        bal, _ = self.get_wallet_data(user.id)
        await interaction.response.send_message(f"🏦 **Bank Transfer Successful**\nAdded {amount:,} coins to {user.mention}.\nNew Balance: **A$ {bal:,}**")

async def setup(bot):
    await bot.add_cog(Economy(bot))