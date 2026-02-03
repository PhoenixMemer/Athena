import discord
from discord.ext import commands
import time

class AFK(commands.Cog):
    """AFK System"""
    
    def __init__(self, bot):
        self.bot = bot
        self.afk_data = {}
    
    @commands.Cog.listener()
    async def on_message(self, message):
        """Handle AFK status on message"""
        # Ignore messages from bots
        if message.author.bot:
            return
            
        user_id = message.author.id
        
        # Check if user is returning from AFK (but only if they actually sent a real message)
        if user_id in self.afk_data:
            # Additional safety check: ignore very short messages that might be commands
            if len(message.content.strip()) > 3 and not message.content.startswith(('a.', 'a!')):
                afk_info = self.afk_data[user_id]
                afk_time = int(message.created_at.timestamp() - afk_info["timestamp"])
                
                # Format time string
                hours, remainder = divmod(afk_time, 3600)
                minutes, seconds = divmod(remainder, 60)
                time_str = f"{hours}h {minutes}m {seconds}s" if hours > 0 else f"{minutes}m {seconds}s"
                
                # Remove user from AFK data
                del self.afk_data[user_id]
                
                # Send welcome back message
                await message.channel.send(
                    f"{message.author.mention} 𝘳𝘦𝘵𝘶𝘳𝘯𝘴 𝘧𝘳𝘰𝘮 𝘵𝘩𝘦 𝘢𝘣𝘺𝘴𝘴..𝘺𝘰𝘶𝘳 𝘈𝘍𝘒 𝘴𝘵𝘢𝘵𝘶𝘴 𝘩𝘢𝘴 𝘣𝘦𝘦𝘯 𝘳𝘦𝘮𝘰𝘷𝘦𝘥. "
                    f"(𝘠𝘰𝘶 𝘸𝘦𝘳𝘦 𝘢𝘸𝘢𝘺 𝘧𝘰𝘳 {time_str})"
                )
        
        # Check if message mentions any AFK users
        for member in message.mentions:
            if member.id in self.afk_data and member.id != user_id:  # Ensure they don't ping themselves
                afk_info = self.afk_data[member.id]
                afk_time = int(message.created_at.timestamp() - afk_info["timestamp"])
                
                # Format time string
                hours, remainder = divmod(afk_time, 3600)
                minutes, seconds = divmod(remainder, 60)
                time_str = f"{hours}h {minutes}m {seconds}s" if hours > 0 else f"{minutes}m {seconds}s"
                
                # Reply with AFK status
                await message.reply(
                    f"**{member.display_name}** 𝑖𝑠 𝑐𝑢𝑟𝑟𝑒𝑛𝑡𝑙𝑦 𝐴𝐹𝐾: {afk_info['reason']} "
                    f"(𝐴𝐹𝐾 𝑓𝑜𝑟 {time_str})"
                )
    
    @commands.command(name='afk', aliases=['away'], help='Set your status as AFK with an optional reason')
    async def afk(self, ctx, *, reason="No reason provided"):
        """Set AFK status"""
        user_id = ctx.author.id
        self.afk_data[user_id] = {
            "reason": reason,
            "timestamp": ctx.message.created_at.timestamp()
        }
        await ctx.send(f"{ctx.author.mention} 𝐷𝑒𝑎𝑟, 𝐼'𝑣𝑒 𝑠𝑒𝑡 𝑦𝑜𝑢𝑟 𝑠𝑡𝑎𝑡𝑢𝑠 𝑡𝑜 𝐴𝐹𝐾: {reason}")

async def setup(bot):
    await bot.add_cog(AFK(bot))