import os
import sys
import discord
from discord.ext import commands
from dotenv import load_dotenv
# Mobile Sync Test - April 2026

# Load environment variables
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')
AI_API_KEY = os.getenv('AI_API_KEY')

# Setup bot with multiple prefixes
async def get_prefix(bot, message):
    """Return multiple prefixes that the bot should respond to"""
    return commands.when_mentioned_or('a.', 'a!')(bot, message)

# Set up the bot with multiple prefixes and all intents
bot = commands.Bot(command_prefix=get_prefix, intents=discord.Intents.all())
bot.remove_command('help')  # Remove default help command

# Auto-reaction configuration
AUTO_REACTION_CHANNELS = {
    1273939243600842795,  # channel ID 1
    1273939292749561866,
    1273945454853492746   # channel ID 2
}
AUTO_REACTION_EMOJI = "<a:h_white4:1416368341244837979>"

# Load cogs/extensions
initial_extensions = [
    'cogs.afk',
    'cogs.fun',
    'cogs.reminders',
    'cogs.vanity',
    'cogs.cupid_engine',
    'cogs.mod_training',
    'cogs.economy',#a72424
    'cogs.casino',
    'cogs.invest',
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
    activity = discord.Streaming(name="Playing Pokemon GO!", url="https://twitch.tv/twitch")
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
@bot.command(name='help', aliases=['commands', 'h'], help='Show all available commands')
async def help_command(ctx):
    """Display a beautiful embed with all commands using custom emojis"""
    # Use your custom emoji names (replace with your actual emoji names)
    embed = discord.Embed(
        title=f"𝐴𝑡ℎ𝑒𝑛𝑎 𝐶𝑜𝑚𝑚𝑎𝑛𝑑 𝑀𝑒𝑛𝑢",
        description=" ",
        color=0xffffff  # Pure white
    )
    
    # Utility Commands
    utility_commands = """
    <:p_hearts:1378053399525982288> `ping` - Check bot latency
    <:p_hearts:1378053399525982288> `afk` - Set your status as AFK
    <:p_hearts:1378053399525982288> `remind` - Set a reminder (e.g., `a.remind 1h30m Buy milk`)
    <:p_hearts:1378053399525982288> `reminders` - List your active reminders
    <:p_hearts:1378053399525982288> `removereminder` - Remove a reminder by ID
    <:p_hearts:1378053399525982288> `vanityinfo` - Show members with vanity role
    """
    embed.add_field(name="<:s_white2:1382052523166142486> Utility Commands", value=utility_commands, inline=False)
    
    # Fun & Social Commands
    fun_commands = """
    <:p_hearts:1378053399525982288> `compat` - Check compatibility between users
    <:p_hearts:1378053399525982288> `love` - Love calculator between users  
    <:p_hearts:1378053399525982288> `mbti` - Get personality insights
    <:p_hearts:1378053399525982288> `romantic` - Detailed romantic compatibility
    """
    embed.add_field(name="<:s_white2:1382052523166142486> Social Commands", value=fun_commands, inline=False)

    # Vanity System Info
    vanity_info = """
    <:p_hearts:1378053399525982288> Rep **/cheriies** in your status to get:
    • Special vanity role 
    • Recognition in the community
    • Exclusive perks!
    """
    embed.add_field(name="<:s_white2:1382052523166142486> Vanity System", value=vanity_info, inline=False)
    
    # Staff Commands
    fun_commands = """
    <:p_hearts:1378053399525982288> `createprofile` - Create your mod user profile
    <:p_hearts:1378053399525982288> `deleteprofile` - Delete your mod user profile  
    <:p_hearts:1378053399525982288> `training` - Begin your staff training modules
    <:p_hearts:1378053399525982288> `strike` - Issue formal strike to staff
    <:p_hearts:1378053399525982288> `modinfo` - View detailed moderator info
    <:p_hearts:1378053399525982288> `loa` - Toggle your LOA status on/off
    <:p_hearts:1378053399525982288> `setrank` - Update rank of staff
    <:p_hearts:1378053399525982288> `reset_training` - Delete old training data for a mod
    <:p_hearts:1378053399525982288> `faq`- Check out frequently answered questions by mods
    <:p_hearts:1378053399525982288> `staffview` - View all current staff
    <:p_hearts:1378053399525982288> `commend` - Commend a mod for excellent work
    <:p_hearts:1378053399525982288> `staffview` - View all current staff
    """
    embed.add_field(name="<:s_white2:1382052523166142486> Staff Commands", value=fun_commands, inline=False)

        # Cupid Commands
    fun_commands = """
    <:p_hearts:1378053399525982288> `analayze_match` - Analyse two user profiles
    <:p_hearts:1378053399525982288> `add_synonym` - Add word(s) to Athena's matchmaking database  
    <:p_hearts:1378053399525982288> `blacklist_add` - Prevent a user from accessing matchmaking channels
    """
    embed.add_field(name="<:s_white2:1382052523166142486> Cupid Commands", value=fun_commands, inline=False)
    
    # Set footer with timestamp
    embed.set_footer(text="Use command prefixes: a. or a!")
    embed.timestamp = discord.utils.utcnow()
    
    await ctx.send(embed=embed)

# Ping command (since it's not in any cog)
@bot.command(name='ping', aliases=['p'], help='Responds with Pong! and latency')
async def ping(ctx):
    latency = round(bot.latency * 1000)  # Latency in milliseconds
    await ctx.send(f'Pong! Latency: {latency}ms')

# Run the bot
if __name__ == "__main__":
    bot.run(TOKEN)