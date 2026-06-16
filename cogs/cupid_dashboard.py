import discord
from discord import app_commands
from discord.ext import commands, tasks
import sqlite3
import asyncio

DB_PATH = "cupid.db"

# ==========================================
# 📊 UTILITIES & AESTHETICS
# ==========================================
def make_emoji_bar(current: int, total: int = 7) -> str:
    """Generates a custom 6-part emoji progress bar for the weekly quota."""
    
    # --- REPLACE 'ID' WITH YOUR ACTUAL EMOJI IDs ---
    fill_left = "<:fillleft:1502707988761153567>"
    fill_mid = "<:fillmid:1502707936823087246>"
    fill_right = "<:fillright:1502707911560794192>"
    
    empty_left = "<:emptyleft:1502707971363311767>"
    empty_mid = "<:emptymid:1502707866744651948>"
    empty_right = "<:emptyright:1502707890664771717>"
    # ------------------------------------------------
    
    visual_current = min(current, total)
    bar = ""
    
    for i in range(total):
        is_filled = i < visual_current
        
        # Left Corner
        if i == 0:
            bar += fill_left if is_filled else empty_left
        # Right Corner
        elif i == total - 1:
            bar += fill_right if is_filled else empty_right
        # Middle Slots
        else:
            bar += fill_mid if is_filled else empty_mid
            
    return f"{bar}  **({current}/{total})**"

