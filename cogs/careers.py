import discord
from discord import app_commands
from discord.ext import commands
import sqlite3
import time
import random
import asyncio
from contextlib import contextmanager

# ==========================================
# ️ DATABASE CONTEXT MANAGER (Safe & Atomic)
# ==========================================
DB_PATH = "economy.db"

@contextmanager
def get_db_cursor():
    """Context manager for safe, atomic DB operations"""
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

# ==========================================
# 📊 CAREER PATHS & CARD MULTIPLIERS
# ==========================================

# ✅ FIX: NO TRAILING SPACES IN KEYS!
CARD_TIERS = {
    "silver": {"threshold": 0, "file": "card_silver.png", "color": (255, 255, 255), "name": "Standard Silver", "multiplier": 1.0},
    "gold": {"threshold": 100000, "file": "card_gold.png", "color": (255, 255, 255), "name": "Gold Elite", "multiplier": 1.9},
    "crystal": {"threshold": 300000, "file": "card_crystal.png", "color": (255, 255, 255), "name": "Crystal Debit", "multiplier": 2.5},
    "plat_black": {"threshold": 600000, "file": "card_plat_black.png", "color": (214, 214, 214), "name": "Platinum Black", "multiplier": 4.5},
    "plat_pink": {"threshold": 600000, "file": "card_plat_pink.png", "color": (219, 120, 200), "name": "Platinum Chérie", "multiplier": 4.5},
    
    "infinite": {"threshold": 1200000, "file": "card_infinite.png", "color": (214, 214, 214), "name": "VISA Infinite", "multiplier": 6.5},
    "signature": {"threshold": 3000000, "file": "card_signature.png", "color": (214, 214, 214), "name": "VISA Signature", "multiplier": 8.0},
    "world_debit": {"threshold": 4500000, "file": "card_worlddebit.png", "color": (214, 214, 214), "name": "VISA World Debit", "multiplier": 10.0}
}

# ✅ FIX: Cleaned up dictionary structure
CAREER_PATHS = {
    "tech": {
        "name": "Technology",
        "emoji": "<:tech_athena:1503090321620336650>",
        "tasks": [
            "fixing a major server outage caused by Kyxrt",
            "pushing new code to production",
            "optimizing the database which Yeo corrupted",
            "designing a new UI mockup for AthenaOS",
            "debugging the matchmaking engine for 4 hours straight"
        ],
        "levels": [
            {"title": "Software Engineering Intern", "base_pay": 900, "xp_req": 0},
            {"title": "Junior Developer", "base_pay": 1500, "xp_req": 150},
            {"title": "Lead Engineer", "base_pay": 3200, "xp_req": 500},
            {"title": "Chief Technology Officer", "base_pay": 7000, "xp_req": 1200}
        ]
    },
    "medicine": {
        "name": "Medicine",
        "emoji": "<:healthcare_athena:1503090377203126282>",
        "tasks": [
            "assisting in the ER during a rush hour",
            "administering vaccinations to flat earthers",
            "performing an unsuccessful surgery on Nami",
            "diagnosing a complex case of chronic silliness in Kyxrt",
            "refilling prescriptions for the entire staff"
        ],
        "levels": [
            {"title": "Hospital Volunteer", "base_pay": 900, "xp_req": 0},
            {"title": "Registered Nurse", "base_pay": 1500, "xp_req": 150},
            {"title": "Junior Doctor", "base_pay": 3200, "xp_req": 500},
            {"title": "General Surgery Consultants", "base_pay": 7500, "xp_req": 1200}
        ]
    },
    "finance": {
        "name": "Finance",
        "emoji": "<:finance_athena:1503090272983060661>",
        "tasks": [
            "processing client deposits",
            "hiding your money laundering in quarterly stock reports",
            "managing a multi million portfolio for Phnx",
            "closing a major corporate merger for Discord",
            "auditing the Chérie central bank reserves"
        ],
        "levels": [
            {"title": "Bank Teller", "base_pay": 900, "xp_req": 0},
            {"title": "Financial Analyst", "base_pay": 1500, "xp_req": 150},
            {"title": "Portfolio Manager", "base_pay": 3200, "xp_req": 500},
            {"title": "Israeli Hedge Fund CEO", "base_pay": 7000, "xp_req": 1200}
        ]
    }
}

