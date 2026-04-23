import discord
from discord.ext import commands
import time
import asyncio

class AFK(commands.Cog):
    """AFK System"""
    
    def __init__(self, bot):
        self.bot = bot
        self.afk_data = {}
    
    @commands.Cog.listener()
    async def on_message(self, message):
        # Ignore messages from bots
        if message.author.bot:
            return
            
        user_id = message.author.id
        content = message.content.strip()
        
        # 1. Check if user is returning from AFK
        if user_id in self.afk_data:
            # We removed the > 3 length check. Now we just ensure it's not a command.
            # We also check if they sent an attachment (like an image) as a sign of activity.
            if (content and not content.startswith(('a.', 'a!', '/'))) or message.attachments:
                afk_info = self.afk_data[user_id]
                afk_time = int(time.time() - afk_info["timestamp"])
                
                hours, remainder = divmod(afk_time, 3600)
                minutes, seconds = divmod(remainder, 60)
                
                if hours > 0:
                    time_str = f"{hours}h {minutes}m {seconds}s"
                elif minutes > 0:
                    time_str = f"{minutes}m {seconds}s"
                else:
                    time_str = f"{seconds}s"
                
                # Instantly remove them from the dictionary so the logic feels fast
                del self.afk_data[user_id]
                
                # Send the welcome back message as a background task to prevent API blocking
                asyncio.create_task(
                    message.channel.send(
                        f"{message.author.mention} 𝘳𝘦𝘵𝘶𝘳𝘯𝘴 𝘧𝘳𝘰𝘮 𝘵𝘩𝘦 𝘢𝘣𝘺𝘴𝘴..𝘺𝘰𝘶𝘳 𝘈𝘍𝘒 𝘴𝘵𝘢𝘵𝘶𝘴 𝘩𝘢𝘴 𝘣𝘦𝘦𝘯 𝘳𝘦𝘮𝘰𝘷𝘦𝘥. "
                        f"(𝘠𝘰𝘶 𝘸𝘦𝘳𝘦 𝘢𝘸𝘢𝘺 𝘧𝘰𝘳 {time_str})"
                    )
                )
        
        # 2. Check if message mentions any AFK users
        if message.mentions:
            for member in message.mentions:
                if member.id in self.afk_data and member.id != user_id:
                    afk_info = self.afk_data[member.id]
                    afk_time = int(time.time() - afk_info["timestamp"])
                    
                    hours, remainder = divmod(afk_time, 3600)
                    minutes, seconds = divmod(remainder, 60)
                    
                    if hours > 0:
                        time_str = f"{hours}h {minutes}m"
                    elif minutes > 0:
                        time_str = f"{minutes}m {seconds}s"
                    else:
                        time_str = f"just a moment"
                    
                    # Send ping notification in the background
                    asyncio.create_task(
                        message.reply(
                            f"**{member.display_name}** 𝑖𝑠 𝑐𝑢𝑟𝑟𝑒𝑛𝑡𝑙𝑦 𝐴𝐹𝐾: {afk_info['reason']} "
                            f"(𝐴𝐹𝐾 𝑓𝑜𝑟 {time_str})",
                            mention_author=False
                        )
                    )
    
    @commands.command(name='afk', aliases=['away'], help='Set your status as AFK with an optional reason')
    async def afk(self, ctx, *, reason="No reason provided"):
        """Set AFK status"""
        user_id = ctx.author.id
        
        self.afk_data[user_id] = {
            "reason": reason,
            "timestamp": time.time()
        }
        
        # Pushed to a background task so the command finishes instantly
        asyncio.create_task(
            ctx.send(f"{ctx.author.mention} 𝐷𝑒𝑎𝑟, 𝐼'𝑣𝑒 𝑠𝑒𝑡 𝑦𝑜𝑢𝑟 𝑠𝑡𝑎𝑡𝑢𝑠 𝑡𝑜 𝐴𝐹𝐾: {reason}")
        )

async def setup(bot):
    await bot.add_cog(AFK(bot))