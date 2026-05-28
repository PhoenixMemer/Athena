import discord
from discord import app_commands
from discord.ext import commands
import sqlite3
import random
import time
from contextlib import contextmanager
from typing import Optional

DB_PATH = "economy.db"
BUG_CHANNEL_ID = 1411661529920704512
OWNER_ID = 743411894416834590  # Phoenix

# ✅ Emojis that resolve the bug (custom emoji IDs can be added)
RESOLVE_EMOJIS = {
    "✅",           # white check mark
    "👍",           # thumbs up
    "<:duathumbsup:896339449473024011>"  # replace EMOJI_ID with your actual custom emoji ID
}

# ==========================================
# 🗄️ DATABASE CONTEXT MANAGER
# ==========================================
@contextmanager
def get_db_cursor():
    conn = sqlite3.connect(DB_PATH, timeout=20, isolation_level=None)
    conn.execute('PRAGMA journal_mode=WAL;')
    conn.execute('PRAGMA temp_store = MEMORY;')
    conn.execute('PRAGMA synchronous = NORMAL;')
    cursor = conn.cursor()
    try:
        yield cursor
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()

# ==========================================
# 🗃️ SETUP DATABASE TABLE
# ==========================================
def setup_db():
    with get_db_cursor() as c:
        c.execute('''
            CREATE TABLE IF NOT EXISTS bug_reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                report_id TEXT UNIQUE,
                user_id INTEGER,
                description TEXT,
                media_url TEXT,
                channel_id INTEGER,
                message_id INTEGER,
                status TEXT DEFAULT 'pending',
                timestamp REAL
            )
        ''')

# ==========================================
# 🔢 GENERATE UNIQUE 3-DIGIT ID
# ==========================================
def generate_unique_id(cursor) -> str:
    """Generate a 3-digit string (001-999) not already in use."""
    while True:
        rid = f"{random.randint(1, 999):03d}"
        cursor.execute("SELECT 1 FROM bug_reports WHERE report_id = ?", (rid,))
        if not cursor.fetchone():
            return rid

# ==========================================
# 🐛 BUG REPORT COG
# ==========================================
class BugReports(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        setup_db()

    @app_commands.command(name="report", description="Report a bug to the developers")
    @app_commands.describe(
        details="Describe the issue in detail",
        media="Attach a screenshot or file (optional)"
    )
    async def bug_report(
        self,
        interaction: discord.Interaction,
        details: str,
        media: Optional[discord.Attachment] = None
    ):
        await interaction.response.defer(ephemeral=False)

        with get_db_cursor() as c:
            report_id = generate_unique_id(c)
            media_url = media.url if media else None
            now = time.time()

            c.execute('''
                INSERT INTO bug_reports (report_id, user_id, description, media_url, timestamp)
                VALUES (?, ?, ?, ?, ?)
            ''', (report_id, interaction.user.id, details, media_url, now))

            # Get the autoincrement id for reference (optional)
            row_id = c.lastrowid

        # Send embed to bug channel
        channel = self.bot.get_channel(BUG_CHANNEL_ID)
        if not channel:
            await interaction.followup.send("Bug channel not found. Please contact an admin.", ephemeral=True)
            return

        embed = discord.Embed(
            title=f"<:Hazard:1509430896162377859> Bug Report #{report_id}",
            description=details,
            color=0xff4444,
            timestamp=discord.utils.utcnow()
        )
        embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.display_avatar.url)
        embed.add_field(name="Reporter", value=f"{interaction.user.mention} (`{interaction.user.id}`)", inline=False)

        if media_url:
            embed.add_field(name="Attachment", value=f"[Click to view]({media_url})", inline=False)
            embed.set_image(url=media_url)  # if it's an image, it will show

        # Send and store message ID
        msg = await channel.send(content=f"<@{OWNER_ID}>", embed=embed)
        with get_db_cursor() as c:
            c.execute("UPDATE bug_reports SET channel_id = ?, message_id = ? WHERE report_id = ?",
                      (BUG_CHANNEL_ID, msg.id, report_id))

        await interaction.followup.send(f"Bug report **#{report_id}** submitted! Thank you for making Athena better <a:h_white4:1416368341244837979>", ephemeral=False)

    # ==========================================
    # 👂 REACTION LISTENER FOR RESOLUTION
    # ==========================================
    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        # Ignore if not in the correct channel
        if payload.channel_id != BUG_CHANNEL_ID:
            return

        # Check emoji
        emoji_str = str(payload.emoji)
        # Handle custom emoji format: "<:name:id>" or "<a:name:id>"
        if emoji_str not in RESOLVE_EMOJIS and not any(emoji_str == e for e in RESOLVE_EMOJIS):
            return

        # Only owner can resolve
        if payload.user_id != OWNER_ID:
            return

        # Get the message
        channel = self.bot.get_channel(payload.channel_id)
        if not channel:
            return
        try:
            message = await channel.fetch_message(payload.message_id)
        except:
            return

        # Check if this message is a bug report (look up in DB)
        with get_db_cursor() as c:
            c.execute("SELECT user_id, report_id, status FROM bug_reports WHERE message_id = ?", (message.id,))
            row = c.fetchone()
            if not row:
                return
            user_id, report_id, status = row
            if status == 'resolved':
                return  # Already resolved

            # Update status
            c.execute("UPDATE bug_reports SET status = 'resolved' WHERE message_id = ?", (message.id,))

        # DM the reporter
        user = self.bot.get_user(user_id)
        if user:
            try:
                embed = discord.Embed(
                    title="Bug Resolved!",
                    description=f"Your report **#{report_id}** has been marked as resolved by phnx <a:blackpixelheart2:1509425208799268914> Thank you for helping improve Athena!",
                    color=0xffffff
                )
                await user.send(embed=embed)
            except discord.Forbidden:
                pass  # User has DMs disabled

        # Optionally, edit the original embed to show resolved status
        embed = message.embeds[0] if message.embeds else None
        if embed:
            embed.color = 0xffffff
            embed.set_footer(text="RESOLVED")
            await message.edit(embed=embed)

        # Remove the reaction so it doesn't trigger again
        try:
            await message.remove_reaction(payload.emoji, channel.guild.get_member(OWNER_ID))
        except:
            pass

async def setup(bot):
    await bot.add_cog(BugReports(bot))