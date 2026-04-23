# cogs/matchmaking.py
import discord
from discord import app_commands
from discord.ext import commands
import sqlite3
import re
import json
import asyncio
import logging
import os
from dotenv import load_dotenv

load_dotenv()
from google import genai
from google.genai import types

logger = logging.getLogger(__name__)

# --- CONFIGURATION ---
MATCHMAKING_CHANNEL_IDS = [1273939243600842795, 1273939292749561866, 1273945454853492746]
HEAD_STAFF_ROLES = [1375079530183790744, 1218201074448732270, 123456789012345678, 1218201777996828752, 1415748019441111070, 1229721606251745300, 1469797367153819678]

def is_staff():
    """Check if the user has a staff role to run Cupid commands."""
    async def predicate(interaction: discord.Interaction):
        if interaction.user.guild_permissions.administrator: return True
        user_role_ids = [role.id for role in interaction.user.roles]
        if any(role_id in HEAD_STAFF_ROLES for role_id in user_role_ids): return True
        await interaction.response.send_message("❌ Access Denied. Cupid/Staff roles required.", ephemeral=True)
        return False
    return app_commands.check(predicate)

# --- DATABASE SETUP ---
def setup_db():
    conn = sqlite3.connect("cupid.db", timeout=20.0)
    cursor = conn.cursor()
    # UPGRADED SCHEMA: We replaced max_age_gap with strict min/max boundaries
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS cupid_profiles (
            user_id INTEGER PRIMARY KEY,
            name TEXT,
            age INTEGER,
            min_age_pref INTEGER,
            max_age_pref INTEGER,
            gender TEXT,
            sexuality TEXT,
            timezone_offset INTEGER,
            energy TEXT,
            mind_trans BOOLEAN,
            is_trans BOOLEAN,
            mind_poly BOOLEAN,
            is_poly BOOLEAN,
            hobbies_and_likes TEXT, 
            dislikes TEXT,
            raw_message_link TEXT
        )
    ''')
    conn.commit()
    conn.close()

# --- PIPELINE STEP 1: INDESTRUCTIBLE REGEX SLICER ---
def extract_raw_profile(raw_text):
    profile = {}
    clean_text = re.sub(r'[\u200B-\u200D\uFEFF]', '', raw_text)

    def extract_field(pattern, text, default=""):
        match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
        if match:
            content = match.group(1).split('╰')[0].split('𐔌')[0].split('‿')[0].strip()
            return content if content else default
        return default

    profile["name"] = extract_field(r"Name:\s*(.*)", clean_text)
    
    age_str = extract_field(r"Age:\s*(\d+)", clean_text)
    profile["age"] = int(age_str) if age_str.isdigit() else 18
    
    # Grab the target age string and send it to Gemini so it can figure out the strict boundaries
    them_section = re.split(r"(?i)𝓣𝒉𝒆𝒎", clean_text)
    if len(them_section) > 1:
        profile["them_age_str"] = extract_field(r"Age:\s*(.*)", them_section[1])
    else:
        profile["them_age_str"] = ""

    profile["gender"] = extract_field(r"Gender:\s*(.*)", clean_text, "Unknown")
    profile["sexuality"] = extract_field(r"Sexuality:\s*(.*)", clean_text, "Unknown")
    profile["timezone"] = extract_field(r"Time zone:\s*(.*)", clean_text)
    
    profile["likes"] = extract_field(r"(?<!dis)likes:\s*(.*)", clean_text)
    profile["dislikes"] = extract_field(r"dislikes:\s*(.*)", clean_text)
    profile["hobbies"] = extract_field(r"hobbies:\s*(.*)", clean_text)
    profile["traits"] = extract_field(r"traits:\s*(.*)", clean_text)
    
    profile["mind_trans"] = extract_field(r"mind them being trans\?[^\w]*(.*)", clean_text, "Yes")
    profile["mind_poly"] = extract_field(r"mind them being poly\?[^\w]*(.*)", clean_text, "Yes")
    profile["note"] = extract_field(r"Note\s*!\s*୧[^\w]*(.*)", clean_text)

    return profile

# --- PIPELINE STEP 2: GEMINI TRANSLATOR ---
keys_string = os.getenv("GEMINI_API_KEYS", "")
if keys_string:
    API_KEYS = [key.strip() for key in keys_string.split(",")]
else:
    API_KEYS = []
    logger.error("CRITICAL: GEMINI_API_KEYS not found in .env file!")

current_key_idx = 0

def get_next_key():
    global current_key_idx
    if not API_KEYS:
        raise ValueError("Cannot rotate keys: API_KEYS empty.")
    key = API_KEYS[current_key_idx]
    current_key_idx = (current_key_idx + 1) % len(API_KEYS)
    return key

async def translate_with_gemini(raw_dict, retries=3):
    # We will try up to 3 times before giving up
    for attempt in range(retries):
        client = genai.Client(api_key=get_next_key())
        
        prompt = f"""
        You are a Matchmaking Data Processor. Convert the following natural language profile into strict JSON.
        
        RAW DATA:
        Target Age Pref: {raw_dict['them_age_str']}
        Timezone String: {raw_dict['timezone']}
        Traits: {raw_dict['traits']}
        Likes: {raw_dict['likes']}
        Hobbies: {raw_dict['hobbies']}
        Dislikes: {raw_dict['dislikes']}
        Answer to 'Mind Trans?': {raw_dict['mind_trans']}
        Answer to 'Mind Poly?': {raw_dict['mind_poly']}
        User Notes: {raw_dict['note']}

        RULES FOR JSON OUTPUT:
        1. "timezone_offset": Convert to UTC integer. USE THIS REFERENCE CHEAT SHEET: EST/CDT=-5, EDT=-4, CST/MDT=-6, MST/PDT=-7, PST/AKDT=-8, GMT/UTC/WET=0, BST/CET/WEST=1, CEST/EET/SAST/CAT=2, EEST/MSK/AST/EAT/IDT=3, GST=4, PKT/IST=5, BST(Bangladesh)=6, WIB=7, WITA/SGT/HKT/CST(China)/AWST=8, WIT/JST/KST=9, AEST=10, AEDT=11, NZST=12. IF UNKNOWN, OUTPUT 99.
        2. "min_age_pref": Integer. Extract the lowest age they want from Target Age Pref. (If they say "18+", output 18).
        3. "max_age_pref": Integer. Extract the highest age they want from Target Age Pref. (If they say "18+", output 99).
        4. "energy": STRICTLY output "Introvert", "Extrovert", or "Ambivert".
        5. "mind_trans": boolean (true if they mind, false if they don't).
        6. "is_trans": boolean (Infer from Traits/Notes. true ONLY if they state they are trans).
        7. "mind_poly": boolean (true if they mind, false if they don't).
        8. "is_poly": boolean (Infer from Traits/Notes. true ONLY if they state they are poly).
        9. "hobbies_and_likes": Array of lowercase 1-word string tags.
        10. "dislikes": Array of lowercase 1-word string tags.
        
        OUTPUT ONLY VALID JSON. No markdown blocks.
        """
        
        try:
            response = await asyncio.to_thread(
                client.models.generate_content,
                model='gemini-2.5-flash',
                contents=prompt,
                config=types.GenerateContentConfig(response_mime_type="application/json")
            )
            
            raw_text = response.text.strip()
            start_idx = raw_text.find('{')
            end_idx = raw_text.rfind('}')
            
            if start_idx != -1 and end_idx != -1:
                return json.loads(raw_text[start_idx:end_idx + 1])
            return None
            
        except Exception as e:
            error_msg = str(e)
            # If we hit the rate limit, we pause and retry instead of crashing!
            if "429" in error_msg or "RESOURCE_EXHAUSTED" in error_msg:
                wait_time = 20 * (attempt + 1) # Waits 15s, then 30s, then 45s
                logger.warning(f"⚠️ Gemini Rate Limit Hit! Athena is resting for {wait_time} seconds before trying again...")
                await asyncio.sleep(wait_time)
            else:
                logger.error(f"Gemini API Error: {e}")
                return None
                
    # If it fails 3 times in a row, we finally give up
    logger.error("❌ Failed to process profile after 3 rate limit retries.")
    return None

# --- PIPELINE STEP 3: DEEPSEEK MATH ENGINE ---
# --- PIPELINE STEP 3: DEEPSEEK MATH ENGINE ---
def calculate_match_score(user_a, user_b):
    score = 0.0
    
    # Standardize the messy gender strings into safe tags
    def get_gender_tag(g_string):
        g = g_string.lower()
        if "female" in g or "woman" in g or "girl" in g or "fem" in g: return "female"
        # Must check that 'female' is NOT in the string so we don't trigger the substring trap!
        if ("male" in g and "female" not in g) or "boy" in g or "man" in g or "guy" in g: return "male"
        return "non-binary"

    def attraction_set(user):
        g_tag = get_gender_tag(user["gender"])
        s = user["sexuality"].lower()

        # Vocabulary Net: Catching typos and synonyms
        is_straight = any(w in s for w in ["straight", "stright", "hetero", "str8"])
        is_gay = any(w in s for w in ["gay", "lesbian", "wlw", "mlm", "homo"])

        if is_straight: return {"male"} if g_tag == "female" else {"female"}
        if is_gay: return {g_tag}

        # Fallback for Bi/Pan/Omni/Unknown
        return {"male", "female", "non-binary"}

    # 1. STRICT DEALBREAKERS
    b_tag = get_gender_tag(user_b["gender"])
    a_tag = get_gender_tag(user_a["gender"])
    
    # Anti-Alt Check: If the names are identical (or contain each other), kill the match
    if user_a["name"].lower() in user_b["name"].lower() or user_b["name"].lower() in user_a["name"].lower():
        return 0

    if b_tag not in attraction_set(user_a) or a_tag not in attraction_set(user_b):
        return 0
        
        
    if (user_a["is_trans"] and user_b["mind_trans"]) or (user_b["is_trans"] and user_a["mind_trans"]): return 0
    if (user_a["is_poly"] and user_b["mind_poly"]) or (user_b["is_poly"] and user_a["mind_poly"]): return 0

    # Strict Asymmetric Age Preferences
    if user_b["age"] < user_a["min_age_pref"] or user_b["age"] > user_a["max_age_pref"]: return 0
    if user_a["age"] < user_b["min_age_pref"] or user_a["age"] > user_b["max_age_pref"]: return 0

    # Server Policy: Hard 4-year gap cap
    age_diff = abs(user_a["age"] - user_b["age"])
    if age_diff > 4: return 0

    # Strict Timezone Dealbreaker
    tz_a, tz_b = user_a["timezone_offset"], user_b["timezone_offset"]
    if tz_a != 99 and tz_b != 99:
        tz_diff = abs(tz_a - tz_b)
        if tz_diff > 5: return 0  

    # 2. SCORING
    score += 30.0 # Passed dealbreakers
    
    # Age
    if age_diff <= 1: score += 15.0
    else: score += max(0.0, 15.0 - (age_diff * 3.0))

    # Timezone Scoring
    if tz_a == 99 or tz_b == 99:
        score += 7.5 
    else:
        score += max(0.0, 15.0 - tz_diff * 3.0) 

    # Energy
    ea, eb = user_a["energy"], user_b["energy"]
    if ea == "Ambivert" or eb == "Ambivert": score += 15.0
    elif ea != eb: score += 15.0 
    else: score += 10.0 

    # Hobbies & Dislikes
    shared = set(user_a["hobbies_and_likes"]).intersection(set(user_b["hobbies_and_likes"]))
    score += min(len(shared) * 10, 35)

    for like in user_a["hobbies_and_likes"]:
        if like in user_b["dislikes"]: score -= 10
    for like in user_b["hobbies_and_likes"]:
        if like in user_a["dislikes"]: score -= 10

    return max(0.0, min(100.0, score))


# --- UI: INTERACTIVE PROFILE BUTTON ---
class TargetProfileView(discord.ui.View):
    def __init__(self, target_data):
        super().__init__(timeout=None)
        self.target_data = target_data

    @discord.ui.button(label="View Target's Profile", style=discord.ButtonStyle.secondary, emoji="<:r_megapreg:1480286043323502796>")
    async def view_profile(self, interaction: discord.Interaction, button: discord.ui.Button):
        hobbies = ", ".join(self.target_data['hobbies_and_likes']) if self.target_data['hobbies_and_likes'] else "None"
        dislikes = ", ".join(self.target_data['dislikes']) if self.target_data['dislikes'] else "None"
        heart = "<:p_hearts:1378053399525982288>"
        
        embed = discord.Embed(title=f"<:r_megapreg:1480286043323502796> {self.target_data['name']}'s Parsed Profile", color=0x2b2d31)
        
        desc = f"""
        **Basic Info**
        {heart} **Age:** {self.target_data['age']} (Wants: {self.target_data['min_age_pref']}-{self.target_data['max_age_pref']}y)
        {heart} **Gender:** {self.target_data['gender']}
        {heart} **Sexuality:** {self.target_data['sexuality']}
        {heart} **Energy:** {self.target_data['energy']}
        
        **Tags & Preferences**
        {heart} **Likes/Hobbies:** `{hobbies}`
        {heart} **Dislikes:** `{dislikes}`
        
        **Dealbreakers (For Them)**
        {heart} **Are they Trans?** {'Yes' if self.target_data['is_trans'] else 'No'} | **Mind Trans?** {'Yes' if self.target_data['mind_trans'] else 'No'}
        {heart} **Are they Poly?** {'Yes' if self.target_data['is_poly'] else 'No'} | **Mind Poly?** {'Yes' if self.target_data['mind_poly'] else 'No'}
        
        [🔗 Jump to Original Message]({self.target_data['raw_message_link']})
        """
        embed.description = desc
        await interaction.response.send_message(embed=embed, ephemeral=True)

# --- THE COG ---
class MatchmakingEngine(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        setup_db()

    async def process_and_save_profile(self, user: discord.User, raw_text: str, message_link: str):
        basic_data = extract_raw_profile(raw_text)
        if not basic_data.get("name"): return False 
        
        ai_data = await translate_with_gemini(basic_data)
        if not ai_data: return False

        def safe_bool(val, default=False):
            if isinstance(val, bool): return val
            if isinstance(val, str): return val.lower() in ['true', 'yes', 'y', '1']
            return default

        mind_trans_val = safe_bool(ai_data.get("mind_trans"), True)
        is_trans_val = safe_bool(ai_data.get("is_trans"), False)
        mind_poly_val = safe_bool(ai_data.get("mind_poly"), True)
        is_poly_val = safe_bool(ai_data.get("is_poly"), False)

        raw_hobbies = ai_data.get("hobbies_and_likes")
        if not raw_hobbies:
            raw_hobbies = (ai_data.get("hobbies") or []) + (ai_data.get("likes") or [])
        if not isinstance(raw_hobbies, list): raw_hobbies = []
        
        raw_dislikes = ai_data.get("dislikes")
        if not isinstance(raw_dislikes, list): raw_dislikes = []

        conn = sqlite3.connect("cupid.db", timeout=20.0)
        cursor = conn.cursor()
        
        hobbies_str = json.dumps(raw_hobbies)
        dislikes_str = json.dumps(raw_dislikes)
        
        cursor.execute('''
            INSERT OR REPLACE INTO cupid_profiles 
            (user_id, name, age, min_age_pref, max_age_pref, gender, sexuality, timezone_offset, energy, mind_trans, is_trans, mind_poly, is_poly, hobbies_and_likes, dislikes, raw_message_link)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            user.id, basic_data["name"], basic_data["age"], ai_data.get("min_age_pref", 13), ai_data.get("max_age_pref", 99),
            basic_data["gender"], basic_data["sexuality"], ai_data.get("timezone_offset", 99),
            ai_data.get("energy", "Ambivert"), mind_trans_val, is_trans_val, mind_poly_val, is_poly_val, 
            hobbies_str, dislikes_str, message_link
        ))
        conn.commit()
        conn.close()
        return True

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or message.channel.id not in MATCHMAKING_CHANNEL_IDS:
            return
            
        if "୨୧◞" in message.content and "Name:" in message.content:
            # 1. Instantly react with an hourglass so the user knows Athena is reading it
            await message.add_reaction("⏳")
            
            success = await self.process_and_save_profile(message.author, message.content, message.jump_url)
            
            # 2. Swap the reaction based on success/fail
            try:
                await message.remove_reaction("⏳", self.bot.user)
            except discord.Forbidden:
                pass # Just in case she lacks permissions to remove reactions
                
            if success:
                await message.add_reaction("✅")
            else:
                await message.add_reaction("❌")

    @app_commands.command(name="sync_backlog", description="Cupid: Process old templates in this channel")
    @is_staff()
    async def sync_backlog(self, interaction: discord.Interaction, limit: int = 100):
        await interaction.response.send_message(f"🔄 Scanning the last {limit} messages... (Please wait, this safely rotates APIs)", ephemeral=False)
        
        processed = 0
        async for msg in interaction.channel.history(limit=limit):
            if "୨୧◞" in msg.content and "Name:" in msg.content:
                conn = sqlite3.connect("cupid.db", timeout=20.0)
                c = conn.cursor()
                c.execute("SELECT user_id FROM cupid_profiles WHERE user_id = ?", (msg.author.id,))
                exists = c.fetchone()
                conn.close()
                
                if not exists:
                    success = await self.process_and_save_profile(msg.author, msg.content, msg.jump_url)
                    if success: processed += 1
                    await asyncio.sleep(8) 
                    
        await interaction.channel.send(f"✅ Backlog sync complete! Added **{processed}** perfect profiles.")

    @app_commands.command(name="match", description="Cupid: Find the perfect match for a user")
    @app_commands.describe(user="The user you are trying to match")
    @is_staff()
    async def match_user(self, interaction: discord.Interaction, user: discord.Member):
        conn = sqlite3.connect("cupid.db", timeout=20.0)
        cursor = conn.cursor()
        
        cursor.execute("SELECT * FROM cupid_profiles WHERE user_id = ?", (user.id,))
        target_row = cursor.fetchone()
        
        if not target_row:
            await interaction.response.send_message(f"❌ {user.mention}'s template has NOT been registered yet.", ephemeral=False)
            conn.close()
            return
            
        cols = [column[0] for column in cursor.description]
        target = dict(zip(cols, target_row))
        target["hobbies_and_likes"] = json.loads(target["hobbies_and_likes"])
        target["dislikes"] = json.loads(target["dislikes"])
        
        cursor.execute("SELECT * FROM cupid_profiles WHERE user_id != ?", (user.id,))
        all_others = cursor.fetchall()
        conn.close()
        
        matches = []
        for row in all_others:
            candidate = dict(zip(cols, row))
            candidate["hobbies_and_likes"] = json.loads(candidate["hobbies_and_likes"])
            candidate["dislikes"] = json.loads(candidate["dislikes"])
            
            score = calculate_match_score(target, candidate)
            if score > 0: 
                matches.append((score, candidate))
                
        if not matches:
            await interaction.response.send_message(f"I searched the entire database, but {user.mention} has zero compatible matches (Dealbreakers triggered for everyone). Bro's dying alone 🤣✌️", ephemeral=False)
            return
            
        matches.sort(key=lambda x: x[0], reverse=True)
        top_matches = matches[:3] 
        
        white_star = "<:s_white2:1382052523166142486>"
        heart = "<:p_hearts:1378053399525982288>"
        
        embed = discord.Embed(
            title=f"𝐴𝑡ℎ𝑒𝑛𝑎 𝑀𝑎𝑡𝑐ℎ𝑚𝑎𝑘𝑖𝑛𝑔 ─ {target['name']}", 
            description=f"Analyzed **{len(all_others)}** profiles instantly.\n\n",
            color=0xffffff
        )
        
        for rank, (score, cand) in enumerate(top_matches, 1):
            shared_tags = set(target["hobbies_and_likes"]).intersection(set(cand["hobbies_and_likes"]))
            shared_str = f"*(**{len(shared_tags)}** shared tags)*" if shared_tags else ""
            
            embed.add_field(
                name=f"{white_star} #{rank} — {cand['name']}", 
                value=f"{heart} **Age/Gender:** {cand['age']}, {cand['gender']}\n"
                      f"{heart} **Match Score:** `{score:.1f}%` {shared_str}\n"
                      f"{heart} **Profile:** [🔗 View Original Template]({cand['raw_message_link']})", 
                inline=False
            )
            
        embed.set_footer(text="Powered by Palantir")
        
        view = TargetProfileView(target_data=target)
        await interaction.response.send_message(embed=embed, view=view)

async def setup(bot):
    await bot.add_cog(MatchmakingEngine(bot))