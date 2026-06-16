import discord
from discord import app_commands
from discord.ext import commands, tasks
import sqlite3
import random
import time
import asyncio
from typing import List, Optional
from contextlib import contextmanager

DB_PATH = "economy.db"
DEFAULT_NETWORTH_BANNER = "https://i.pinimg.com/originals/e8/f6/1b/e8f61b64959302d3b04a4db7dbb53f3a.gif"

def make_quality_bar(percent: int) -> str:
    """Creates a custom emoji progress bar for property quality (0-100) – 5 segments to avoid mobile wrapping."""
    filled_segments = percent // 20          # 0-5 segments
    empty_segments = 5 - filled_segments

    fill_left = "<:fillleft:1502707988761153567>"
    fill_mid = "<:fillmid:1502707936823087246>"
    fill_right = "<:fillright:1502707911560794192>"
    empty_left = "<:emptyleft:1502707971363311767>"
    empty_mid = "<:emptymid:1502707866744651948>"
    empty_right = "<:emptyright:1502707890664771717>"

    bar = ""
    for i in range(5):
        is_filled = i < filled_segments
        if i == 0:
            bar += fill_left if is_filled else empty_left
        elif i == 4:
            bar += fill_right if is_filled else empty_right
        else:
            bar += fill_mid if is_filled else empty_mid

    return f"{bar}  **({percent}%)**"

