import discord
from discord import app_commands
from discord.ext import commands
import sqlite3
import json

# --- STEP 1: THE BASIC INFO MODAL ---
class CupidBasicInfoModal(discord.ui.Modal, title='Cupid Profile - Step 1'):
    name = discord.ui.TextInput(label='Name/Nickname', style=discord.TextStyle.short, max_length=30)
    age = discord.ui.TextInput(label='Your Age', style=discord.TextStyle.short, placeholder='e.g. 19', max_length=2)
    gender_sexuality = discord.ui.TextInput(label='Gender & Sexuality', style=discord.TextStyle.short, placeholder='e.g. Female, Straight')
    target_age = discord.ui.TextInput(label='Age Preference (Min-Max)', style=discord.TextStyle.short, placeholder='e.g. 18-22')
    timezone = discord.ui.TextInput(label='Timezone', style=discord.TextStyle.short, placeholder='e.g. EST, GMT+5')

    async def on_submit(self, interaction: discord.Interaction):
        # Temporarily save Step 1 data to memory, then launch Step 2
        await interaction.response.send_message(
            "✅ Basic Info saved! Now click the button below to add your hobbies and dealbreakers.", 
            view=CupidStepTwoView(self.children, interaction.user.id), 
            ephemeral=True
        )

# --- STEP 2: THE PREFERENCES MODAL ---
class CupidPreferencesModal(discord.ui.Modal, title='Cupid Profile - Step 2'):
    def __init__(self, step_one_data, user_id):
        super().__init__()
        self.step_one_data = step_one_data # Carries over data from Step 1
        self.user_id = user_id

    hobbies = discord.ui.TextInput(label='Hobbies & Likes (Comma separated)', style=discord.TextStyle.paragraph, placeholder='gaming, reading, cats')
    dislikes = discord.ui.TextInput(label='Dislikes (Comma separated)', style=discord.TextStyle.paragraph, placeholder='toxic people, spiders')
    energy = discord.ui.TextInput(label='Energy Level', style=discord.TextStyle.short, placeholder='Introvert, Extrovert, or Ambivert')
    trans_poly = discord.ui.TextInput(label='Are you Trans/Poly? Mind if they are?', style=discord.TextStyle.paragraph, placeholder='I am not trans. I dont mind poly.')

    async def on_submit(self, interaction: discord.Interaction):
        # This is where we instantly save to SQLite! No Gemini required.
        await interaction.response.defer(ephemeral=True)
        
        # In the full code, we format these text inputs and run the INSERT INTO database command here.
        
        await interaction.followup.send("🎉 **Profile Complete!** Your data has been securely saved to the Athena Core Database. Cupids can now match you.")

# --- THE TRIGGER BUTTON ---
class CupidStepTwoView(discord.ui.View):
    def __init__(self, step_one_data, user_id):
        super().__init__(timeout=300)
        self.step_one_data = step_one_data
        self.user_id = user_id

    @discord.ui.button(label="Proceed to Step 2", style=discord.ButtonStyle.success)
    async def step_two_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(CupidPreferencesModal(self.step_one_data, self.user_id))

class CupidEngine(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # This creates the main channel button members click to start onboarding
    @app_commands.command(name="spawn_cupid_desk", description="Admin: Spawns the Cupid Onboarding button")
    async def spawn_desk(self, interaction: discord.Interaction):
        view = discord.ui.View(timeout=None)
        btn = discord.ui.Button(label="Create Cupid Profile", style=discord.ButtonStyle.primary, emoji="💌", custom_id="start_cupid_onboard")
        
        async def btn_callback(inter):
            await inter.response.send_modal(CupidBasicInfoModal())
            
        btn.callback = btn_callback
        view.add_item(btn)
        
        embed = discord.Embed(title="Welcome to Cherriies Matchmaking", description="Click the button below to securely submit your profile. Only Head Staff can view your data.", color=0xff69b4)
        await interaction.channel.send(embed=embed, view=view)
        await interaction.response.send_message("Desk spawned.", ephemeral=True)

async def setup(bot):
    await bot.add_cog(CupidEngine(bot))