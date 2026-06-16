import discord
from discord import app_commands
from discord.ext import commands

# ==========================================
# CUSTOMIZE THESE
# ==========================================
BANNER_URL = "https://i.pinimg.com/736x/f1/c5/df/f1c5df4440587834df5d1715de05ec74.jpg"
ATHENA_EMOJI = "<:btb_white3:1375474689467748517>"
DOT_EMOJI = "<:014White_Dot:1509293534799331408>"

# ────────────────────────────────────────────────────────────
# COMMAND LIST (emoji, command, description)
# ────────────────────────────────────────────────────────────
COMMANDS = [
    (DOT_EMOJI, "/daily", "Claim your daily allowance\n"),
    (DOT_EMOJI, "/work", "Work a shift and earn XP + A$\n"),
    (DOT_EMOJI, "/appoint", "Appoint a VP/COO/CFO for your business\n"),
    (DOT_EMOJI, "/bal", "View your wallet and debit card\n"),
    (DOT_EMOJI, "/vanityinfo", "View all members with the vanity role\n"),
    (DOT_EMOJI, "/bizleaderboard", "Top companies by capital\n"),
    (DOT_EMOJI, "/blacklist", "Manage user blacklist (staff)\n"),
    (DOT_EMOJI, "/business", "Access your CEO terminal\n"),
    (DOT_EMOJI, "/career", "Choose and track your career path\n"),
    (DOT_EMOJI, "/casino", "Play 11+ gambling games\n"),
    (DOT_EMOJI, "/convert", "Convert Mimu ↔ Athena\n"),
    (DOT_EMOJI, "/exchange_rate", "Show current Mimu rate\n"),
    (DOT_EMOJI, "/faq", "Frequently asked questions\n"),
    (DOT_EMOJI, "/garage", "View your vehicle collection\n"),
    (DOT_EMOJI, "/give", "Transfer A$ to another user\n"),
    (DOT_EMOJI, "/guidebiz", "Official business manual\n"),
    (DOT_EMOJI, "/heist", "Attempt a risky corporate heist\n"),
    (DOT_EMOJI, "/invest", "Buy/sell stocks and view portfolio\n"),
    (DOT_EMOJI, "/leaderboard", "Top 10 wealthiest users\n"),
    (DOT_EMOJI, "/loan", "Take a short‑term loan\n"),
    (DOT_EMOJI, "/marketplace", "Buy properties, vehicles, and more\n"),
    (DOT_EMOJI, "/networth", "Total valuation of your empire\n"),
    (DOT_EMOJI, "/rob", "Attempt to rob another user\n"),
    (DOT_EMOJI, "/setcard", "Equip a higher‑tier debit card\n"),
    (DOT_EMOJI, "/stake", "Lock A$ for guaranteed yields\n"),
    (DOT_EMOJI, "/statement", "View your transaction history\n"),
]

ITEMS_PER_PAGE = 6
PAGES = [COMMANDS[i:i + ITEMS_PER_PAGE] for i in range(0, len(COMMANDS), ITEMS_PER_PAGE)]

# ==========================================
# 🧭 PAGINATION VIEW
# ==========================================
class HelpPaginator(discord.ui.View):
    def __init__(self, pages):
        super().__init__(timeout=180)
        self.pages = pages
        self.current_page = 0
        self.update_buttons()

    def update_buttons(self):
        self.prev_btn.disabled = self.current_page == 0
        self.next_btn.disabled = self.current_page == len(self.pages) - 1

    @discord.ui.button(label="Previous", emoji="<:w_arrowleft:1272235695137751162>", style=discord.ButtonStyle.secondary)
    async def prev_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page -= 1
        self.update_buttons()
        await interaction.response.edit_message(embed=self.pages[self.current_page], view=self)

    @discord.ui.button(label="Next", emoji="<:w_arrowright:1272235711721898005>", style=discord.ButtonStyle.secondary)
    async def next_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page += 1
        self.update_buttons()
        await interaction.response.edit_message(embed=self.pages[self.current_page], view=self)

# ==========================================
# 📖 MAIN HELP COMMAND
# ==========================================
class HelpCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="help", description="View all available Athena commands")
    async def help_cmd(self, interaction: discord.Interaction):
        pages = []
        for idx, chunk in enumerate(PAGES, 1):
            embed = discord.Embed(color=0xffffff)
            embed.set_image(url=BANNER_URL)

            # ─── Header ─────────────────────────────────
            desc = f"# {ATHENA_EMOJI} **Athena Commands**\n\n\n\n"
            #desc += f"*The complete list of every slash command available to you.*\n\n"

            # ─── Commands ──────────────────────────────
            for emoji, cmd, txt in chunk:
                desc += f"{emoji} **{cmd}** – {txt}\n"

            # ─── Footer info ───────────────────────────
            embed.description = desc
            embed.set_footer(text="For prefix commands, use a.help")
            pages.append(embed)

        view = HelpPaginator(pages)
        await interaction.response.send_message(embed=pages[0], view=view, ephemeral=False)

async def setup(bot):
    await bot.add_cog(HelpCog(bot))