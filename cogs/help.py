import discord
from discord import app_commands
from discord.ext import commands

# 🛠️ Replace the "000000000000000000" with the actual command IDs.
# Replace the "123456" in the White_Dot with your actual server emoji ID.
ALL_COMMANDS = [
    "<:014White_Dot:1509293534799331408> </daily:1500499221562916979>",
    "<:014White_Dot:1509293534799331408> </work:1500499221562916980>",
    "<:014White_Dot:1509293534799331408> </appoint:1504591742995791878>",
    "<:014White_Dot:1509293534799331408> </bal:1500232954302173391>",
    "<:014White_Dot:1509293534799331408> </bizleaderboard:1504591742995791882>",
    "<:014White_Dot:1509293534799331408> </blacklist_add:1491867177655996707>",
    "<:014White_Dot:1509293534799331408> </blacklist_check:1491867177655996709>",
    "<:014White_Dot:1509293534799331408> </blacklist_remove:1491867177655996708>",
    "<:014White_Dot:1509293534799331408> </blacklist_view:1491867177655996710>",
    "<:014White_Dot:1509293534799331408> </business:1504591742995791877>",
    "<:014White_Dot:1509293534799331408> </career:1503097462343073932>",
    "<:014White_Dot:1509293534799331408> </casino:1503540125563486359>",
    "<:014White_Dot:1509293534799331408> </convert:1500507537022390383>",
    "<:014White_Dot:1509293534799331408> </exchange_rate:1500507537022390382>",
    "<:014White_Dot:1509293534799331408> </faq:1483418327580803182>",
    "<:014White_Dot:1509293534799331408> </garage:1503478405163651234>",
    "<:014White_Dot:1509293534799331408> </give:1500499221562916976>",
    "<:014White_Dot:1509293534799331408> </guidebiz:1504591742995791876>",
    "<:014White_Dot:1509293534799331408> </heist:1501536387789361345>",
    "<:014White_Dot:1509293534799331408> </invest:1500499221562916981>",
    "<:014White_Dot:1509293534799331408> </leaderboard:1503478405163651236>",
    "<:014White_Dot:1509293534799331408> </loan:1500499221562916978>",
    "<:014White_Dot:1509293534799331408> </marketplace:1503478405163651233>",
    "<:014White_Dot:1509293534799331408> </networth:1503478405163651235>",
    "<:014White_Dot:1509293534799331408> </rob:1505182307550756965>",
    "<:014White_Dot:1509293534799331408> </setcard:1500319704005349467>",
    "<:014White_Dot:1509293534799331408> </stake:1501536387789361344>",
    "<:014White_Dot:1509293534799331408> </statement:1503509286637277234>"
]

# Break the list down into chunks of 10 commands per page
ITEMS_PER_PAGE = 10
PAGES_DATA = [ALL_COMMANDS[i:i + ITEMS_PER_PAGE] for i in range(0, len(ALL_COMMANDS), ITEMS_PER_PAGE)]

class HelpPaginator(discord.ui.View):
    def __init__(self, pages):
        super().__init__(timeout=180)
        self.pages = pages
        self.current_page = 0
        self.update_buttons()

    def update_buttons(self):
        # Disable "left" arrow if on the first page, disable "right" arrow if on the last page
        self.prev_btn.disabled = self.current_page == 0
        self.next_btn.disabled = self.current_page == len(self.pages) - 1

    @discord.ui.button(emoji="<:w_arrowleft:1272235695137751162>", style=discord.ButtonStyle.secondary)
    async def prev_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page -= 1
        self.update_buttons()
        await interaction.response.edit_message(embed=self.pages[self.current_page], view=self)

    @discord.ui.button(emoji="<:w_arrowright:1272235711721898005>", style=discord.ButtonStyle.secondary)
    async def next_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page += 1
        self.update_buttons()
        await interaction.response.edit_message(embed=self.pages[self.current_page], view=self)


class HelpCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="help", description="View all available Athena commands")
    async def help_cmd(self, interaction: discord.Interaction):
        pages = []
        
        for i, chunk in enumerate(PAGES_DATA):
            # 0x0f0f17 is the precise hex code you requested
            embed = discord.Embed(color=0x0f0f17)
            
            # Using the description to hold the title text as requested so the embed has no official 'Title' attribute
            # Replace the 123456 below with your actual athena emoji ID
            desc = "# <:athena:1509268817916858588> **Athena Commands**\n\n"
            desc += "\n".join(chunk)
            
            embed.description = desc
            embed.set_footer(text=f"Page {i+1}/{len(PAGES_DATA)}")
            pages.append(embed)

        view = HelpPaginator(pages)
        await interaction.response.send_message(embed=pages[0], view=view, ephemeral=True)


async def setup(bot):
    await bot.add_cog(HelpCog(bot))