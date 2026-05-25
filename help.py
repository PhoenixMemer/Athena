import discord

class HelpView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None) # Persistent

    @discord.ui.select(
        placeholder="Select a category to view commands...",
        options=[
            discord.SelectOption(label="Business", description="Manage HQ & HQ Production", emoji="🏢"),
            discord.SelectOption(label="Economy", description="Banks & Transfers", emoji="💰"),
            discord.SelectOption(label="Investments", description="Stock Ticker & Trading", emoji="📈"),
        ]
    )
    async def select_callback(self, i: discord.Interaction, select: discord.ui.Select):
        if select.values[0] == "Business":
            embed = discord.Embed(title="🏢 Business Commands", description="/launch, /audit, /hire, /hq", color=0xffffff)
        elif select.values[0] == "Economy":
            embed = discord.Embed(title="💰 Economy Commands", description="/rob, /balance, /transfer", color=0xffffff)
        else:
            embed = discord.Embed(title="📈 Investment Commands", description="/invest buy, /invest sell, /ticker", color=0xffffff)
        
        await i.response.edit_message(embed=embed)

# Register this in your bot's on_ready() or setup_hook:
# bot.add_view(HelpView())