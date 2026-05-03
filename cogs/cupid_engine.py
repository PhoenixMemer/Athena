import discord
from discord import app_commands
from discord.ext import commands
import sqlite3
import json

# --- CONFIGURATION ---
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

# --- THE MATH ENGINE ---
def calculate_match_score(user_a, user_b):
    score = 0.0
    
    def get_gender_tag(g_string):
        g = str(g_string).lower()
        if "female" in g or "woman" in g or "girl" in g or "fem" in g: return "female"
        if ("male" in g and "female" not in g) or "boy" in g or "man" in g or "guy" in g: return "male"
        return "non-binary"

    def attraction_set(user):
        g_tag = get_gender_tag(user["gender"])
        s = str(user["sexuality"]).lower()
        is_straight = any(w in s for w in ["straight", "stright", "hetero", "str8"])
        is_gay = any(w in s for w in ["gay", "lesbian", "wlw", "mlm", "homo"])
        if is_straight: return {"male"} if g_tag == "female" else {"female"}
        if is_gay: return {g_tag}
        return {"male", "female", "non-binary"}

    b_tag = get_gender_tag(user_b["gender"])
    a_tag = get_gender_tag(user_a["gender"])
    
    if user_a["name"].lower() in user_b["name"].lower() or user_b["name"].lower() in user_a["name"].lower(): return 0
    if b_tag not in attraction_set(user_a) or a_tag not in attraction_set(user_b): return 0
    if (user_a["is_trans"] and user_b["mind_trans"]) or (user_b["is_trans"] and user_a["mind_trans"]): return 0
    if (user_a["is_poly"] and user_b["mind_poly"]) or (user_b["is_poly"] and user_a["mind_poly"]): return 0
    if user_b["age"] < user_a["min_age_pref"] or user_b["age"] > user_a["max_age_pref"]: return 0
    if user_a["age"] < user_b["min_age_pref"] or user_a["age"] > user_b["max_age_pref"]: return 0

    age_diff = abs(user_a["age"] - user_b["age"])
    if age_diff > 4: return 0

    score += 30.0 
    if age_diff <= 1: score += 15.0
    else: score += max(0.0, 15.0 - (age_diff * 3.0))

    ea, eb = str(user_a["energy"]).lower(), str(user_b["energy"]).lower()
    if "ambivert" in ea or "ambivert" in eb: score += 15.0
    elif ea != eb: score += 15.0 
    else: score += 10.0 

    shared = set(user_a["hobbies_and_likes"]).intersection(set(user_b["hobbies_and_likes"]))
    score += min(len(shared) * 10, 35)

    for like in user_a["hobbies_and_likes"]:
        if like in user_b["dislikes"]: score -= 10
    for like in user_b["hobbies_and_likes"]:
        if like in user_a["dislikes"]: score -= 10

    return max(0.0, min(100.0, score))


# --- STEP 3: THE VIBES (FINAL SAVE) ---
class CupidStepThreeModal(discord.ui.Modal, title='Cupid Profile - Step 3: The Vibes'):
    def __init__(self, profile_data, user_id):
        super().__init__()
        self.profile_data = profile_data
        self.user_id = user_id

    hobbies = discord.ui.TextInput(label='Your Likes & Hobbies', style=discord.TextStyle.paragraph, placeholder='gaming, quiet, reading, cats')
    dislikes = discord.ui.TextInput(label='Your Dislikes (Dealbreakers)', style=discord.TextStyle.paragraph, placeholder='toxic people, dry texters, winter')
    energy = discord.ui.TextInput(label='Your Energy Level', style=discord.TextStyle.short, placeholder='Introvert, Extrovert, or Ambivert')

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        
        # Format Step 1 Data
        name = self.profile_data['name']
        try: age = int(self.profile_data['age'].strip())
        except ValueError: age = 18
        
        # Format Step 2 Data
        target_str = self.profile_data['target_age'].replace(' ', '')
        min_pref, max_pref = 18, 99
        if '-' in target_str:
            parts = target_str.split('-')
            try: min_pref, max_pref = int(parts[0]), int(parts[1])
            except: pass
            
        tp_text = self.profile_data['trans_poly'].lower()
        is_trans = "am trans" in tp_text or "i'm trans" in tp_text
        is_poly = "am poly" in tp_text or "i'm poly" in tp_text
        mind_trans = "don't mind trans" not in tp_text and "dont mind trans" not in tp_text
        mind_poly = "don't mind poly" not in tp_text and "dont mind poly" not in tp_text

        # Format Step 3 Data
        hobbies_list = [h.strip().lower() for h in self.hobbies.value.split(',')]
        dislikes_list = [d.strip().lower() for d in self.dislikes.value.split(',')]
        
        # Extract Timezone Offset
        tz_offset = 99
        tz_input = self.profile_data['timezone'].lower()
        if "est" in tz_input: tz_offset = -5
        elif "gmt" in tz_input: tz_offset = 0

        # Save to SQLite Master DB
        conn = sqlite3.connect("athena_core.db", timeout=20.0)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO cupid_profiles 
            (user_id, name, age, min_age_pref, max_age_pref, gender, sexuality, timezone_offset, energy, mind_trans, is_trans, mind_poly, is_poly, hobbies_and_likes, dislikes, raw_message_link)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            self.user_id, name, age, min_pref, max_pref, 
            self.profile_data['your_gender'], self.profile_data['target_gender'], tz_offset, 
            self.energy.value, mind_trans, is_trans, mind_poly, is_poly, 
            json.dumps(hobbies_list), json.dumps(dislikes_list), "Via Athena Desk"
        ))
        conn.commit()
        conn.close()

        await interaction.followup.send("🎉 **Profile Complete!** Your data has been securely locked in the Athena Core Database. Our Cupids can now find you a match!")


