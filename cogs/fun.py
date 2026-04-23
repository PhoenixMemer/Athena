import discord
from discord import app_commands
from discord.ext import commands
import random
import asyncio
import re

class Fun(commands.Cog):
    """Fun and Social Commands"""
    
    def __init__(self, bot):
        self.bot = bot

        # ===== SEKRET SYSTEM - MOVE THIS TO THE TOP =====
        self.sekret_users = set()  # Store user IDs being monitored
        self.sekret_channels = {1126516721952497756, 1408129613586104360, 1013385461743501342}  # REPLACE WITH YOUR CHANNEL IDs
        
        # MBTI types for personality command (existing code)
        self.mbti_types = [
            "INFJ - The Mystic 🔮", "INFP - The Dreamer 🌈", "INTJ - The Strategist ♟️",
            "INTP - The Thinker 🤔", "ENFJ - The Mentor 🌟", "ENFP - The Explorer 🎭",
            "ENTJ - The Commander 🏆", "ENTP - The Debater 💡", "ISFJ - The Nurturer 🏠",
            "ISFP - The Artist 🎨", "ISTJ - The Organizer 📊", "ISTP - The Crafter 🔧",
            "ESFJ - The Host 🎉", "ESFP - The Performer 🎭", "ESTJ - The Supervisor 📋",
            "ESTP - The Dynamo ⚡"
        ]
        
        # Personality traits pool (existing code)
        self.traits_pool = [
            "Creative 🎨", "Analytical 🔍", "Empathetic 💖", "Adventurous 🗺️",
            "Organized 📅", "Spontaneous 🌟", "Logical 🧠", "Passionate 🔥",
            "Practical 🛠️", "Visionary 🔮", "Charming 😊", "Determined 💪",
            "Witty 🎭", "Loyal 🛡️", "Optimistic 🌈", "Thoughtful 🤔"
        ]
        
        # Personality descriptions (existing code)
        self.mbti_descriptions = {
            "INFJ": "Mysterious and intuitive, you understand people on a deep level.",
            "INFP": "Idealistic and creative, you see the beauty in everything.",
            "INTJ": "Strategic and independent, you're always planning several steps ahead.",
            "INTP": "Curious and analytical, you love exploring ideas and theories.",
            "ENFJ": "Charismatic and inspiring, you naturally bring people together.",
            "ENFP": "Enthusiastic and free-spirited, you find possibilities everywhere.",
            "ENTJ": "Natural leader, you're driven to achieve your ambitious goals.",
            "ENTP": "Quick-witted and innovative, you love debating and exploring concepts.",
            "ISFJ": "Caring and reliable, you're the foundation of your social circles.",
            "ISFP": "Artistic and gentle, you express yourself through creativity.",
            "ISTJ": "Responsible and practical, you value tradition and reliability.",
            "ISTP": "Adaptable and logical, you excel at solving practical problems.",
            "ESFJ": "Sociable and caring, you thrive on helping and connecting with others.",
            "ESFP": "Energetic and playful, you bring fun and excitement everywhere.",
            "ESTJ": "Organized and efficient, you're natural at managing and leading.",
            "ESTP": "Bold and action-oriented, you live in the moment and take risks."
        }

        # Gun types for blushandbang command
        self.gun_types = {
            "pink_pearl": {
                "name": "Pink Pearl Pistol",
                "description": "A delicate but deadly sidearm with floral engravings",
                "emoji": "🌸"
            },
            "lace_sniper": {
                "name": "Lace Trimmed Sniper", 
                "description": "For long range eliminations with elegance",
                "emoji": "🎀"
            },
            "velvet_smg": {
                "name": "Velvet Vengeance SMG",
                "description": "Rapid fire cuteness that's simply irresistible", 
                "emoji": "💕"
            },
            "bow_shotgun": {
                "name": "Bowtique Shotgun",
                "description": "Close range devastation wrapped in silk ribbons",
                "emoji": "🎗️"
            },
            "champagne_rifle": {
                "name": "Champagne Carbine", 
                "description": "A Bubbly and lethal autoloader pistol in equal measures",
                "emoji": "🥂"
            },
            "strawberry_launcher": {
                "name": "Strawberry Shortcake Launcher",
                "description": "Explosive sweetness that's literally impossible to resist",
                "emoji": "🍓"
            },
            "crystal_dagger": {
                "name": "Crystal Dagger",
                "description": "Silent but stunning melee perfection", 
                "emoji": "💎"
            },
            "hearts_crossbow": {
                "name": "Hearts & Arrows Crossbow",
                "description": "A cupid's best weapon meets modern precision",
                "emoji": "💘"
            }
        }

        # Kill messages for blushandbang command
        self.kill_messages = [
            "<:pb_sniper:1436282705154150412> *giggles while aiming* Sorry darling~ 💕 **{gun_name}** to the heart! {target} has been eliminated with extreme cuteness!",
            "<:pb_dagger3:1436282299653029988> *blushes* Oopsie! Looks like someone just got **{gun_name}'D**! {target} couldn't handle the adorable assault~",
            "<:pb_sniper:1436282705154150412> *adjusts hair ribbon* Aww, did that hurt? **{gun_name}** says goodnight, {target}! 💥",
            "<:pb_dagger3:1436282299653029988> *strikes a pose* Sorry not sorry! **{gun_name}** popped off and {target} couldn't handle the bubbles! 🥂",
            "<:pb_sniper:1436282705154150412> *flutters eyelashes* Who said violence can't be pretty? **{gun_name}** just eliminated {target} from a distance! 💋",
            "<:pb_dagger3:1436282299653029988> *checks nails* Strategic elimination complete! **{gun_name}** made sweet work of {target}! 🍓",
            "<:pb_sniper:1436282705154150412> *blows kiss* Tactical cuteness deployed! {target} has been neutralized by **{gun_name}**! 🎯",
            "<:pb_gun1:1436280815905411182> *does a graceful spin* Mission accomplished! **{gun_name}** proved too pretty for {target} to handle! 💎",
            "<:pb_dagger3:1436282299653029988> *dramatic sigh* Another day, another elimination~ **{gun_name}** was simply too charming for {target}! 💕",
            "<:pb_gun1:1436280815905411182> *curtsies* Professional courtesy, darling! **{gun_name}** just ended {target}'s streak! 🌹",
            "<:pb_sniper:1436282705154150412> *sparkles appear* Magical elimination! {target} has been sent to the shadow realm by **{gun_name}**! ✨",
            "<:pb_dagger3:1436282299653029988> *pops candy* Sweet revenge! **{gun_name}** made sure {target} won't forget this sugar rush! 🍰",
            "<:pb_gun1:1436280815905411182> *circus music plays* Ta-da! **{gun_name}** just made {target} disappear! 🎪💥",
            "<:pb_dagger3:1436282299653029988> *hugs teddy bear* Aww, was that too much? **{gun_name}** eliminated {target} with maximum cuteness! 🐻",
            "<:pb_sniper:1436282705154150412> *rainbow appears* Oops! **{gun_name}** found their mark in {target}'s heart! Too romantic? 💘",
            "<:pb_gun1:1436280815905411182> *hair flip* Basic elimination for a basic target~ **{gun_name}** out! {target} eliminated! 💋",
            "<:pb_shotgun:1436282564297097266> *adjusts crown* Royal decree: {target} has been removed from the game! **{gun_name}** reigns supreme! ✨",
            "<:pb_sniper:1436282705154150412> *ties ribbon* All wrapped up! **{gun_name}** made quick work of {target}! So elegant, so deadly~ 💎",
            "<:pb_gun1:1436280815905411182> *dance move* And the award for best elimination goes to... **{gun_name}** against {target}! 🏆",
            "<:pb_dagger3:1436282299653029988> *pushes up glasses* Calculated. Precise. Adorable. **{gun_name}** eliminated {target}! 📐",
            "<:pb_sniper:1436282705154150412> *magical girl transformation* In the name of love and justice! **{gun_name}** eliminated {target}! 💫",
            "<:pb_gun1:1436280815905411182> *sparkle sound effect* Love and bullets! {target} couldn't handle the **{gun_name}**'s magical girl energy! 🌸",
            "<:pb_shotgun:1436282564297097266> *fireworks* Making the world cuter, one elimination at a time! **{gun_name}** struck {target}! 💘",
            "<:pb_sniper:1436282705154150412> *crystal ball glows* I foresaw this! **{gun_name}** was destined to eliminate {target}! ✨",
            "<:pb_gun1:1436280815905411182> *flower petals fall* Bloom and doom! **{gun_name}** made {target}'s defeat beautiful! 💐",
            "<:pb_dagger3:1436282299653029988> *stage lights focus* And... scene! **{gun_name}** gives a stellar performance against {target}! 👏",
            "<:pb_shotgun:1436282564297097266> *circus tent appears* Ladies and gentlemen, watch as {target} gets eliminated by **{gun_name}**! 🎪",
            "<:pb_dagger:1436281865278459996> *slot machine sounds* Jackpot! **{gun_name}** hit the cute jackpot on {target}! 💎",
            "<:pb_gun1:1436280815905411182> *paints canvas* A masterpiece of elimination! **{gun_name}** created art with {target}! 🖼️",
            "<:pb_dagger:1436281865278459996> *piano chord* Dramatic finish! **{gun_name}** ends {target}'s melody! 🎶",
            "<:pb_sniper:1436282705154150412> *stars twinkle* Universal laws of cuteness applied! {target} eliminated by **{gun_name}**! ✨",
            "<:pb_gun1:1436280815905411182> *planet orbits* Galactic elimination complete! **{gun_name}** sent {target} to another dimension! 💫",
            "<:pb_dagger:1436281865278459996> *comet flies* Cosmic cuteness collision! **{gun_name}** eliminated {target} with stellar precision! 🌠",
            "<:pb_sniper:1436282705154150412> *moon phases* Lunar cycle complete! **{gun_name}** made {target} disappear like the dark moon! 💫",
            "<:pb_gun1:1436280815905411182> *constellation forms* Written in the stars! **{gun_name}** was fated to eliminate {target}! 🔮",
            "<:pb_shotgun:1436282564297097266> *licks lollipop* Too sweet to handle? **{gun_name}** proved lethal to {target}! 🍓",
            "<:pb_dagger:1436281865278459996> *birthday candles* Make a wish! Oh wait, {target} can't—eliminated by **{gun_name}**! 🥂",
            "<:pb_gun1:1436280815905411182> *ice cream scoop* Cold and sweet! **{gun_name}** gave {target} the ultimate brain freeze! ❄️",
            "<:pb_sniper:1436282705154150412> *chocolate melts* Rich, smooth, and deadly! **{gun_name}** eliminated {target} with sweet precision! 🍬",
            "<:pb_dagger:1436281865278459996> *tea sip* Quite the refreshing elimination! **{gun_name}** made {target}'s defeat taste like victory! ☕",
            "<:pb_gun1:1436280815905411182> *flower presentation* A bouquet of bullets for you! **{gun_name}** eliminated {target} with floral grace! 🌸",
            "<:pb_shotgun:1436282564297097266> *closes book* Chapter closed! **{gun_name}** wrote {target}'s final page! 📚",
            "<:pb_dagger:1436281865278459996> *music note* Hit the wrong note! **{gun_name}** ended {target}'s symphony! 🎶",
            "<:pb_gun1:1436280815905411182> *paint splatter* Abstract elimination! **{gun_name}** made art out of {target}'s defeat! 🖼️",
            "<:pb_shotgun:1436282564297097266> *thread cuts* Snip snip! **{gun_name}** cut {target} out of the picture! ✂️",
            "<:pb_sniper:1436282705154150412> *supernova* Brilliant elimination! {target} blinded by **{gun_name}**'s radiant cuteness! 💫",
            "<:pb_dagger:1436281865278459996> *firework finale* Grand finish! **{gun_name}** gave {target} the sendoff they deserved! 🎇",
            "<:pb_shotgun:1436282564297097266> *graceful movement* So elegant, so final! **{gun_name}** eliminated {target} with balletic precision! 💃",
            "<:pb_dagger:1436281865278459996> *bullseye sound* Perfect aim, perfect style! **{gun_name}** found their mark in {target}! 🎯",
            "<:pb_shotgun:1436282564297097266> *diamond shines* Flawless victory! **{gun_name}** proved too refined for {target}! ✨"
        ]

    @commands.command(name='compat', aliases=['compatibility', 'compatability', 'match'], 
                     help='Check compatibility between two users!')
    async def compatibility(self, ctx, user1: discord.Member, user2: discord.Member = None):
        """Check compatibility between two users"""
        if user2 is None:
            user2 = ctx.author
        
        if user1 == user2:
            await ctx.send("𝑌𝑜𝑢 𝑐𝑎𝑛'𝑡 𝑐ℎ𝑒𝑐𝑘 𝑐𝑜𝑚𝑝𝑎𝑡𝑖𝑏𝑖𝑙𝑖𝑡𝑦 𝑤𝑖𝑡ℎ 𝑦𝑜𝑢𝑟𝑠𝑒𝑙𝑓! 𝑇ℎ𝑎𝑡 𝑤𝑜𝑢𝑙𝑑 𝑏𝑒 0% 𝑎𝑛𝑦𝑤𝑎𝑦.")
            return
        
        # Create a deterministic "score" based on user IDs
        seed = (user1.id + user2.id) % 100
        compatibility_score = (seed * 83) % 101  # Ensure it's between 0-100
        
        # Get fun descriptions based on score ranges
        if compatibility_score >= 90:
            description = "**𝑆𝑜𝑢𝑙𝑚𝑎𝑡𝑒 𝐶𝑜𝑛𝑛𝑒𝑐𝑡𝑖𝑜𝑛!** 💖 𝑇ℎ𝑒𝑠𝑒 𝑡𝑤𝑜 𝑎𝑟𝑒 𝑝𝑟𝑎𝑐𝑡𝑖𝑐𝑎𝑙𝑙𝑦 𝑚𝑎𝑑𝑒 𝑓𝑜𝑟 𝑒𝑎𝑐ℎ 𝑜𝑡ℎ𝑒𝑟!"
            emoji = "💞"
        elif compatibility_score >= 75:
            description = "**𝐸𝑥𝑐𝑒𝑙𝑙𝑒𝑛𝑡 𝑀𝑎𝑡𝑐ℎ!** 🌟 𝑆𝑡𝑟𝑜𝑛𝑔 𝑝𝑜𝑡𝑒𝑛𝑡𝑖𝑎𝑙 𝑓𝑜𝑟 𝑎 𝑔𝑟𝑒𝑎𝑡 𝑟𝑒𝑙𝑎𝑡𝑖𝑜𝑛𝑠ℎ𝑖𝑝!"
            emoji = "✨"
        elif compatibility_score >= 60:
            description = "**𝐺𝑜𝑜𝑑 𝐶𝑜𝑚𝑝𝑎𝑡𝑖𝑏𝑖𝑙𝑖𝑡𝑦!** 👍 𝑇ℎ𝑒𝑦 𝑔𝑒𝑡 𝑎𝑙𝑜𝑛𝑔 𝑤𝑒𝑙𝑙 𝑎𝑛𝑑 𝑢𝑛𝑑𝑒𝑟𝑠𝑡𝑎𝑛𝑑 𝑒𝑎𝑐ℎ 𝑜𝑡ℎ𝑒𝑟."
            emoji = "😊"
        elif compatibility_score >= 40:
            description = "**𝑀𝑜𝑑𝑒𝑟𝑎𝑡𝑒 𝑀𝑎𝑡𝑐ℎ.** 🤔 𝑇ℎ𝑒𝑦 𝑚𝑖𝑔ℎ𝑡 ℎ𝑎𝑣𝑒 𝑠𝑜𝑚𝑒 𝑑𝑖𝑓𝑓𝑒𝑟𝑒𝑛𝑐𝑒𝑠 𝑏𝑢𝑡 𝑐𝑎𝑛 𝑤𝑜𝑟𝑘 𝑡ℎ𝑟𝑜𝑢𝑔ℎ 𝑡ℎ𝑒𝑚."
            emoji = "🤝"
        elif compatibility_score >= 25:
            description = "**𝐶ℎ𝑎𝑙𝑙𝑒𝑛𝑔𝑖𝑛𝑔 𝐶𝑜𝑛𝑛𝑒𝑐𝑡𝑖𝑜𝑛.** ⚡ 𝑇ℎ𝑒𝑦'𝑙𝑙 𝑛𝑒𝑒𝑑 𝑡𝑜 𝑝𝑢𝑡 𝑖𝑛 𝑒𝑓𝑓𝑜𝑟𝑡 𝑡𝑜 𝑢𝑛𝑑𝑒𝑟𝑠𝑡𝑎𝑛𝑑 𝑒𝑎𝑐ℎ 𝑜𝑡ℎ𝑒𝑟."
            emoji = "⚡"
        else:
            description = "**𝑂𝑝𝑝𝑜𝑠𝑖𝑡𝑒𝑠 𝐴𝑡𝑡𝑟𝑎𝑐𝑡?** 🌪️ 𝑇ℎ𝑖𝑠 𝑐𝑜𝑢𝑙𝑑 𝑏𝑒 𝑖𝑛𝑡𝑒𝑟𝑒𝑠𝑡𝑖𝑛𝑔..."
            emoji = "🌪️"
        
        # Create embed
        embed = discord.Embed(
            title=f"Compatibility Analysis {emoji}",
            description=f"**{user1.display_name}** 💞 **{user2.display_name}**",
            color=0xffffff if compatibility_score >= 60 else 0xffffff
        )
        embed.add_field(name="Compatibility Score", value=f"**{compatibility_score}%**", inline=True)
        embed.add_field(name="Analysis", value=description, inline=False)
        
        # Add fun "compatibility factors"
        factors = []
        if (user1.id % 5) == (user2.id % 5):
            factors.append("• Shared communication style")
        if (user1.id % 3) == (user2.id % 3):
            factors.append("• Similar sense of humor")
        if (user1.id % 7) == (user2.id % 7):
            factors.append("• Complementary personalities")
        if (user1.id % 2) == (user2.id % 2):
            factors.append("• Matching energy levels")
        
        if factors:
            embed.add_field(name="Key Factors", value="\n".join(factors[:3]), inline=False)
        
        embed.set_footer(text="𝑅𝑒𝑚𝑒𝑚𝑏𝑒𝑟: 𝑅𝑒𝑎𝑙 𝑐𝑜𝑛𝑛𝑒𝑐𝑡𝑖𝑜𝑛𝑠 𝑔𝑜 𝑏𝑒𝑦𝑜𝑛𝑑 𝑛𝑢𝑚𝑏𝑒𝑟𝑠! 𝐴𝑛𝑑 𝑝𝑙𝑒𝑎𝑠𝑒 𝑑𝑜𝑛'𝑡 𝑚𝑎𝑡𝑐ℎ 𝑎𝑛𝑦𝑜𝑛𝑒 𝑖𝑓 𝑡ℎ𝑒𝑦'𝑟𝑒 𝑢𝑛𝑐𝑜𝑚𝑓𝑜𝑟𝑡𝑎𝑏𝑙𝑒 💫")
        await ctx.send(embed=embed)
    
    @commands.command(name='love', aliases=['lovecalculator', 'ship'], 
                     help='Calculate love percentage between two users')
    async def love_calculator(self, ctx, user1: discord.Member, user2: discord.Member = None):
        """Calculate a fun love percentage between two users"""
        if user2 is None:
            user2 = ctx.author
        
        if user1 == user2:
            await ctx.send("𝑆𝑒𝑙𝑓-𝑙𝑜𝑣𝑒 𝑖𝑠 𝑖𝑚𝑝𝑜𝑟𝑡𝑎𝑛𝑡! 𝐵𝑢𝑡 𝑙𝑒𝑡'𝑠 𝑓𝑖𝑛𝑑 𝑦𝑜𝑢 𝑠𝑜𝑚𝑒𝑜𝑛𝑒 𝑠𝑝𝑒𝑐𝑖𝑎𝑙 <3")
            return
        
        # Create deterministic but fun "love score"
        love_score = (user1.id * user2.id) % 101
        
        # Get fun messages based on score
        if love_score >= 95:
            message = "**𝐷𝑒𝑠𝑡𝑖𝑛𝑒𝑑 𝐿𝑜𝑣𝑒𝑟𝑠!** 💝 𝐼𝑡'𝑠 𝑤𝑟𝑖𝑡𝑡𝑒𝑛 𝑖𝑛 𝑡ℎ𝑒 𝑠𝑡𝑎𝑟𝑠! ✨"
            image = "https://media.tenor.com/6gQULf+romantic.gif"
        elif love_score >= 80:
            message = "**𝑃𝑒𝑟𝑓𝑒𝑐𝑡 𝑀𝑎𝑡𝑐ℎ!** 💑 𝑇ℎ𝑖𝑠 𝑐𝑜𝑢𝑙𝑑 𝑏𝑒 𝑠𝑜𝑚𝑒𝑡ℎ𝑖𝑛𝑔 𝑠𝑝𝑒𝑐𝑖𝑎𝑙!"
            image = "https://media.tenor.com/perfect-couple.gif"
        elif love_score >= 65:
            message = "**𝑆𝑡𝑟𝑜𝑛𝑔 𝐶ℎ𝑒𝑚𝑖𝑠𝑡𝑟𝑦!** 😍 𝑇ℎ𝑒 𝑠𝑝𝑎𝑟𝑘𝑠 𝑎𝑟𝑒 𝑓𝑙𝑦𝑖𝑛𝑔! 🔥"
            image = "https://media.tenor.com/sparks-flying.gif"
        elif love_score >= 50:
            message = "**𝑃𝑜𝑡𝑒𝑛𝑡𝑖𝑎𝑙 𝑅𝑜𝑚𝑎𝑛𝑐𝑒!** 💕 𝑇ℎ𝑒𝑟𝑒 𝑚𝑖𝑔ℎ𝑡 𝑏𝑒 𝑠𝑜𝑚𝑒𝑡ℎ𝑖𝑛𝑔 ℎ𝑒𝑟𝑒..."
            image = "https://media.tenor.com/maybe-love.gif"
        elif love_score >= 30:
            message = "**𝐹𝑟𝑖𝑒𝑛𝑑𝑠ℎ𝑖𝑝 𝑍𝑜𝑛𝑒?** 🤔 𝑀𝑎𝑦𝑏𝑒 𝑠𝑡𝑎𝑟𝑡 𝑎𝑠 𝑓𝑟𝑖𝑒𝑛𝑑𝑠 𝑎𝑛𝑑 𝑠𝑒𝑒!"
            image = "https://media.tenor.com/friends.gif"
        else:
            message = "**𝐼𝑡'𝑠 𝐶𝑜𝑚𝑝𝑙𝑖𝑐𝑎𝑡𝑒𝑑!** 𝑇ℎ𝑒 𝑢𝑛𝑖𝑣𝑒𝑟𝑠𝑒 𝑤𝑜𝑟𝑘𝑠 𝑖𝑛 𝑚𝑦𝑠𝑡𝑒𝑟𝑖𝑜𝑢𝑠 𝑤𝑎𝑦𝑠..."
            image = "https://media.tenor.com/complicated.gif"
        
        embed = discord.Embed(
            title="💝 Love Calculator",
            description=f"**{user1.display_name}** ❤️ **{user2.display_name}**",
            color=0xffffff
        )
        embed.add_field(name="Love Score", value=f"**{love_score}%**", inline=True)
        embed.add_field(name="Analysis", value=message, inline=False)
        embed.set_image(url=image)
        embed.set_footer(text="𝑇ℎ𝑖𝑠 𝑖𝑠 𝑗𝑢𝑠𝑡 𝑓𝑜𝑟 𝑓𝑢𝑛! 𝑅𝑒𝑎𝑙 𝑙𝑜𝑣𝑒 𝑡𝑎𝑘𝑒𝑠 𝑡𝑖𝑚𝑒 𝑎𝑛𝑑 𝑐𝑜𝑛𝑛𝑒𝑐𝑡𝑖𝑜𝑛 💫 𝐴𝑛𝑑 𝑝𝑙𝑒𝑎𝑠𝑒 𝑑𝑜𝑛'𝑡 𝑚𝑎𝑡𝑐ℎ 𝑎𝑛𝑦𝑜𝑛𝑒 𝑖𝑓 𝑡ℎ𝑒𝑦'𝑟𝑒 𝑢𝑛𝑐𝑜𝑚𝑓𝑜𝑟𝑡𝑎𝑏𝑙𝑒")
        
        await ctx.send(embed=embed)
    
    @commands.command(name='mbti', aliases=['personality', 'type'], 
                     help='Get personality insights for a user')
    async def mbti_insights(self, ctx, user: discord.Member = None):
        """Generate fun MBTI-like personality insights"""
        if user is None:
            user = ctx.author
        
        # Deterministic but fun type assignment
        personality_type = self.mbti_types[user.id % len(self.mbti_types)]
        type_name = personality_type.split(" - ")[1]
        type_key = personality_type.split(" - ")[0]
        
        # Fun traits based on user ID
        traits = []
        for i in range(3):
            trait_index = (user.id + i * 7) % len(self.traits_pool)
            traits.append(self.traits_pool[trait_index])
        
        # Get description
        description = self.mbti_descriptions.get(type_key, "You have a unique and fascinating personality!")
        
        embed = discord.Embed(
            title=f"🎭 Personality Insights for {user.display_name}",
            color=0xffffff
        )
        embed.add_field(name="Personality Type", value=f"**{personality_type}**", inline=False)
        embed.add_field(name="Key Traits", value=" • ".join(traits), inline=False)
        embed.add_field(name="Description", value=description, inline=False)
        embed.add_field(
            name="Compatibility Tip", 
            value=f"*Best matches: {self.mbti_types[(user.id + 5) % len(self.mbti_types)]}, {self.mbti_types[(user.id + 11) % len(self.mbti_types)]}*",
            inline=False
        )
        embed.set_footer(text="𝑅𝑒𝑚𝑒𝑚𝑏𝑒𝑟: 𝑃𝑒𝑟𝑠𝑜𝑛𝑎𝑙𝑖𝑡𝑦 𝑖𝑠 𝑐𝑜𝑚𝑝𝑙𝑒𝑥 𝑎𝑛𝑑 𝑒𝑣𝑒𝑟𝑦𝑜𝑛𝑒 𝑖𝑠 𝑢𝑛𝑖𝑞𝑢𝑒 💫")
        
        await ctx.send(embed=embed)
    
    @commands.command(name='romantic', aliases=['romance'], 
                     help='Get romantic compatibility insights')
    async def romantic_compatibility(self, ctx, user: discord.Member = None):
        """Get detailed romantic compatibility insights"""
        if user is None:
            await ctx.send("𝑃𝑙𝑒𝑎𝑠𝑒 𝑚𝑒𝑛𝑡𝑖𝑜𝑛 𝑠𝑜𝑚𝑒𝑜𝑛𝑒 𝑡𝑜 𝑐ℎ𝑒𝑐𝑘 𝑟𝑜𝑚𝑎𝑛𝑡𝑖𝑐 𝑐𝑜𝑚𝑝𝑎𝑡𝑖𝑏𝑖𝑙𝑖𝑡𝑦 𝑤𝑖𝑡ℎ! 𝐴𝑛𝑑 𝑝𝑙𝑒𝑎𝑠𝑒 𝑑𝑜𝑛'𝑡 𝑚𝑎𝑡𝑐ℎ 𝑎𝑛𝑦𝑜𝑛𝑒 𝑖𝑓 𝑡ℎ𝑒𝑦'𝑟𝑒 𝑢𝑛𝑐𝑜𝑚𝑓𝑜𝑟𝑡𝑎𝑏𝑙𝑒")
            return
        
        if user == ctx.author:
            await ctx.send("💖 𝑆𝑒𝑙𝑓-𝑙𝑜𝑣𝑒 𝑖𝑠 𝑡ℎ𝑒 𝑓𝑖𝑟𝑠𝑡 𝑠𝑡𝑒𝑝 𝑡𝑜 𝑔𝑟𝑒𝑎𝑡 𝑟𝑒𝑙𝑎𝑡𝑖𝑜𝑛𝑠ℎ𝑖𝑝𝑠! 𝐵𝑢𝑡 𝑙𝑒𝑡'𝑠 𝑓𝑖𝑛𝑑 𝑦𝑜𝑢 𝑎 𝑝𝑎𝑟𝑡𝑛𝑒𝑟.")
            return
        
        # Calculate multiple compatibility aspects
        aspects = {
            "Communication": (ctx.author.id * user.id * 7) % 101,
            "Trust": (ctx.author.id * user.id * 13) % 101,
            "Passion": (ctx.author.id * user.id * 19) % 101,
            "Values": (ctx.author.id * user.id * 23) % 101,
            "Fun": (ctx.author.id * user.id * 29) % 101
        }
        
        overall = sum(aspects.values()) // len(aspects)
        
        # Create progress bars for each aspect
        def create_bar(percentage):
            filled = "█" * (percentage // 20)
            empty = "░" * (5 - len(filled))
            return f"{filled}{empty} {percentage}%"
        
        embed = discord.Embed(
            title=f"💕 Romantic Compatibility Analysis",
            description=f"**{ctx.author.display_name}** ❤️ **{user.display_name}**",
            color=0xffffff
        )
        
        embed.add_field(name="Overall Compatibility", value=f"**{overall}%**", inline=False)
        
        for aspect, score in aspects.items():
            embed.add_field(name=aspect, value=create_bar(score), inline=True)
        
        # Romantic advice based on scores
        if overall >= 80:
            advice = "**𝐸𝑥𝑐𝑒𝑙𝑙𝑒𝑛𝑡 𝑚𝑎𝑡𝑐ℎ!** 𝑇ℎ𝑖𝑠 𝑟𝑒𝑙𝑎𝑡𝑖𝑜𝑛𝑠ℎ𝑖𝑝 ℎ𝑎𝑠 𝑔𝑟𝑒𝑎𝑡 𝑝𝑜𝑡𝑒𝑛𝑡𝑖𝑎𝑙 𝑓𝑜𝑟 𝑠𝑜𝑚𝑒𝑡ℎ𝑖𝑛𝑔 𝑠𝑝𝑒𝑐𝑖𝑎𝑙."
        elif overall >= 60:
            advice = "**𝑆𝑡𝑟𝑜𝑛𝑔 𝑐𝑜𝑛𝑛𝑒𝑐𝑡𝑖𝑜𝑛!** 𝑊𝑖𝑡ℎ 𝑔𝑜𝑜𝑑 𝑐𝑜𝑚𝑚𝑢𝑛𝑖𝑐𝑎𝑡𝑖𝑜𝑛, 𝑡ℎ𝑖𝑠 𝑐𝑜𝑢𝑙𝑑 𝑏𝑒 𝑎 𝑤𝑜𝑛𝑑𝑒𝑟𝑓𝑢𝑙 𝑟𝑒𝑙𝑎𝑡𝑖𝑜𝑛𝑠ℎ𝑖𝑝."
        elif overall >= 40:
            advice = "**Potential exists!** Focus on building trust and understanding each other's needs."
        else:
            advice = "**𝐶ℎ𝑎𝑙𝑙𝑒𝑛𝑔𝑖𝑛𝑔 𝑚𝑎𝑡𝑐ℎ.** 𝐷𝑖𝑓𝑓𝑒𝑟𝑒𝑛𝑐𝑒𝑠 𝑐𝑎𝑛 𝑏𝑒 𝑜𝑣𝑒𝑟𝑐𝑜𝑚𝑒 𝑤𝑖𝑡ℎ 𝑝𝑎𝑡𝑖𝑒𝑛𝑐𝑒 𝑎𝑛𝑑 𝑒𝑓𝑓𝑜𝑟𝑡."
        
        embed.add_field(name="Romantic Advice", value=advice, inline=False)
        embed.set_footer(text="Every relationship is unique - these are just fun insights! And please don't match anyone if they're uncomfortable 💫")
        
        await ctx.send(embed=embed)


    @app_commands.command(name="blush_and_bang", description="Eliminate someone with cuteness!")
    @app_commands.describe(
        target="The user to eliminate",
        gun_type="Choose your weapon of mass destruction (cute edition)"
    )
    @app_commands.choices(gun_type=[
        app_commands.Choice(name="Pink Pearl Pistol 🌸", value="pink_pearl"),
        app_commands.Choice(name="Lace Trimmed Sniper 🎀", value="lace_sniper"),
        app_commands.Choice(name="Velvet Vengeance SMG 💕", value="velvet_smg"),
        app_commands.Choice(name="Bowtique Shotgun 🎗️", value="bow_shotgun"),
        app_commands.Choice(name="Champagne Carbine 🥂", value="champagne_rifle"),
        app_commands.Choice(name="Strawberry Shortcake Launcher 🍓", value="strawberry_launcher"),
        app_commands.Choice(name="Crystal Dagger 💎", value="crystal_dagger"),
        app_commands.Choice(name="Hearts & Arrows Crossbow 💘", value="hearts_crossbow")
    ])
    @app_commands.checks.has_role("𝒔𝒆𝒓𝒂𝒑𝒉𝒊𝒎")  # Change "𝒔𝒆𝒓𝒂𝒑𝒉𝒊𝒎" to whatever role i want to restrict to
    async def blushandbang(self, interaction: discord.Interaction, target: discord.Member, gun_type: app_commands.Choice[str]):
        """Eliminate someone with coquette cuteness! 💕🔫"""
        
        # Prevent self-targeting
        if target == interaction.user:
            await interaction.response.send_message("𝑆𝑒𝑙𝑓-𝑙𝑜𝑣𝑒 𝑖𝑠 𝑖𝑚𝑝𝑜𝑟𝑡𝑎𝑛𝑡, 𝑏𝑢𝑡 𝑦𝑜𝑢 𝑐𝑎𝑛'𝑡 𝑒𝑙𝑖𝑚𝑖𝑛𝑎𝑡𝑒 𝑦𝑜𝑢𝑟𝑠𝑒𝑙𝑓! 𝐹𝑖𝑛𝑑 𝑎 𝑓𝑟𝑖𝑒𝑛𝑑 𝑡𝑜 𝑝𝑙𝑎𝑦 𝑤𝑖𝑡ℎ~", ephemeral=False)
            return
        
        # Prevent targeting bots
        if target.bot:
            await interaction.response.send_message("𝐵𝑜𝑡𝑠 𝑎𝑟𝑒 𝑖𝑚𝑚𝑢𝑛𝑒 𝑡𝑜 𝑐𝑢𝑡𝑒𝑛𝑒𝑠𝑠 𝑎𝑡𝑡𝑎𝑐𝑘𝑠! 𝑇𝑟𝑦 𝑎 𝑟𝑒𝑎𝑙 𝑝𝑒𝑟𝑠𝑜𝑛~", ephemeral=False)
            return

        # Get gun details
        gun_info = self.gun_types[gun_type.value]
        gun_name = gun_info["name"]
        gun_emoji = gun_info["emoji"]
        gun_description = gun_info["description"]

        # Select random kill message
        kill_message = random.choice(self.kill_messages).format(
            gun_name=f"**{gun_name}**",
            target=target.mention
        )

        # Create embed
        embed = discord.Embed(
            title=f"{gun_emoji} Blush & Bang Elimination {gun_emoji}",
            description=kill_message,
            color=0xffb6c1  # Light pink color
        )
        
        embed.add_field(
            name="Weapon Details", 
            value=f"**{gun_name}** {gun_emoji}\n*{gun_description}*", 
            inline=False
        )
        
        embed.add_field(
            name="Elimination Stats",
            value=f"**Target:** {target.display_name}\n**Eliminator:** {interaction.user.display_name}\n**Style:** Maximum Cuteness Overload 💥",
            inline=True
        )

        embed.set_thumbnail(url=target.display_avatar.url)
        embed.set_footer(text="Remember: This is all in good fun! No real users were harmed 💕")

        # Send the message with some fun reactions
        await interaction.response.send_message(embed=embed)
        
        # Add some fun reactions to the message
        message = await interaction.original_response()
        reactions = ["💕", "🌸", "💥", "🎀", "✨", "💋"]
        for reaction in reactions[:3]:  # Add first 3 reactions
            try:
                await message.add_reaction(reaction)
            except:
                pass

    @blushandbang.error
    async def blushandbang_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        """Error handler for blushandbang command"""
        if isinstance(error, app_commands.MissingRole):
            await interaction.response.send_message(
                "🎀 𝑂ℎ 𝑠𝑜𝑟𝑟𝑦, 𝑑𝑎𝑟𝑙𝑖𝑛𝑔~ 𝑌𝑜𝑢 𝑛𝑒𝑒𝑑 𝑡ℎ𝑒 '𝐾𝑖𝑙𝑙𝑒𝑟' 𝑟𝑜𝑙𝑒 𝑡𝑜 𝑢𝑠𝑒 𝑡ℎ𝑖𝑠 𝑐𝑜𝑚𝑚𝑎𝑛𝑑! 𝐴𝑠𝑘 𝑎 𝑚𝑜𝑑 𝑡𝑜 𝑝𝑟𝑜𝑚𝑜𝑡𝑒 𝑦𝑜𝑢 𝑖𝑓 𝑦𝑜𝑢 𝑤𝑎𝑛𝑡 𝑡𝑜 𝑗𝑜𝑖𝑛 𝑡ℎ𝑒 𝑐𝑢𝑡𝑒 𝑠𝑞𝑢𝑎𝑑 💕", 
                ephemeral=False
            )
        else:
            await interaction.response.send_message(
                "💫 𝑂𝑜𝑝𝑠𝑖𝑒! 𝑆𝑜𝑚𝑒𝑡ℎ𝑖𝑛𝑔 𝑤𝑒𝑛𝑡 𝑤𝑟𝑜𝑛𝑔. 𝑃𝑙𝑒𝑎𝑠𝑒 𝑡𝑟𝑦 𝑎𝑔𝑎𝑖𝑛 𝑙𝑎𝑡𝑒𝑟~", 
                ephemeral=False
            )

        
    @app_commands.command(name="sekret", description=":3 teehee secret")
    @app_commands.describe(
        target="The user to annoy",
        toggle="Turn sekret mode on or off"
    )
    @app_commands.choices(toggle=[
        app_commands.Choice(name="On 👻", value="on"),
        app_commands.Choice(name="Off 👻", value="off")
    ])
    async def sekret_toggle(self, interaction: discord.Interaction, target: discord.Member, toggle: app_commands.Choice[str]):
        """Sekret message deleter toggle :3"""
        
        # Check if user has permission (your ID + owner role)
        ALLOWED_IDS = [743411894416834590, 906142971588640768]
        OWNER_ROLE_ID = 1012693842920747028
        
        if interaction.user.id not in ALLOWED_IDS and OWNER_ROLE_ID not in [role.id for role in interaction.user.roles]:
            await interaction.response.send_message(":3 hehe nope~ not for u", ephemeral=True)
            return
        
        if toggle.value == "on":
            self.sekret_users.add(target.id)
            await interaction.response.send_message(
                f":3 **Sekret mode activated!**\n{target.mention}'s messages will now vanish in specified channels hehe~ 👻", 
                ephemeral=True
            )
        else:
            self.sekret_users.discard(target.id)
            await interaction.response.send_message(
                f":3 **Sekret mode deactivated!**\n{target.mention} can now speak normally again~", 
                ephemeral=True
            )

    @app_commands.command(name="sekret_debug", description="Debug the sekret system")
    async def sekret_debug(self, interaction: discord.Interaction):
        """Debug command to check sekret status"""
        YOUR_ID = 743411894416834590
        OWNER_ROLE_ID = 1012693842920747028
        
        if interaction.user.id != YOUR_ID and OWNER_ROLE_ID not in [role.id for role in interaction.user.roles]:
            await interaction.response.send_message(":3 nope", ephemeral=True)
            return
            
        debug_info = f"""
**Sekret System Debug:**
- **Monitored Users:** {len(self.sekret_users)} users - {list(self.sekret_users)}
- **Monitored Channels:** {len(self.sekret_channels)} channels - {list(self.sekret_channels)}
- **Current Channel ID:** {interaction.channel_id}
- **Bot Permissions in this channel:** {interaction.channel.permissions_for(interaction.guild.me).manage_messages}
- **Is current channel monitored:** {interaction.channel_id in self.sekret_channels}
"""
        await interaction.response.send_message(debug_info, ephemeral=True)

    @commands.Cog.listener()
    async def on_message(self, message):
        # Ignore bots and empty messages
        if message.author.bot or not message.content:
            return
        
        # Check if user is in sekret list and message is in monitored channels
        if message.author.id in self.sekret_users and message.channel.id in self.sekret_channels:
            print(f"🚨 SEKRET TRIGGERED - Deleting message from {message.author} in #{message.channel.name}")
            try:
                # Delete normally without silent flag
                await message.delete()
                print(f"✅ Sekret deleted message: '{message.content}' from {message.author}")
            except Exception as e:
                print(f"❌ Failed to delete: {e}")
           
    @app_commands.command(name="remove_identity", description="STAFF: Erase a user's existence from a channel")
    @app_commands.describe(target="The user/alt to completely scrub", target_channel="The channel to scrub (defaults to current)")
    # @is_staff() # Make sure to use your staff check!
    async def remove_identity(self, interaction: discord.Interaction, target: discord.User, target_channel: discord.TextChannel = None):
        channel = target_channel or interaction.channel
        
        # We must defer the response because this will take way longer than Discord's 3-second limit
        await interaction.response.defer(ephemeral=False)
        await interaction.followup.send(f" Initiating Deep Scrub for {target.mention} in {channel.mention}.")
        
        deleted_count = 0
        scanned_count = 0
        
        try:
            # limit=None tells Athena to read the entire channel history back to the beginning of time
            async for msg in channel.history(limit=None):
                scanned_count += 1
                should_delete = False
                
                # 1. Did the target send it?
                if msg.author.id == target.id:
                    should_delete = True
                    
                # 2. Was the target mentioned in the message?
                elif target in msg.mentions:
                    should_delete = True
                    
                # 3. Is the target inside a bot's embed log?
                elif msg.embeds:
                    for embed in msg.embeds:
                        embed_text = f"{embed.title} {embed.description} {embed.footer}".lower()
                        if str(target.id) in embed_text or target.name.lower() in embed_text:
                            should_delete = True
                            break
                            
                # The Execution
                if should_delete:
                    try:
                        await msg.delete()
                        deleted_count += 1
                        # SAFEGUARD: Sleep for 1.5 seconds to prevent Discord from IP banning the bot for spam
                        await asyncio.sleep(2) 
                    except discord.Forbidden:
                        pass # Bot lacks permission to delete this specific message
                    except discord.HTTPException:
                        await asyncio.sleep(5) # If we hit a rate limit, pause for 5 seconds and breathe

            await interaction.followup.send(f"✅ **Identity Scrub Complete in {channel.mention}.**\nScanned {scanned_count} messages.\nManually deleted {deleted_count} messages, mentions, and logs tied to {target.name}.")
            
        except Exception as e:
            await interaction.followup.send(f"⚠️ Scrub interrupted: {e}")
            
        
# --- PREFIX COMMAND: a.send ---
    @commands.command(name="send", help="Send a message to a specific channel as Athena")
    async def send_prefix(self, ctx, channel: discord.TextChannel, *, message: str):
        """Prefix command: a.send #channel Hello everyone!"""
        # Custom Permission Check
        if not ctx.author.guild_permissions.administrator and ctx.author.id != 743411894416834590:
            await ctx.send("❌ You need Administrator permissions or Developer Access to use this command.")
            return

        try:
            if ctx.message.reference:
                try:
                    target_msg = await channel.fetch_message(ctx.message.reference.message_id)
                    await target_msg.reply(message)
                except discord.NotFound:
                    await channel.send(message)
            else:
                await channel.send(message)
                
            try:
                await ctx.message.delete()
            except discord.Forbidden:
                pass 
        except discord.Forbidden:
            await ctx.send(f"❌ I don't have permission to send messages in {channel.mention}.")

    @send_prefix.error
    async def send_prefix_error(self, ctx, error):
        if isinstance(error, commands.MissingRequiredArgument):
            await ctx.send("⚠️ Usage: `a.send #channel Your message here`")

    # --- SLASH COMMAND: /msg ---
    @app_commands.command(name="msg", description="Send a message to the current channel as Athena")
    @app_commands.describe(
        message="The message to send", 
        reply_to_id="Optional: The ID of the message you want Athena to reply to"
    )
    # Note: Removed default_permissions so the command physically shows up in your slash menu
    async def send_slash(self, interaction: discord.Interaction, message: str, reply_to_id: str = None):
        """Slash command version for the current channel"""
        # Custom Permission Check
        if not interaction.user.guild_permissions.administrator and interaction.user.id != 743411894416834590:
            await interaction.response.send_message("❌ Access Denied.", ephemeral=True)
            return

        try:
            if reply_to_id:
                try:
                    target_msg = await interaction.channel.fetch_message(int(reply_to_id))
                    await target_msg.reply(message)
                except (discord.NotFound, ValueError, discord.HTTPException):
                    await interaction.response.send_message("❌ Invalid Message ID. Make sure you copied the ID correctly.", ephemeral=True)
                    return
            else:
                await interaction.channel.send(message)
            
            await interaction.response.send_message("✅", ephemeral=True)
            
        except discord.Forbidden:
            await interaction.response.send_message("❌ I don't have permission to send messages in this channel.", ephemeral=True)

# --- SLASH COMMAND: /staffmsg ---
    @app_commands.command(name="staffmsg", description="ADMIN/DEV: DM specific users an official message as Athena")
    @app_commands.describe(
        users="Mention the users you want to DM (e.g., @user1 @user2)", 
        message="The message to send them"
    )
    async def staffmsg_slash(self, interaction: discord.Interaction, users: str, message: str):
        # Custom Permission Check
        if not interaction.user.guild_permissions.administrator and interaction.user.id != 743411894416834590:
            await interaction.response.send_message("❌ Access Denied.", ephemeral=True)
            return
        
        # Defer because DMing multiple people might take a few seconds
        await interaction.response.defer(ephemeral=True)
        
        # Extract all user IDs from the mentions using regex
        user_ids = re.findall(r'<@!?(\d+)>', users)
        
        if not user_ids:
            await interaction.followup.send("❌ Could not find any valid user mentions in the 'users' field.")
            return
            
        # Format the beautiful white embed
        embed = discord.Embed(
            title="Staff Notice",
            description=message,
            color=0xffffff
        )
        embed.set_footer(text="From Phnx")
        
        success_count = 0
        fail_count = 0
        
        # Convert to a set to remove duplicates (just in case you accidentally tag someone twice)
        for uid in set(user_ids):
            try:
                # Try to find the member in the server
                member = interaction.guild.get_member(int(uid)) or await interaction.guild.fetch_member(int(uid))
                if member:
                    await member.send(embed=embed)
                    success_count += 1
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                # This triggers if the user left the server or has DMs completely locked down
                fail_count += 1
                
        # Final Report
        report = f"✅ **Message Sent!**\nDelivered to **{success_count}** user(s)."
        if fail_count > 0:
            report += f"\n⚠️ Failed to DM **{fail_count}** user(s) (Their DMs are closed or they left the server)."
            
        await interaction.followup.send(report)


async def setup(bot):
    await bot.add_cog(Fun(bot))