import discord
from discord import app_commands
from discord.ext import commands

class HelpDropdown(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="Economy & Wallet", emoji="💰"),
            discord.SelectOption(label="Business & Corporate", emoji="🏢"),
            discord.SelectOption(label="Investing & Stocks", emoji="📈"),
            discord.SelectOption(label="Marketplace & Assets", emoji="🏠"),
            discord.SelectOption(label="Casino & Gambling", emoji="🎰"),
            discord.SelectOption(label="Careers & Jobs", emoji="💼"),
            discord.SelectOption(label="Utility & Fun", emoji="🛠️")
        ]
        super().__init__(placeholder="Select a module to view commands...", options=options)

    async def callback(self, interaction: discord.Interaction):
        embed = discord.Embed(color=0x2b2d31)
        choice = self.values[0]
        
        if choice == "Economy & Wallet":
            embed.title = "💰 Economy & Wallet"
            embed.description = (
                "`/bal` - View your debit card & balance\n"
                "`/daily` - Claim daily allowance\n"
                "`/give` - Transfer money to a user\n"
                "`/rob` - Attempt to rob a user\n"
                "`/heist` - High risk corporate heist\n"
                "`/loan` - Take a bank loan\n"
                "`/stake deposit` - Lock money for yield\n"
                "`/stake claim` - Claim matured stake\n"
                "`/statement` - View transaction history"
            )
        elif choice == "Business & Corporate":
            embed.title = "🏢 Business & Corporate"
            embed.description = (
                "`/business` - Open CEO Terminal\n"
                "`/appoint` - Appoint a VP/COO\n"
                "`/rename_company` - Rename your business\n"
                "`/bizleaderboard` - Top 10 corporations\n"
                "`/guidebiz` - Read the business manual"
            )
        elif choice == "Investing & Stocks":
            embed.title = "📈 Investing & Stocks"
            embed.description = (
                "`/invest market` - View stock exchange\n"
                "`/invest buy` - Buy shares\n"
                "`/invest sell` - Sell shares\n"
                "`/invest portfolio` - View your holdings"
            )
        elif choice == "Marketplace & Assets":
            embed.title = "🏠 Marketplace & Assets"
            embed.description = (
                "`/marketplace browse` - Buy real estate & cars\n"
                "`/marketplace list` - List property P2P\n"
                "`/marketplace repair` - Fix broken assets\n"
                "`/garage` - View your vehicles\n"
                "`/networth` - Total empire valuation"
            )
        elif choice == "Casino & Gambling":
            embed.title = "🎰 Casino & Gambling"
            embed.description = (
                "`/casino` - Enter the Grand Casino (11 Games)\n"
                "`a.cf` - Quick prefix coinflip"
            )
        elif choice == "Careers & Jobs":
            embed.title = "💼 Careers & Jobs"
            embed.description = (
                "`/career` - Choose a career path\n"
                "`/work` - Work a shift for A$ & XP"
            )
        elif choice == "Utility & Fun":
            embed.title = "🛠️ Utility & Fun"
            embed.description = (
                "`/pick` - Scavenge for drops (1h cooldown)\n"
                "`/afk` - Set AFK status\n"
                "`/remind` - Set a reminder\n"
                "`/compat` - Love/compatibility calculator\n"
                "`/mbti` - Personality insights"
            )
            
        await interaction.response.edit_message(embed=embed)

class HelpView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=180)
        self.add_item(HelpDropdown())

class HelpCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="help", description="View all bot commands and modules")
    async def help_cmd(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="꒰ა Athena Command Directory ⸝⸝",
            description="Select a module from the dropdown below to view its commands.\n\n*Use `/pick` in general chat to scavenge for random cash drops, or buy a lottery ticket!*",
            color=0xffffff
        )
        embed.set_thumbnail(url=self.bot.user.display_avatar.url)
        embed.set_footer(text="Athena Mark 17.2 | Developed for Chérie")
        
        await interaction.response.send_message(embed=embed, view=HelpView(), ephemeral=True)

async def setup(bot):
    # Remove default help if it exists to prevent conflicts
    if bot.tree.get_command("help"):
        bot.tree.remove_command("help")
    await bot.add_cog(HelpCog(bot))