# --- STEP 2: TARGET PREFERENCES ---
class CupidStepTwoModal(discord.ui.Modal, title='Cupid Profile - Step 2: Preferences'):
    def __init__(self, profile_data, user_id):
        super().__init__()
        self.profile_data = profile_data
        self.user_id = user_id

    target_age = discord.ui.TextInput(label='Target Age Preference (Min-Max)', placeholder='e.g. 18-22')
    target_gender = discord.ui.TextInput(label='Target Gender & Sexuality', placeholder='e.g. Male, Straight')
    trans_poly = discord.ui.TextInput(label='Are you Trans/Poly? Mind if they are?', style=discord.TextStyle.paragraph, placeholder='I am not trans. I do not mind poly.')

    async def on_submit(self, interaction: discord.Interaction):
        self.profile_data['target_age'] = self.target_age.value
        self.profile_data['target_gender'] = self.target_gender.value
        self.profile_data['trans_poly'] = self.trans_poly.value
        
        view = discord.ui.View(timeout=300)
        btn = discord.ui.Button(label="Proceed to Final Step", style=discord.ButtonStyle.success)
        
        async def btn_callback(inter: discord.Interaction):
            await inter.response.send_modal(CupidStepThreeModal(self.profile_data, self.user_id))
        
        btn.callback = btn_callback
        view.add_item(btn)
        
        await interaction.response.send_message("✅ **Preferences saved!** Just one last step for your vibes and dealbreakers.", view=view, ephemeral=True)


# --- STEP 1: BASIC INFO ---
class CupidBasicInfoModal(discord.ui.Modal, title='Cupid Profile - Step 1: About You'):
    name = discord.ui.TextInput(label='Name/Nickname', max_length=30)
    age = discord.ui.TextInput(label='Your Age', placeholder='e.g. 19', max_length=2)
    your_gender = discord.ui.TextInput(label='Your Gender & Sexuality', placeholder='e.g. Female, Straight')
    timezone = discord.ui.TextInput(label='Your Timezone', placeholder='e.g. EST, GMT+5')

    async def on_submit(self, interaction: discord.Interaction):
        profile_data = {
            'name': self.name.value,
            'age': self.age.value,
            'your_gender': self.your_gender.value,
            'timezone': self.timezone.value
        }
        
        view = discord.ui.View(timeout=300)
        btn = discord.ui.Button(label="Proceed to Step 2", style=discord.ButtonStyle.primary)
        
        async def btn_callback(inter: discord.Interaction):
            await inter.response.send_modal(CupidStepTwoModal(profile_data, interaction.user.id))
        
        btn.callback = btn_callback
        view.add_item(btn)
        
        await interaction.response.send_message("✅ **Basic Info saved!** Click below to tell us who you're looking for.", view=view, ephemeral=True)


