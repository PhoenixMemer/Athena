import discord
from discord import app_commands
from discord.ext import commands


class Help(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="help", description="View all available Athena commands")
    async def help_cmd(self, interaction: discord.Interaction):
        # Dynamically resolve slash command IDs so they render as clickable mentions
        def cmd_mention(name: str) -> str:
            cmd = self.bot.tree.get_command(name)
            if cmd:
                return f"</{name}:{cmd.id}>"
            # Fallback for subcommands or unsynced commands
            parts = name.split(" ")
            if len(parts) > 1:
                parent = self.bot.tree.get_command(parts[0])
                if parent:
                    return f"</{name}:{parent.id}>"
            return f"`/{name}`"

        embed = discord.Embed(
            title="",
            color=0x0f0f17
        )

        embed.description = (
            f"• {cmd_mention('profile')} to view your level and achievements\n\n"
            f"• {cmd_mention('daily')} to claim a random amount of XP daily\n\n"
            f"• {cmd_mention('business')} to access your corporate CEO terminal\n\n"
            f"• {cmd_mention('casino')} to enter the VIP gambling floor\n\n"
            f"• {cmd_mention('audit')} to run a comprehensive business analysis\n"
            "*(Only available for registered CEOs)*"
        )

        embed.set_footer(text="Click any command above to autofill it in your chat box.")

        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Help(bot))