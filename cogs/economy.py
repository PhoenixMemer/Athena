import discord
from discord import app_commands
from discord.ext import commands
import sqlite3
import os
import io
from PIL import Image, ImageDraw, ImageFont

class Economy(commands.Cog):
    """Athena Central Bank & Economy System"""
    
    def __init__(self, bot):
        self.bot = bot
        self.db_path = "economy.db"
        self.template_path = "athena_card.png"
        self.setup_db()
        
    def setup_db(self):
        """Initializes the separate economy database"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Wallets Table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS wallets (
                user_id INTEGER PRIMARY KEY,
                balance INTEGER DEFAULT 0
            )
        ''')
        
        # Exchange Rate Table (Always stored in row id=1)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS config (
                id INTEGER PRIMARY KEY,
                mimu_rate INTEGER DEFAULT 100
            )
        ''')
        
        # Ensure the default rate exists
        cursor.execute("INSERT OR IGNORE INTO config (id, mimu_rate) VALUES (1, 100)")
        
        conn.commit()
        conn.close()

    def get_balance(self, user_id: int) -> int:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT balance FROM wallets WHERE user_id = ?", (user_id,))
        result = cursor.fetchone()
        conn.close()
        return result[0] if result else 0

    def add_balance(self, user_id: int, amount: int):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("INSERT INTO wallets (user_id, balance) VALUES (?, ?) ON CONFLICT(user_id) DO UPDATE SET balance = balance + ?", (user_id, amount, amount))
        conn.commit()
        conn.close()

    def get_rate(self) -> int:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT mimu_rate FROM config WHERE id = 1")
        rate = cursor.fetchone()[0]
        conn.close()
        return rate

    async def generate_wallet_card(self, member: discord.Member, balance: int) -> io.BytesIO:
        """Generates the Arcane-style image card"""
        # If the template doesn't exist yet, generate a sleek dark fallback image
        if not os.path.exists(self.template_path):
            img = Image.new('RGB', (800, 250), color=(15, 23, 42)) # Dark Navy
            draw = ImageDraw.Draw(img)
            draw.text((40, 20), "⚠️ athena_card.png NOT FOUND", fill=(255, 100, 100))
        else:
            img = Image.open(self.template_path).convert("RGBA")
            draw = ImageDraw.Draw(img)

        # Try to load a default font, otherwise fallback to basic PIL font
        try:
            # Using a larger font size for the balance
            font_large = ImageFont.truetype("arial.ttf", 60)
            font_small = ImageFont.truetype("arial.ttf", 35)
        except IOError:
            font_large = ImageFont.load_default()
            font_small = ImageFont.load_default()

        # Text positioning (You will need to adjust these X, Y coordinates based on your actual card design)
        # Writing the Username
        draw.text((50, 40), f"{member.display_name.upper()}", fill=(255, 255, 255), font=font_small)
        
        # Writing the Balance
        draw.text((50, 120), f"A$ {balance:,}", fill=(255, 215, 0), font=font_large) # Gold color

        # Save to memory buffer instead of disk
        buffer = io.BytesIO()
        img.save(buffer, format="PNG")
        buffer.seek(0)
        return buffer

    # --- USER COMMANDS ---

    @app_commands.command(name="bal", description="Check your Athena Reserve wallet balance")
    async def balance(self, interaction: discord.Interaction):
        await interaction.response.defer() # Defer because image generation takes a second
        
        bal = self.get_balance(interaction.user.id)
        image_buffer = await self.generate_wallet_card(interaction.user, bal)
        
        # Send the image buffer to Discord
        file = discord.File(fp=image_buffer, filename="wallet.png")
        await interaction.followup.send(file=file)

    @app_commands.command(name="exchange_rate", description="View the current Mimu to Athena exchange rate")
    async def view_rate(self, interaction: discord.Interaction):
        rate = self.get_rate()
        embed = discord.Embed(title="🏦 Athena Reserve Exchange Rate", color=0xffffff)
        embed.description = f"**Current Rate:** `1 Athena Coin` = `{rate} Mimu Coins`\n\n*Ping the developer to request a currency exchange.*"
        await interaction.response.send_message(embed=embed)

    # --- ADMIN/DEV COMMANDS ---

    @app_commands.command(name="set_rate", description="ADMIN: Set the Mimu exchange rate")
    @app_commands.describe(new_rate="How many Mimu coins equal 1 Athena coin?")
    async def set_rate(self, interaction: discord.Interaction, new_rate: int):
        if not interaction.user.guild_permissions.administrator and interaction.user.id != 743411894416834590:
            await interaction.response.send_message("❌ Access Denied.", ephemeral=True)
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

    @app_commands.command(name="mint", description="ADMIN: Print Athena coins and add them to a user's wallet")
    @app_commands.describe(user="The user receiving funds", amount="Amount to add (can be negative to remove)")
    async def mint_coins(self, interaction: discord.Interaction, user: discord.Member, amount: int):
        if not interaction.user.guild_permissions.administrator and interaction.user.id != 743411894416834590:
            await interaction.response.send_message("❌ Access Denied.", ephemeral=True)
            return

        self.add_balance(user.id, amount)
        new_bal = self.get_balance(user.id)
        
        await interaction.response.send_message(f"🏦 **Bank Transfer Successful**\nAdded {amount:,} coins to {user.mention}.\nNew Balance: **A$ {new_bal:,}**")

async def setup(bot):
    await bot.add_cog(Economy(bot))