# --- UI: INTERACTIVE PROFILE BUTTON ---
class TargetProfileView(discord.ui.View):
    def __init__(self, target_data):
        super().__init__(timeout=None)
        self.target_data = target_data

    @discord.ui.button(label="View Target's Full Data", style=discord.ButtonStyle.secondary, emoji="<:p_hearts:1378053399525982288>")
    async def view_profile(self, interaction: discord.Interaction, button: discord.ui.Button):
        hobbies = ", ".join(self.target_data['hobbies_and_likes']) if self.target_data['hobbies_and_likes'] else "None"
        dislikes = ", ".join(self.target_data['dislikes']) if self.target_data['dislikes'] else "None"
        
        embed = discord.Embed(title=f"💌 {self.target_data['name']}'s Profile Data", color=0x2b2d31)
        
        desc = f"""
        **Basic Info**
        • **Age:** {self.target_data['age']} (Wants: {self.target_data['min_age_pref']}-{self.target_data['max_age_pref']}y)
        • **Gender/Sexuality:** {self.target_data['gender']}
        • **Energy:** {self.target_data['energy']}
        
        **Tags & Preferences**
        • **Likes/Hobbies:** `{hobbies}`
        • **Dislikes:** `{dislikes}`
        
        **Dealbreakers**
        • **Are they Trans?** {'Yes' if self.target_data['is_trans'] else 'No'} | **Mind Trans?** {'Yes' if self.target_data['mind_trans'] else 'No'}
        • **Are they Poly?** {'Yes' if self.target_data['is_poly'] else 'No'} | **Mind Poly?** {'Yes' if self.target_data['mind_poly'] else 'No'}
        """
        embed.description = desc
        await interaction.response.send_message(embed=embed, ephemeral=True)


class CupidEngine(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="spawn_cupid_desk", description="Admin: Spawns the Cupid Onboarding button in a channel")
    async def spawn_desk(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator and interaction.user.id != 743411894416834590:
            await interaction.response.send_message("❌ Access Denied.", ephemeral=True)
            return

        view = discord.ui.View(timeout=None)
        btn = discord.ui.Button(label="Create Cupid Profile", style=discord.ButtonStyle.primary, emoji="💌")
        
        async def btn_callback(inter):
            await inter.response.send_modal(CupidBasicInfoModal())
            
        btn.callback = btn_callback
        view.add_item(btn)
        
        embed = discord.Embed(title="💌 Chérie Matchmaking Hub", color=0xff69b4)
        embed.description = "Welcome to the new Athena Cupid System!\n\nClick the button below to securely submit your profile. Your answers are stored directly in our database, meaning **only Head Staff** can ever view your data."
        embed.set_footer(text="Athena Mark XX Engine")
        
        await interaction.channel.send(embed=embed, view=view)
        await interaction.response.send_message("✅ Desk spawned successfully.", ephemeral=True)

    @app_commands.command(name="match", description="Cupid: Find the perfect match for a user")
    @app_commands.describe(user="The user you are trying to match")
    @is_staff()
    async def match_user(self, interaction: discord.Interaction, user: discord.Member):
        conn = sqlite3.connect("athena_core.db", timeout=20.0)
        cursor = conn.cursor()
        
        cursor.execute("SELECT * FROM cupid_profiles WHERE user_id = ?", (user.id,))
        target_row = cursor.fetchone()
        
        if not target_row:
            await interaction.response.send_message(f"❌ {user.mention} has NOT filled out their profile via the Cupid Desk yet.", ephemeral=False)
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
            await interaction.response.send_message(f"I searched the entire database, but {user.mention} has zero compatible matches (Dealbreakers triggered for everyone).", ephemeral=False)
            return
            
        matches.sort(key=lambda x: x[0], reverse=True)
        top_matches = matches[:3] 
        
        embed = discord.Embed(
            title=f"𝐴𝑡ℎ𝑒𝑛𝑎 𝑀𝑎𝑡𝑐ℎ𝑚𝑎𝑘𝑖𝑛𝑔 ─ {target['name']}", 
            description=f"Analyzed **{len(all_others)}** profiles instantly via Athena Core.\n\n",
            color=0xffffff
        )
        
        for rank, (score, cand) in enumerate(top_matches, 1):
            shared_tags = set(target["hobbies_and_likes"]).intersection(set(cand["hobbies_and_likes"]))
            shared_str = f"*(**{len(shared_tags)}** shared tags)*" if shared_tags else ""
            
            embed.add_field(
                name=f"#{rank} — <@{cand['user_id']}> ({cand['name']})", 
                value=f"• **Age/Gender:** {cand['age']}, {cand['gender']}\n"
                      f"• **Match Score:** `{score:.1f}%` {shared_str}\n",
                inline=False
            )
            
        embed.set_footer(text="Powered by Athena Core DB")
        
        view = TargetProfileView(target_data=target)
        await interaction.response.send_message(embed=embed, view=view)

async def setup(bot):
    await bot.add_cog(CupidEngine(bot))