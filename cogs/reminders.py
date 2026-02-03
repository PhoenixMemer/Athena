import discord
from discord.ext import commands, tasks
import time
import re
from collections import deque

class Reminders(commands.Cog):
    """Reminder System"""
    
    def __init__(self, bot):
        self.bot = bot
        self.reminders = []
        self.next_reminder_id = 1
        
        # Start the reminder background task
        self.check_reminders.start()
    
    def cog_unload(self):
        self.check_reminders.cancel()
    
    def parse_time(self, time_str):
        """Parse time string into seconds"""
        # Regex to match time components
        pattern = r'(\d+)([smhd])'
        matches = re.findall(pattern, time_str.lower())
        
        if not matches and time_str.isdigit():
            # Default to minutes if just a number
            return int(time_str) * 60
        
        total_seconds = 0
        for value, unit in matches:
            if unit == 's':
                total_seconds += int(value)
            elif unit == 'm':
                total_seconds += int(value) * 60
            elif unit == 'h':
                total_seconds += int(value) * 3600
            elif unit == 'd':
                total_seconds += int(value) * 86400
                
        return total_seconds
    
    def format_time(self, seconds):
        """Format seconds into human-readable time"""
        days, remainder = divmod(seconds, 86400)
        hours, remainder = divmod(remainder, 3600)
        minutes, seconds = divmod(remainder, 60)
        
        time_parts = []
        if days > 0:
            time_parts.append(f"{days} day{'s' if days > 1 else ''}")
        if hours > 0:
            time_parts.append(f"{hours} hour{'s' if hours > 1 else ''}")
        if minutes > 0:
            time_parts.append(f"{minutes} minute{'s' if minutes > 1 else ''}")
        if seconds > 0:
            time_parts.append(f"{seconds} second{'s' if seconds > 1 else ''}")
        
        return ' '.join(time_parts)
    
    @tasks.loop(seconds=30)
    async def check_reminders(self):
        """Check and send reminders every 30 seconds"""
        current_time = time.time()
        reminders_to_remove = []
        
        for reminder in self.reminders:
            if current_time >= reminder["reminder_time"]:
                try:
                    channel = self.bot.get_channel(reminder["channel_id"])
                    user = self.bot.get_user(reminder["user_id"])
                    if channel and user:
                        await channel.send(f"⏰ Reminder for {user.mention}: {reminder['message']}")
                    reminders_to_remove.append(reminder)
                except Exception as e:
                    print(f"Error sending reminder: {e}")
                    reminders_to_remove.append(reminder)
        
        # Remove processed reminders
        for reminder in reminders_to_remove:
            if reminder in self.reminders:
                self.reminders.remove(reminder)
    
    @check_reminders.before_loop
    async def before_check_reminders(self):
        """Wait until bot is ready before starting reminder checks"""
        await self.bot.wait_until_ready()
    
    @commands.command(name='remind', aliases=['reminder', 'timer'], 
                     help='Set a reminder. Usage: a.remind 1h30m Buy milk')
    async def remind(self, ctx, *, message: str = None):
        """
        Parse the entire message to extract time and reminder text.
        Expected format: <time><space><reminder text>
        Example: "1h30m Buy milk" or "15m Check the oven"
        """
        if message is None:
            # Show help if no arguments provided
            help_text = """
            **How to use the remind command:**
            `a.remind <time> <message>`
            
            **Examples:**
            `a.remind 1h30m Buy milk`
            `a.remind 15m Check the oven` 
            `a.remind 2d12h Call mom`
            `a.remind 45 Take pizza out` (45 minutes)
            
            **Time formats:** s (seconds), m (minutes), h (hours), d (days)
            """
            await ctx.send(help_text)
            return
        
        # Find the split between time and reminder text
        time_part = ''
        reminder_text = ''
        
        # Find where the time specification ends (first space after digits+letters)
        for i, char in enumerate(message):
            if char.isspace():
                # Found the end of time specification
                time_part = message[:i].strip()
                reminder_text = message[i:].strip()
                break
            elif not char.isdigit() and char not in 'smhd':  # If we encounter an invalid time character
                # This might be the reminder text starting without a space
                # Let's try to find the last valid time character
                for j in range(i, 0, -1):
                    if message[j] in 'smhd':
                        time_part = message[:j+1].strip()
                        reminder_text = message[j+1:].strip()
                        break
                break
        else:
            # No space found - entire message is probably time
            time_part = message.strip()
            reminder_text = "Reminder!"
        
        # If we couldn't extract time properly
        if not time_part:
            await ctx.send("𝑃𝑙𝑒𝑎𝑠𝑒 𝑠𝑝𝑒𝑐𝑖𝑓𝑦 𝑎 𝑡𝑖𝑚𝑒 (𝑒.𝑔., `1ℎ30𝑚`, `15𝑚`, `2𝑑`) 𝑓𝑜𝑙𝑙𝑜𝑤𝑒𝑑 𝑏𝑦 𝑦𝑜𝑢𝑟 𝑟𝑒𝑚𝑖𝑛𝑑𝑒𝑟 𝑡𝑒𝑥𝑡.")
            return
        
        # Convert time string to seconds
        seconds = self.parse_time(time_part)
        
        if seconds == 0:
            await ctx.send("𝑃𝑙𝑒𝑎𝑠𝑒 𝑠𝑝𝑒𝑐𝑖𝑓𝑦 𝑎 𝑣𝑎𝑙𝑖𝑑 𝑡𝑖𝑚𝑒 (𝑒.𝑔., `1ℎ30𝑚`, `15𝑚`, `2𝑑`)")
            return
        
        if seconds < 60:  # Minimum 1 minute
            await ctx.send("𝑃𝑙𝑒𝑎𝑠𝑒 𝑠𝑒𝑡 𝑎 𝑟𝑒𝑚𝑖𝑛𝑑𝑒𝑟 𝑓𝑜𝑟 𝑎𝑡 𝑙𝑒𝑎𝑠𝑡 1 𝑚𝑖𝑛𝑢𝑡𝑒.")
            return
        
        reminder_time = time.time() + seconds
        
        # Add reminder to list with unique ID
        reminder_id = self.next_reminder_id
        self.next_reminder_id += 1
        
        self.reminders.append({
            "id": reminder_id,
            "user_id": ctx.author.id,
            "channel_id": ctx.channel.id,
            "reminder_time": reminder_time,
            "message": reminder_text
        })
        
        # Calculate human-readable time
        time_display = self.format_time(seconds)
        
        await ctx.send(f"𝑅𝑒𝑚𝑖𝑛𝑑𝑒𝑟 #{reminder_id} 𝑠𝑒𝑡! 𝐼'𝑙𝑙 𝑟𝑒𝑚𝑖𝑛𝑑 𝑦𝑜𝑢 𝑖𝑛 {time_display}: {reminder_text}")
    
    @commands.command(name='reminders', aliases=['myreminders', 'listreminders'], 
                     help='List your active reminders')
    async def list_reminders(self, ctx):
        """List all active reminders for the user"""
        user_reminders = [r for r in self.reminders if r["user_id"] == ctx.author.id]
        
        if not user_reminders:
            await ctx.send("𝑌𝑜𝑢 𝑑𝑜𝑛'𝑡 ℎ𝑎𝑣𝑒 𝑎𝑛𝑦 𝑎𝑐𝑡𝑖𝑣𝑒 𝑟𝑒𝑚𝑖𝑛𝑑𝑒𝑟𝑠.")
            return
        
        reminder_list = []
        for reminder in user_reminders:
            time_left = int(reminder["reminder_time"] - time.time())
            if time_left <= 0:
                continue
                
            time_str = self.format_time(time_left)
            reminder_list.append(f"**#{reminder['id']}** - {time_str}: {reminder['message']}")
        
        if not reminder_list:
            await ctx.send("𝑌𝑜𝑢 𝑑𝑜𝑛'𝑡 ℎ𝑎𝑣𝑒 𝑎𝑛𝑦 𝑎𝑐𝑡𝑖𝑣𝑒 𝑟𝑒𝑚𝑖𝑛𝑑𝑒𝑟𝑠.")
            return
            
        await ctx.send(f"**𝑌𝑜𝑢𝑟 𝑎𝑐𝑡𝑖𝑣𝑒 𝑟𝑒𝑚𝑖𝑛𝑑𝑒𝑟𝑠:**\n" + "\n".join(reminder_list))
    
    @commands.command(name='removereminder', aliases=['deletereminder', 'cancelreminder', 'rmreminder'], 
                     help='Remove a reminder by its ID')
    async def remove_reminder(self, ctx, reminder_id: int = None):
        """Remove a specific reminder by its ID"""
        if reminder_id is None:
            # Check if user has any reminders first
            user_reminders = [r for r in self.reminders if r["user_id"] == ctx.author.id]
            if not user_reminders:
                await ctx.send("𝑌𝑜𝑢 𝑑𝑜𝑛'𝑡 ℎ𝑎𝑣𝑒 𝑎𝑛𝑦 𝑎𝑐𝑡𝑖𝑣𝑒 𝑟𝑒𝑚𝑖𝑛𝑑𝑒𝑟𝑠.")
                return
            else:
                # Show their reminders so they know what IDs to use
                reminder_list = []
                for reminder in user_reminders:
                    time_left = int(reminder["reminder_time"] - time.time())
                    time_str = self.format_time(time_left)
                    reminder_list.append(f"**#{reminder['id']}** - {time_str}: {reminder['message']}")
                
                await ctx.send(f"**𝑌𝑜𝑢𝑟 𝑎𝑐𝑡𝑖𝑣𝑒 𝑟𝑒𝑚𝑖𝑛𝑑𝑒𝑟𝑠:**\n" + "\n".join(reminder_list) + "\n\nUse `a.removereminder <ID>` to remove one.")
                return
        
        user_reminders = [r for r in self.reminders if r["user_id"] == ctx.author.id]
        reminder_to_remove = None
        
        for reminder in user_reminders:
            if reminder["id"] == reminder_id:
                reminder_to_remove = reminder
                break
        
        if reminder_to_remove:
            self.reminders.remove(reminder_to_remove)
            await ctx.send(f"𝑅𝑒𝑚𝑖𝑛𝑑𝑒𝑟 #{reminder_id} ℎ𝑎𝑠 𝑏𝑒𝑒𝑛 𝑟𝑒𝑚𝑜𝑣𝑒𝑑.")
        else:
            await ctx.send(f"𝐶𝑜𝑢𝑙𝑑𝑛'𝑡 𝑓𝑖𝑛𝑑 𝑟𝑒𝑚𝑖𝑛𝑑𝑒𝑟 #{reminder_id}. 𝑈𝑠𝑒 `𝑎.𝑟𝑒𝑚𝑖𝑛𝑑𝑒𝑟𝑠` 𝑡𝑜 𝑠𝑒𝑒 𝑦𝑜𝑢𝑟 𝑎𝑐𝑡𝑖𝑣𝑒 𝑟𝑒𝑚𝑖𝑛𝑑𝑒𝑟𝑠.")

async def setup(bot):
    await bot.add_cog(Reminders(bot))