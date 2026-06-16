import os
import sys
import discord
from discord.ext import commands
from dotenv import load_dotenv
from typing import Literal
from discord import app_commands

# Load environment variables
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')
AI_API_KEY = os.getenv('AI_API_KEY')

# Setup bot with multiple prefixes
async def get_prefix(bot, message):
    """Return multiple prefixes that the bot should respond to"""
    return commands.when_mentioned_or('a?', 'a!')(bot, message)

# Set up the bot with multiple prefixes and all intents
bot = commands.Bot(command_prefix=get_prefix, intents=discord.Intents.all())
bot.remove_command('help')  # Remove default help command

# Auto-reaction configuration
AUTO_REACTION_CHANNELS = {
    1273939243600842795,  # channel ID 1
    1273939292749561866,
    1462901038364229865,
    1273945454853492746   # channel ID 2
}
AUTO_REACTION_EMOJI = "<a:h_white4:1416368341244837979>"

# Load cogs/extensions
initial_extensions = [
    'cogs.afk',
    'cogs.fun',
    'cogs.reminders',
    'cogs.cupid_engine',
    'cogs.travel',
    'cogs.mod_training',
    'cogs.economy',
    'cogs.casino',
    'cogs.help',
    'cogs.business3',
    'cogs.invest',
    'cogs.chat_events',
    'cogs.careers',
    'cogs.cupid_dashboard',
    'cogs.marketplace',
    'cogs.cupid_blacklist'
]

async def load_extensions():
    """Load all extensions/cogs"""
    for extension in initial_extensions:
        try:
            await bot.load_extension(extension)
            print(f'✓ Loaded {extension}')
        except Exception as e:
            print(f'✗ Failed to load {extension}: {e}')

@bot.command()
async def sync(ctx):
    """Force syncs commands to the current server instantly"""
    # This copies your global commands to THIS specific server
    bot.tree.copy_global_to(guild=ctx.guild)
    
    # This syncs them instantly
    await bot.tree.sync(guild=ctx.guild)
    
    await ctx.send(f"**INSTANT SYNC:** Commands updated for {ctx.guild.name}! \n*(If it still fails, then lwk kys)*")

@bot.command(name='syncguild', help='Sync slash commands to current guild')
@commands.is_owner()
async def syncguild(ctx):
    """Sync slash commands to specific guild"""
    try:
        bot.tree.copy_global_to(guild=ctx.guild)
        synced = await bot.tree.sync(guild=ctx.guild)
        await ctx.send(f"Synced {len(synced)} commands to this guild.")
    except Exception as e:
        await ctx.send(f"Guild sync failed: {e}")


# Global events
@bot.event
async def on_ready():
    """Event called when the bot has successfully connected to Discord"""
    print(f'{bot.user.name} has connected to Discord!')
    print(f'Bot is online and ready in {len(bot.guilds)} server(s)!')
    
    # Load extensions
    await load_extensions()
    
    # Debug: Show loaded cogs and commands
    print("\nLoaded Cogs:")
    for cog_name in bot.cogs:
        print(f"  - {cog_name}")
    
    print("\nAvailable Commands:")
    for command in bot.commands:
        print(f"  - {command.name}")
    
    # Set custom status
    activity = discord.Streaming(name="Arguing w/ the British | Mark 17.1", url="https://twitch.tv/twitch")
    await bot.change_presence(activity=activity, status=discord.Status.online)
    print(f'Custom status set: {activity.type.name} {activity.name}')

# Global message handler
@bot.event
async def on_message(message):
    # Ignore messages from the bot itself
    if message.author == bot.user:
        await bot.process_commands(message)
        return
    
    # 1. Check for autoreaction in designated channels
    if message.channel.id in AUTO_REACTION_CHANNELS:
        try:
            await message.add_reaction(AUTO_REACTION_EMOJI)
        except discord.errors.Forbidden:
            print(f"Error: Lack permissions to add reactions in #{message.channel.name}")
    
    # 2. Process commands (this allows the AFK system in the cog to work)
    await bot.process_commands(message)

