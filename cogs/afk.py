import discord
from discord.ext import commands
import time
import asyncio
import sqlite3

class AFK(commands.Cog):
    """AFK System"""
    
    def __init__(self, bot):
        self.bot = bot
        self.db_path = "athena_core.db"
        self.setup_db()
        
    def setup_db(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''CREATE TABLE IF NOT EXISTS afk (
            user_id INTEGER PRIMARY KEY,
            reason TEXT,
            timestamp REAL
        )''')
        conn.commit()
        conn.close()
    
    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot:
            return
            
        user_id = message.author.id
        content = message.content.strip()
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # 1. Check if user is returning from AFK
        cursor.execute("SELECT timestamp FROM afk WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()
        
        if row:
            if (content and not content.startswith(('a.', 'a!', '/'))) or message.attachments:
                afk_time = int(time.time() - row[0])
                hours, remainder = divmod(afk_time, 3600)
                minutes, seconds = divmod(remainder, 60)
                
                time_str = f"{hours}h {minutes}m {seconds}s" if hours > 0 else f"{minutes}m {seconds}s" if minutes > 0 else f"{seconds}s"
                
                cursor.execute("DELETE FROM afk WHERE user_id = ?", (user_id,))
                conn.commit()
                
                asyncio.create_task(
                    message.channel.send(
                        f"{message.author.mention} 𝑟𝑒𝑡𝑢𝑟𝑛𝑠 𝑓𝑟𝑜𝑚 𝑡ℎ𝑒 𝑎𝑏𝑦𝑠𝑠 𝑎𝑓𝑡𝑒𝑟 {time_str} . . . 𝑦𝑜𝑢𝑟 𝑎𝑓𝑘 𝑠𝑡𝑎𝑡𝑢𝑠 ℎ𝑎𝑠 𝑏𝑒𝑒𝑛 𝑟𝑒𝑚𝑜𝑣𝑒𝑑."
                    )
                )
        
        # 2. Check if message mentions any AFK users
        if message.mentions:
            mentioned_ids = [m.id for m in message.mentions if m.id != user_id]
            if mentioned_ids:
                placeholders = ','.join('?' * len(mentioned_ids))
                cursor.execute(f"SELECT user_id, reason, timestamp FROM afk WHERE user_id IN ({placeholders})", mentioned_ids)
                
                for m_id, reason, timestamp in cursor.fetchall():
                    member = message.guild.get_member(m_id) if message.guild else None
                    name = member.display_name if member else "A user"
                    
                    afk_time = int(time.time() - timestamp)
                    hours, remainder = divmod(afk_time, 3600)
                    minutes, seconds = divmod(remainder, 60)
                    
                    time_str = f"{hours}h {minutes}m" if hours > 0 else f"{minutes}m {seconds}s" if minutes > 0 else "just a moment"
                    
                    asyncio.create_task(
                        message.reply(
                            f"**{name}** 𝑖𝑠 𝑐𝑢𝑟𝑟𝑒𝑛𝑡𝑙𝑦 𝐴𝐹𝐾: {reason} "
                            f"(𝐴𝐹𝐾 𝑓𝑜𝑟 {time_str})",
                            mention_author=False
                        )
                    )
        conn.close()
    
    @commands.command(name='afk', aliases=['away'], help='Set your status as AFK with an optional reason')
    async def afk(self, ctx, *, reason="No reason provided"):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("INSERT OR REPLACE INTO afk (user_id, reason, timestamp) VALUES (?, ?, ?)", 
                      (ctx.author.id, reason, time.time()))
        conn.commit()
        conn.close()
        
        asyncio.create_task(ctx.send(f"{ctx.author.mention} 𝐷𝑒𝑎𝑟, 𝐼'𝑣𝑒 𝑠𝑒𝑡 𝑦𝑜𝑢𝑟 𝑠𝑡𝑎𝑡𝑢𝑠 𝑡𝑜 𝐴𝐹𝐾: {reason}"))

async def setup(bot):
    await bot.add_cog(AFK(bot))