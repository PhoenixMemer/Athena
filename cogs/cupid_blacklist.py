import discord
from discord import app_commands
from discord.ext import commands
import json
import os
from typing import List, Union

class CupidBlacklist(commands.Cog):
    """Cupid Blacklist Management System"""
    
    def __init__(self, bot):
        self.bot = bot
        self.blacklist_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'blacklist.json')
        self.blacklist = self.load_blacklist()
        
        # CHANGED: Now a proper Python List using brackets []
        self.CUPID_ROLE_IDS = [1218983330201075792, 1469797367153819678] 
        self.BLACKLISTED_CHANNELS = [
            1273939243600842795,  
            1273939292749561866,  
            1273945454853492746,
            1273926745724026891   
        ]
        self.ROLE_A_ID = 1418944629427929118  # Role to REMOVE
        self.ROLE_B_ID = 1421220600231231579  # Role to ADD
    
    def load_blacklist(self) -> dict:
        if os.path.exists(self.blacklist_file):
            # Check if Wispbyte created a 0-byte ghost file
            if os.path.getsize(self.blacklist_file) == 0:
                print("⚠️ blacklist.json is totally empty. Starting fresh to prevent crash.")
                return {}
            try:
                with open(self.blacklist_file, 'r') as f:
                    return json.load(f)
            except json.JSONDecodeError:
                # If the file has corrupted garbage in it, catch the error and survive
                print("⚠️ blacklist.json is corrupted! Starting fresh to prevent crash.")
                return {}
        return {}
    
    def save_blacklist(self):
        with open(self.blacklist_file, 'w') as f:
            json.dump(self.blacklist, f, indent=4)
    
    async def check_cupid_permission(self, interaction: discord.Interaction) -> bool:
        # CHANGED: Now loops through your user roles to see if they have ANY of the allowed staff roles
        user_role_ids = [role.id for role in interaction.user.roles]
        if any(role_id in self.CUPID_ROLE_IDS for role_id in user_role_ids) or interaction.user.guild_permissions.administrator:
            return True
            
        await interaction.response.send_message("*You need the Staffies role to use this command. Please contact high staff~*", ephemeral=True)
        return False
    
    async def update_member_roles(self, member: discord.Member, blacklisted: bool):
        try:
            role_a = member.guild.get_role(self.ROLE_A_ID)
            role_b = member.guild.get_role(self.ROLE_B_ID)
            
            if not role_a or not role_b:
                print(f"*Warning: Ophanim or Blacklist Role not found. A: {role_a}, B: {role_b}*")
                return
            
            if blacklisted:
                if role_a in member.roles:
                    await member.remove_roles(role_a)
                if role_b not in member.roles:
                    await member.add_roles(role_b)
            else:
                if role_b in member.roles:
                    await member.remove_roles(role_b)
                if role_a not in member.roles:
                    await member.add_roles(role_a)
                    
        except discord.Forbidden:
            print(f"*Missing permissions to modify roles for {member.display_name}*")
        except Exception as e:
            print(f"*Error updating roles for {member.display_name}: {e}*")
    
    async def get_user_info(self, user_id: int) -> dict:
        guild = self.bot.guilds[0] if self.bot.guilds else None
        if guild:
            member = guild.get_member(user_id)
            if member:
                return {
                    'name': f"{member.display_name} ({member.name})",
                    'mention': member.mention,
                    'is_in_server': True
                }
        
        user = self.bot.get_user(user_id)
        if user:
            return {
                'name': f"{user.name}",
                'mention': f"`{user.name}` (ID: {user_id})",
                'is_in_server': False
            }
        
        try:
            user = await self.bot.fetch_user(user_id)
            return {
                'name': f"{user.name}",
                'mention': f"`{user.name}` (ID: {user_id})",
                'is_in_server': False
            }
        except discord.NotFound:
            return {'name': f"Unknown User (ID: {user_id})", 'mention': f"`Unknown User` (ID: {user_id})", 'is_in_server': False}
        except discord.HTTPException:
            return {'name': f"Unknown User (ID: {user_id})", 'mention': f"`Unknown User` (ID: {user_id})", 'is_in_server': False}
    
    @app_commands.command(name="blacklist_add", description="Add a user to the nuclear blacklist")
    @app_commands.describe(user="The user to blacklist (mention or user ID)", reason="Reason for blacklisting")
    async def blacklist_add(self, interaction: discord.Interaction, user: str, reason: str = "No reason provided"):
        if not await self.check_cupid_permission(interaction): return
        
        await interaction.response.defer(ephemeral=False)
        
        user_id = user.strip('<@!>') if user.startswith('<@') and user.endswith('>') else user
        
        try:
            user_id = int(user_id)
        except (ValueError, TypeError):
            await interaction.followup.send("*Invalid user ID format.*", ephemeral=True)
            return
        
        if str(user_id) in self.blacklist:
            await interaction.followup.send("*This user is already in the blacklist.*", ephemeral=True)
            return
        
        user_info = await self.get_user_info(user_id)
        
        self.blacklist[str(user_id)] = {
            'name': user_info['name'],
            'reason': reason,
            'blacklisted_by': f"{interaction.user.display_name} ({interaction.user.name})",
            'timestamp': interaction.created_at.isoformat(),
            'is_in_server': user_info['is_in_server']
        }
        self.save_blacklist()
        
        if user_info['is_in_server']:
            member = interaction.guild.get_member(user_id)
            if member: await self.update_member_roles(member, True)
        
        embed = discord.Embed(title="*User Has Been Added to the Nuclear Blacklist!*", color=0xffffff)
        embed.add_field(name="User", value=user_info['mention'], inline=False)
        embed.add_field(name="Reason", value=reason, inline=False)
        embed.add_field(name="Blacklisted by", value=interaction.user.mention, inline=False)
        embed.add_field(name="Status", value="In Server" if user_info['is_in_server'] else "Not in Server", inline=False)
        embed.set_footer(text=f"User ID: {user_id}")
        
        await interaction.followup.send(embed=embed)
    
    @app_commands.command(name="blacklist_remove", description="Remove a user from the blacklist")
    @app_commands.describe(user="The user to remove from blacklist (mention or user ID)")
    async def blacklist_remove(self, interaction: discord.Interaction, user: str):
        if not await self.check_cupid_permission(interaction): return
        
        await interaction.response.defer(ephemeral=False)
        
        user_id = user.strip('<@!>') if user.startswith('<@') and user.endswith('>') else user
        
        try:
            user_id = int(user_id)
        except (ValueError, TypeError):
            await interaction.followup.send("*Invalid user ID format.*", ephemeral=True)
            return
        
        user_id_str = str(user_id)
        if user_id_str not in self.blacklist:
            await interaction.followup.send("*This user is not in the blacklist.*", ephemeral=True)
            return
        
        removed_data = self.blacklist.pop(user_id_str)
        self.save_blacklist()
        
        member = interaction.guild.get_member(user_id)
        if member: await self.update_member_roles(member, False)
        
        user_info = await self.get_user_info(user_id)
        
        embed = discord.Embed(title="*User Has Been Unblacklisted*", color=0x00ff00)
        embed.add_field(name="User", value=user_info['mention'], inline=False)
        embed.add_field(name="Was blacklisted for", value=removed_data['reason'], inline=False)
        embed.add_field(name="Removed by", value=interaction.user.mention, inline=False)
        embed.set_footer(text=f"User ID: {user_id}")
        
        await interaction.followup.send(embed=embed)
    
    @app_commands.command(name="blacklist_check", description="Check if a user is blacklisted")
    @app_commands.describe(user="The user to check (mention or user ID)")
    async def blacklist_check(self, interaction: discord.Interaction, user: str):
        if not await self.check_cupid_permission(interaction): return
        
        await interaction.response.defer(ephemeral=True)
        
        user_id = user.strip('<@!>') if user.startswith('<@') and user.endswith('>') else user
        
        try:
            user_id = int(user_id)
        except (ValueError, TypeError):
            await interaction.followup.send("*Invalid user ID format.*", ephemeral=True)
            return
        
        user_id_str = str(user_id)
        user_info = await self.get_user_info(user_id)
        
        if user_id_str in self.blacklist:
            data = self.blacklist[user_id_str]
            embed = discord.Embed(title="_User **is** Blacklisted_", color=0xff0000)
            embed.add_field(name="User", value=user_info['mention'], inline=False)
            embed.add_field(name="Reason", value=data['reason'], inline=False)
            embed.add_field(name="Blacklisted by", value=data['blacklisted_by'], inline=False)
            embed.add_field(name="Status", value="In Server" if user_info['is_in_server'] else "Not in Server", inline=False)
            embed.set_footer(text=f"User ID: {user_id}")
        else:
            embed = discord.Embed(title="_User is **Not** Blacklisted_", color=0x00ff00)
            embed.add_field(name="User", value=user_info['mention'], inline=False)
            embed.add_field(name="Status", value="In Server" if user_info['is_in_server'] else "Not in Server", inline=False)
            embed.set_footer(text=f"User ID: {user_id}")
        
        await interaction.followup.send(embed=embed)
    
    @app_commands.command(name="blacklist_view", description="View all blacklisted users")
    async def blacklist_view(self, interaction: discord.Interaction):
        if not await self.check_cupid_permission(interaction): return
        await interaction.response.defer(ephemeral=True)
        
        if not self.blacklist:
            await interaction.followup.send("*The blacklist is currently empty.*", ephemeral=True)
            return
        
        blacklist_entries = list(self.blacklist.items())
        embeds = []
        
        for i in range(0, len(blacklist_entries), 10):
            embed = discord.Embed(title="Blacklisted Users", description=f"Total: {len(self.blacklist)} users", color=0xffffff)
            for member_id, data in blacklist_entries[i:i+10]:
                status = "In Server" if data.get('is_in_server', False) else "Not in Server"
                embed.add_field(name=data['name'], value=f"**Reason:** {data['reason']}\n**By:** {data['blacklisted_by']}\n**ID:** {member_id}\n**Status:** {status}", inline=False)
            embed.set_footer(text=f"Page {i//10 + 1}/{(len(blacklist_entries)-1)//10 + 1}")
            embeds.append(embed)
        
        for embed in embeds:
            await interaction.followup.send(embed=embed, ephemeral=True)
    
    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot or message.channel.id not in self.BLACKLISTED_CHANNELS:
            return
            
        if str(message.author.id) in self.blacklist:
            try:
                await message.delete()
                try:
                    embed = discord.Embed(title="Message Blocked", description=f"Your message in {message.channel.mention} was removed because you are blacklisted from form channels.", color=0xffffff)
                    embed.add_field(name="Reason", value=self.blacklist[str(message.author.id)]['reason'], inline=False)
                    await message.author.send(embed=embed)
                except discord.Forbidden:
                    pass 
            except Exception:
                pass
    
    @commands.Cog.listener()
    async def on_member_join(self, member):
        if str(member.id) in self.blacklist:
            await self.update_member_roles(member, True)

async def setup(bot):
    await bot.add_cog(CupidBlacklist(bot))