# Help command (since we removed the default one)
@bot.command(name="help")
async def help_command(ctx):
    embed = discord.Embed(title="𝐴𝑡ℎ𝑒𝑛𝑎 𝐶𝑜𝑚𝑚𝑎𝑛𝑑 𝑀𝑒𝑛𝑢", color=0xffffff)

    # Utility Commands
    utility_commands = """
<:p_hearts:1378053399525982288> `ping` - Check bot latency
<:p_hearts:1378053399525982288> `afk` - Set your status as AFK
<:p_hearts:1378053399525982288> `remind` - Set a reminder (e.g., a.remind 1h30m Buy milk)
<:p_hearts:1378053399525982288> `reminders` - List your active reminders
<:p_hearts:1378053399525982288> `removereminder` - Remove a reminder by ID
<:p_hearts:1378053399525982288> `vanityinfo` - Show members with vanity role
"""
    embed.add_field(name="<:s_white2:1382052523166142486> Utility Commands", value=utility_commands, inline=False)

    # Social Commands
    social_commands = """
<:p_hearts:1378053399525982288> `compat` - Check compatibility between users
<:p_hearts:1378053399525982288> `love` - Love calculator between users
<:p_hearts:1378053399525982288> `mbti` - Get personality insights
<:p_hearts:1378053399525982288> `romantic` - Detailed romantic compatibility
"""
    embed.add_field(name="<:s_white2:1382052523166142486> Social Commands", value=social_commands, inline=False)

    # Vanity System
    vanity_text = """
<:p_hearts:1378053399525982288> Rep `/cheriies` in your status to get:
• Special vanity role
• Recognition in the community
• Exclusive perks!
"""
    embed.add_field(name="<:s_white2:1382052523166142486> Vanity System", value=vanity_text, inline=False)

    # NEW: Economy Commands
    economy_commands = """
<:p_hearts:1378053399525982288> `bal` - Check your wallet & card
<:p_hearts:1378053399525982288> `work` - Earn coins (Commute bonus applies)
<:p_hearts:1378053399525982288> `daily` - Claim your daily allowance
<:p_hearts:1378053399525982288> `give` - Transfer coins to another user
<:p_hearts:1378053399525982288> `loan` - Take a loan from the Reserve
<:p_hearts:1378053399525982288> `stake` - Lock capital for high yields
<:p_hearts:1378053399525982288> `invest` - Buy/Sell stocks & view yields
<:p_hearts:1378053399525982288> `marketplace` - Buy houses & luxury cars
<:p_hearts:1378053399525982288> `garage` - View your vehicle collection
<:p_hearts:1378053399525982288> `networth` - Total valuation of your empire
<:p_hearts:1378053399525982288> `leaderboard` - Top 10 wealthiest users
<:p_hearts:1378053399525982288> `casino` - Access 11 VIP gambling tables
<:p_hearts:1378053399525982288> `convert` - Mimu to Athena calculator
"""
    embed.add_field(name="<:s_white2:1382052523166142486> Economy Commands", value=economy_commands, inline=False)

    # Staff Commands
    staff_commands = """
<:p_hearts:1378053399525982288> `createprofile` - Create your mod user profile
<:p_hearts:1378053399525982288> `training` - Begin your staff training modules
<:p_hearts:1378053399525982288> `modinfo` - View detailed moderator info
<:p_hearts:1378053399525982288> `loa` - Toggle your LOA status on/off
<:p_hearts:1378053399525982288> `staffview` - View all current staff
<:p_hearts:1378053399525982288> `commend` - Commend a mod for excellent work
"""
    embed.add_field(name="<:s_white2:1382052523166142486> Staff Commands", value=staff_commands, inline=False)

    embed.set_footer(text="Athena v16.3 UNSTABLE | Use slash commands or a. prefix")
    await ctx.send(embed=embed)

@bot.command(name='ping', aliases=['p'], help='Responds with Pong! and latency')
async def ping(ctx):
    latency = round(bot.latency * 1000)  # Latency in milliseconds
    await ctx.send(f'Pong! Latency: {latency}ms')



# Inside your main.py or help cog


@bot.tree.command(name="setstatus", description="HIGH STAFF: Change Athena's live Discord status")
@app_commands.describe(
    activity_type="Choose the type of activity",
    status_text="The text to display (e.g. 'with your heart')",
    stream_url="Optional: Only used for 'Streaming' type"
)
async def set_status(
    interaction: discord.Interaction, 
    activity_type: Literal["Playing", "Streaming", "Listening", "Watching"], 
    status_text: str, 
    stream_url: str = "https://twitch.tv/twitch"
):
    # Security check: Only Phoenix and Head Staff can change status
    AUTHORIZED = [743411894416834590, 866380792728387584, 906142971588640768, 860192411627552788] # Replace with actual IDs
    if interaction.user.id not in AUTHORIZED:
        return await interaction.response.send_message("<a:wt_torono:1480580892706603018> Unauthorized access to system appearance.", ephemeral=True)

    # Apply the correct Discord Activity formatting
    if activity_type == "Playing":
        activity = discord.Game(name=status_text)
    elif activity_type == "Streaming":
        activity = discord.Streaming(name=status_text, url=stream_url)
    elif activity_type == "Listening":
        activity = discord.Activity(type=discord.ActivityType.listening, name=status_text)
    elif activity_type == "Watching":
        activity = discord.Activity(type=discord.ActivityType.watching, name=status_text)

    # Push the status to Discord instantly
    await bot.change_presence(activity=activity, status=discord.Status.online)
    await interaction.response.send_message(f"Athena's presence updated to: **{activity_type} {status_text}**", ephemeral=False)


# Run the bot
if __name__ == "__main__":
    bot.run(TOKEN)