def make_progress_bar(current: int, total: int) -> str:
    if total == 0: return "`[MAX LEVEL]`"
    fill_left = "<:fillleft:1502707988761153567>"
    fill_mid = "<:fillmid:1502707936823087246>"
    fill_right = "<:fillright:1502707911560794192>"
    empty_left = "<:emptyleft:1502707971363311767>"
    empty_mid = "<:emptymid:1502707866744651948>"
    empty_right = "<:emptyright:1502707890664771717>"
    segments = 10
    percent = current / total
    visual_current = min(max(int(percent * segments), 0), segments)

    bar = ""
    for i in range(segments):
        is_filled = i < visual_current
        if i == 0: bar += fill_left if is_filled else empty_left
        elif i == segments - 1: bar += fill_right if is_filled else empty_right
        else: bar += fill_mid if is_filled else empty_mid
    
    return f"{bar}  **({current}/{total} XP)**"

# ==========================================
# 🔒 ATOMIC BALANCE HELPER (Thread-Safe)
# ==========================================
def atomic_balance_update(cursor, user_id: int, delta: int) -> bool:
    """Atomically updates balance. Returns True on success, False on collision."""
    cursor.execute("SELECT balance FROM wallets WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    
    if row is None:
        cursor.execute("INSERT OR IGNORE INTO wallets (user_id, balance) VALUES (?, 0)", (user_id,))
        cursor.execute("UPDATE wallets SET balance = balance + ? WHERE user_id = ?", (delta, user_id))
        return True
    
    old_balance = row[0] or 0
    new_balance = old_balance + delta
    
    # Only update if balance hasn't changed since we read it
    cursor.execute(
        "UPDATE wallets SET balance = ? WHERE user_id = ? AND balance = ?",
        (new_balance, user_id, old_balance)
    )
    return cursor.rowcount > 0

# ==========================================
# 🏛️ UI COMPONENTS
# ==========================================
class CareerDropdown(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label='Technology Sector', description='Code your way to CTO.', value='tech', emoji='<:tech_athena:1503090321620336650>'),
            discord.SelectOption(label='Medical Field', description='Save lives and run the hospital.', value='medicine', emoji='<:healthcare_athena:1503090377203126282>'),
            discord.SelectOption(label='Financial District', description='Climb Wall Street to Hedge Fund CEO.', value='finance', emoji='<:finance_athena:1503090272983060661>')
        ]
        super().__init__(placeholder='Select a career path...', min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        path_key = self.values[0]
        with get_db_cursor() as cursor:
            cursor.execute("SELECT path FROM user_careers WHERE user_id = ?", (interaction.user.id,))
            if cursor.fetchone():
                return await interaction.response.send_message("<a:wt_torono:1480580892706603018> You already have a career!", ephemeral=True)
                
            cursor.execute("INSERT INTO user_careers (user_id, path, level, xp, last_worked) VALUES (?, ?, 0, 0, 0)", (interaction.user.id, path_key))
        
        job_title = CAREER_PATHS[path_key]["levels"][0]["title"]
        await interaction.response.send_message(
            f"<a:wt_toroexclaim:1480581004317036624> **Congratulations!** You have been hired as a **{job_title}**! Use `/work` to start earning.", 
            ephemeral=True
        )

class CareerView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(CareerDropdown())

    @discord.ui.button(label="View My Profile", style=discord.ButtonStyle.secondary, emoji="<a:wt_torolove:1480580899430203484>", row=1)
    async def profile_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        with get_db_cursor() as cursor:
            cursor.execute("SELECT path, level, xp FROM user_careers WHERE user_id = ?", (interaction.user.id,))
            career = cursor.fetchone()
            
            # Get badges
            badges = []
            cursor.execute("SELECT balance FROM wallets WHERE user_id = ?", (interaction.user.id,))
            bal = (cursor.fetchone() or [0])[0]
            if bal >= 2000000: badges.append("💰") 
            if bal >= 4500000: badges.append("🏦") 
            if career and career[1] >= 3: badges.append("💼")
            
            # Get Portfolio Badges
            try:
                cursor.execute("SELECT SUM(p.shares * s.price) FROM portfolio p JOIN stocks s ON p.symbol = s.symbol WHERE p.user_id = ?", (interaction.user.id,))
                stock_v = (cursor.fetchone() or [0])[0] or 0
                if stock_v >= 5000000: badges.append("💎")
            except: pass

            # Get Property Badges
            try:
                cursor.execute("SELECT property_id FROM user_properties WHERE user_id = ?", (interaction.user.id,))
                owned_props = [r[0] for r in cursor.fetchall()]
                has_res = any(p.startswith("RES") for p in owned_props)
                has_com = any(p.startswith("COM") for p in owned_props)
                has_eli = any(p.startswith("ELI") for p in owned_props)
                if has_eli: badges.append("👑")
                if has_res and has_com and has_eli: badges.append("🏗️")
            except: pass
            
            badge_str = " ".join(badges)

        if not career:
            return await interaction.response.send_message("<a:wt_toroconfused:1480580932367945918> You are unemployed. Select a path from the dropdown above.", ephemeral=True)

        path_key, level, xp = career
        path_data = CAREER_PATHS[path_key]
        current_level_data = path_data["levels"][level]
        
        is_max = level >= len(path_data["levels"]) - 1
        next_req = 0 if is_max else path_data["levels"][level + 1]["xp_req"]
        
        embed = discord.Embed(title="꒰ა ﹒chérie  ⸝⸝", color=0xffffff)
        
        # Add badges to the top of the profile
        desc = f"{badge_str}\n\n" if badge_str else ""
        desc += (
            f"** <:s_white2:1382052523166142486> Industry:** {path_data['name']} {path_data['emoji']}\n"
            f"** <:s_white2:1382052523166142486> Current Role:** {current_level_data['title']}\n"
            f"** <:s_white2:1382052523166142486> Base Salary:** A$ {current_level_data['base_pay']:,}\n\n"
            f"** <a:wt_toroking:1480580998742937691> Promotion Progress**\n"
            f"{make_progress_bar(xp, next_req)}\n"
        )
        embed.description = desc
        embed.set_thumbnail(url=interaction.user.display_avatar.url)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="Badge Index", style=discord.ButtonStyle.secondary, emoji="<a:wt_toroking:1480580998742937691>", row=1)
    async def index_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(title="Central Reserve Badge Index", color=0xffffff)
        embed.description = "Elite honors awarded automatically based on your financial achievements. View your earned badges via `/networth` or your career profile."
        
        embed.add_field(name="<:liquid_gold:1504512350550495312> Liquid Gold", value="Maintain a liquid balance of **A$ 2,000,000**.", inline=False)
        embed.add_field(name="<:reserve_governor:1504512821042483250> Reserve Governor", value="Maintain a liquid balance of **A$ 4,500,000**.", inline=False)
        embed.add_field(name="<:diamond_hands:1504512947089834034> Diamond Hands", value="Hold over **A$ 5,000,000** in active stock investments.", inline=False)
        embed.add_field(name="<:monopolist:1504515470932447394> The Monopolist", value="Purchase any **Elite Tier** property.", inline=False)
        embed.add_field(name="<:empire:1504512585096237227> Empire Builder", value="Own at least one Residential, Commercial, and Elite property simultaneously.", inline=False)
        embed.add_field(name="<:corporate:1504515833148211270> Master of Industry", value="Reach the absolute **MAX level** in your chosen career path.", inline=False)
        
        embed.set_footer(text="More badges will be introduced very soon.")
        await interaction.response.send_message(embed=embed, ephemeral=False)

