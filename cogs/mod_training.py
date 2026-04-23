# cogs/mod_training.py
import discord
from discord import app_commands
from discord.ext import commands
import sqlite3
import json
import random
import time
import logging

logger = logging.getLogger(__name__)

# --- CONFIGURATION ---
# Replace these with the actual Discord Role IDs of your Head Staff / Management
HEAD_STAFF_ROLES = [1375079530183790744, 123456789012345678, 1218201777996828752, 1415748019441111070, 1229721606251745300, 1469797367153819678] 

# --- COMMENDATION PRESETS ---
COMMENDATION_MESSAGES = [
    "🌟 **Stellar work!** Your recent efforts haven't gone unnoticed by the Head Staff. Keep it up!",
    "🌟 **Massive thank you!** We've officially logged a commendation on your profile for your dedication.",
    "🌟 **Outstanding job!** Your handling of recent situations has been exemplary. You've earned a commendation.",
    "🌟 **Official Commendation:** Head Staff has recognized your hard work. Thank you for protecting the vibe!",
    "🌟 **You're crushing it!** A new commendation has been added to your permanent record. We appreciate you."
]

def is_head_staff():
    """Custom check to see if the user has a Head Staff role OR is an Admin."""
    async def predicate(interaction: discord.Interaction):
        # Always let Server Admins through
        if interaction.user.guild_permissions.administrator:
            return True
            
        # Check if they have one of the allowed roles
        user_role_ids = [role.id for role in interaction.user.roles]
        if any(role_id in HEAD_STAFF_ROLES for role_id in user_role_ids):
            return True
            
        await interaction.response.send_message("**Access Denied:** You do not have the required Head Staff roles to use this command.", ephemeral=True)
        return False
    return app_commands.check(predicate)
# ---------------------

