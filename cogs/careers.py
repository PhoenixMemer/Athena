import discord
from discord import app_commands
from discord.ext import commands
import sqlite3
import time
import random
import asyncio
from contextlib import contextmanager

# ==========================================
# 🗄️ DATABASE CONTEXT MANAGER (Safe & Atomic)
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
CARD_TIERS = {
    "owner1": {"threshold": 0, "file": "nami.png", "color": (39, 39, 39), "name": "Premier Edition", "multiplier": 3.5},
    "owner2": {"threshold": 0, "file": "ari.png", "color": (244, 212, 242), "name": "Premier Edition", "multiplier": 3.5},
    "cod": {"threshold": 5000, "file": "cod_limited.png", "color": (255, 255, 255), "name": "Limited 01", "multiplier": 1.5},
    "sub": {"threshold": 5000, "file": "sub_limited.png", "color": (214, 214, 214), "name": "Limited 02", "multiplier": 1.5},
    "blade": {"threshold": 5000, "file": "blade_limited.png", "color": (214, 214, 214), "name": "Limited 03", "multiplier": 1.5},
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
    },
    "diplomat": {
        "name": "Diplomat",
        "emoji": "<:diplomacy:1509315782650237162>",
        "tasks": [
            "negotiating a peace treaty between rival countries",
            "hosting a highly classified UN summit",
            "defusing a geopolitical crisis caused by a rogue ping",
            "drafting international trade agreements",
            "attending a state dinner to secure foreign alliances"
        ],
        "levels": [
            {"title": "Foreign Service Intern", "base_pay": 900, "xp_req": 0},
            {"title": "Embassy Attaché", "base_pay": 1500, "xp_req": 150},
            {"title": "Ambassador to Israel", "base_pay": 3200, "xp_req": 500},
            {"title": "Foreign Minister", "base_pay": 7500, "xp_req": 1200}
        ]
    },
    "army": {
        "name": "Army",
        "emoji": "🪖",
        "tasks": [
            "running a brutal 10-mile boot camp drill",
            "cleaning the barracks with a toothbrush",
            "leading a covert ground assault mission",
            "maintaining the armory's tank treads",
            "strategizing infantry maneuvers for the next campaign"
        ],
        "levels": [
            {"title": "Private", "base_pay": 900, "xp_req": 0},
            {"title": "Sergeant", "base_pay": 1500, "xp_req": 150},
            {"title": "Captain", "base_pay": 3200, "xp_req": 500},
            {"title": "Major", "base_pay": 4000, "xp_req": 800}
        ]
    },
    "navy": {
        "name": "Navy",
        "emoji": "⚓",
        "tasks": [
            "swabbing the deck of an aircraft carrier",
            "monitoring sonar for unidentified submarines",
            "coordinating a massive fleet blockade",
            "inspecting the nuclear reactor on the sub",
            "navigating a destroyer through rough seas"
        ],
        "levels": [
            {"title": "Seaman Recruit", "base_pay": 900, "xp_req": 0},
            {"title": "Petty Officer", "base_pay": 1500, "xp_req": 150},
            {"title": "Lieutenant Commander", "base_pay": 3200, "xp_req": 500},
            {"title": "Commander", "base_pay": 4000, "xp_req": 800}
        ]
    },
    "air_force": {
        "name": "Air Force",
        "emoji": "<:air_force:1509315094868394105>",
        "tasks": [
            "performing pre flight checks on the F-22 Raptor",
            "running flight simulation drills",
            "executing a supersonic stealth reconnaissance mission",
            "refueling jets in mid air",
            "managing global air traffic control operations"
        ],
        "levels": [
            {"title": "Airman", "base_pay": 900, "xp_req": 0},
            {"title": "Staff Sergeant", "base_pay": 1500, "xp_req": 150},
            {"title": "Fighter Pilot", "base_pay": 3200, "xp_req": 500},
            {"title": "Wing Commander", "base_pay": 4000, "xp_req": 800}
        ]
    },
    "hockey": {
        "name": "Hockey Operations",
        "emoji": "🏒",
        "tasks": [
            "scouting prospects at a junior league tournament ",
            "analyzing advanced analytics and Corsi ratings ",
            "negotiating entry-level contracts with draft picks ",
            "managing the team's salary cap space ",
            "overseeing the minor league affiliate's development program "
        ],
        "levels": [
            {"title": "Hockey Operations Intern ", "base_pay": 900, "xp_req": 0},
            {"title": "Coordinator ", "base_pay": 1500, "xp_req": 150},
            {"title": "Manager of Hockey Operations ", "base_pay": 3200, "xp_req": 500},
            {"title": "Director of Player Personnel ", "base_pay": 5500, "xp_req": 1200},
            {"title": "General Manager ", "base_pay": 8000, "xp_req": 2500},
            {"title": "President/CEO ", "base_pay": 12000, "xp_req": 5000}
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
            discord.SelectOption(label='Financial District', description='Climb Wall Street to Hedge Fund CEO.', value='finance', emoji='<:finance_athena:1503090272983060661>'),
            discord.SelectOption(label='Diplomatic Corps', description='Negotiate peace as Secretary of State.', value='diplomat', emoji='<:diplomacy:1509315782650237162>'),
            discord.SelectOption(label='Army', description='Lead ground assaults as an Army Officer.', value='army', emoji='🪖'),
            discord.SelectOption(label='Navy', description='Command the seas as a Navy Officer.', value='navy', emoji='⚓'),
            discord.SelectOption(label='Hockey Operations', description='Build a championship roster from the ground up.', value='hockey', emoji='🏒'),
            discord.SelectOption(label='Air Force', description='Dominate the skies as an Air Force pilot.', value='air_force', emoji='<:air_force:1509315094868394105>')
        ]
        super().__init__(placeholder='Select a career path...', min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        path_key = self.values[0]
        user_id = interaction.user.id
        
        with get_db_cursor() as cursor:
            cursor.execute("SELECT path, level FROM user_careers WHERE user_id = ?", (user_id,))
            career = cursor.fetchone()
            
            if career:
                current_path, current_level = career
                
                if current_path == path_key:
                    return await interaction.response.send_message("<a:wt_torono:1480580892706603018> You are already pursuing this career!", ephemeral=True)
                
                # Dynamic MAX level check based on the length of the current career's levels list
                max_level_for_current = len(CAREER_PATHS[current_path]["levels"]) - 1
                
                if current_level < max_level_for_current:
                    return await interaction.response.send_message(
                        f"<a:wt_torono:1480580892706603018> You cannot switch careers yet! You must reach the MAX level (**Level {max_level_for_current}**) in your current **{CAREER_PATHS[current_path]['name']}** career first.", 
                        ephemeral=True
                    )
                
                # Process the career switch and reset XP/Level
                cursor.execute(
                    "UPDATE user_careers SET path = ?, level = 0, xp = 0, last_worked = 0 WHERE user_id = ?", 
                    (path_key, user_id)
                )
                new_title = CAREER_PATHS[path_key]["levels"][0]["title"]
                await interaction.response.send_message(
                    f"<a:wt_toroexclaim:1480581004317036624> **Congratulations!** You have successfully switched your career to **{CAREER_PATHS[path_key]['name']}** and are now a **{new_title}**. Your progress has been reset for the new pathway.", 
                    ephemeral=True
                )
            else:
                # Brand new user
                cursor.execute(
                    "INSERT INTO user_careers (user_id, path, level, xp, last_worked) VALUES (?, ?, 0, 0, 0)", 
                    (user_id, path_key)
                )
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
            if bal >= 2000000: badges.append("<:liquid_gold:1504512350550495312>") 
            if bal >= 4500000: badges.append("<:reserve_governor:1504512821042483250>") 
            if career and career[1] >= 3: badges.append("<:corporate:1504515833148211270>")
            
            # Get Portfolio Badges
            try:
                cursor.execute("SELECT SUM(p.shares * s.price) FROM portfolio p JOIN stocks s ON p.symbol = s.symbol WHERE p.user_id = ?", (interaction.user.id,))
                stock_v = (cursor.fetchone() or [0])[0] or 0
                if stock_v >= 5000000: badges.append("<:diamond_hands:1504512947089834034>")
            except: pass

            # Get Property Badges
            try:
                cursor.execute("SELECT property_id FROM user_properties WHERE user_id = ?", (interaction.user.id,))
                owned_props = [r[0] for r in cursor.fetchall()]
                has_res = any(p.startswith("RES") for p in owned_props)
                has_com = any(p.startswith("COM") for p in owned_props)
                has_eli = any(p.startswith("ELI") for p in owned_props)
                if has_eli: badges.append("<:monopolist:1504515470932447394>")
                if has_res and has_com and has_eli: badges.append("<:empire:1504512585096237227>")
            except: pass
            
            badge_str = "  ".join(badges)

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
            f"**<:s_white2:1382052523166142486> Industry:** {path_data['name']} {path_data['emoji']}\n"
            f"**<:s_white2:1382052523166142486> Current Role:** {current_level_data['title']}\n"
            f"**<:s_white2:1382052523166142486> Base Salary:** A$ {current_level_data['base_pay']:,}\n\n"
            f"**<a:wt_toroking:1480580998742937691> Promotion Progress**\n"
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
            "**<:s_white2:1382052523166142486> Medical:** Hospital Volunteer > Registered Nurse > Junior Doctor > General Surgery Consultants\n\n"
            "**<:s_white2:1382052523166142486> Tech:** Software Engineering Intern > Junior Developer > Lead Engineer > Chief Technology Officer\n\n"
            "**<:s_white2:1382052523166142486> Finance:** Bank Teller > Financial Analyst > Portfolio Manager > Israeli Hedge Fund CEO\n\n"
            "**<:s_white2:1382052523166142486> Diplomat:** Foreign Service Intern > Embassy Attaché > Ambassador to Israel > Foreign Minister\n\n"
            "**<:s_white2:1382052523166142486> Army:** Private > Sergeant > Captain > Major\n\n"
            "**<:s_white2:1382052523166142486> Navy:** Seaman Recruit > Petty Officer > Lieutenant Commander > Commander\n\n"
            "**<:s_white2:1382052523166142486> Air Force:** Airman > Staff Sergeant > Fighter Pilot > Wing Commander\n\n"
            "** <:s_white2:1382052523166142486 > Hockey:** Intern  > Coordinator  > Manager of Hockey Operations  > Director of Player Personnel  > General Manager  > President\n\n "
            "*Note: Once you choose a career, you must reach the MAX level to switch it!*"
        )
        embed.set_image(url="https://i.pinimg.com/1200x/01/b9/0e/01b90ed975824daa7f09ea32fe3b9013.jpg")
        await interaction.edit_original_response(content=None, embed=embed, view=CareerView())

    @app_commands.command(name="work", description="Work a shift at your job to earn A$ and XP")
    async def work(self, interaction: discord.Interaction):
        await interaction.response.defer()

        with get_db_cursor() as cursor:
            cursor.execute("SELECT path, level, xp, last_worked FROM user_careers WHERE user_id = ?", (interaction.user.id,))
            career = cursor.fetchone()

            if not career:
                return await interaction.followup.send("<a:wt_torono:1480580892706603018> You are unemployed! Use `/career` to find a job.", ephemeral=True)

            path_key, level, xp, last_worked = career

            # --- FETCH CAR DATA ONCE ---
            cursor.execute("""
                SELECT MAX(m.cooldown_reduction), m.name
                FROM user_vehicles u
                JOIN market_vehicles m ON u.vehicle_id = m.id
                WHERE u.user_id = ? AND u.needs_repair = 0
                ORDER BY m.price DESC LIMIT 1
            """, (interaction.user.id,))
            car_data = cursor.fetchone()

            if car_data and car_data[0] is not None:
                max_reduction_minutes = car_data[0]
                car_name = car_data[1]
            else:
                max_reduction_minutes = 0
                car_name = "your feet"

            # --- DYNAMIC COOLDOWN (Balanced) ---
            base_cooldown = 2700  # 45 minutes
            absolute_minimum = 900  # 15 minutes

            calculated_cooldown = base_cooldown - (max_reduction_minutes * 60)
            actual_cooldown = max(absolute_minimum, calculated_cooldown)

            now = time.time()
            if now - last_worked < actual_cooldown:
                rem = int(actual_cooldown - (now - last_worked))
                mins, secs = divmod(rem, 60)
                return await interaction.followup.send(
                    f"<a:wt_toronerd:1480580983593111602> You are too tired! Your next shift starts in **{mins}m {secs}s**.",
                    ephemeral=True
                )

            # --- CALCULATE PAYOUT & CARDS ---
            cursor.execute("SELECT active_card FROM wallets WHERE user_id = ?", (interaction.user.id,))
            card_row = cursor.fetchone()
            active_card = (card_row[0] if card_row else 'silver').strip()

            path_data = CAREER_PATHS[path_key]
            current_level_data = path_data["levels"][level]

            base_pay = current_level_data["base_pay"]
            mult = CARD_TIERS.get(active_card, CARD_TIERS["silver"])["multiplier"]

            payout = int((base_pay * random.uniform(0.9, 1.2)) * mult)

            # --- XP INCENTIVE ---
            gained_xp_base = random.randint(15, 30)
            xp_mult = 1 + (max_reduction_minutes / 100)
            gained_xp = int(gained_xp_base * xp_mult)
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

        # --- DB IS NOW CLOSED ---

        from cogs.economy import apply_balance_increase
        await apply_balance_increase(interaction.user.id, payout, interaction.channel, tx_type="work")

        task_done = random.choice(path_data["tasks"])

        if path_key == "tech":
            flavor_msg = "<:btb_white3:1375474689467748517> **Shift Report:** You spent your shift debugging code for Athena."
        elif path_key == "medicine":
            flavor_msg = "<:btb_white3:1375474689467748517> **Shift Report:** You spent your shift in the bunker treating burn unit patients."
        elif path_key == "finance":
            flavor_msg = "<:btb_white3:1375474689467748517> **Shift Report:** You spent your shift on the trading floor hiding tax gains."
        elif path_key == "hockey":
            flavor_msg = " <:btb_white3:1375474689467748517> **Shift Report:** You spent your shift at the rink managing the front office. "
        elif path_key in ["diplomat", "army", "navy", "air_force"]:
            flavor_msg = f"<:btb_white3:1375474689467748517> **Shift Report:** You spent your shift serving the {path_data['name']} branch."
        else:
            flavor_msg = "<:btb_white3:1375474689467748517> **Shift Report:** You spent your shift working."

        embed = discord.Embed(title="꒰ა ﹒chérie  ⸝", color=0xffffff)
        desc = (
            f"<a:wt_torocellphone:1503815758730366976> **Commute:** You pulled up to work in **{car_name}**.\n"
            f"{flavor_msg}\n"
            f"<:s_white2:1382052523166142486> **Task:** {task_done}\n"
            f"<:s_white2:1382052523166142486> **Earned:** A$ {payout:,} <:athenacoin:1503804322280902767>\n"
            f"<:s_white2:1382052523166142486> **XP Gained:** +{gained_xp} XP (Car Bonus included!)\n\n"
        )

        if promoted:
            new_title = path_data["levels"][new_level]["title"]
            desc += f"<a:wt_toroexclaim:1480581004317036624> **PROMOTION!** You have climbed the ladder and are now a **{new_title}**! Your base salary has increased, continue working hard."

        embed.description = desc
        embed.set_thumbnail(url=interaction.user.display_avatar.url)
        await interaction.followup.send(embed=embed)
    
async def setup(bot):
    await bot.add_cog(Careers(bot))