# ==========================================
# 📄 PAGINATION SYSTEM (PAGE FLIPPERS)
# ==========================================
class SimplePaginationView(discord.ui.View):
    def __init__(self, items, title, items_per_page=5):
        super().__init__(timeout=180)
        self.items = items
        self.title = title
        self.items_per_page = items_per_page
        self.current_page = 0
        self.max_pages = max(1, (len(items) - 1) // items_per_page + 1) if items else 1
        self.update_buttons()

    def update_buttons(self):
        self.prev_button.disabled = self.current_page == 0
        self.next_button.disabled = self.current_page == self.max_pages - 1

    def get_embed(self):
        embed = discord.Embed(title=self.title, color=0xffffff)
        if not self.items:
            embed.description = "No data available."
            return embed

        start = self.current_page * self.items_per_page
        end = start + self.items_per_page
        page_data = self.items[start:end]

        embed.description = "".join(page_data)
        embed.set_footer(text=f"")
        return embed

    # Added emoji placeholders for your custom pagination buttons
    @discord.ui.button(label="", emoji="<:w_arrowleft:1272235695137751162>", style=discord.ButtonStyle.secondary)
    async def prev_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page -= 1
        self.update_buttons()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    @discord.ui.button(label="", emoji="<:w_arrowright:1272235711721898005>", style=discord.ButtonStyle.secondary)
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page += 1
        self.update_buttons()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

# ==========================================
# 🏛️ UI COMPONENTS (DASHBOARD)
# ==========================================
class StrikeModal(discord.ui.Modal, title='Issue Formal Strike'):
    user_id = discord.ui.TextInput(label='User ID', placeholder='e.g., 123456789012345678', min_length=17, max_length=20)
    strike_amount = discord.ui.TextInput(label='Strike Level (1, 2, or 3)', placeholder='Enter 1, 2, or 3', min_length=1, max_length=1)
    reason = discord.ui.TextInput(label='Reason for Strike', style=discord.TextStyle.paragraph, placeholder='Describe the form violation here...')

    async def on_submit(self, interaction: discord.Interaction):
        try:
            uid = int(self.user_id.value)
            amount = int(self.strike_amount.value)
            if amount not in [1, 2, 3]:
                return await interaction.response.send_message("<a:wt_torono:1480580892706603018> 𝑆𝑡𝑟𝑖𝑘𝑒 𝐿𝑒𝑣𝑒𝑙 𝑚𝑢𝑠𝑡 𝑏𝑒 1, 2, 𝑜𝑟 3.", ephemeral=True)
                
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            cursor.execute("INSERT INTO user_strikes (user_id, strike_level, reason, issuer_id) VALUES (?, ?, ?, ?)", (uid, amount, self.reason.value, interaction.user.id))
            conn.commit()
            conn.close()

            try:
                target = await interaction.guild.fetch_member(uid)
                if target:
                    embed = discord.Embed(title="𝑆𝑜𝑚𝑒𝑜𝑛𝑒 𝐹𝑜𝑟𝑔𝑜𝑡 𝑇𝑜 𝐵𝑒ℎ𝑎𝑣𝑒..", color=0xffffff)
                    embed.description = f"You have been issued **strike {amount}** regarding your matchmaking form.\n\n**Reason**\n{self.reason.value}"
                    
                    await target.send(embed=embed)
                    dm_status = "𝑎𝑛𝑑 𝑢𝑠𝑒𝑟 𝑛𝑜𝑡𝑖𝑓𝑖𝑒𝑑 𝑣𝑖𝑎 𝑑𝑚."
            except:
                dm_status = "𝑏𝑢𝑡 𝑢𝑠𝑒𝑟 𝑑𝑚𝑠 𝑎𝑟𝑒 𝑐𝑙𝑜𝑠𝑒𝑑."

            await interaction.response.send_message(f"<a:wt_toroleaf:1480580940785913967> 𝑆𝑡𝑟𝑖𝑘𝑒 {amount} 𝑜𝑓𝑓𝑖𝑐𝑖𝑎𝑙𝑙𝑦 𝑙𝑜𝑔𝑔𝑒𝑑 𝑓𝑜𝑟 𝑢𝑠𝑒𝑟 `{uid}` {dm_status}", ephemeral=False)
            
        except ValueError:
            await interaction.response.send_message("<a:wt_torono:1480580892706603018> 𝐼𝑛𝑣𝑎𝑙𝑖𝑑 𝑈𝑠𝑒𝑟 𝐼𝐷 𝑜𝑟 𝑆𝑡𝑟𝑖𝑘𝑒 𝐿𝑒𝑣𝑒𝑙 𝑝𝑟𝑜𝑣𝑖𝑑𝑒𝑑.", ephemeral=False)

class DashboardView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="", style=discord.ButtonStyle.secondary, custom_id="btn_analytics", emoji="<:wb_bow3:1276920947453988898>")
    async def btn_analytics(self, interaction: discord.Interaction, button: discord.ui.Button):
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT weekly_matches, all_time_matches FROM cupid_stats WHERE user_id = ?", (interaction.user.id,))
        stats = cursor.fetchone()
        conn.close()

        weekly = stats[0] if stats else 0
        all_time = stats[1] if stats else 0

        embed = discord.Embed(title=f"{interaction.user.name}'𝑠 𝐴𝑛𝑎𝑙𝑦𝑡𝑖𝑐𝑠", color=0xffffff)
        embed.add_field(name="𝑊𝑒𝑒𝑘𝑙𝑦 𝑄𝑢𝑜𝑡𝑎 𝑃𝑟𝑜𝑔𝑟𝑒𝑠𝑠", value=make_emoji_bar(weekly), inline=False)
        embed.add_field(name="𝑇𝑜𝑡𝑎𝑙 𝐿𝑖𝑓𝑒𝑡𝑖𝑚𝑒 𝑀𝑎𝑡𝑐ℎ𝑒𝑠", value=f"**{all_time}** 𝑚𝑎𝑡𝑐ℎ𝑒𝑠 𝑑𝑜𝑛𝑒.", inline=False)
        
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="", style=discord.ButtonStyle.secondary, custom_id="btn_sops", emoji="<:wb_bow8:1375516856609275904>")
    async def btn_sops(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(title="", color=0xffffff)
        embed.description = (
            "<a:wt_torolove:1480580899430203484> **𝑂𝑛𝑏𝑜𝑎𝑟𝑑𝑖𝑛𝑔 & 𝑇𝑟𝑖𝑎𝑙 𝑃ℎ𝑎𝑠𝑒**\n"
            "♡⸝⸝ Add the prefix `૮꒱ 𝑐𝑢𝑝𝑖𝑑` to your server nickname.\n"
            "♡⸝⸝ Enable 2FA on your account and verify in <#1273926745724026891>. For instructions on 2FA, do `/2fa_guide`.\n"
            "♡⸝⸝ Trial Cupids are on a 1 week trial. Reach out to the Head Cupid <@1185340015920820345> for guidance.\n\n\n"
            "<a:wt_torolove:1480580899430203484> **𝑀𝑎𝑡𝑐ℎ𝑚𝑎𝑘𝑖𝑛𝑔 𝑃𝑟𝑜𝑡𝑜𝑐𝑜𝑙**\n"
            "♡⸝⸝ Source: Review intake forms in the gender channels.\n"
            "♡⸝⸝ Approve: Trial Cupids must forward potential pairs to the Cupid Chat for approval.\n"
            "♡⸝⸝ Process: Once approved, send the match to <#1367570345598648422> and *delete* the original forms from the channels they were in.\n"
            "♡⸝⸝ Execute: Use the template from <#1273938255703707661> to post the final pair in <#1273938255703707661>. *(Right click this message -> Apps -> Log Match)*\n\n\n"
            "<a:wt_torolove:1480580899430203484> **𝐴𝑔𝑒 𝐺𝑢𝑖𝑑𝑒𝑙𝑖𝑛𝑒𝑠**\n"
            "♡⸝⸝ Minors and adults cannot be matched, with one strict exception: 17 years old with 18 years old. No other gaps are permitted.\n\n\n"
            "<a:wt_torolove:1480580899430203484> **𝑃𝑒𝑟𝑓𝑜𝑟𝑚𝑎𝑛𝑐𝑒**\n"
            "♡⸝⸝ Maintain your quota of 7 matches per week.\n"
            "♡⸝⸝ The Cupid with the highest weekly matches earns the Cupid of the Week (COTW) title AND a mimu bonus reward!"
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="", style=discord.ButtonStyle.secondary, custom_id="btn_strike", emoji="<:wb_bow2:1276926528646545490>")
    async def btn_strike(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(StrikeModal())

# ==========================================
# 🏙️ THE CUPID DASHBOARD COG
# ==========================================
class CupidDashboard(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.setup_db()
        self.weekly_reset.start()
        
        self.ctx_menu = app_commands.ContextMenu(
            name='Log Match',
            callback=self.log_match_context,
        )
        self.bot.tree.add_command(self.ctx_menu)

    async def cog_unload(self) -> None:
        self.bot.tree.remove_command(self.ctx_menu.name, type=self.ctx_menu.type)
        self.weekly_reset.cancel()

    def setup_db(self):
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        cursor.execute('''CREATE TABLE IF NOT EXISTS cupid_stats (
            user_id INTEGER PRIMARY KEY,
            weekly_matches INTEGER DEFAULT 0,
            all_time_matches INTEGER DEFAULT 0
        )''')
        
        cursor.execute('''CREATE TABLE IF NOT EXISTS user_strikes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            strike_level INTEGER,
            reason TEXT,
            issuer_id INTEGER,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )''')
        
        cursor.execute('''CREATE TABLE IF NOT EXISTS cupid_profiles (
            user_id INTEGER PRIMARY KEY
        )''')
        
        conn.commit()
        conn.close()

    # ==========================================
    # 📌 THE RIGHT-CLICK LOGGER
    # ==========================================
    async def log_match_context(self, interaction: discord.Interaction, message: discord.Message):
        MATCHED_CHANNEL_ID = 1273938255703707661
        
        if message.channel.id != MATCHED_CHANNEL_ID:
            return await interaction.response.send_message("<a:wt_torono:1480580892706603018> 𝑌𝑜𝑢 𝑐𝑎𝑛 𝑜𝑛𝑙𝑦 𝑙𝑜𝑔 𝑚𝑒𝑠𝑠𝑎𝑔𝑒𝑠 𝑓𝑟𝑜𝑚 𝑡ℎ𝑒 <#1273938255703707661> 𝑐ℎ𝑎𝑛𝑛𝑒𝑙.", ephemeral=True)
            
        if message.author.id != interaction.user.id:
            return await interaction.response.send_message("<a:wt_torono:1480580892706603018> 𝑌𝑜𝑢 𝑐𝑎𝑛 𝑜𝑛𝑙𝑦 𝑙𝑜𝑔 𝑦𝑜𝑢𝑟 𝑜𝑤𝑛 𝑚𝑎𝑡𝑐ℎ 𝑚𝑒𝑠𝑠𝑎𝑔𝑒𝑠.", ephemeral=True)
            
        if len(message.mentions) < 2:
            return await interaction.response.send_message("<a:wt_toronerd:1480580983593111602> 𝐼 𝑑𝑜𝑛'𝑡 𝑠𝑒𝑒 𝑡𝑤𝑜 𝑢𝑠𝑒𝑟𝑠 𝑚𝑒𝑛𝑡𝑖𝑜𝑛𝑒𝑑 𝑖𝑛 𝑡ℎ𝑖𝑠 𝑚𝑒𝑠𝑠𝑎𝑔𝑒. 𝐴𝑟𝑒 𝑦𝑜𝑢 𝑠𝑢𝑟𝑒 𝑡ℎ𝑖𝑠 𝑖𝑠 𝑎 𝑚𝑎𝑡𝑐ℎ?", ephemeral=True)

        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('''INSERT INTO cupid_stats (user_id, weekly_matches, all_time_matches) 
                          VALUES (?, 1, 1) 
                          ON CONFLICT(user_id) DO UPDATE SET 
                          weekly_matches = weekly_matches + 1, 
                          all_time_matches = all_time_matches + 1''', (interaction.user.id,))
        conn.commit()
        conn.close()
        
        await interaction.response.send_message("<a:wt_toroexclaim:1480581004317036624> 𝑀𝑎𝑡𝑐ℎ 𝑠𝑢𝑐𝑐𝑒𝑠𝑠𝑓𝑢𝑙𝑙𝑦 𝑙𝑜𝑔𝑔𝑒𝑑 𝑎𝑛𝑑 𝑎𝑑𝑑𝑒𝑑 𝑡𝑜 𝑦𝑜𝑢𝑟 𝑤𝑒𝑒𝑘𝑙𝑦 𝑞𝑢𝑜𝑡𝑎!", ephemeral=True)

    # ==========================================
    # ⚙️ AUTOMATED WEEKLY RESET
    # ==========================================
    @tasks.loop(hours=168) 
    async def weekly_reset(self):
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("UPDATE cupid_stats SET weekly_matches = 0")
        conn.commit()
        conn.close()

    @weekly_reset.before_loop
    async def before_reset(self):
        await self.bot.wait_until_ready()

    # ==========================================
    # 🛡️ CUPID COMMANDS
    # ==========================================
    @app_commands.command(name="cupid", description="Access the Matchmaking Terminal")
    @app_commands.checks.has_role(1218201074448732270) 
    async def cupid_dashboard(self, interaction: discord.Interaction):
        await interaction.response.send_message(f"<a:wt_torospin:1480580977867624540> 𝐼𝑛𝑖𝑡𝑖𝑎𝑙𝑖𝑧𝑖𝑛𝑔 𝐶𝑢𝑝𝑖𝑑 𝐼𝑛𝑡𝑒𝑟𝑓𝑎𝑐𝑒 𝑓𝑜𝑟 {interaction.user.name}...", ephemeral=False)
        await asyncio.sleep(1.5)
        
        embed = discord.Embed(title="꒰ა ﹒chérie  ⸝⸝", color=0xffffff)
        embed.description = (
            "'As the Head of the Matchmaking Division, my objective is to ensure absolute precision in our matches."
            "I am here to oversee your pairings, approve final matches, and resolve any operational anomalies.' **-Nami**\n\n"
            "**<a:wt_torolove:1480580899430203484> Standard Operating Procedures** <a:wt_torolove:1480580899430203484>\n\n"
            "<:s_white2:1382052523166142486> A minimum of 7 matches must be finalized weekly.\n\n"
            "<:s_white2:1382052523166142486> All forms must be reviewed with absolute scrutiny.\n\n"
            "<:s_white2:1382052523166142486> Any applications violating community guidelines must be immediately logged, the user issued a strike, and formal notification sent.\n"
        )
        embed.set_thumbnail(url=interaction.user.display_avatar.url)
        # Adds the beautiful banner to the bottom of the dashboard
        embed.set_image(url="https://cdn.discordapp.com/attachments/1441473281420169367/1501576429761200290/0ac4c99804a08a107d2cf6f09d79655f.jpg?ex=6a008806&is=69ff3686&hm=4205b070b2abc9c883782db32c3e709027a4b6381ba1c83da86b0ad8c9834784&")
        
        await interaction.edit_original_response(content=None, embed=embed, view=DashboardView())

    @cupid_dashboard.error
    async def cupid_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.MissingRole):
            await interaction.response.send_message("<a:wt_torono:1480580892706603018> 𝑇ℎ𝑖𝑠 𝑡𝑒𝑟𝑚𝑖𝑛𝑎𝑙 𝑖𝑠 𝑟𝑒𝑠𝑡𝑟𝑖𝑐𝑡𝑒𝑑 𝑡𝑜 𝑜𝑓𝑓𝑖𝑐𝑖𝑎𝑙 𝐶𝑢𝑝𝑖𝑑𝑠.", ephemeral=False)

    @app_commands.command(name="strikesview", description="View all users with active matchmaking strikes")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def strikesview(self, interaction: discord.Interaction):
        await interaction.response.defer()
        
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT user_id, strike_level, reason, issuer_id FROM user_strikes ORDER BY timestamp DESC")
        strikes = cursor.fetchall()
        conn.close()

        if not strikes:
            return await interaction.followup.send("<a:wt_toroleaf:1480580940785913967> 𝑁𝑜 𝑎𝑐𝑡𝑖𝑣𝑒 𝑠𝑡𝑟𝑖𝑘𝑒𝑠 ℎ𝑎𝑣𝑒 𝑏𝑒𝑒𝑛 𝑖𝑠𝑠𝑢𝑒𝑑.")

        formatted_strikes = []
        for uid, level, reason, issuer in strikes:
            # Safely fetch user from cache or API to prevent "Unknown User"
            member = interaction.guild.get_member(uid)
            if member:
                name = member.name
            else:
                try:
                    user_obj = await self.bot.fetch_user(uid)
                    name = user_obj.name
                except discord.NotFound:
                    name = "Unknown User"

            formatted_strikes.append(
                f"**<:s_white2:1382052523166142486> User:** {name} (`{uid}`)\n"
                f"**Severity:** Strike {level}\n"
                f"**Reason:** {reason}\n"
                f"**Issued By:** <@{issuer}>\n\n\n" 
            )

        view = SimplePaginationView(formatted_strikes, "𝑆𝑡𝑟𝑖𝑘𝑒 𝐿𝑜𝑔", items_per_page=5)
        await interaction.followup.send(embed=view.get_embed(), view=view)

    # ==========================================
    # 📋 CUPID HR & ONBOARDING COMMANDS
    # ==========================================

    @app_commands.command(name="cupidprofilecreate", description="Create a profile for a new Cupid")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def create_cupid(self, interaction: discord.Interaction, user: discord.Member):
        if user.bot:
            return await interaction.response.send_message("<a:wt_torono:1480580892706603018> 𝐶𝑎𝑛𝑛𝑜𝑡 𝑐𝑟𝑒𝑎𝑡𝑒 𝑎 𝑝𝑟𝑜𝑓𝑖𝑙𝑒 𝑓𝑜𝑟 𝑎 𝑏𝑜𝑡.", ephemeral=True)
            
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        cursor.execute("SELECT user_id FROM cupid_profiles WHERE user_id = ?", (user.id,))
        if cursor.fetchone():
            conn.close()
            return await interaction.response.send_message(f"<a:wt_torono:1480580892706603018> {user.mention} 𝑎𝑙𝑟𝑒𝑎𝑑𝑦 ℎ𝑎𝑠 𝑎 𝐶𝑢𝑝𝑖𝑑 𝑃𝑟𝑜𝑓𝑖𝑙𝑒.", ephemeral=True)
            
        cursor.execute("INSERT INTO cupid_profiles (user_id) VALUES (?)", (user.id,))
        cursor.execute("INSERT OR IGNORE INTO cupid_stats (user_id, weekly_matches, all_time_matches) VALUES (?, 0, 0)", (user.id,))
        
        conn.commit()
        conn.close()
        
        await interaction.response.send_message(f"<a:wt_toroexclaim:1480581004317036624> 𝑆𝑢𝑐𝑐𝑒𝑠𝑠𝑓𝑢𝑙𝑙𝑦 𝑐𝑟𝑒𝑎𝑡𝑒𝑑 𝑡ℎ𝑒 𝐶𝑢𝑝𝑖𝑑 𝑃𝑟𝑜𝑓𝑖𝑙𝑒 𝑓𝑜𝑟 {user.name}.")

        # --- DM DISPATCH FOR NEW CUPIDS ---
        try:
            dm_embed = discord.Embed(title="𝑊𝑒𝑙𝑐𝑜𝑚𝑒 𝑡𝑜 𝑡ℎ𝑒 𝐶𝑢𝑝𝑖𝑑 𝐷𝑖𝑣𝑖𝑠𝑖𝑜𝑛", color=0xffffff)
            dm_embed.description = "Your offical Cupid Profile has been created! You can now access the cupid terminal and view your progress by typing `/cupid` in the server."
            await user.send(embed=dm_embed)
        except discord.Forbidden:
            pass # Fails silently if their DMs are closed

    @app_commands.command(name="cupidprofiledelete", description="Remove a Cupid's profile")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def delete_cupid(self, interaction: discord.Interaction, user: discord.User):
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        cursor.execute("SELECT user_id FROM cupid_profiles WHERE user_id = ?", (user.id,))
        if not cursor.fetchone():
            conn.close()
            return await interaction.response.send_message(f"❌ {user.name} does not have a Cupid Profile.", ephemeral=True)
            
        cursor.execute("DELETE FROM cupid_profiles WHERE user_id = ?", (user.id,))
        
        conn.commit()
        conn.close()
        
        await interaction.response.send_message(f"<a:wt_toroexclaim:1480581004317036624> 𝑆𝑢𝑐𝑐𝑒𝑠𝑠𝑓𝑢𝑙𝑙𝑦 𝑑𝑒𝑙𝑒𝑡𝑒𝑑 𝑡ℎ𝑒 𝐶𝑢𝑝𝑖𝑑 𝑃𝑟𝑜𝑓𝑖𝑙𝑒 𝑓𝑜𝑟 {user.name}.")

    @app_commands.command(name="cupidview", description="STAFF: View all active Cupids and their quotas")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def cupidview(self, interaction: discord.Interaction):
        await interaction.response.defer()
        
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('''
            SELECT p.user_id, COALESCE(s.weekly_matches, 0)
            FROM cupid_profiles p
            LEFT JOIN cupid_stats s ON p.user_id = s.user_id
        ''')
        cupids = cursor.fetchall()
        conn.close()

        if not cupids:
            return await interaction.followup.send("<a:wt_toroconfused:1480580932367945918> 𝑁𝑜 𝐶𝑢𝑝𝑖𝑑 𝑝𝑟𝑜𝑓𝑖𝑙𝑒𝑠 ℎ𝑎𝑣𝑒 𝑏𝑒𝑒𝑛 𝑐𝑟𝑒𝑎𝑡𝑒𝑑 𝑦𝑒𝑡. 𝑈𝑠𝑒 `/cupidprofilecreate`.")

        formatted_cupids = []
        for uid, weekly in cupids:
            # Safely fetch user from cache or API to prevent "Unknown User"
            member = interaction.guild.get_member(uid)
            if member:
                name = member.name
            else:
                try:
                    user_obj = await self.bot.fetch_user(uid)
                    name = user_obj.name
                except discord.NotFound:
                    name = "Unknown User"

            formatted_cupids.append(f"**{name}** (`{uid}`)\n**Quota:** {make_emoji_bar(weekly, 7)}\n\n")

        view = SimplePaginationView(formatted_cupids, "", items_per_page=10)
        await interaction.followup.send(embed=view.get_embed(), view=view)

async def setup(bot):
    await bot.add_cog(CupidDashboard(bot))