# ---------------- DATABASE SETUP ----------------
def setup_db():
    conn = sqlite3.connect("modsVSC.db")
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS mod_profiles (
            user_id INTEGER PRIMARY KEY,
            rank TEXT DEFAULT 'Trial Mod',
            loa BOOLEAN DEFAULT 0,
            training_score INTEGER DEFAULT 0,
            training_completed BOOLEAN DEFAULT 0,
            warnings INTEGER DEFAULT 0,
            commendations INTEGER DEFAULT 0
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS mod_strikes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            reason TEXT,
            timestamp INTEGER
        )
    ''')
    
    # Safely upgrade existing databases
    try:
        cursor.execute("ALTER TABLE mod_profiles ADD COLUMN commendations INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass # Column already exists
        
    conn.commit()
    conn.close()

def load_curriculum():
    try:
        with open("training_curriculum.json", "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Failed to load curriculum: {e}")
        return {"info_pages": [], "quiz_sets": []}

# ---------------- UI: MOD INFO VIEW ----------------
class ModInfoView(discord.ui.View):
    def __init__(self, user_id: int):
        super().__init__(timeout=None)
        self.user_id = user_id

    @discord.ui.button(label="View Strike History", style=discord.ButtonStyle.danger, custom_id="view_strike_history", emoji="<a:wt_toronerd:1480580983593111602>")
    async def view_history(self, interaction: discord.Interaction, button: discord.ui.Button):
        conn = sqlite3.connect("modsVSC.db")
        cursor = conn.cursor()
        cursor.execute("SELECT reason, timestamp FROM mod_strikes WHERE user_id = ? ORDER BY timestamp DESC", (self.user_id,))
        strikes = cursor.fetchall()
        conn.close()

        if not strikes:
            await interaction.response.send_message("This moderator has no strikes in their history.", ephemeral=True)
            return

        embed = discord.Embed(title="𝑂𝑓𝑓𝑖𝑐𝑖𝑎𝑙 𝑆𝑡𝑟𝑖𝑘𝑒 𝐻𝑖𝑠𝑡𝑜𝑟𝑦", color=0xffffff)
        history_text = ""
        for idx, (reason, ts) in enumerate(strikes, 1):
            history_text += f"**{idx}.** {reason} \n*(Issued: <t:{ts}:D>)*\n\n"
            
        embed.description = history_text
        await interaction.response.send_message(embed=embed, ephemeral=True)

# ---------------- UI: QUIZ VIEW ----------------
class QuizView(discord.ui.View):
    def __init__(self, user_id: int, questions: list):
        super().__init__(timeout=None) 
        self.user_id = user_id
        self.questions = questions
        self.current_q = 0
        self.score = 0
        self.wrong_answers = [] 
        self.build_buttons()

    def build_buttons(self):
        self.clear_items()
        if self.current_q >= len(self.questions):
            return 
            
        options = self.questions[self.current_q]["options"]
        labels = ["A", "B", "C", "D", "E"]
        
        for i, opt in enumerate(options):
            btn = discord.ui.Button(label=labels[i], style=discord.ButtonStyle.primary, custom_id=f"ans_{i}")
            btn.callback = self.create_callback(labels[i], opt)
            self.add_item(btn)

    def create_callback(self, chosen_label: str, full_option_text: str):
        async def button_callback(interaction: discord.Interaction):
            # Tell Discord to wait while the laptop processes the answer
            await interaction.response.defer()
            
            correct_label = self.questions[self.current_q]["correct_answer"]
            
            if chosen_label == correct_label:
                self.score += 1
            else:
                self.wrong_answers.append({
                    "question": self.questions[self.current_q]["question"],
                    "their_answer": chosen_label,
                    "correct_answer": correct_label
                })
                
            self.current_q += 1
            
            if self.current_q >= len(self.questions):
                await self.finish_quiz(interaction)
            else:
                self.build_buttons()
                # Edit the original message directly since we already deferred
                await interaction.message.edit(embed=self.get_embed(), view=self)
        return button_callback

    def get_embed(self):
        q_data = self.questions[self.current_q]
        embed = discord.Embed(title=f"Question {self.current_q + 1} of {len(self.questions)}", color=0xffffff)
        
        desc = f"**{q_data['question']}**\n\n"
        for opt in q_data["options"]:
            desc += f"{opt}\n"
            
        embed.description = desc
        embed.set_footer(text="Select the correct letter below.")
        return embed

    async def finish_quiz(self, interaction: discord.Interaction):
        conn = sqlite3.connect("modsVSC.db")
        cursor = conn.cursor()
        cursor.execute("UPDATE mod_profiles SET training_score = ?, training_completed = 1 WHERE user_id = ?", (self.score, self.user_id))
        conn.commit()
        conn.close()

        percent = int((self.score / len(self.questions)) * 100)
        
        try:
            head_staff_channel = interaction.client.get_channel(1375079530183790744) # Make sure this channel ID is correct
            if head_staff_channel:
                report_embed = discord.Embed(title="<a:wt_torolick:1487786362475384982> 𝑀𝑜𝑑 𝑇𝑟𝑎𝑖𝑛𝑖𝑛𝑔 𝑅𝑒𝑠𝑢𝑙𝑡𝑠", color=0xffffff)
                report_embed.add_field(name="Trainee", value=f"<@{self.user_id}>", inline=True)
                report_embed.add_field(name="Score", value=f"{self.score}/{len(self.questions)} ({percent}%)", inline=True)
                status = "✅ Passed" if percent >= 80 else "❌ Immediate Termination is Advised"
                report_embed.add_field(name="Status", value=status, inline=False)
                
                if self.wrong_answers:
                    mistakes_text = "**Mistakes Breakdown:**\n\n"
                    for mistake in self.wrong_answers:
                        mistakes_text += f"**Q:** {mistake['question']}\n❌ Picked: **{mistake['their_answer']}** | ✅ Correct: **{mistake['correct_answer']}**\n\n"
                    report_embed.description = mistakes_text[:4096] 

                await head_staff_channel.send(embed=report_embed)
        except Exception as e:
            logger.error(f"Failed to send score: {e}")

        embed = discord.Embed(title="Training Completed!", color=0xffffff)
        embed.description = f"You have finished the Athena Training Module.\n\n**Your Score:** {self.score}/{len(self.questions)} ({percent}%)\n\n*Your Head Staff have been notified.*"
        
        self.clear_items() 
        # We use message.edit here because we deferred at the start of the callback
        await interaction.message.edit(embed=embed, view=self)

# ---------------- UI: PAGINATOR VIEW ----------------
class TrainingPaginator(discord.ui.View):
    def __init__(self, user_id: int, curriculum: dict):
        super().__init__(timeout=None)
        self.user_id = user_id
        self.pages = curriculum.get("info_pages", [])
        
        self.questions = []
        quiz_sets = curriculum.get("quiz_sets", [])
        if quiz_sets:
            self.questions = random.choice(quiz_sets)
            random.shuffle(self.questions) 
        
        self.current_page = 0
        self.update_buttons()

    def get_embed(self):
        page_data = self.pages[self.current_page]
        embed = discord.Embed(title=page_data.get("title", "Training"), description=page_data.get("content", ""), color=0xffffff)
        embed.set_footer(text=f"Page {self.current_page + 1} of {len(self.pages)} | Read carefully!")
        return embed

    def update_buttons(self):
        self.btn_back.disabled = (self.current_page == 0)
        
        if self.current_page == len(self.pages) - 1:
            self.btn_next.disabled = True
            self.btn_start_quiz.disabled = False
            self.btn_start_quiz.style = discord.ButtonStyle.success
        else:
            self.btn_next.disabled = False
            self.btn_start_quiz.disabled = True
            self.btn_start_quiz.style = discord.ButtonStyle.secondary

    @discord.ui.button(label="◀ Back", style=discord.ButtonStyle.primary, custom_id="train_back")
    async def btn_back(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page -= 1
        self.update_buttons()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    @discord.ui.button(label="Next ▶", style=discord.ButtonStyle.primary, custom_id="train_next")
    async def btn_next(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page += 1
        self.update_buttons()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    @discord.ui.button(label="Start Quiz", style=discord.ButtonStyle.secondary, custom_id="train_quiz", emoji="<a:wt_toroexclaim:1480581004317036624>", disabled=True)
    async def btn_start_quiz(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.questions:
            await interaction.response.send_message("⚠️ Error: No questions found in the curriculum.", ephemeral=True)
            return
        quiz_view = QuizView(self.user_id, self.questions)
        await interaction.response.edit_message(embed=quiz_view.get_embed(), view=quiz_view)


# ---------------- UI: 2FA GUIDE DROPDOWN ----------------
class TwoFactorSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="iPhone / iOS", description="Step-by-step for Apple devices", emoji="<a:wt_toroleaf:1480580940785913967>"),
            discord.SelectOption(label="Android", description="Step-by-step for Android devices", emoji="<a:wt_toroleaf:1480580940785913967>"),
            discord.SelectOption(label="Desktop / PC", description="Step-by-step for Computer/Web", emoji="<a:wt_toroleaf:1480580940785913967>"),
            discord.SelectOption(label="Troubleshooting & FAQ", description="Fix common 2FA errors and lockouts", emoji="<a:wt_toroconfused:1480580932367945918>")
        ]
        super().__init__(placeholder="Select your device or view FAQ...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        
        embed = discord.Embed(title=f"2FA Setup Guide: {self.values[0]}", color=0xffffff)
        
        if self.values[0] in ["iPhone / iOS", "Android"]:
            embed.description = """
            **Step 1:** Download an Authenticator App from your App Store. We highly recommend **Google Authenticator** or **Authy**.
            **Step 2:** Open the Discord app and tap your **Profile Picture** in the bottom right corner.
            **Step 3:** Tap the **Gear Icon (⚙️)** in the top right to open Settings.
            **Step 4:** Tap **Account**.
            **Step 5:** Scroll down and tap **Enable Two-Factor Auth**.
            **Step 6:** Type in your Discord password.
            **Step 7:** Discord will give you a setup key (a long mix of letters and numbers). Copy it, open your new Authenticator App, and paste it in!
            **Step 8:** The app will generate a 6-digit code. Go back to Discord and type it in.
            
            **CRITICAL WARNING:** Discord will prompt you to save **Backup Codes**. YOU MUST SAVE THESE. Screenshot them, write them down, or email them to yourself. If you get a new phone without these codes, your account is gone forever.
            """
        elif self.values[0] == "Desktop / PC":
            embed.description = """
            **Step 1:** Download an Authenticator App on your phone. We highly recommend **Google Authenticator** or **Authy**.
            **Step 2:** Open Discord on your computer and click the **Gear Icon (⚙️)** next to your microphone at the bottom left.
            **Step 3:** You will instantly be on the "My Account" page. Scroll down to the "Password and Authentication" section.
            **Step 4:** Click the purple **Enable Two-Factor Auth** button.
            **Step 5:** Type in your Discord password.
            **Step 6:** Discord will show a QR Code on your computer screen. Open the Authenticator app on your phone and scan the QR code.
            **Step 7:** The app will give you a 6-digit code. Type that code into Discord.
            
            **CRITICAL WARNING:** Discord will prompt you to download **Backup Codes**. YOU MUST SAVE THESE. Put the file somewhere safe. If you get a new phone or lose access to your app without these codes, your account is gone forever.
            """
        elif self.values[0] == "Troubleshooting & FAQ":
            embed.title = "2FA Troubleshooting & FAQ"
            embed.color = 0xffffff # Orange warning color
            embed.description = """
            **Q: My 6-digit code says "Invalid" but I typed it perfectly!**
            **A:** Your Authenticator app's internal clock is slightly out of sync. 
            *If using Google Authenticator:* Open the app -> Tap the 3 dots (top right) -> Settings -> Time correction for codes -> Sync now.
            
            **Q: I got a new phone and my authenticator app is empty!**
            **A:** You must use one of your 8-digit **Backup Codes** to log into Discord. Once logged in, go to Settings > My Account > Remove 2FA, then set it up again on your new phone.
            
            **Q: I lost my phone AND I didn't save my backup codes!**
            **A:** Unfortunately, Discord Support cannot and will not remove 2FA or give you new codes. **Your account is permanently lost.** You will have to make a new one. (This is why we emphasize saving those codes!).
            
            **Q: I'm logged in, but where do I find my backup codes?**
            **A:** Go to User Settings > My Account > Click "View Backup Codes". You will need to enter your password to see them.
            """
        
        await interaction.message.edit(embed=embed)

class TwoFactorView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(TwoFactorSelect())


# ---------------- DISCORD COG ----------------
class ModTraining(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        setup_db()

    @app_commands.command(name="createprofile", description="Head Staff: Create a permanent Mod Profile for a user")
    @app_commands.describe(user="The user being promoted/trained")
    @is_head_staff() # <-- Replaced Admin Check
    async def createprofile(self, interaction: discord.Interaction, user: discord.Member):
        # 1. DEFER FIRST: Tell Discord to give us time to process
        await interaction.response.defer(ephemeral=False)
        
        conn = sqlite3.connect("modsVSC.db")
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM mod_profiles WHERE user_id = ?", (user.id,))
        exists = cursor.fetchone()
        
        if exists:
            await interaction.followup.send(f"{user.mention} already has a Mod Profile.")
            conn.close()
            return
            
        cursor.execute("INSERT INTO mod_profiles (user_id) VALUES (?)", (user.id,))
        conn.commit()
        conn.close()
        
        # --- NEW: DM Notification ---
        dm_failed = False
        try:
            welcome_embed = discord.Embed(title="Welcome to the Team", color=0xffffff)
            welcome_embed.description = "Your official Moderation Profile has been created in the database.\n\nPlease head to the server and run the `/training` command to complete your mandatory onboarding."
            await user.send(embed=welcome_embed)
        except discord.Forbidden:
            dm_failed = True

        embed = discord.Embed(title="𝑀𝑜𝑑 𝑃𝑟𝑜𝑓𝑖𝑙𝑒 𝐶𝑟𝑒𝑎𝑡𝑒𝑑", color=0xffffff)
        embed.description = f"A permanent database profile has been created for {user.mention}.\nThey can now run `/training`."
        if dm_failed:
            embed.description += "\n\n*(Note: Could not DM them to notify them. DMs are closed.)*"
        embed.set_footer(text="Powered By Palantir")
        
        # 2. USE FOLLOWUP: Because we deferred earlier
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="deleteprofile", description="Head Staff: Permanently delete a mod's profile from the database")
    @app_commands.describe(user="The user whose profile should be wiped")
    @is_head_staff() # <-- Replaced Admin Check
    async def deleteprofile(self, interaction: discord.Interaction, user: discord.Member):
        conn = sqlite3.connect("modsVSC.db")
        cursor = conn.cursor()
        
        cursor.execute("SELECT * FROM mod_profiles WHERE user_id = ?", (user.id,))
        exists = cursor.fetchone()
        
        if not exists:
            await interaction.response.send_message(f"No profile found for {user.mention} in the database.", ephemeral=True)
            conn.close()
            return
            
        cursor.execute("DELETE FROM mod_profiles WHERE user_id = ?", (user.id,))
        cursor.execute("DELETE FROM mod_strikes WHERE user_id = ?", (user.id,)) 
        conn.commit()
        conn.close()
        
        embed = discord.Embed(title="𝑀𝑜𝑑 𝑃𝑟𝑜𝑓𝑖𝑙𝑒 𝐷𝑒𝑙𝑒𝑡𝑒𝑑", color=0xffffff)
        embed.description = f"All database records for {user.mention} have been permanently wiped.\n\n*This action cannot be undone.*"
        embed.set_footer(text="Powered by Palantir")
        
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="training", description="Trainee: Begin your mandatory staff training module")
    async def start_training(self, interaction: discord.Interaction):
        conn = sqlite3.connect("modsVSC.db")
        cursor = conn.cursor()
        cursor.execute("SELECT training_completed FROM mod_profiles WHERE user_id = ?", (interaction.user.id,))
        user_data = cursor.fetchone()
        conn.close()

        is_admin = interaction.user.guild_permissions.administrator

        if not user_data and not is_admin:
            await interaction.response.send_message("Access Denied. You do not have a registered Mod Profile.", ephemeral=True)
            return
            
        if user_data and user_data[0] == 1 and not is_admin: 
            await interaction.response.send_message("You have already completed the training module!", ephemeral=True)
            return

        curriculum = load_curriculum()
        if not curriculum.get("info_pages"):
            await interaction.response.send_message("⚠️ The training curriculum is currently empty.", ephemeral=True)
            return

        view = TrainingPaginator(interaction.user.id, curriculum)
        await interaction.response.send_message(embed=view.get_embed(), view=view, ephemeral=True)

    @app_commands.command(name="reset_training", description="Head Staff: Force a mod to retake the training module")
    @app_commands.describe(user="The moderator to reset")
    @is_head_staff() # <-- Replaced Admin Check
    async def reset_training(self, interaction: discord.Interaction, user: discord.Member):
        conn = sqlite3.connect("modsVSC.db")
        cursor = conn.cursor()
        cursor.execute("UPDATE mod_profiles SET training_completed = 0, training_score = 0 WHERE user_id = ?", (user.id,))
        conn.commit()
        conn.close()
        
        await interaction.response.send_message(f"{user.mention}'s training status has been reset. They can now run `/training` again.")

    @app_commands.command(name="modinfo", description="View a moderator's permanent profile")
    @app_commands.describe(user="The moderator to check")
    @is_head_staff() # <-- Replaced Admin Check
    async def check_mod(self, interaction: discord.Interaction, user: discord.Member):
        conn = sqlite3.connect("modsVSC.db")
        cursor = conn.cursor()
        # --- NEW: Fetch commendations ---
        cursor.execute("SELECT rank, loa, training_score, training_completed, warnings, commendations FROM mod_profiles WHERE user_id = ?", (user.id,))
        data = cursor.fetchone()
        conn.close()

        if not data:
            await interaction.response.send_message(f"{user.mention} does not have a Mod Profile.", ephemeral=True)
            return

        rank, loa, score, completed, warnings, commendations = data
        
        loa_status = "🔴 ON LEAVE (LOA)" if loa else "🟢 Active"
        
        # --- NEW VISUAL STRIKE LOGIC ---
        if warnings == 0:
            strike_display = "⚪ ⚪ ⚪ (No strikes)"
        elif warnings == 1:
            strike_display = "🔴 ⚪ ⚪"
        elif warnings == 2:
            strike_display = "🔴 🔴 ⚪"
        elif warnings == 3:
            strike_display = "🔴 🔴 🔴"
        else:
            strike_display = f"🔴 🔴 🔴 (+{warnings - 3} more)"
        # -------------------------------
        
        embed = discord.Embed(title=f"𝑀𝑜𝑑 𝑃𝑟𝑜𝑓𝑖𝑙𝑒: {user.display_name}", color=0xffffff)
        if user.display_avatar:
            embed.set_thumbnail(url=user.display_avatar.url)
            
        embed.add_field(name="Rank", value=f"**{rank}**", inline=True)
        embed.add_field(name="Status", value=f"**{loa_status}**", inline=True)
        embed.add_field(name="Strikes", value=f"**{strike_display}**", inline=True)
        
        # --- NEW: Commendations Field ---
        embed.add_field(name="Commendations 🌟", value=f"**{commendations}**", inline=True)
        
        training_text = f"{score} points (Completed)" if completed else "Pending / Not Finished"
        embed.add_field(name="Training Module", value=training_text, inline=True)
        
        embed.set_footer(text=f"User ID: {user.id}")
        
        view = ModInfoView(user.id)
        await interaction.response.send_message(embed=embed, view=view)

    @app_commands.command(name="set_rank", description="Head Staff: Update a moderator's rank")
    @app_commands.describe(user="The moderator", rank="Their new rank (e.g., Mod, Head Mod)")
    @is_head_staff() # <-- Replaced Admin Check
    async def set_rank(self, interaction: discord.Interaction, user: discord.Member, rank: str):
        conn = sqlite3.connect("modsVSC.db")
        cursor = conn.cursor()
        cursor.execute("UPDATE mod_profiles SET rank = ? WHERE user_id = ?", (rank, user.id))
        if cursor.rowcount == 0:
            await interaction.response.send_message(f"{user.mention} does not have a profile.", ephemeral=True)
        else:
            conn.commit()
            await interaction.response.send_message(f"Updated {user.mention}'s rank to **{rank}**.")
        conn.close()

    @app_commands.command(name="strike", description="Head Staff: Issue a formal strike to a moderator")
    @app_commands.describe(user="The moderator to strike", reason="Reason for the strike")
    @is_head_staff() # <-- Replaced Admin Check
    async def strike(self, interaction: discord.Interaction, user: discord.Member, reason: str):
        conn = sqlite3.connect("modsVSC.db")
        cursor = conn.cursor()
        
        cursor.execute("SELECT warnings FROM mod_profiles WHERE user_id = ?", (user.id,))
        exists = cursor.fetchone()
        
        if not exists:
            await interaction.response.send_message(f"{user.mention} does not have a profile.", ephemeral=True)
            conn.close()
            return

        cursor.execute("UPDATE mod_profiles SET warnings = warnings + 1 WHERE user_id = ?", (user.id,))
        
        current_time = int(time.time())
        cursor.execute("INSERT INTO mod_strikes (user_id, reason, timestamp) VALUES (?, ?, ?)", (user.id, reason, current_time))
        
        conn.commit()
        total_strikes = exists[0] + 1
        conn.close()

        dm_failed = False
        try:
            embed = discord.Embed(title="𝑂𝑓𝑓𝑖𝑐𝑖𝑎𝑙 𝑆𝑡𝑎𝑓𝑓 𝑆𝑡𝑟𝑖𝑘𝑒", color=0xffffff)
            embed.description = f"You have received a strike from Head Staff in Cherriies.\n\n**Reason:** {reason}\n**Total Strikes:** {total_strikes}\n\n*Please reach out to Head Staff if you wish to discuss this.*"
            await user.send(embed=embed)
        except discord.Forbidden:
            dm_failed = True

        response_text = f"Issued a strike to {user.mention}. They now have **{total_strikes}** strikes."
        if dm_failed:
            response_text += "\n*(Note: I could not DM them. Their DMs are closed.)*"
            
        await interaction.response.send_message(response_text)

    # --- NEW COMMAND: COMMEND ---
    @app_commands.command(name="commend", description="Head Staff: Commend a moderator for excellent work")
    @app_commands.describe(user="The moderator to commend", reason="Reason for commendation (optional log)")
    @is_head_staff()
    async def commend(self, interaction: discord.Interaction, user: discord.Member, reason: str = "Excellent moderation work."):
        conn = sqlite3.connect("modsVSC.db")
        cursor = conn.cursor()
        
        cursor.execute("SELECT commendations FROM mod_profiles WHERE user_id = ?", (user.id,))
        exists = cursor.fetchone()
        
        if not exists:
            await interaction.response.send_message(f"❌ {user.mention} does not have a profile.", ephemeral=True)
            conn.close()
            return

        cursor.execute("UPDATE mod_profiles SET commendations = commendations + 1 WHERE user_id = ?", (user.id,))
        conn.commit()
        total_commendations = exists[0] + 1
        conn.close()

        dm_failed = False
        try:
            chosen_msg = random.choice(COMMENDATION_MESSAGES)
            embed = discord.Embed(title="🌟 𝑂𝑓𝑓𝑖𝑐𝑖𝑎𝑙 𝐶𝑜𝑚𝑚𝑒𝑛𝑑𝑎𝑡𝑖𝑜𝑛", color=0xffffff)
            embed.description = f"{chosen_msg}\n\n**Reason:** {reason}\n**Total Commendations:** {total_commendations}"
            await user.send(embed=embed)
        except discord.Forbidden:
            dm_failed = True

        response_text = f"🌟 Successfully commended {user.mention}! They now have **{total_commendations}** commendations."
        if dm_failed: response_text += "\n*(Note: I could not DM them. Their DMs are closed.)*"
        await interaction.response.send_message(response_text)

    # --- NEW COMMAND: STAFF VIEW ---
    @app_commands.command(name="staffview", description="Head Staff: View the entire active staff roster")
    @is_head_staff()
    async def staffview(self, interaction: discord.Interaction):
        conn = sqlite3.connect("modsVSC.db")
        cursor = conn.cursor()
        cursor.execute("SELECT user_id, rank, loa, warnings, commendations FROM mod_profiles")
        all_mods = cursor.fetchall()
        conn.close()

        if not all_mods:
            await interaction.response.send_message("The staff database is currently empty.", ephemeral=True)
            return

        # Group mods by rank
        roster_dict = {}
        for user_id, rank, loa, warnings, commendations in all_mods:
            if rank not in roster_dict:
                roster_dict[rank] = []
            roster_dict[rank].append({
                "id": user_id,
                "loa": loa,
                "warnings": warnings,
                "commendations": commendations
            })

        embed = discord.Embed(title="📋 𝐶ℎ𝑒𝑟𝑟𝑖𝑖𝑒𝑠 𝑆𝑡𝑎𝑓𝑓 𝑅𝑜𝑠𝑡𝑒𝑟", color=0xffffff)
        
        for rank_name, members in roster_dict.items():
            rank_text = ""
            for m in members:
                status_emoji = "🔴 [LOA]" if m["loa"] else "🟢"
                rank_text += f"{status_emoji} <@{m['id']}> | Strikes: **{m['warnings']}** | 🌟: **{m['commendations']}**\n"
            
            embed.add_field(name=f"=== {rank_name} ===", value=rank_text[:1024], inline=False)
            
        embed.set_footer(text="Powered by Palantir • Use /modinfo for detailed views")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="loa", description="Staff: Toggle your Leave of Absence (LOA) status")
    async def toggle_loa(self, interaction: discord.Interaction):
        conn = sqlite3.connect("modsVSC.db")
        cursor = conn.cursor()
        
        cursor.execute("SELECT loa FROM mod_profiles WHERE user_id = ?", (interaction.user.id,))
        result = cursor.fetchone()
        
        if not result:
            await interaction.response.send_message("You don't have a Mod Profile registered.", ephemeral=True)
            conn.close()
            return
            
        new_loa_status = 0 if result[0] else 1 
        
        cursor.execute("UPDATE mod_profiles SET loa = ? WHERE user_id = ?", (new_loa_status, interaction.user.id))
        conn.commit()
        conn.close()

        if new_loa_status == 1:
            await interaction.response.send_message("You are now officially marked as **On Leave (LOA)**. Staff are not allowed to ping you.", ephemeral=False)
        else:
            await interaction.response.send_message("You have returned from LOA. Welcome back to active duty!", ephemeral=False)

    # --- NEW COMMAND: SEARCHABLE FAQ ---
    @app_commands.command(name="faq", description="Staff: Search the Moderator Knowledge Base")
    @app_commands.describe(question="Start typing to search the FAQs")
    async def faq_command(self, interaction: discord.Interaction, question: str):
        curriculum = load_curriculum()
        faqs = curriculum.get("faqs", [])
        
        # Find the exact matching question in the JSON
        match = next((f for f in faqs if f["question"] == question), None)
        
        if not match:
            await interaction.response.send_message("I couldn't find that specific FAQ. Please use the autocomplete menu to select a valid question.", ephemeral=True)
            return
            
        embed = discord.Embed(title=match["category"], color=0xffffff)
        embed.add_field(name=match["question"], value=match["answer"], inline=False)
        embed.set_footer(text="Powered by Palantir")
        
        # We send this publicly so if a mod asks a question in staff-chat, 
        # another mod can pull up the FAQ to show them the answer.
        await interaction.response.send_message(embed=embed)

    @faq_command.autocomplete('question')
    async def faq_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        curriculum = load_curriculum()
        faqs = curriculum.get("faqs", [])
        
        choices = []
        for faq in faqs:
            # If the user's typed text is in the question, suggest it!
            if current.lower() in faq["question"].lower():
                # Discord caps autocomplete names at 100 characters. All yours fit perfectly!
                choices.append(app_commands.Choice(name=faq["question"], value=faq["question"]))
                
        # Discord only allows a maximum of 25 autocomplete choices to be shown at once
        return choices[:25]
    

    @app_commands.command(name="2fa_guide", description="Staff: Get a foolproof, step-by-step guide on how to set up Two-Factor Authentication")
    async def two_factor_guide(self, interaction: discord.Interaction):
        embed = discord.Embed(title="Mandatory Staff 2FA Setup", color=0xffffff)
        embed.description = (
            "Two-Factor Authentication (2FA) is **mandatory** for all staff in this server. "
            "It prevents hackers from stealing your account and nuking the server.\n\n"
            "**Please select the device you are currently using from the dropdown menu below** to get an exact, step-by-step guide on how to turn it on!"
        )
        
        view = TwoFactorView()
        await interaction.response.send_message(embed=embed, view=view)


async def setup(bot):
    await bot.add_cog(ModTraining(bot))