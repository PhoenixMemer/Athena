import discord
from discord.ext import commands, tasks
import time
import re
import sqlite3

class Reminders(commands.Cog):
    """Reminder System"""
    
    def __init__(self, bot):
        self.bot = bot
        self.db_path = "athena_core.db"
        self.setup_db()
        self.check_reminders.start()
        
    def setup_db(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''CREATE TABLE IF NOT EXISTS reminders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            channel_id INTEGER,
            reminder_time REAL,
            message TEXT
        )''')
        conn.commit()
        conn.close()
    
    def cog_unload(self):
        self.check_reminders.cancel()
    
    def parse_time(self, time_str):
        pattern = r'(\d+)([smhd])'
        matches = re.findall(pattern, time_str.lower())
        
        if not matches and time_str.isdigit():
            return int(time_str) * 60
        
        total_seconds = 0
        for value, unit in matches:
            if unit == 's': total_seconds += int(value)
            elif unit == 'm': total_seconds += int(value) * 60
            elif unit == 'h': total_seconds += int(value) * 3600
            elif unit == 'd': total_seconds += int(value) * 86400
                
        return total_seconds
    
    def format_time(self, seconds):
        days, remainder = divmod(seconds, 86400)
        hours, remainder = divmod(remainder, 3600)
        minutes, seconds = divmod(remainder, 60)
        
        time_parts = []
        if days > 0: time_parts.append(f"{days} day{'s' if days > 1 else ''}")
        if hours > 0: time_parts.append(f"{hours} hour{'s' if hours > 1 else ''}")
        if minutes > 0: time_parts.append(f"{minutes} minute{'s' if minutes > 1 else ''}")
        if seconds > 0: time_parts.append(f"{seconds} second{'s' if seconds > 1 else ''}")
        
        return ' '.join(time_parts)
    
    @tasks.loop(seconds=30)
    async def check_reminders(self):
        current_time = time.time()
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("SELECT id, user_id, channel_id, reminder_time, message FROM reminders WHERE reminder_time <= ?", (current_time,))
        due_reminders = cursor.fetchall()
        
        for r_id, user_id, channel_id, reminder_time, message in due_reminders:
            try:
                channel = self.bot.get_channel(channel_id)
                user = self.bot.get_user(user_id)
                if channel and user:
                    await channel.send(f"⏰ Reminder for {user.mention}: {message}")
            except Exception as e:
                print(f"Error sending reminder: {e}")
            
            # Remove processed reminder from database
            cursor.execute("DELETE FROM reminders WHERE id = ?", (r_id,))
            
        conn.commit()
        conn.close()
    
    @check_reminders.before_loop
    async def before_check_reminders(self):
        await self.bot.wait_until_ready()
    
    @commands.command(name='remind', aliases=['reminder', 'timer'], help='Set a reminder. Usage: a.remind 1h30m Buy milk')
    async def remind(self, ctx, *, message: str = None):
        if message is None:
            help_text = """
            **How to use the remind command:**
            `a.remind <time> <message>`
            
            **Examples:**
            `a.remind 1h30m Buy milk`
            `a.remind 15m Check the oven` 
            `a.remind 2d12h Call mom`
            """
            return await ctx.send(help_text)
        
        time_part, reminder_text = '', ''
        for i, char in enumerate(message):
            if char.isspace():
                time_part, reminder_text = message[:i].strip(), message[i:].strip()
                break
            elif not char.isdigit() and char not in 'smhd':
                for j in range(i, 0, -1):
                    if message[j] in 'smhd':
                        time_part, reminder_text = message[:j+1].strip(), message[j+1:].strip()
                        break
                break
        else:
            time_part, reminder_text = message.strip(), "Reminder!"
        
        if not time_part: return await ctx.send("𝑃𝑙𝑒𝑎𝑠𝑒 𝑠𝑝𝑒𝑐𝑖𝑓𝑦 𝑎 𝑡𝑖𝑚𝑒 (𝑒.𝑔., `1ℎ30𝑚`, `15𝑚`, `2𝑑`) 𝑓𝑜𝑙𝑙𝑜𝑤𝑒𝑑 𝑏𝑦 𝑦𝑜𝑢𝑟 𝑟𝑒𝑚𝑖𝑛𝑑𝑒𝑟 𝑡𝑒𝑥𝑡.")
        
        seconds = self.parse_time(time_part)
        if seconds == 0: return await ctx.send("𝑃𝑙𝑒𝑎𝑠𝑒 𝑠𝑝𝑒𝑐𝑖𝑓𝑦 𝑎 𝑣𝑎𝑙𝑖𝑑 𝑡𝑖𝑚𝑒 (𝑒.𝑔., `1ℎ30𝑚`, `15𝑚`, `2𝑑`)")
        if seconds < 60: return await ctx.send("𝑃𝑙𝑒𝑎𝑠𝑒 𝑠𝑒𝑡 𝑎 𝑟𝑒𝑚𝑖𝑛𝑑𝑒𝑟 𝑓𝑜𝑟 𝑎𝑡 𝑙𝑒𝑎𝑠𝑡 1 𝑚𝑖𝑛𝑢𝑡𝑒.")
        
        reminder_time = time.time() + seconds
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("INSERT INTO reminders (user_id, channel_id, reminder_time, message) VALUES (?, ?, ?, ?)", 
                      (ctx.author.id, ctx.channel.id, reminder_time, reminder_text))
        reminder_id = cursor.lastrowid
        conn.commit()
        conn.close()
        
        time_display = self.format_time(seconds)
        await ctx.send(f"𝑅𝑒𝑚𝑖𝑛𝑑𝑒𝑟 #{reminder_id} 𝑠𝑒𝑡! 𝐼'𝑙𝑙 𝑟𝑒𝑚𝑖𝑛𝑑 𝑦𝑜𝑢 𝑖𝑛 {time_display}: {reminder_text}")
    
    @commands.command(name='reminders', aliases=['myreminders', 'listreminders'], help='List your active reminders')
    async def list_reminders(self, ctx):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT id, reminder_time, message FROM reminders WHERE user_id = ?", (ctx.author.id,))
        user_reminders = cursor.fetchall()
        conn.close()
        
        if not user_reminders:
            return await ctx.send("𝑌𝑜𝑢 𝑑𝑜𝑛'𝑡 ℎ𝑎𝑣𝑒 𝑎𝑛𝑦 𝑎𝑐𝑡𝑖𝑣𝑒 𝑟𝑒𝑚𝑖𝑛𝑑𝑒𝑟𝑠.")
        
        reminder_list = []
        for r_id, r_time, msg in user_reminders:
            time_left = int(r_time - time.time())
            if time_left > 0:
                reminder_list.append(f"**#{r_id}** - {self.format_time(time_left)}: {msg}")
        
        if not reminder_list:
            return await ctx.send("𝑌𝑜𝑢 𝑑𝑜𝑛'𝑡 ℎ𝑎𝑣𝑒 𝑎𝑛𝑦 𝑎𝑐𝑡𝑖𝑣𝑒 𝑟𝑒𝑚𝑖𝑛𝑑𝑒𝑟𝑠.")
            
        await ctx.send(f"**𝑌𝑜𝑢𝑟 𝑎𝑐𝑡𝑖𝑣𝑒 𝑟𝑒𝑚𝑖𝑛𝑑𝑒𝑟𝑠:**\n" + "\n".join(reminder_list))
    
    @commands.command(name='removereminder', aliases=['deletereminder', 'cancelreminder', 'rmreminder'], help='Remove a reminder by its ID')
    async def remove_reminder(self, ctx, reminder_id: int = None):
        if reminder_id is None:
            return await ctx.send("𝑃𝑙𝑒𝑎𝑠𝑒 𝑝𝑟𝑜𝑣𝑖𝑑𝑒 𝑡ℎ𝑒 𝐼𝐷 𝑜𝑓 𝑡ℎ𝑒 𝑟𝑒𝑚𝑖𝑛𝑑𝑒𝑟 𝑦𝑜𝑢 𝑤𝑎𝑛𝑡 𝑡𝑜 𝑟𝑒𝑚𝑜𝑣𝑒. (𝑈𝑠𝑒 `a.reminders` 𝑡𝑜 𝑐ℎ𝑒𝑐𝑘)")
            
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM reminders WHERE id = ? AND user_id = ?", (reminder_id, ctx.author.id))
        
        if cursor.fetchone():
            cursor.execute("DELETE FROM reminders WHERE id = ?", (reminder_id,))
            conn.commit()
            conn.close()
            await ctx.send(f"𝑅𝑒𝑚𝑖𝑛𝑑𝑒𝑟 #{reminder_id} ℎ𝑎𝑠 𝑏𝑒𝑒𝑛 𝑟𝑒𝑚𝑜𝑣𝑒𝑑.")
        else:
            conn.close()
            await ctx.send(f"𝐶𝑜𝑢𝑙𝑑𝑛'𝑡 𝑓𝑖𝑛𝑑 𝑟𝑒𝑚𝑖𝑛𝑑𝑒𝑟 #{reminder_id}. 𝑈𝑠𝑒 `𝑎.𝑟𝑒𝑚𝑖𝑛𝑑𝑒𝑟𝑠` 𝑡𝑜 𝑠𝑒𝑒 𝑦𝑜𝑢𝑟 𝑎𝑐𝑡𝑖𝑣𝑒 𝑟𝑒𝑚𝑖𝑛𝑑𝑒𝑟𝑠.")

async def setup(bot):
    await bot.add_cog(Reminders(bot))