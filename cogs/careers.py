import discord
from discord import app_commands
from discord.ext import commands
import sqlite3
import time
import random
import asyncio

DB_PATH = "economy.db"

def get_db_connection():
    # Adding a 20-second timeout gives tasks time to wait for a lock to release
    conn = sqlite3.connect(DB_PATH, timeout=20, isolation_level=None)
    # This line is the magic fix for "database is locked"
    conn.execute('PRAGMA journal_mode=WAL;') 
    conn.execute('PRAGMA temp_store = MEMORY;')
    conn.execute('PRAGMA synchronous = NORMAL;')
    return conn

# ==========================================
# 📊 CAREER PATHS & CARD MULTIPLIERS
# ==========================================
CARD_TIERS = {
    "silver": {"multiplier": 1.0, "name": "Standard Silver"},
    "gold": {"multiplier": 1.9, "name": "Gold Elite"},
    "crystal": {"multiplier": 2.5, "name": "Crystal Debit"},
    "plat_black": {"multiplier": 4.5, "name": "Platinum Black"},
    "plat_pink": {"multiplier": 4.5, "name": "Platinum Chérie"}
}

CAREER_PATHS = {
    "tech": {
        "name": "Technology",
        "emoji": "<:tech_athena:1503090321620336650>",
        "tasks": ["fixing a major server outage caused by Kyxrt", "pushing new code to production", "optimizing the database which Yeo corrupted", "designing a new UI mockup for AthenaOS"],
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
        "tasks": ["assisting in the ER", "administering vaccinations to flat earthers", "performing an unsuccessful surgery on Nami", "diagnosing a complex case of chronic silliness in Ari"],
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
        "tasks": ["processing client deposits", "hiding your money laundering in quarterly stock reports", "managing a multi million portfolio for Phnx", "closing a major corporate merger for Discord"],
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
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Check if they already have a career
        cursor.execute("SELECT path FROM user_careers WHERE user_id = ?", (interaction.user.id,))
        if cursor.fetchone():
            conn.close()
            return await interaction.response.send_message("<a:wt_torono:1480580892706603018> 𝑌𝑜𝑢 𝑎𝑙𝑟𝑒𝑎𝑑𝑦 ℎ𝑎𝑣𝑒 𝑎 𝑐𝑎𝑟𝑒𝑒𝑟!", ephemeral=True)
            
        # Enroll them at Level 0
        cursor.execute("INSERT INTO user_careers (user_id, path, level, xp, last_worked) VALUES (?, ?, 0, 0, 0)", (interaction.user.id, path_key))
        conn.commit()
        conn.close()
        
        job_title = CAREER_PATHS[path_key]["levels"][0]["title"]
        await interaction.response.send_message(f"<a:wt_toroexclaim:1480581004317036624> 𝐶𝑜𝑛𝑔𝑟𝑎𝑡𝑢𝑙𝑎𝑡𝑖𝑜𝑛𝑠! 𝑌𝑜𝑢 ℎ𝑎𝑣𝑒 𝑏𝑒𝑒𝑛 ℎ𝑖𝑟𝑒𝑑 𝑎𝑠 𝑎 **{job_title}**! 𝑈𝑠𝑒 `/work` 𝑡𝑜 𝑠𝑡𝑎𝑟𝑡 𝑒𝑎𝑟𝑛𝑖𝑛𝑔.", ephemeral=True)

class CareerView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(CareerDropdown())

    @discord.ui.button(label="View My Profile", style=discord.ButtonStyle.secondary, emoji="<a:wt_torolove:1480580899430203484>", row=1)
    async def profile_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT path, level, xp FROM user_careers WHERE user_id = ?", (interaction.user.id,))
        career = cursor.fetchone()
        conn.close()

        if not career:
            return await interaction.response.send_message("<a:wt_toroconfused:1480580932367945918> 𝑌𝑜𝑢 𝑎𝑟𝑒 𝑢𝑛𝑒𝑚𝑝𝑙𝑜𝑦𝑒𝑑. 𝑆𝑒𝑙𝑒𝑐𝑡 𝑎 𝑝𝑎𝑡ℎ 𝑓𝑟𝑜𝑚 𝑡ℎ𝑒 𝑑𝑟𝑜𝑝𝑑𝑜𝑤𝑛 𝑎𝑏𝑜𝑣𝑒.", ephemeral=True)

        path_key, level, xp = career
        path_data = CAREER_PATHS[path_key]
        current_level_data = path_data["levels"][level]
        
        is_max = level >= len(path_data["levels"]) - 1
        next_req = 0 if is_max else path_data["levels"][level + 1]["xp_req"]
        
        embed = discord.Embed(title="꒰ა ﹒chérie  ⸝⸝", color=0xffffff)
        desc = (
            f"**<:s_white2:1382052523166142486> Industry:** {path_data['name']} {path_data['emoji']}\n"
            f"**<:s_white2:1382052523166142486> Current Role:** {current_level_data['title']}\n"
            f"**<:s_white2:1382052523166142486> Base Salary:** A$ {current_level_data['base_pay']:,}\n\n"
            f"**<a:wt_toroking:1480580998742937691> Promotion Progress**\n"
            f"{make_progress_bar(xp, next_req)}\n"
        )
        embed.description = desc
        embed.set_thumbnail(url=interaction.user.display_avatar.url)
        await interaction.response.send_message(embed=embed, ephemeral=True)

# ==========================================
# 🏙️ THE CAREERS COG
# ==========================================
class Careers(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.setup_db()

    def setup_db(self):
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('''CREATE TABLE IF NOT EXISTS user_careers (
            user_id INTEGER PRIMARY KEY, path TEXT, level INTEGER DEFAULT 0, xp INTEGER DEFAULT 0, last_worked REAL DEFAULT 0
        )''')
        conn.commit()
        conn.close()

    @app_commands.command(name="career", description="Choose a career path and view your progress")
    async def career_hub(self, interaction: discord.Interaction):
        await interaction.response.send_message("<a:wt_torospin:1480580977867624540> 𝐼𝑛𝑖𝑡𝑖𝑎𝑙𝑖𝑧𝑖𝑛𝑔 𝐶𝑎𝑟𝑒𝑒𝑟 𝑃𝑜𝑟𝑡𝑎𝑙...", ephemeral=False)
        await asyncio.sleep(1.5)
        
        embed = discord.Embed(title="꒰ა ﹒chérie  ⸝⸝", color=0xffffff)
        embed.description = (
            "<a:wt_torolove:1480580899430203484> **𝑇ℎ𝑒 𝐶𝑜𝑟𝑝𝑜𝑟𝑎𝑡𝑒 𝐿𝑎𝑑𝑑𝑒𝑟**\n"
            "Select an industry below to begin your professional journey. Every time you `/work`, you will gain experience and climb the ranks, unlocking higher base salaries and exclusive titles.\n\n"
            "**<:s_white2:1382052523166142486> Medical:** Hospital Volunteer > Registered Nurse > Junior Doctor > General Surgery Consultants\n\n"
            "**<:s_white2:1382052523166142486> Tech:** Software Engineering Intern > Junior Developer > Lead Engineer > Chief Technology Officer\n\n"
            "**<:s_white2:1382052523166142486> Finance:** Bank Teller > Financial Analyst > Portfolio Manager > Israeli Hedge Fund CEO\n\n"
            "*Note: Once you choose a career, you cannot change it!*"
        )
        embed.set_image(url="https://media.discordapp.net/attachments/1375079530183790744/1501577920270041199/2227dbca3d307d172781fdb78c85f5ae.jpg?ex=6a01daea&is=6a00896a&hm=b7ae30d45a5a48da6327d1fe629ee924e09036c2aacae1ee55644c776f125881&=&format=webp&width=1008&height=336")
        await interaction.edit_original_response(content=None, embed=embed, view=CareerView())

    @app_commands.command(name="work", description="Work a shift at your job to earn A$ and XP")
    async def work(self, interaction: discord.Interaction):
        conn = sqlite3.connect("economy.db", timeout=20, isolation_level=None)
        conn.execute('PRAGMA journal_mode=WAL;')
        cursor = conn.cursor()
        
        # Ensure wallet exists first
        cursor.execute("INSERT OR IGNORE INTO wallets (user_id, balance, active_card, highest_balance) VALUES (?, 0, 'silver', 0)", (interaction.user.id,))
        
        cursor.execute("SELECT path, level, xp, last_worked FROM user_careers WHERE user_id = ?", (interaction.user.id,))
        career = cursor.fetchone()
        
        if not career:
            conn.close()
            return await interaction.response.send_message("<a:wt_torono:1480580892706603018> 𝑌𝑜𝑢 𝑎𝑟𝑒 𝑢𝑛𝑒𝑚𝑝𝑙𝑜𝑦𝑒𝑑! 𝑈𝑠𝑒 `/career` 𝑡𝑜 𝑓𝑖𝑛𝑑 𝑎 𝑗𝑜𝑏.", ephemeral=True)

        path_key, level, xp, last_worked = career
        
        # --- DYNAMIC COOLDOWN BUG FIX ---
        base_cooldown = 3600 # 1 hour
        try:
            cursor.execute("SELECT MAX(m.cooldown_reduction) FROM user_vehicles u JOIN market_vehicles m ON u.vehicle_id = m.id WHERE u.user_id = ? AND u.needs_repair = 0", (interaction.user.id,))
            max_reduction = cursor.fetchone()[0] or 0
        except sqlite3.OperationalError:
            max_reduction = 0 # Failsafe: Bypasses crash if marketplace vehicles table is empty
            
        actual_cooldown = max(0, base_cooldown - (max_reduction * 60))
        
        now = time.time()
        if now - last_worked < actual_cooldown:
            conn.close()
            rem = int(actual_cooldown - (now - last_worked))
            mins, secs = divmod(rem, 60)
            return await interaction.response.send_message(f"<a:wt_toronerd:1480580983593111602> 𝑌𝑜𝑢 𝑎𝑟𝑒 𝑡𝑜𝑜 𝑡𝑖𝑟𝑒𝑑! 𝑌𝑜𝑢𝑟 𝑛𝑒𝑥𝑡 𝑠ℎ𝑖𝑓𝑡 𝑠𝑡𝑎𝑟𝑡𝑠 𝑖𝑛 **{mins}m {secs}s**.", ephemeral=True)

        # --- CALCULATE PAYOUT & CARDS ---
        # Get the user's ACTUAL card tier from database (not relying on defaults)
        cursor.execute("SELECT active_card FROM wallets WHERE user_id = ?", (interaction.user.id,))
        card_row = cursor.fetchone()
        active_card = card_row[0] if card_row and card_row[0] else 'silver'
        
        path_data = CAREER_PATHS[path_key]
        current_level_data = path_data["levels"][level]
        
        base_pay = current_level_data["base_pay"]
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
        cursor.execute("UPDATE user_careers SET xp = ?, level = ?, last_worked = ? WHERE user_id = ?", (new_xp, new_level, now, interaction.user.id))
        conn.commit()
        conn.close()

        # Use the centralized balance helper for auto card upgrade
        from cogs.economy import apply_balance_increase
        await apply_balance_increase(interaction.user.id, payout, interaction.channel)

        card_name = CARD_TIERS.get(active_card, CARD_TIERS["silver"])["name"]
        task_done = random.choice(path_data["tasks"])
        
        embed = discord.Embed(title="꒰ა ﹒chérie  ⸝⸝", color=0xffffff)
        desc = (
            f"<:s_white2:1382052523166142486> You spent your shift doing {task_done}.\n"
            f"<:s_white2:1382052523166142486> **Earned:** A$ {payout:,} *(Includes {mult}x {card_name} Bonus)*\n"
            f"<:s_white2:1382052523166142486> **XP Gained:** +{gained_xp} XP\n\n"
        )
        
        if promoted:
            new_title = path_data["levels"][new_level]["title"]
            desc += f"<a:wt_toroexclaim:1480581004317036624> **𝑃𝑅𝑂𝑀𝑂𝑇𝐼𝑂𝑁!** 𝑌𝑜𝑢 ℎ𝑎𝑣𝑒 𝑐𝑙𝑖𝑚𝑏𝑒𝑑 𝑡ℎ𝑒 𝑙𝑎𝑑𝑑𝑒𝑟 𝑎𝑛𝑑 𝑎𝑟𝑒 𝑛𝑜𝑤 𝑎 **{new_title}**! 𝑌𝑜𝑢𝑟 𝑏𝑎𝑠𝑒 𝑠𝑎𝑙𝑎𝑟𝑦 ℎ𝑎𝑠 𝑖𝑛𝑐𝑟𝑒𝑎𝑠𝑒𝑑."
            
        embed.description = desc
        embed.set_thumbnail(url=interaction.user.display_avatar.url)
        await interaction.response.send_message(embed=embed)

async def setup(bot):
    await bot.add_cog(Careers(bot))