# ==========================================
# 🗄️ SAFE DATABASE CONTEXT MANAGER
# ==========================================
@contextmanager
def get_db_cursor():
    """Context manager for safe, atomic DB operations with WAL mode"""
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
# 🔒 ATOMIC BALANCE & TRANSACTION HELPERS
# ==========================================
def atomic_balance_update(cursor, user_id: int, delta: int, max_retries: int = 10) -> bool:
    """Atomically updates balance and highest_balance with optimistic locking and retries."""
    for attempt in range(max_retries):
        cursor.execute("SELECT balance, highest_balance FROM wallets WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()
        
        if row is None:
            cursor.execute("INSERT OR IGNORE INTO wallets (user_id, balance, active_card, highest_balance) VALUES (?, 0, 'silver', 0)", (user_id,))
            new_highest = max(0, delta)
            cursor.execute("UPDATE wallets SET balance = ?, highest_balance = ? WHERE user_id = ?", (delta, new_highest, user_id))
            return True
        
        old_balance = row[0] or 0
        old_highest = row[1] or 0
        new_balance = old_balance + delta
        new_highest = max(old_highest, new_balance)
        
        cursor.execute(
            "UPDATE wallets SET balance = ?, highest_balance = ? WHERE user_id = ? AND balance = ?",
            (new_balance, new_highest, user_id, old_balance)
        )
        if cursor.rowcount > 0:
            return True
        
        # Small exponential backoff before retry
        time.sleep(0.1 * (2 ** attempt))
    
    return False

def log_transaction(cursor, user_id: int, amount: int, tx_type: str, description: str):
    """Logs every balance change for audit trails"""
    cursor.execute(
        "INSERT INTO transactions (user_id, amount, type, description) VALUES (?, ?, ?, ?)",
        (user_id, amount, tx_type.upper(), description)
    )


def check_tier_upgrade(cursor, user_id: int):
    """Checks highest_balance and upgrades active_card if threshold crossed"""
    cursor.execute("SELECT highest_balance, active_card FROM wallets WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    if not row: return
    
    highest = row[0] or 0
    current_card = (row[1] or "silver").strip()  # ✅ FIX: strip whitespace
    new_card = current_card
    
    for threshold, tier_key, _ in TIER_THRESHOLDS:
        if highest >= threshold and tier_key != current_card:
            new_card = tier_key
            break
            
    if new_card != current_card and not (current_card == "plat_pink" and new_card == "plat_black"):
        cursor.execute("UPDATE wallets SET active_card = ? WHERE user_id = ?", (new_card, user_id))
        log_transaction(cursor, user_id, 0, "TIER_UPGRADE", f"Auto-upgraded to {new_card}")

# ✅ FIX: Cleaned thresholds & card tiers (NO TRAILING SPACES)
TIER_THRESHOLDS = [
    (100_000, "gold", "Gold Elite"),
    (300_000, "crystal", "Crystal Debit"),
    (600_000, "plat_black", "Platinum Black"),
]

CARD_TIERS = {
    "silver": {"threshold": 0, "name": "Standard Silver"},
    "gold": {"threshold": 100_000, "name": "Gold Elite"},
    "crystal": {"threshold": 300_000, "name": "Crystal Debit"},
    "plat_black": {"threshold": 600_000, "name": "Platinum Black"},
    "plat_pink": {"threshold": 600_000, "name": "Platinum Chérie"}
}

def make_progress_bar(percent: int) -> str:
    filled = percent // 10
    empty = 10 - filled
    return f"`[{'█' * filled}{'░' * empty}] {percent}%`"

# ==========================================
# 🛒 DYNAMIC BUY BUTTONS (EPHEMERAL)
# ==========================================
class BuyOptionButton(discord.ui.Button):
    def __init__(self, item_id, item_type):
        label_text = f"#{item_id}" if item_type == "p2p" else item_id
        super().__init__(label=label_text, style=discord.ButtonStyle.primary)
        self.item_id = item_id
        self.item_type = item_type

    async def callback(self, i: discord.Interaction):
        with get_db_cursor() as c:
            # Ensure wallet exists
            c.execute("INSERT OR IGNORE INTO wallets (user_id, balance, active_card, highest_balance) VALUES (?, 0, 'silver', 0)", (i.user.id,))
            c.execute("SELECT balance FROM wallets WHERE user_id = ?", (i.user.id,))
            bal_row = c.fetchone()
            bal = bal_row[0] if bal_row else 0

            if self.item_type == "property":
                c.execute("SELECT name, base_price FROM market_properties WHERE id = ?", (self.item_id,))
                prop = c.fetchone()
                if not prop:
                    return await i.response.send_message("❌ Invalid property ID.", ephemeral=True)
                
                c.execute("SELECT id FROM user_properties WHERE user_id = ? AND property_id = ?", (i.user.id, self.item_id))
                if c.fetchone():
                    return await i.response.send_message("❌ You already own this property.", ephemeral=True)
                    
                if bal < prop[1]:
                    return await i.response.send_message(f"❌ Insufficient funds. You need **A$ {prop[1]:,}**.", ephemeral=True)
                    
                if not atomic_balance_update(c, i.user.id, -prop[1]):
                    return await i.response.send_message("❌ Balance updated concurrently. Please try again.", ephemeral=True)
                log_transaction(c, i.user.id, -prop[1], "PROPERTY_PURCHASE", f"Bought {prop[0]}")
                
                c.execute("INSERT INTO user_properties (user_id, property_id, quality, needs_repair) VALUES (?, ?, 20, 0)", (i.user.id, self.item_id))
                
                # --- MARKET LINKAGE: Real Estate Boom ---
                try: c.execute("UPDATE stocks SET price = price + int(price * 0.02), trend = '<:stockup_athena:1503776772850712616> UP' WHERE symbol = 'ARE'")
                except: pass

                check_tier_upgrade(c, i.user.id)
                await i.response.send_message(embed=discord.Embed(title="Deed Acquired", description=f"You now own **{prop[0]}**!\n\n<:stockup_athena:1503776772850712616> *The real estate market is booming! Your purchase just drove up the price of `ARE` stock!*", color=0xffffff), ephemeral=False)

            elif self.item_type == "vehicle":
                c.execute("SELECT name, price FROM market_vehicles WHERE id = ?", (self.item_id,))
                veh = c.fetchone()
                if not veh:
                    return await i.response.send_message("❌ Invalid vehicle ID.", ephemeral=True)
                
                c.execute("SELECT vehicle_id FROM user_vehicles WHERE user_id = ? AND vehicle_id = ?", (i.user.id, self.item_id))
                if c.fetchone():
                    return await i.response.send_message("❌ You already own this vehicle.", ephemeral=True)
                    
                if bal < veh[1]:
                    return await i.response.send_message(f"❌ Insufficient funds. You need **A$ {veh[1]:,}**.", ephemeral=True)
                    
                if not atomic_balance_update(c, i.user.id, -veh[1]):
                    return await i.response.send_message("❌ Balance updated concurrently. Please try again.", ephemeral=True)
                log_transaction(c, i.user.id, -veh[1], "VEHICLE_PURCHASE", f"Bought {veh[0]}")
                
                c.execute("INSERT INTO user_vehicles (user_id, vehicle_id, needs_repair) VALUES (?, ?, 0)", (i.user.id, self.item_id))
                check_tier_upgrade(c, i.user.id)
                await i.response.send_message(embed=discord.Embed(title="<:car_athena:1501939281479073842> Keys Handed Over", description=f"You purchased a **{veh[0]}**!", color=0xffffff), ephemeral=True)

            elif self.item_type == "p2p":
                lid = int(self.item_id)
                c.execute("SELECT seller_id, item_id, price FROM p2p_listings WHERE id = ?", (lid,))
                listing = c.fetchone()
                if not listing:
                    return await i.response.send_message("❌ Listing not found or already sold.", ephemeral=True)
                    
                if bal < listing[2]:
                    return await i.response.send_message("❌ Insufficient funds.", ephemeral=True)
                    
                fee = int(listing[2] * 0.02)
                payout = listing[2] - fee
                
                # Atomic updates for both parties
                if not atomic_balance_update(c, listing[0], payout):
                    return await i.response.send_message("❌ Seller balance updated concurrently. Please try again.", ephemeral=True)
                if not atomic_balance_update(c, i.user.id, -listing[2]):
                    # Rollback seller payout if buyer fails (best effort)
                    atomic_balance_update(c, listing[0], -payout)
                    return await i.response.send_message("❌ Your balance updated concurrently. Please try again.", ephemeral=True)
                    
                log_transaction(c, listing[0], payout, "P2P_SALE", f"Sold listing #{lid}")
                log_transaction(c, i.user.id, -listing[2], "P2P_PURCHASE", f"Bought listing #{lid}")
                
                c.execute("INSERT INTO user_properties (user_id, property_id, quality, needs_repair) VALUES (?, ?, 100, 0)", (i.user.id, listing[1]))
                c.execute("DELETE FROM p2p_listings WHERE id = ?", (lid,))

                # --- MARKET LINKAGE: Minor Real Estate Bump ---
                try: c.execute("UPDATE stocks SET price = price + int(price * 0.01), trend = '📈 UP' WHERE symbol = 'ARE'")
                except: pass

                check_tier_upgrade(c, i.user.id)
                await i.response.send_message(embed=discord.Embed(title=" P2P Purchase Complete", description=f"You purchased listing #{lid} for **A$ {listing[2]:,}**!\n\n📈 *This private transfer drove up the price of `ARE` stock!*", color=0xffffff), ephemeral=True)


# ==========================================
# 🏛️ UI COMPONENTS (DROPDOWN + BUY BTN)
# ==========================================
class BannerModal(discord.ui.Modal, title="Customize Profile Banner"):
    banner_url = discord.ui.TextInput(
        label="Image URL (Must end in .png, .jpg, .gif)",
        placeholder="e.g https://media.discordapp.net/attachments/...",
        required=True,
        max_length=500
    )

    async def on_submit(self, interaction: discord.Interaction):
        url = self.banner_url.value
        
        # Basic validation to ensure Discord can actually embed it
        if not (url.startswith("http") and any(ext in url.lower() for ext in [".png", ".jpg", ".jpeg", ".gif"])):
            return await interaction.response.send_message("<a:wt_torono:1480580892706603018> Invalid image URL. It must be a direct link to an image file.", ephemeral=True)
            
        with get_db_cursor() as cursor:
            # We already know they have 1.2mil+ because the button only appears if they do
            cursor.execute("UPDATE wallets SET profile_banner = ? WHERE user_id = ?", (url, interaction.user.id))
            
        await interaction.response.send_message("<a:wt_torohappyjump:1480580973400690932> Your custom banner has been set! Run `/networth` to view it.", ephemeral=True)

class NetworthView(discord.ui.View):
    def __init__(self, user_id: int):
        super().__init__(timeout=None)
        self.user_id = user_id

    @discord.ui.button(label="Set Banner", style=discord.ButtonStyle.secondary, emoji="<a:wt_toropeek:1480580945084944484>")
    async def banner_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("You can only set the banner on your own profile.", ephemeral=True)
        await interaction.response.send_modal(BannerModal())




class MarketplaceDropdown(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label='Residential Listings', description='Flats, Townhouses, and Cottages', value='Residential', emoji="<a:wt_torosoul:1480580991503306865>"),
            discord.SelectOption(label='Commercial Listings', description='M&S, Greggs, Weatherspoons', value='Commercial', emoji="<a:wt_torosilly:1480580853720551637>"),
            discord.SelectOption(label='Elite Listings', description='High society luxury real estate', value='Elite', emoji="<a:wt_toroking:1480580998742937691>"),
            discord.SelectOption(label='Yacht Marina', description='Superyachts for the wealthy', value='Yacht', emoji="<a:wt_torofreeze:1480580916559478966>"),
            discord.SelectOption(label='Private Aviation', description='Private Jets for the not broke people', value='Jet', emoji="<a:wt_toroglassesshock:1480581012475084892>"),
            discord.SelectOption(label='Vehicle Showroom', description='Supercars and Luxury Commuters', value='Vehicles', emoji="<a:wt_toroleaf:1480580940785913967>"),
            discord.SelectOption(label='P2P Trading Floor', description='Buy assets directly from OTHER players', value='P2P', emoji="<a:wt_torofly:1480580890185826364>"),
        ]
        super().__init__(placeholder='Select a sector to browse...', min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        category = self.values[0]
        self.view.current_category = category
        self.view.buy_btn.disabled = False

        with get_db_cursor() as cursor:
            if category == "P2P":
                cursor.execute('''SELECT l.id, m.name, l.price, l.seller_id 
                                  FROM p2p_listings l JOIN market_properties m ON l.item_id = m.id''')
                listings = cursor.fetchall()
                embed = discord.Embed(title="P2P Trading Floor", color=0xffffff)
                desc = "Direct listings from other property owners. Click **Buy** below to purchase.\n\n"
                for lid, name, price, seller_id in listings:
                    seller = interaction.guild.get_member(seller_id) if interaction.guild else None
                    s_name = seller.name if seller else "Inactive User"
                    desc += f"**<a:014White_Heart2:1509413123810136196> {name}** `[Listing #{lid}]`\n"
                    desc += f"**<a:014White_Heart2:1509413123810136196> Seller:** {s_name}\n"
                    desc += f"<:athenacoin:1503804322280902767> **Price:** A$ {price:,}\n\n"
                embed.description = desc if listings else "The trading floor is currently empty. List your properties with `/marketplace list`!"

            elif category in ["Car", "Yacht", "Jet"]:
                cursor.execute("SELECT id, name, price, cooldown_reduction FROM market_vehicles WHERE category = ?", (category,))
                vehicles = cursor.fetchall()
                embed = discord.Embed(title=f"{category} Showroom", color=0xffffff)
                desc = "Luxury assets. Owning these boosts prestige (will soon have perks for businesses)\n\n"
                for vid, name, price, bonus in vehicles:
                    desc += f"<a:014White_Heart2:1509413123810136196> **{name}** `[{vid}]`\n"
                    if bonus > 0:
                        desc += f"<a:014White_Heart2:1509413123810136196> **Commute Bonus:** -{bonus}m On Work Cooldown\n"
                    desc += f"<:athenacoin:1503804322280902767> **Price:** A$ {price:,}\n\n"
                embed.description = desc

            elif category == "Vehicles":
                # Show only cars (not yachts or jets)
                cursor.execute("SELECT id, name, price, cooldown_reduction FROM market_vehicles WHERE category = 'Car'")
                vehicles = cursor.fetchall()
                embed = discord.Embed(title="Athena Showroom", color=0xffffff)
                desc = "Luxury vehicles. Owning these reduces your `/work` cooldown.\n\n"
                for vid, name, price, bonus in vehicles:
                    desc += f"<a:014White_Heart2:1509413123810136196> **{name}** `[{vid}]`\n"
                    desc += f"**<a:014White_Heart2:1509413123810136196> Commute Bonus:** -{bonus}m On Work Cooldown\n"
                    desc += f"<:athenacoin:1503804322280902767> **Price:** A$ {price:,}\n\n"
                embed.description = desc

            else:
                cursor.execute("SELECT id, name, base_price, base_rent FROM market_properties WHERE category = ?", (category,))
                properties = cursor.fetchall()
                embed = discord.Embed(title=f"{category} Real Estate", color=0xffffff)
                desc = "Available deeds. Click **Buy** below to purchase.\n\n"
                for pid, name, price, rent in properties:
                    desc += f"<a:014White_Heart2:1509413123810136196> **{name}** `[{pid}]`\n"
                    desc += f"**<a:014White_Heart2:1509413123810136196> Price:** A$ {price:,}\n"
                    desc += f"<:athenacoin:1503804322280902767> **Base Rent:** A$ {rent:,} / day\n\n"
                embed.description = desc

        await interaction.response.edit_message(embed=embed, view=self.view)

class MarketplaceView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.current_category = None
        
        self.dropdown = MarketplaceDropdown()
        self.add_item(self.dropdown)

        self.buy_btn = discord.ui.Button(label="Buy", style=discord.ButtonStyle.success, disabled=True, row=1)
        self.buy_btn.callback = self.buy_callback
        self.add_item(self.buy_btn)

    async def buy_callback(self, interaction: discord.Interaction):
        cat = self.current_category
        if not cat:
            return

        with get_db_cursor() as c:
            options_view = discord.ui.View(timeout=60)

            # Handle all vehicle categories (Car, Yacht, Jet, Vehicles)
            if cat in ("Vehicles", "Car", "Yacht", "Jet"):
                if cat == "Vehicles":
                    # Show only cars
                    c.execute("SELECT id FROM market_vehicles WHERE category = 'Car'")
                else:
                    # Show only vehicles matching the category
                    c.execute("SELECT id FROM market_vehicles WHERE category = ?", (cat,))
                for (vid,) in c.fetchall()[:25]:
                    options_view.add_item(BuyOptionButton(vid, "vehicle"))

            elif cat == "P2P":
                c.execute("SELECT id FROM p2p_listings")
                for (lid,) in c.fetchall()[:25]:
                    options_view.add_item(BuyOptionButton(str(lid), "p2p"))
            else:
                # Real estate categories (Residential, Commercial, Elite)
                c.execute("SELECT id FROM market_properties WHERE category = ?", (cat,))
                for (pid,) in c.fetchall()[:25]:
                    options_view.add_item(BuyOptionButton(pid, "property"))

            if len(options_view.children) == 0:
                return await interaction.response.send_message("No items available to buy in this category.", ephemeral=True)

            await interaction.response.send_message("**Select an asset code to purchase:**", view=options_view, ephemeral=True)

# ==========================================
# 🏙️ THE MARKETPLACE COG
# ==========================================
class Marketplace(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.setup_db()
        self.rent_collection.start() 
        self.maintenance_sweep.start()

    def setup_db(self):
        with get_db_cursor() as cursor:
            cursor.execute('CREATE TABLE IF NOT EXISTS market_properties (id TEXT PRIMARY KEY, name TEXT, category TEXT, base_price INTEGER, base_rent INTEGER)')
            cursor.execute('CREATE TABLE IF NOT EXISTS user_properties (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, property_id TEXT, quality INTEGER DEFAULT 20, needs_repair INTEGER DEFAULT 0, UNIQUE(user_id, property_id))')
            cursor.execute('''CREATE TABLE IF NOT EXISTS rent_failures (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                property_id TEXT,
                amount INTEGER,
                failed_at REAL
            )''')
            cursor.execute('CREATE TABLE IF NOT EXISTS market_vehicles (id TEXT PRIMARY KEY, name TEXT, price INTEGER, cooldown_reduction INTEGER, category TEXT DEFAULT "Car")')
            cursor.execute('CREATE TABLE IF NOT EXISTS user_vehicles (user_id INTEGER, vehicle_id TEXT, needs_repair INTEGER DEFAULT 0, UNIQUE(user_id, vehicle_id))')
            
            cursor.execute('CREATE TABLE IF NOT EXISTS p2p_listings (id INTEGER PRIMARY KEY AUTOINCREMENT, seller_id INTEGER, item_id TEXT, price INTEGER)')
            
            # Ensure transactions table exists
            cursor.execute('''CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER,
                amount INTEGER, type TEXT, description TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )''')

            # Cycle tracker for rent guard
            cursor.execute('''CREATE TABLE IF NOT EXISTS cycle_tracker (
                key TEXT PRIMARY KEY,
                last_run REAL
            )''')

            try: cursor.execute("ALTER TABLE market_vehicles ADD COLUMN category TEXT DEFAULT 'Car'")
            except: pass
            try: cursor.execute("ALTER TABLE wallets ADD COLUMN profile_banner TEXT")
            except: pass
            try: cursor.execute("ALTER TABLE user_properties ADD COLUMN needs_repair INTEGER DEFAULT 0")
            except: pass
            try: cursor.execute("ALTER TABLE user_vehicles ADD COLUMN needs_repair INTEGER DEFAULT 0")
            except: pass
            try: cursor.execute("ALTER TABLE wallets ADD COLUMN profile_banner TEXT")
            except: pass

            vehicles = [
                ('CAR1', 'Mini Cooper S', 15000, 20, 'Car'),
                ('CAR2', 'Land Rover Defender', 45000, 30, 'Car'),
                ('CAR3', 'Jaguar F-Type', 95000, 35, 'Car'),
                ('CAR4', 'Aston Martin DB12', 185000, 40, 'Car'),
                ('CAR5', 'Chevrolet Corvette ZR1', 195000, 45, 'Car'),
                ('CAR6', 'Rolls-Royce Cullinan', 250000, 50, 'Car'),
                ('CAR7', 'Ferrari SF90 Stradale', 320000, 60, 'Car')
            ]
            cursor.executemany("INSERT OR REPLACE INTO market_vehicles VALUES (?, ?, ?, ?, ?)", vehicles)

            yachts_and_planes = [
                ('YACHT1', 'Sunseeker Predator 84', 15000000, 0, 'Yacht'),
                ('YACHT2', 'Benetti Oasis 67', 25000000, 0, 'Yacht'),
                ('YACHT3', 'Azzam Superyacht', 35000000, 0, 'Yacht'),
                ('YACHT4', 'Cassiopeia', 45000000, 0, 'Yacht'),
                ('YACHT5', 'Polaris Valencia', 55000000, 0, 'Yacht'),
                ('JET1', 'Cessna Citation CJ4', 7000000, 0, 'Jet'),
                ('JET2', 'Gulfstream G700', 15000000, 0, 'Jet'),
                ('JET3', 'Dassault Falcon 10X', 25000000, 0, 'Jet'),
                ('JET4', 'Bombardier Global 6000', 35000000, 0, 'Jet')
            ]
            cursor.executemany("INSERT OR IGNORE INTO market_vehicles VALUES (?, ?, ?, ?, ?)", yachts_and_planes)
            
            properties = [
                ('RES1', 'The Kensington Flat', 'Residential', 25000, 1250),
                ('RES2', 'Camden Townhouse', 'Residential', 75000, 3750),
                ('RES3', 'Cobblestone Mews', 'Residential', 150000, 7500),
                ('RES4', 'Berkshire Cottage', 'Residential', 200000, 10000),
                ('COM1', "Marks and Spencer's (M&S)", 'Commercial', 350000, 17500),
                ('COM2', 'Block & Quayle (B&Q)', 'Commercial', 500000, 25000),
                ('COM3', 'Greggs', 'Commercial', 150000, 7500),
                ('COM4', 'Weatherspoons Pub', 'Commercial', 250000, 12500),
                ('COM5', 'Peppa Pig World', 'Commercial', 1500000, 75000),
                ('COM6', 'Sanrio Studios', 'Commercial', 3500000, 75000),
                ('COM7', 'Ferrari Land', 'Commercial', 4000000, 95000),
                ('ELI1', 'The Windsor Estate', 'Elite', 5000000, 250000),
                ('ELI2', 'Chelsea Penthouse', 'Elite', 8000000, 400000),
                ('ELI3', 'Buckingham Manor', 'Elite', 15000000, 750000)
            ]
            cursor.executemany("INSERT OR REPLACE INTO market_properties VALUES (?, ?, ?, ?, ?)", properties)

    @app_commands.command(name="fix_vehicles_force", description="ADMIN: Force rebuild vehicle table with all assets")
    @app_commands.default_permissions(administrator=True)
    async def fix_vehicles_force(self, i: discord.Interaction):
        await i.response.defer(ephemeral=True)
        with get_db_cursor() as c:
            # Drop and recreate the table to ensure correct schema
            c.execute("DROP TABLE IF EXISTS market_vehicles")
            c.execute('''CREATE TABLE market_vehicles (
                id TEXT PRIMARY KEY,
                name TEXT,
                price INTEGER,
                cooldown_reduction INTEGER,
                category TEXT DEFAULT 'Car'
            )''')
            # Insert all vehicles: cars, yachts, jets
            vehicles = [
                # Cars
                ('CAR1', 'Mini Cooper S', 15000, 20, 'Car'),
                ('CAR2', 'Land Rover Defender', 45000, 30, 'Car'),
                ('CAR3', 'Jaguar F-Type', 95000, 35, 'Car'),
                ('CAR4', 'Aston Martin DB12', 185000, 40, 'Car'),
                ('CAR5', 'Chevrolet Corvette ZR1', 195000, 45, 'Car'),
                ('CAR6', 'Rolls-Royce Cullinan', 250000, 50, 'Car'),
                ('CAR7', 'Ferrari SF90 Stradale', 320000, 60, 'Car'),
                # Yachts
                ('YACHT1', 'Sunseeker Predator 84', 15000000, 0, 'Yacht'),
                ('YACHT2', 'Benetti Oasis 67', 25000000, 0, 'Yacht'),
                ('YACHT3', 'Azzam Superyacht', 35000000, 0, 'Yacht'),
                ('YACHT4', 'Cassiopeia', 45000000, 0, 'Yacht'),
                ('YACHT5', 'Polaris Valencia', 55000000, 0, 'Yacht'),
                # Jets
                ('JET1', 'Cessna Citation CJ4', 7000000, 0, 'Jet'),
                ('JET2', 'Gulfstream G700', 15000000, 0, 'Jet'),
                ('JET3', 'Dassault Falcon 10X', 25000000, 0, 'Jet'),
                ('JET4', 'Bombardier Global 6000', 35000000, 0, 'Jet')
            ]
            c.executemany("INSERT INTO market_vehicles (id, name, price, cooldown_reduction, category) VALUES (?, ?, ?, ?, ?)", vehicles)
        await i.followup.send("✅ Vehicle table rebuilt with all cars, yachts, and jets.", ephemeral=True)

    # ==========================================
    #  AUTOMATED BACKGROUND TASKS
    # ==========================================
    @tasks.loop(hours=24)
    async def rent_collection(self):
        import datetime
        with get_db_cursor() as cursor:
            # Guard using date string (compatible with old data)
            cursor.execute("SELECT last_run FROM cycle_tracker WHERE key = 'last_rent_cycle'")
            row = cursor.fetchone()
            today = datetime.datetime.now().strftime("%Y-%m-%d")
            if row and row[0] == today:
                return

            print(f"[RENT] Starting rent collection at {datetime.datetime.now()}")

            cursor.execute('''SELECT u.user_id, m.base_rent, u.quality, u.property_id, m.category
                              FROM user_properties u JOIN market_properties m ON u.property_id = m.id 
                              WHERE u.needs_repair = 0''')
            properties = cursor.fetchall()

            failed_payments = []

            for uid, base_rent, quality, prop_id, category in properties:
                try:
                    mult = 1.0 + (1.5 * (quality / 100.0))
                    gross_rent = int(base_rent * mult)

                    if category == 'Residential':
                        tax_rate = 0.05
                    elif category == 'Commercial':
                        tax_rate = 0.20
                    elif category == 'Elite':
                        tax_rate = 0.35
                    else:
                        tax_rate = 0.0

                    tax = int(gross_rent * tax_rate)
                    net_rent = gross_rent - tax

                    success = False
                    for attempt in range(5):
                        if atomic_balance_update(cursor, uid, net_rent):
                            log_transaction(cursor, uid, net_rent, "RENT_INCOME", 
                                            f"Daily rent from {prop_id} (quality {quality}%) - Tax A${tax:,}")
                            if tax > 0:
                                log_transaction(cursor, uid, -tax, "PROPERTY_TAX", 
                                                f"Tax on {prop_id} ({category})")
                            check_tier_upgrade(cursor, uid)
                            success = True
                            break
                        await asyncio.sleep(0.2)
                    if not success:
                        failed_payments.append((uid, prop_id, net_rent))
                        print(f"[RENT FAIL] User {uid}, property {prop_id}, amount A${net_rent:,} – will be retried manually")
                except Exception as e:
                    print(f"[RENT ERROR] User {uid}, property {prop_id}: {e}")

            if failed_payments:
                try:
                    cursor.execute("CREATE TABLE IF NOT EXISTS rent_failures (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, property_id TEXT, amount INTEGER, failed_at REAL)")
                    now_ts = time.time()
                    for uid, pid, amt in failed_payments:
                        cursor.execute("INSERT INTO rent_failures (user_id, property_id, amount, failed_at) VALUES (?, ?, ?, ?)", (uid, pid, amt, now_ts))
                except:
                    pass

            cursor.execute("INSERT OR REPLACE INTO cycle_tracker (key, last_run) VALUES ('last_rent_cycle', ?)", (today,))

            
    @tasks.loop(hours=24)
    async def maintenance_sweep(self):
        with get_db_cursor() as cursor:
            cursor.execute("SELECT id FROM user_properties WHERE needs_repair = 0")
            for (pid,) in cursor.fetchall():
                if random.random() < 0.24: 
                    cursor.execute("UPDATE user_properties SET needs_repair = 1 WHERE id = ?", (pid,))
                    
            cursor.execute("SELECT user_id, vehicle_id FROM user_vehicles WHERE needs_repair = 0")
            for uid, vid in cursor.fetchall():
                if random.random() < 0.10: 
                    cursor.execute("UPDATE user_vehicles SET needs_repair = 1 WHERE user_id = ? AND vehicle_id = ?", (uid, vid))

    @rent_collection.before_loop
    @maintenance_sweep.before_loop
    async def before_tasks(self): await self.bot.wait_until_ready()

    # ==========================================
    # 🔍 AUTOCOMPLETES
    # ==========================================
    async def owned_prop_auto(self, i: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
        with get_db_cursor() as c:
            c.execute("SELECT m.id, m.name FROM user_properties u JOIN market_properties m ON u.property_id = m.id WHERE u.user_id = ?", (i.user.id,))
            res = c.fetchall()
        return [app_commands.Choice(name=f"{n} ({id})", value=id) for id, n in res if current.lower() in n.lower()][:25]

    # ==========================================
    # ️ COMMANDS
    # ==========================================

    @app_commands.command(name="rent", description="Retry all failed rent payments from the last cycle")
    @app_commands.default_permissions(administrator=True)
    async def retry_rent(self, i: discord.Interaction):
        await i.response.defer(ephemeral=True)
        with get_db_cursor() as c:
            # Check if table exists
            c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='rent_failures'")
            if not c.fetchone():
                return await i.followup.send("No failed rent payments to retry (table doesn't exist yet).", ephemeral=True)
            
            c.execute("SELECT id, user_id, property_id, amount FROM rent_failures")
            failures = c.fetchall()
            if not failures:
                return await i.followup.send("No failed rent payments to retry.", ephemeral=True)

            retried = 0
            still_failed = []
            for fid, uid, pid, amt in failures:
                if atomic_balance_update(c, uid, amt):
                    log_transaction(c, uid, amt, "RENT_RETRY", f"Retroactive rent from {pid}")
                    c.execute("DELETE FROM rent_failures WHERE id = ?", (fid,))
                    retried += 1
                else:
                    still_failed.append(fid)

            if still_failed:
                print(f"[RENT RETRY] {len(still_failed)} payments still failed")
                await i.followup.send(f"✅ Successfully retried {retried} payments. {len(still_failed)} remain failed.", ephemeral=True)
            else:
                await i.followup.send(f"✅ All {retried} failed rent payments have been processed.", ephemeral=True)

    @app_commands.command(name="compensate_rent", description="ADMIN: Pay 3 days of missed rent to all property owners")
    @app_commands.default_permissions(administrator=True)
    async def compensate_rent(self, i: discord.Interaction):
        await i.response.defer(ephemeral=True)
        with get_db_cursor() as c:
            c.execute('''SELECT u.user_id, m.base_rent, u.quality, u.property_id, m.category
                         FROM user_properties u JOIN market_properties m ON u.property_id = m.id
                         WHERE u.needs_repair = 0''')
            properties = c.fetchall()

            payments = {}
            for uid, base_rent, quality, prop_id, category in properties:
                mult = 1.0 + (1.5 * (quality / 100.0))
                gross_rent = int(base_rent * mult)

                if category == 'Residential':
                    tax_rate = 0.05
                elif category == 'Commercial':
                    tax_rate = 0.20
                elif category == 'Elite':
                    tax_rate = 0.35
                else:
                    tax_rate = 0.0

                tax = int(gross_rent * tax_rate)
                net_rent = gross_rent - tax
                # 3 days missed
                total_rent = net_rent * 3
                payments[uid] = payments.get(uid, 0) + total_rent

            # Pay each user
            paid_users = 0
            for uid, amount in payments.items():
                if atomic_balance_update(c, uid, amount):
                    log_transaction(c, uid, amount, "RENT_COMPENSATION", f"3 days missed rent (manual)")
                    paid_users += 1

            await i.followup.send(f"✅ Compensated {paid_users} users with a total of A$ {sum(payments.values()):,} for 3 missed rent days.", ephemeral=True)


    market_group = app_commands.Group(name="marketplace", description="Buy assets and manage your empire")

    @market_group.command(name="browse", description="Browse real estate, vehicles, and player listings")
    async def browse(self, i: discord.Interaction):
        e = discord.Embed(title="Athena Marketplace", color=0xffffff, description="Select a category from the dropdown to view available listings.")
        await i.response.send_message(embed=e, view=MarketplaceView())

    @market_group.command(name="list", description="List a property on the P2P trading floor")
    @app_commands.autocomplete(property_id=owned_prop_auto)
    async def list_p2p(self, i: discord.Interaction, property_id: str, price: int):
        pid = property_id.upper()
        with get_db_cursor() as c:
            c.execute("SELECT base_price FROM market_properties WHERE id = ?", (pid,))
            cost_row = c.fetchone()
            if not cost_row: return await i.response.send_message("❌ Invalid property ID.", ephemeral=True)
            cost = cost_row[0]
            if price < cost: return await i.response.send_message(f"❌ Price cannot be lower than original cost (A$ {cost:,}).", ephemeral=True)
            
            c.execute("SELECT id FROM user_properties WHERE user_id = ? AND property_id = ?", (i.user.id, pid))
            if not c.fetchone(): return await i.response.send_message("❌ You do not own this property.", ephemeral=True)
            
            c.execute("INSERT INTO p2p_listings (seller_id, item_id, price) VALUES (?, ?, ?)", (i.user.id, pid, price))
            c.execute("DELETE FROM user_properties WHERE user_id = ? AND property_id = ?", (i.user.id, pid))
            log_transaction(c, i.user.id, 0, "P2P_LISTED", f"Listed {pid} for A$ {price:,}")
        
        await i.response.send_message(embed=discord.Embed(title="<:house_athena:1501918600787922944> Asset Listed", description=f"Property listed for A$ {price:,} on the trading floor.", color=0xffffff))

    @market_group.command(name="repair", description="Pay to restore broken assets")
    async def repair_assets(self, i: discord.Interaction):
        await i.response.defer()
        with get_db_cursor() as c:
            # Get broken properties
            c.execute("SELECT property_id FROM user_properties WHERE user_id = ? AND needs_repair = 1", (i.user.id,))
            broken_props = [r[0] for r in c.fetchall()]
            # Get broken vehicles
            c.execute("SELECT vehicle_id FROM user_vehicles WHERE user_id = ? AND needs_repair = 1", (i.user.id,))
            broken_vehs = [r[0] for r in c.fetchall()]
            
            total_broken = len(broken_props) + len(broken_vehs)
            if total_broken == 0:
                return await i.followup.send("Sonion all your assets are in perfect condition..", ephemeral=True)
            
            # Calculate repair cost based on asset value
            repair_cost = 0
            for pid in broken_props:
                c.execute("SELECT base_price FROM market_properties WHERE id = ?", (pid,))
                base = c.fetchone()[0]
                repair_cost += int(base * 0.009)  # 0.5% of property value
            for vid in broken_vehs:
                c.execute("SELECT price FROM market_vehicles WHERE id = ?", (vid,))
                price = c.fetchone()[0]
                repair_cost += int(price * 0.01)   # 1% of vehicle value
            
            # Ensure minimum repair cost of A$500 per asset (optional)
            min_repair = total_broken * 500
            repair_cost = max(repair_cost, min_repair)
            
            c.execute("SELECT balance FROM wallets WHERE user_id = ?", (i.user.id,))
            bal_row = c.fetchone()
            bal = bal_row[0] if bal_row else 0
            if bal < repair_cost:
                return await i.followup.send(f"❌ You need **A$ {repair_cost:,}** to repair your {total_broken} broken assets.", ephemeral=True)
            
            if not atomic_balance_update(c, i.user.id, -repair_cost):
                return await i.followup.send("❌ Balance updated concurrently. Please try again.", ephemeral=True)
            log_transaction(c, i.user.id, -repair_cost, "ASSET_REPAIR", f"Repaired {total_broken} assets (scale cost)")
            
            c.execute("UPDATE user_properties SET needs_repair = 0 WHERE user_id = ?", (i.user.id,))
            c.execute("UPDATE user_vehicles SET needs_repair = 0 WHERE user_id = ?", (i.user.id,))
        
        e = discord.Embed(title="🔧 Maintenance Complete", description=f"You paid **A$ {repair_cost:,}** to fully service your empire. Rent yields and work bonuses have resumed!", color=0xffffff)
        await i.followup.send(embed=e)

    @market_group.command(name="renovate", description="Fund a renovation shift (+20% Quality)")
    @app_commands.autocomplete(property_id=owned_prop_auto)
    async def renovate(self, i: discord.Interaction, property_id: str):
        pid = property_id.upper()
        with get_db_cursor() as c:
            c.execute("SELECT u.quality, m.base_price, m.name FROM user_properties u JOIN market_properties m ON u.property_id = m.id WHERE u.user_id = ? AND u.property_id = ?", (i.user.id, pid))
            d = c.fetchone()
            if not d or d[0] >= 100: return await i.response.send_message("❌ Max quality reached or not owned.", ephemeral=True)
            cost = int(d[1] * 0.10)
            c.execute("SELECT balance FROM wallets WHERE user_id = ?", (i.user.id,))
            bal_row = c.fetchone()
            if not bal_row or bal_row[0] < cost: return await i.response.send_message(f"❌ Needs A$ {cost:,}.", ephemeral=True)
            
            if not atomic_balance_update(c, i.user.id, -cost):
                return await i.response.send_message("❌ Balance updated concurrently. Please try again.", ephemeral=True)
            log_transaction(c, i.user.id, -cost, "PROPERTY_RENOVATION", f"Renovated {d[2]}")
            
            c.execute("UPDATE user_properties SET quality = quality + 20 WHERE user_id = ? AND property_id = ?", (i.user.id, pid))
        
        await i.response.send_message(embed=discord.Embed(title=" Renovation Shift Complete", description=f"Invested into **{d[2]}**.\n{make_progress_bar(min(100, d[0]+20))}", color=0xffffff))

    @market_group.command(name="portfolio", description="View your real estate empire")
    async def portfolio(self, i: discord.Interaction):
        await i.response.defer()
        with get_db_cursor() as c:
            # Fetch user's custom banner (same as networth)
            c.execute("SELECT profile_banner FROM wallets WHERE user_id = ?", (i.user.id,))
            banner_row = c.fetchone()
            profile_banner = banner_row[0] if banner_row and banner_row[0] else None

            c.execute("""
                SELECT m.name, u.quality, m.base_rent, u.needs_repair, m.category, m.base_price
                FROM user_properties u 
                JOIN market_properties m ON u.property_id = m.id 
                WHERE u.user_id = ?
            """, (i.user.id,))
            properties = c.fetchall()

            c.execute("SELECT SUM(ABS(amount)) FROM transactions WHERE user_id = ? AND type = 'PROPERTY_TAX'", (i.user.id,))
            total_tax = c.fetchone()[0] or 0

        if not properties:
            return await i.followup.send("You do not own any real estate... smells of broke here.", ephemeral=True)

        embed = discord.Embed(
            title="꒰ა Real Estate Portfolio ⸝⸝",
            description=f"*Properties owned by {i.user.display_name}*",
            color=0xffffff
        )
        embed.set_thumbnail(url=i.user.display_avatar.url)

        # Add banner image if the user has one (same as networth)
        if profile_banner:
            embed.set_image(url=profile_banner)

        total_daily_rent = 0
        total_market_value = 0

        for name, quality, base_rent, needs_repair, category, base_price in properties:
            if needs_repair:
                daily_rent = 0
                status_emoji = "<a:wt_torosob:1480580873782034483>"
                status_text = "Needs Repair"
            else:
                mult = 1.0 + (1.5 * (quality / 100.0))
                gross_rent = int(base_rent * mult)
                tax_rate = 0.05 if category == 'Residential' else 0.20 if category == 'Commercial' else 0.35
                tax = int(gross_rent * tax_rate)
                daily_rent = gross_rent - tax
                status_emoji = "<a:wt_torohearts:1480580920737005672>"
                status_text = "Active"

            total_daily_rent += daily_rent
            total_market_value += base_price

            bar = make_quality_bar(quality)

            embed.add_field(
                name=f"{status_emoji} **{name}**",
                value=(
                    f"{bar}\n"
                    f"└ **Daily Rent:** A$ {daily_rent:,}\n"
                    f"└ **Status:** {status_text}\n"
                    f"└ **Category:** {category}\n\n"
                ),
                inline=False
            )

        embed.add_field(
            name="<:athenacoin:1503804322280902767> Total Daily Rent",
            value=f"**A$ {total_daily_rent:,}**",
            inline=True
        )
        embed.add_field(
            name="<:s_white2:1382052523166142486> Market Value",
            value=f"**A$ {total_market_value:,}**",
            inline=True
        )
        embed.add_field(
            name="<:s_white2:1382052523166142486> Lifetime Tax Paid",
            value=f"**A$ {total_tax:,}**",
            inline=True
        )

        embed.set_footer(text="Rent is paid daily at 00:00 UTC")
        await i.followup.send(embed=embed)

    @app_commands.command(name="garage", description="View your luxury vehicle collection")
    async def garage(self, i: discord.Interaction):
        with get_db_cursor() as c:
            c.execute("SELECT m.name, u.needs_repair, m.cooldown_reduction FROM user_vehicles u JOIN market_vehicles m ON u.vehicle_id = m.id WHERE u.user_id = ?", (i.user.id,))
            vehicles = c.fetchall()
        if not vehicles: return await i.response.send_message("You don't own any vehicles. Visit `/marketplace browse` to buy one!", ephemeral=True)

        e = discord.Embed(title=f"꒰ა {i.user.name}'s Garage ⸝⸝", color=0xffffff)
        desc = ""
        for name, repair, bonus in vehicles:
            status = "**NEEDS SERVICE (Bonus Paused)**" if repair else "Active"
            desc += f"<:car_athena:1501939281479073842> **{name}**\n**Status:** {status}\n**Commute Bonus:** -{bonus}m Work Cooldown\n\n"
            
        e.description = desc
        e.set_image(url="https://media.tenor.com/L7R86JpM-pUAAAAd/rolls-royce.gif")
        await i.response.send_message(embed=e)

    def get_user_badges(self, cursor, user_id: int) -> str:
        """Dynamically calculates and returns a string of ALL earned badge emojis."""
        badges = []
        
        # 1. Liquid Badges (Changed to separate 'if' statements so they stack)
        cursor.execute("SELECT balance FROM wallets WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()
        bal = row[0] if row else 0
        
        if bal >= 2000000: 
            badges.append("<:liquid_gold:1504512350550495312>") # Liquid Gold
        if bal >= 4500000: 
            badges.append("<:reserve_governor:1504512821042483250>") # Reserve Governor
            
        # 2. Diamond Hands
        try:
            cursor.execute("SELECT SUM(p.shares * s.price) FROM portfolio p JOIN stocks s ON p.symbol = s.symbol WHERE p.user_id = ?", (user_id,))
            stock_v = (cursor.fetchone() or [0])[0] or 0
            if stock_v >= 5000000: 
                badges.append("<:diamond_hands:1504512947089834034>")
        except: pass
            
        # 3. Real Estate
        try:
            cursor.execute("SELECT property_id FROM user_properties WHERE user_id = ?", (user_id,))
            owned_props = [r[0] for r in cursor.fetchall()]
            has_res = any(p.startswith("RES") for p in owned_props)
            has_com = any(p.startswith("COM") for p in owned_props)
            has_eli = any(p.startswith("ELI") for p in owned_props)
            
            if has_eli: 
                badges.append("<:monopolist:1504515470932447394>") # Monopolist
            if has_res and has_com and has_eli: 
                badges.append("<:empire:1504512585096237227>") # Empire Builder
        except: pass
            
        # 4. Careers
        try:
            cursor.execute("SELECT level FROM user_careers WHERE user_id = ?", (user_id,))
            career = cursor.fetchone()
            if career and career[0] >= 3: 
                badges.append("<:corporate:1504515833148211270>") # Master of Industry
        except: pass
            
        return " ".join(badges) if badges else ""

    @app_commands.command(name="networth", description="Calculate your total empire valuation and view your badges")
    async def networth(self, i: discord.Interaction, user: Optional[discord.Member] = None):
        t = user or i.user
        with get_db_cursor() as c:
            # Fetch balance AND the custom banner
            try:
                c.execute("SELECT balance, profile_banner FROM wallets WHERE user_id = ?", (t.id,))
                row = c.fetchone()
                bal = row[0] if row else 0
                banner_url = row[1] if row and len(row) > 1 else None
            except:
                bal = 0
                banner_url = None
            
            c.execute("SELECT SUM(m.base_price) FROM user_properties u JOIN market_properties m ON u.property_id = m.id WHERE u.user_id = ?", (t.id,))
            prop_v = c.fetchone()[0] or 0
            
            c.execute("SELECT SUM(m.price) FROM user_vehicles u JOIN market_vehicles m ON u.vehicle_id = m.id WHERE u.user_id = ?", (t.id,))
            veh_v = c.fetchone()[0] or 0
            
            try:
                c.execute("SELECT SUM(p.shares * s.price) FROM portfolio p JOIN stocks s ON p.symbol = s.symbol WHERE p.user_id = ?", (t.id,))
                stock_v = c.fetchone()[0] or 0
            except: stock_v = 0
            
            # Fetch Badges!
            badge_str = self.get_user_badges(c, t.id)
            
        total = bal + prop_v + veh_v + stock_v
        
        # --- PREMIUM EMBED UPGRADE ---
        e = discord.Embed(title="꒰ა Athena Central Reserve  ⸝⸝", color=0xffffff) #2b2d31
        e.set_author(name=f"{t.name}'s Financial Profile", icon_url=t.display_avatar.url)
        
        # Uses the custom banner if set, otherwise falls back to the default
        e.set_image(url=banner_url or DEFAULT_NETWORTH_BANNER)
        
        desc = f"**Awards:**\n{badge_str if badge_str else '*No badges unlocked yet.*'}\n"
        desc += "━━━━━━━━━━━━━━━━━━━━━━\n"
        desc += f"**TOTAL VALUATION: A$ {total:,}**\n"
        desc += "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        e.description = desc
        
        e.add_field(name="<:athenacoin:1503804322280902767> Liquid Capital", value=f"`A$ {bal:,}`", inline=True)
        e.add_field(name="<:stocks_athena:1501958537067364464> Stock Portfolio", value=f"`A$ {stock_v:,}`", inline=True)
        e.add_field(name="\u200b", value="\u200b", inline=True) 
        
        e.add_field(name="<:house_athena:1501918600787922944> Real Estate", value=f"`A$ {prop_v:,}`", inline=True)
        e.add_field(name="<:car_athena:1501939281479073842> Luxury Garage", value=f"`A$ {veh_v:,}`", inline=True)
        e.add_field(name="\u200b", value="\u200b", inline=True) 
        
        e.set_footer(text="")
        
        # Only attach the "Set Banner" view if the user is checking THEIR OWN profile AND they have 1.2M+
        if t.id == i.user.id and bal >= 1200000:
            await i.response.send_message(embed=e, view=NetworthView(i.user.id))
        else:
            await i.response.send_message(embed=e)

    @app_commands.command(name="leaderboard", description="View the Top 10 High Net Worth Individuals")
    async def leaderboard(self, i: discord.Interaction):
        await i.response.defer()
        with get_db_cursor() as c:
            nw = {}
            # 1. Liquid Capital
            c.execute("SELECT user_id, balance FROM wallets")
            for u, b in c.fetchall(): nw[u] = b
            
            # 2. Real Estate Valuation
            c.execute("SELECT u.user_id, m.base_price FROM user_properties u JOIN market_properties m ON u.property_id = m.id")
            for u, p in c.fetchall(): nw[u] = nw.get(u,0) + p
            
            # 3. Vehicle Valuation
            c.execute("SELECT u.user_id, m.price FROM user_vehicles u JOIN market_vehicles m ON u.vehicle_id = m.id")
            for u, p in c.fetchall(): nw[u] = nw.get(u,0) + p
            
            # 4. Stock Portfolio Valuation
            try:
                c.execute("SELECT p.user_id, p.shares, s.price FROM portfolio p JOIN stocks s ON p.symbol = s.symbol")
                for u, s, p in c.fetchall(): nw[u] = nw.get(u,0) + (s*p)
            except: pass
            
            # Sort and take top 10
            sorted_nw = sorted(nw.items(), key=lambda x: x[1], reverse=True)[:10]
            
            # Fetch badges for the top 10
            leaderboard_data = []
            for uid, val in sorted_nw:
                badge_str = self.get_user_badges(c, uid)
                leaderboard_data.append((uid, val, badge_str))

        # --- PREMIUM EMBED UPGRADE ---
        e = discord.Embed(title="꒰ა Athena Wealth Leaderboard  ⸝⸝", color=0xffffff)
        e.description = "*The Top 10 High Net Worth Individuals (HNWI) ranked by total global asset valuation.*\n\n"
        
        desc = ""
        for rank, (uid, val, badges) in enumerate(leaderboard_data, 1):
            user = self.bot.get_user(uid)
            name_display = user.name.upper() if user else 'UNKNOWN'
            
            # Formatting the top 3 with special medals
            if rank == 1:
                medal = "<:firstplace:1504526139199197444>"
            elif rank == 2:
                medal = "<:secondplace:1504526178688569394>"
            elif rank == 3:
                medal = "<:thirdplace:1504526220103127070>"
            else:
                medal = f"`#{rank}`"

            # Format: 🥇 USERNAME 👑💎
            #         A$ 10,000,000
            desc += f"{medal} {name_display} {badges}\n"
            desc += f"└ <:athenacoin:1503804322280902767> **A$ {val:,}**\n\n"
            
        e.description += desc if desc else "*No financial data available.*"
        e.set_footer(text="Athena Central Reserve")
        
        # Add server icon as thumbnail if it exists
        if i.guild and i.guild.icon:
            e.set_thumbnail(url=i.guild.icon.url)
            
        await i.followup.send(embed=e)

async def setup(bot): await bot.add_cog(Marketplace(bot))