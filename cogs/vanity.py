import discord
from discord.ext import commands, tasks
import asyncio
import logging

# Set up a logger for proper error reporting
logger = logging.getLogger(__name__)

class Vanity(commands.Cog):
    """Vanity URL Tracking System"""
    
    def __init__(self, bot):
        self.bot = bot
        self.vanity_urls = ["/cheriies", "/Cheriies", "discord.gg/Cheriies", "discord.gg/cheriies"]
        self.vanity_role_id = 1376492245448130651
        self.vanity_announcement_channel_id = 1400515374977650799
        self.vanity_embed_image = "https://i.pinimg.com/1200x/cb/38/25/cb382553542ef736d455d377bf8592e1.jpg"
        self.vanity_tracking = {}
        
        # Start checking existing members on ready
        self.check_existing_members.start()
    
    def cog_unload(self):
        self.check_existing_members.cancel()
    
    @tasks.loop(count=1)
    async def check_existing_members(self):
        """Check all existing members for vanity URLs on startup"""
        await self.bot.wait_until_ready()
        
        for guild in self.bot.guilds:
            for member in guild.members:
                if member.bot:
                    continue
                await self.check_vanity_url(member, force_check=True)
    
    async def check_vanity_url(self, member, force_check=False, is_presence_update=False):
        """Check if a member has vanity URL in their activities and manage role"""
        if member.bot:
            return False
        
        vanity_role = member.guild.get_role(self.vanity_role_id)
        #if not vanity_role:
            #logger.warning(f"⚠️ Vanity role ID {self.vanity_role_id} not found in guild {member.guild.name}")
            #return False
        
        # Skip checking presence updates for offline members (but still allow manual checks)
        if member.status == discord.Status.offline and not force_check:
            # If they already have the role and we've verified it before, keep it
            if vanity_role in member.roles and self.vanity_tracking.get(member.id):
                return True
            return False
        
        # Check for vanity URLs in activities
        has_vanity = False
        if member.activities:
            for activity in member.activities:
                if activity.name and any(url in activity.name for url in self.vanity_urls):
                    has_vanity = True
                    break
                if hasattr(activity, 'details') and activity.details and any(url in activity.details for url in self.vanity_urls):
                    has_vanity = True
                    break
                if hasattr(activity, 'state') and activity.state and any(url in activity.state for url in self.vanity_urls):
                    has_vanity = True
                    break
        
        has_role = vanity_role in member.roles
        
        if has_vanity and not has_role:
            # Add role and send announcement
            try:
                await member.add_roles(vanity_role)
                self.vanity_tracking[member.id] = True
                
                # Send announcement only if this is a new detection
                announcement_channel = self.bot.get_channel(self.vanity_announcement_channel_id)
                if announcement_channel:
                    embed = discord.Embed(
                        title="𝐴𝑛 𝐴𝑛𝑔𝑒𝑙 𝐻𝑎𝑠 𝐺𝑎𝑖𝑛𝑒𝑑 𝐼𝑡𝑠 𝑊𝑖𝑛𝑔𝑠..",
                        description=f"𝑇ℎ𝑎𝑛𝑘 𝑦𝑜𝑢 {member.mention} 𝑓𝑜𝑟 𝑟𝑒𝑝𝑝𝑖𝑛𝑔 /𝗰𝗵𝗲𝗿𝗶𝗶𝗲𝘀 ♡ 𓂃 𝑖𝑛 𝑦𝑜𝑢𝑟 𝑠𝑡𝑎𝑡𝑢𝑠 . . . <#1400815717506617494>",
                        color=0xffffff
                    )
                    embed.set_image(url=self.vanity_embed_image)
                    embed.set_footer(text="")
                    
                    await announcement_channel.send(embed=embed)
                return True
                
            except discord.Forbidden:
                logger.warning(f"⚠️ Missing permissions to add vanity role to {member.display_name}")
                return False
            except discord.HTTPException as e:
                logger.error(f"❌ HTTP error adding role to {member.display_name}: {e}")
                return False
        
        elif not has_vanity and has_role:
            # Remove role if they genuinely removed the vanity URL
            # But only if this is a real presence update (not just going offline)
            # OR if it's a manual force check
            if force_check or (is_presence_update and member.status != discord.Status.offline):
                try:
                    await member.remove_roles(vanity_role)
                    self.vanity_tracking[member.id] = False
                except discord.Forbidden:
                    logger.warning(f"⚠️ Missing permissions to remove vanity role from {member.display_name}. Check role hierarchy.")
                    return True  # They still have the role even though we can't remove it
                except discord.HTTPException as e:
                    logger.error(f"❌ HTTP error removing role from {member.display_name}: {e}")
                    return has_role
        
        return has_role
    
    @commands.Cog.listener()
    async def on_presence_update(self, before, after):
        """Check when a user updates their presence"""
        if before.bot:
            return
        
        # Only check if this is a meaningful presence update (not just going offline)
        if after.status != discord.Status.offline or before.activities != after.activities:
            await self.check_vanity_url(after, is_presence_update=True)
    
    @commands.Cog.listener()
    async def on_member_update(self, before, after):
        """Check when a member updates their profile"""
        if before.bot:
            return
        
        # Check if activities might have changed
        if before.activities != after.activities or before.display_name != after.display_name:
            await self.check_vanity_url(after, is_presence_update=True)
    
    @commands.command(name='checkvanity', aliases=['vanitycheck'], help='Manually check for vanity URL reps (Admin only)')
    @commands.has_permissions(administrator=True)
    async def check_vanity_command(self, ctx):
        """Manual check for vanity URL representations"""
        message = await ctx.send("🔄 Checking all members for vanity URLs...")
        
        count = 0
        for member in ctx.guild.members:
            if member.bot:
                continue
            
            result = await self.check_vanity_url(member, force_check=True)
            if result:
                count += 1
        
        await message.edit(content=f"Vanity check complete! {count} members have the vanity role.")
    
    @commands.command(name='vanityinfo', aliases=['vanityusers'], help='Show members with vanity role')
    async def vanity_info(self, ctx):
        """Show information about vanity role members"""
        vanity_role = ctx.guild.get_role(self.vanity_role_id)
        if not vanity_role:
            await ctx.send("Vanity role not configured.")
            return
        
        members_with_role = [member for member in vanity_role.members if not member.bot]
        
        if not members_with_role:
            await ctx.send("No members currently have the vanity role.")
            return
        
        # Create embed with member list
        embed = discord.Embed(
            title="𝑉𝑎𝑛𝑖𝑡𝑦 𝑅𝑜𝑙𝑒 𝑀𝑒𝑚𝑏𝑒𝑟𝑠",
            description=f"{len(members_with_role)} members repping /cheriies",
            color=0xffffff
        )
        
        member_list = []
        for member in members_with_role[:25]:  # Limit to first 25 members
            status_emoji = "🟢" if member.status != discord.Status.offline else "⚫"
            member_list.append(f"{status_emoji} {member.mention}")
        
        embed.add_field(
            name="Members", 
            value="\n".join(member_list) if member_list else "None",
            inline=False
        )
        
        if len(members_with_role) > 25:
            embed.set_footer(text=f"And {len(members_with_role) - 25} more members...")
        
        await ctx.send(embed=embed)

async def setup(bot):
    await bot.add_cog(Vanity(bot))