# ==========================================
# 🏙️ THE CAREERS COG
# ==========================================
class Careers(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.setup_db()

    def setup_db(self):
        with get_db_cursor() as cursor:
            cursor.execute('''CREATE TABLE IF NOT EXISTS user_careers (
                user_id INTEGER PRIMARY KEY, path TEXT, level INTEGER DEFAULT 0, 
                xp INTEGER DEFAULT 0, last_worked REAL DEFAULT 0
            )''')

    @app_commands.command(name="career", description="Choose a career path and view your progress")
    async def career_hub(self, interaction: discord.Interaction):
        await interaction.response.send_message("<a:wt_torospin:1480580977867624540> Initializing Career Portal...", ephemeral=False)
        await asyncio.sleep(1.5)
        
        embed = discord.Embed(title="꒰ა ﹒chérie  ⸝⸝", color=0xffffff)
        embed.description = (
             "<a:wt_torolove:1480580899430203484> **The Corporate Ladder**\n"
             "Select an industry below to begin your professional journey. Every time you `/work`, you will gain experience and climb the ranks, unlocking higher base salaries and exclusive titles.\n\n"
             "** <:s_white2:1382052523166142486> Medical:** Hospital Volunteer > Registered Nurse > Junior Doctor > General Surgery Consultants\n\n"
             "** <:s_white2:1382052523166142486> Tech:** Software Engineering Intern > Junior Developer > Lead Engineer > Chief Technology Officer\n\n"
             "** <:s_white2:1382052523166142486> Finance:** Bank Teller > Financial Analyst > Portfolio Manager > Israeli Hedge Fund CEO\n\n"
             "*Note: Once you choose a career, you cannot change it!*"
        )
        embed.set_image(url="https://media.discordapp.net/attachments/1375079530183790744/1501577920270041199/2227dbca3d307d172781fdb78c85f5ae.jpg?ex=6a01daea&is=6a00896a&hm=b7ae30d45a5a48da6327d1fe629ee924e09036c2aacae1ee55644c776f125881&&format=webp&width=1008&height=336")
        await interaction.edit_original_response(content=None, embed=embed, view=CareerView())

    @app_commands.command(name="work", description="Work a shift at your job to earn A$ and XP")
    async def work(self, interaction: discord.Interaction):
        with get_db_cursor() as cursor:
            cursor.execute("SELECT path, level, xp, last_worked FROM user_careers WHERE user_id = ?", (interaction.user.id,))
            career = cursor.fetchone()
            
            if not career:
                return await interaction.response.send_message("<a:wt_torono:1480580892706603018> You are unemployed! Use `/career` to find a job.", ephemeral=True)

            path_key, level, xp, last_worked = career
            
            # --- DYNAMIC COOLDOWN ---
            base_cooldown = 3600 # 1 hour
            cursor.execute("SELECT MAX(m.cooldown_reduction) FROM user_vehicles u JOIN market_vehicles m ON u.vehicle_id = m.id WHERE u.user_id = ? AND u.needs_repair = 0", (interaction.user.id,))
            max_reduction = cursor.fetchone()[0] or 0
            actual_cooldown = max(0, base_cooldown - (max_reduction * 60))
            
            now = time.time()
            if now - last_worked < actual_cooldown:
                rem = int(actual_cooldown - (now - last_worked))
                mins, secs = divmod(rem, 60)
                return await interaction.response.send_message(
                    f"<a:wt_toronerd:1480580983593111602> You are too tired! Your next shift starts in **{mins}m {secs}s**.", 
                    ephemeral=True
                )

            # --- CALCULATE PAYOUT & CARDS ---
            # ✅ FIX: Strip whitespace from card name to prevent lookup failures
            cursor.execute("SELECT active_card FROM wallets WHERE user_id = ?", (interaction.user.id,))
            card_row = cursor.fetchone()
            active_card = (card_row[0] if card_row else 'silver').strip()
            
            path_data = CAREER_PATHS[path_key]
            current_level_data = path_data["levels"][level]
            
            base_pay = current_level_data["base_pay"]
            # ✅ FIX: Use clean CARD_TIERS dictionary
            mult = CARD_TIERS.get(active_card, CARD_TIERS["silver"])["multiplier"]
            
            payout = int((base_pay * random.uniform(0.9, 1.2)) * mult)
            gained_xp = random.randint(15, 30)
            new_xp = xp + gained_xp
            
            # --- CHECK PROMOTION ---
            is_max = level >= len(path_data["levels"]) - 1
            promoted = False
            new_level = level
            
            if not is_max:
                next_req = path_data["levels"][level + 1]["xp_req"]
                if new_xp >= next_req:
                    promoted = True
                    new_level += 1
            
            # --- UPDATE DATABASE ---
            cursor.execute("UPDATE user_careers SET xp = ?, level = ?, last_worked = ? WHERE user_id = ?", 
                           (new_xp, new_level, now, interaction.user.id))
            
            # --- ATOMIC BALANCE UPDATE ---
            success = atomic_balance_update(cursor, interaction.user.id, payout)
            
            if not success:
                # Fallback if collision occurred (retry once)
                success = atomic_balance_update(cursor, interaction.user.id, payout)
        
        # --- VARYING MESSAGES PER CAREER ---
        task_done = random.choice(path_data["tasks"])
        
        # Flavor text based on career type
        if path_key == "tech":
            flavor_msg = "<:btb_white3:1375474689467748517> **Shift Report:** You spent your shift debugging code for Athena."
        elif path_key == "medicine":
            flavor_msg = "<:btb_white3:1375474689467748517> **Shift Report:** You spent your shift in the bunker treating burn unit patients."
        elif path_key == "finance":
            flavor_msg = "<:btb_white3:1375474689467748517> **Shift Report:** You spent your shift on the trading floor hiding tax gains."
        else:
            flavor_msg = "<:btb_white3:1375474689467748517> **Shift Report:** You spent your shift working."

        embed = discord.Embed(title="꒰ა ﹒chérie  ⸝", color=0xffffff)
        desc = (
            f"{flavor_msg}\n"
            f"<:s_white2:1382052523166142486> **Task:** {task_done}\n"
            f"<:s_white2:1382052523166142486> **Earned:** A$ {payout:,} <:athenacoin:1503804322280902767> *(Includes {mult}x {CARD_TIERS[active_card]['name']} Bonus)*\n"
            f"<:s_white2:1382052523166142486> **XP Gained:** +{gained_xp} XP\n\n"
        )
        
        if promoted:
            new_title = path_data["levels"][new_level]["title"]
            desc += f"<a:wt_toroexclaim:1480581004317036624> **PROMOTION!** You have climbed the ladder and are now a **{new_title}**! Your base salary has increased, continue working hard."
            
        embed.description = desc
        embed.set_thumbnail(url=interaction.user.display_avatar.url)
        await interaction.response.send_message(embed=embed)

async def setup(bot):
    await bot.add_cog(Careers(bot))