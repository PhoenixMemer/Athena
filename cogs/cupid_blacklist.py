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
        self.blacklist_file = 'blacklist.json'
        self.blacklist = self.load_blacklist()
        
        # Configuration - UPDATE THESE IDs AS NEEDED
        self.CUPID_ROLE_ID = 1218983330201075792  # REPLACE WITH CUPID ROLE ID
        self.BLACKLISTED_CHANNELS = [
            1273939243600842795,  # REPLACE WITH CHANNEL 1 ID
            1273939292749561866,  # REPLACE WITH CHANNEL 2 ID  
            1273945454853492746,
            1273926745724026891   # REPLACE WITH CHANNEL 3 ID
        ]
        self.ROLE_A_ID = 1418944629427929118  # REPLACE WITH ROLE TO REMOVE (e.g., Form Access)
        self.ROLE_B_ID = 1421220600231231579  # REPLACE WITH ROLE TO ADD (e.g., Blacklisted)
    
    def load_blacklist(self) -> dict:
        """Load blacklist from JSON file"""
        if os.path.exists(self.blacklist_file):
            with open(self.blacklist_file, 'r') as f:
                return json.load(f)
        return {}
    
    def save_blacklist(self):
        """Save blacklist to JSON file"""
        with open(self.blacklist_file, 'w') as f:
            json.dump(self.blacklist, f, indent=4)
    
    async def check_cupid_permission(self, interaction: discord.Interaction) -> bool:
        """Check if user has cupid role"""
        cupid_role = interaction.guild.get_role(self.CUPID_ROLE_ID)
        if not cupid_role:
            await interaction.response.send_message("*Staffies role not configured properly. Please contact high staff~*", ephemeral=True)
            return False
        
        if cupid_role not in interaction.user.roles:
            await interaction.response.send_message("*You need the Staffies role to use this command. Please contact high staff~*", ephemeral=True)
            return False
        
        return True
    
    async def update_member_roles(self, member: discord.Member, blacklisted: bool):
        """Update member roles when blacklist status changes"""
        try:
            role_a = member.guild.get_role(self.ROLE_A_ID)
            role_b = member.guild.get_role(self.ROLE_B_ID)
            
            if not role_a or not role_b:
                print(f"*Warning: Ophanim or Blacklist Role not found. A: {role_a}, B: {role_b}*")
                return
            
            if blacklisted:
                # Add blacklisted role, remove access role
                if role_a in member.roles:
                    await member.remove_roles(role_a)
                if role_b not in member.roles:
                    await member.add_roles(role_b)
            else:
                # Remove blacklisted role, add access role
                if role_b in member.roles:
                    await member.remove_roles(role_b)
                if role_a not in member.roles:
                    await member.add_roles(role_a)
                    
        except discord.Forbidden:
            print(f"*Missing permissions to modify roles for {member.display_name}*")
        except Exception as e:
            print(f"*Error updating roles for {member.display_name}: {e}*")
    
    async def get_user_info(self, user_id: int) -> dict:
        """Get user information, trying both guild member and bot's global user cache"""
        # First try to get as guild member
        guild = self.bot.guilds[0] if self.bot.guilds else None
        if guild:
            member = guild.get_member(user_id)
            if member:
                return {
                    'name': f"{member.display_name} ({member.name})",
                    'mention': member.mention,
                    'is_in_server': True
                }
        
        # Try to get user from bot's cache
        user = self.bot.get_user(user_id)
        if user:
            return {
                'name': f"{user.name}",
                'mention': f"`{user.name}` (ID: {user_id})",
                'is_in_server': False
            }
        
        # If user not in cache, try to fetch (this may make an API call)
        try:
            user = await self.bot.fetch_user(user_id)
            return {
                'name': f"{user.name}",
                'mention': f"`{user.name}` (ID: {user_id})",
                'is_in_server': False
            }
        except discord.NotFound:
            return {
                'name': f"Unknown User (ID: {user_id})",
                'mention': f"`Unknown User` (ID: {user_id})",
                'is_in_server': False
            }
        except discord.HTTPException:
            return {
                'name': f"Unknown User (ID: {user_id})",
                'mention': f"`Unknown User` (ID: {user_id})",
                'is_in_server': False
            }
    
    @app_commands.command(name="blacklist_add", description="Add a user to the nuclear blacklist")
    @app_commands.describe(user="The user to blacklist (mention or user ID)", reason="Reason for blacklisting")
    async def blacklist_add(self, interaction: discord.Interaction, user: str, reason: str = "No reason provided"):
        """Add a user to the blacklist"""
        if not await self.check_cupid_permission(interaction):
            return
        
        await interaction.response.defer(ephemeral=False)
        
        # Parse user input - could be mention or user ID
        user_id = None
        
        # Try to parse as mention
        if user.startswith('<@') and user.endswith('>'):
            user_id = user.strip('<@!>')
        # Try to parse as raw user ID
        else:
            try:
                user_id = int(user)
            except ValueError:
                await interaction.followup.send("*Invalid user format. Please use @mention or user ID.*", ephemeral=True)
                return
        
        # Validate user ID
        try:
            user_id = int(user_id)
        except (ValueError, TypeError):
            await interaction.followup.send("*Invalid user ID format.*", ephemeral=True)
            return
        
        # Check if already blacklisted
        if str(user_id) in self.blacklist:
            await interaction.followup.send("*This user is already in the blacklist.*", ephemeral=True)
            return
        
        # Get user info
        user_info = await self.get_user_info(user_id)
        
        # Add to blacklist
        self.blacklist[str(user_id)] = {
            'name': user_info['name'],
            'reason': reason,
            'blacklisted_by': f"{interaction.user.display_name} ({interaction.user.name})",
            'timestamp': interaction.created_at.isoformat(),
            'is_in_server': user_info['is_in_server']
        }
        self.save_blacklist()
        
        # Update roles if user is in server
        if user_info['is_in_server']:
            member = interaction.guild.get_member(user_id)
            if member:
                await self.update_member_roles(member, True)
        
        # Send confirmation
        embed = discord.Embed(
            title="*User Has Been Added to the Nuclear Blacklist!*",
            color=0xffffff
        )
        embed.add_field(name="User", value=user_info['mention'], inline=False)
        embed.add_field(name="Reason", value=reason, inline=False)
        embed.add_field(name="Blacklisted by", value=interaction.user.mention, inline=False)
        embed.add_field(name="Status", value="In Server" if user_info['is_in_server'] else "Not in Server", inline=False)
        embed.set_footer(text=f"User ID: {user_id}")
        
        await interaction.followup.send(embed=embed)
        
        # Log the action
        print(f"Blacklisted: {user_info['name']} ({user_id}) by {interaction.user.display_name}. Reason: {reason}")
    
    @app_commands.command(name="blacklist_remove", description="Remove a user from the blacklist")
    @app_commands.describe(user="The user to remove from blacklist (mention or user ID)")
    async def blacklist_remove(self, interaction: discord.Interaction, user: str):
        """Remove a user from the blacklist"""
        if not await self.check_cupid_permission(interaction):
            return
        
        await interaction.response.defer(ephemeral=False)
        
        # Parse user input
        user_id = None
        
        if user.startswith('<@') and user.endswith('>'):
            user_id = user.strip('<@!>')
        else:
            try:
                user_id = int(user)
            except ValueError:
                await interaction.followup.send("*Invalid user format. Please use @mention or user ID.*", ephemeral=True)
                return
        
        try:
            user_id = int(user_id)
        except (ValueError, TypeError):
            await interaction.followup.send("*Invalid user ID format.*", ephemeral=True)
            return
        
        user_id_str = str(user_id)
        if user_id_str not in self.blacklist:
            await interaction.followup.send("*This user is not in the blacklist.*", ephemeral=True)
            return
        
        # Remove from blacklist
        removed_data = self.blacklist.pop(user_id_str)
        self.save_blacklist()
        
        # Update roles if user is in server
        member = interaction.guild.get_member(user_id)
        if member:
            await self.update_member_roles(member, False)
        
        # Get current user info for display
        user_info = await self.get_user_info(user_id)
        
        # Send confirmation
        embed = discord.Embed(
            title="*User Has Been Unblacklisted*",
            color=0x00ff00
        )
        embed.add_field(name="User", value=user_info['mention'], inline=False)
        embed.add_field(name="Was blacklisted for", value=removed_data['reason'], inline=False)
        embed.add_field(name="Removed by", value=interaction.user.mention, inline=False)
        embed.set_footer(text=f"User ID: {user_id}")
        
        await interaction.followup.send(embed=embed)
        
        # Log the action
        print(f"Unblacklisted: {user_info['name']} ({user_id}) by {interaction.user.display_name}")
    
    @app_commands.command(name="blacklist_check", description="Check if a user is blacklisted")
    @app_commands.describe(user="The user to check (mention or user ID)")
    async def blacklist_check(self, interaction: discord.Interaction, user: str):
        """Check a user's blacklist status"""
        if not await self.check_cupid_permission(interaction):
            return
        
        await interaction.response.defer(ephemeral=True)
        
        # Parse user input
        user_id = None
        
        if user.startswith('<@') and user.endswith('>'):
            user_id = user.strip('<@!>')
        else:
            try:
                user_id = int(user)
            except ValueError:
                await interaction.followup.send("*Invalid user format. Please use @mention or user ID.*", ephemeral=True)
                return
        
        try:
            user_id = int(user_id)
        except (ValueError, TypeError):
            await interaction.followup.send("*Invalid user ID format.*", ephemeral=True)
            return
        
        user_id_str = str(user_id)
        user_info = await self.get_user_info(user_id)
        
        if user_id_str in self.blacklist:
            data = self.blacklist[user_id_str]
            embed = discord.Embed(
                title="_User **is** Blacklisted_",
                color=0xff0000
            )
            embed.add_field(name="User", value=user_info['mention'], inline=False)
            embed.add_field(name="Reason", value=data['reason'], inline=False)
            embed.add_field(name="Blacklisted by", value=data['blacklisted_by'], inline=False)
            embed.add_field(name="Date", value=discord.utils.format_dt(discord.utils.parse_time(data['timestamp'].replace('Z', '+00:00')), 'R'), inline=False)
            embed.add_field(name="Status", value="In Server" if user_info['is_in_server'] else "Not in Server", inline=False)
            embed.set_footer(text=f"User ID: {user_id}")
        else:
            embed = discord.Embed(
                title="_User is **Not** Blacklisted_",
                color=0x00ff00
            )
            embed.add_field(name="User", value=user_info['mention'], inline=False)
            embed.add_field(name="Status", value="In Server" if user_info['is_in_server'] else "Not in Server", inline=False)
            embed.set_footer(text=f"User ID: {user_id}")
        
        await interaction.followup.send(embed=embed)
    
    @app_commands.command(name="blacklist_view", description="View all blacklisted users")
    async def blacklist_view(self, interaction: discord.Interaction):
        """View the complete blacklist"""
        if not await self.check_cupid_permission(interaction):
            return
        
        await interaction.response.defer(ephemeral=True)
        
        if not self.blacklist:
            await interaction.followup.send("*The blacklist is currently empty.*", ephemeral=True)
            return
        
        # Create paginated embeds if too many entries
        blacklist_entries = list(self.blacklist.items())
        embeds = []
        
        for i in range(0, len(blacklist_entries), 10):
            embed = discord.Embed(
                title="Blacklisted Users",
                description=f"Total: {len(self.blacklist)} users",
                color=0xffffff
            )
            
            for member_id, data in blacklist_entries[i:i+10]:
                status = "In Server" if data.get('is_in_server', False) else "Not in Server"
                embed.add_field(
                    name=data['name'],
                    value=f"**Reason:** {data['reason']}\n**By:** {data['blacklisted_by']}\n**ID:** {member_id}\n**Status:** {status}",
                    inline=False
                )
            
            embed.set_footer(text=f"Page {i//10 + 1}/{(len(blacklist_entries)-1)//10 + 1}")
            embeds.append(embed)
        
        for embed in embeds:
            await interaction.followup.send(embed=embed, ephemeral=True)
    
    @commands.Cog.listener()
    async def on_message(self, message):
        """Prevent blacklisted members from posting in specified channels"""
        if message.author.bot:
            return
        
        # Check if message is in a blacklisted channel
        if message.channel.id not in self.BLACKLISTED_CHANNELS:
            return
        
        # Check if user is blacklisted
        if str(message.author.id) in self.blacklist:
            try:
                await message.delete()
                
                # Send warning DM
                try:
                    embed = discord.Embed(
                        title="Message Blocked",
                        description=f"Your message in {message.channel.mention} was removed because you are blacklisted from form channels.",
                        color=0xffffff
                    )
                    embed.add_field(name="Reason", value=self.blacklist[str(message.author.id)]['reason'], inline=False)
                    embed.add_field(name="Appeal", value="Contact a Cupid if you believe this is a mistake.", inline=False)
                    await message.author.send(embed=embed)
                except discord.Forbidden:
                    pass  # Can't DM user
                    
            except discord.Forbidden:
                print(f"Missing permissions to delete message from blacklisted user {message.author.display_name}")
            except Exception as e:
                print(f"Error handling blacklisted user message: {e}")
    
    @commands.Cog.listener()
    async def on_member_join(self, member):
        """Check if rejoining member was previously blacklisted"""
        if str(member.id) in self.blacklist:
            # Re-apply blacklisted role if they rejoin
            await self.update_member_roles(member, True)
            print(f"Reapplied blacklist roles to rejoining member: {member.display_name}")

async def setup(bot):
    await bot.add_cog(CupidBlacklist(bot))