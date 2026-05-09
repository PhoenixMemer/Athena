import discord
from discord import app_commands
from discord.ext import commands, tasks
import sqlite3
import random
from typing import List, Optional

DB_PATH = "economy.db"

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
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        
        c.execute("SELECT balance FROM wallets WHERE user_id = ?", (i.user.id,))
        bal_row = c.fetchone()
        bal = bal_row[0] if bal_row else 0

        if self.item_type == "property":
            c.execute("SELECT name, base_price FROM market_properties WHERE id = ?", (self.item_id,))
            prop = c.fetchone()
            if not prop:
                conn.close()
                return await i.response.send_message("❌ Invalid property ID.", ephemeral=True)
            
            c.execute("SELECT id FROM user_properties WHERE user_id = ? AND property_id = ?", (i.user.id, self.item_id))
            if c.fetchone():
                conn.close()
                return await i.response.send_message("❌ You already own this property.", ephemeral=True)
                
            if bal < prop[1]:
                conn.close()
                return await i.response.send_message(f"❌ Insufficient funds. You need **A$ {prop[1]:,}**.", ephemeral=True)
                
            c.execute("UPDATE wallets SET balance = balance - ? WHERE user_id = ?", (prop[1], i.user.id))
            c.execute("INSERT INTO user_properties (user_id, property_id, quality, needs_repair) VALUES (?, ?, 20, 0)", (i.user.id, self.item_id))
            conn.commit()
            conn.close()
            await i.response.send_message(embed=discord.Embed(title="📜 Deed Acquired", description=f"You now own **{prop[0]}**!", color=0xffffff), ephemeral=False)

        elif self.item_type == "vehicle":
            c.execute("SELECT name, price FROM market_vehicles WHERE id = ?", (self.item_id,))
            veh = c.fetchone()
            if not veh:
                conn.close()
                return await i.response.send_message("❌ Invalid vehicle ID.", ephemeral=True)
            
            c.execute("SELECT vehicle_id FROM user_vehicles WHERE user_id = ? AND vehicle_id = ?", (i.user.id, self.item_id))
            if c.fetchone():
                conn.close()
                return await i.response.send_message("❌ You already own this vehicle.", ephemeral=True)
                
            if bal < veh[1]:
                conn.close()
                return await i.response.send_message(f"❌ Insufficient funds. You need **A$ {veh[1]:,}**.", ephemeral=True)
                
            c.execute("UPDATE wallets SET balance = balance - ? WHERE user_id = ?", (veh[1], i.user.id))
            c.execute("INSERT INTO user_vehicles (user_id, vehicle_id, needs_repair) VALUES (?, ?, 0)", (i.user.id, self.item_id))
            conn.commit()
            conn.close()
            await i.response.send_message(embed=discord.Embed(title="<:car_athena:1501939281479073842> Keys Handed Over", description=f"You purchased a **{veh[0]}**!", color=0xffffff), ephemeral=False)

        elif self.item_type == "p2p":
            lid = int(self.item_id)
            c.execute("SELECT seller_id, item_id, price FROM p2p_listings WHERE id = ?", (lid,))
            listing = c.fetchone()
            if not listing:
                conn.close()
                return await i.response.send_message("❌ Listing not found or already sold.", ephemeral=True)
                
            if bal < listing[2]:
                conn.close()
                return await i.response.send_message("❌ Insufficient funds.", ephemeral=True)
                
            fee = int(listing[2] * 0.02)
            payout = listing[2] - fee
            
            c.execute("UPDATE wallets SET balance = balance + ? WHERE user_id = ?", (payout, listing[0]))
            c.execute("UPDATE wallets SET balance = balance - ? WHERE user_id = ?", (listing[2], i.user.id))
            c.execute("INSERT INTO user_properties (user_id, property_id, quality, needs_repair) VALUES (?, ?, 100, 0)", (i.user.id, listing[1]))
            c.execute("DELETE FROM p2p_listings WHERE id = ?", (lid,))
            conn.commit()
            conn.close()
            
            await i.response.send_message(embed=discord.Embed(title="🤝 P2P Purchase Complete", description=f"You purchased listing #{lid} for **A$ {listing[2]:,}**!", color=0xffffff), ephemeral=False)


# ==========================================
# 🏛️ UI COMPONENTS (DROPDOWN + BUY BTN)
# ==========================================
class MarketplaceDropdown(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label='Residential Listings', description='Flats, Townhouses, and Cottages', value='Residential', emoji="<a:wt_torosoul:1480580991503306865>"),
            discord.SelectOption(label='Commercial Listings', description='M&S, Greggs, Weatherspoons', value='Commercial', emoji="<a:wt_torosilly:1480580853720551637>"),
            discord.SelectOption(label='Elite Listings', description='High society luxury real estate', value='Elite', emoji="<a:wt_toroking:1480580998742937691>"),
            discord.SelectOption(label='Vehicle Showroom', description='Supercars and Luxury Commuters', value='Vehicles', emoji="<a:wt_toroleaf:1480580940785913967>"),
            discord.SelectOption(label='P2P Trading Floor', description='Buy assets directly from OTHER players', value='P2P', emoji="<a:wt_torofly:1480580890185826364>"),
        ]
        super().__init__(placeholder='Select a sector to browse...', min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        category = self.values[0]
        self.view.current_category = category
        self.view.buy_btn.disabled = False
        
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        if category == "P2P":
            cursor.execute('''SELECT l.id, m.name, l.price, l.seller_id 
                              FROM p2p_listings l JOIN market_properties m ON l.item_id = m.id''')
            listings = cursor.fetchall()
            embed = discord.Embed(title="P2P Trading Floor", color=0xffffff)
            desc = "Direct listings from other property owners. Click **Buy** below to purchase.\n\n"
            for lid, name, price, seller_id in listings:
                seller = interaction.guild.get_member(seller_id)
                s_name = seller.name if seller else "Inactive User"
                desc += f"**{name}** `[Listing #{lid}]`\n"
                desc += f"**Seller:** {s_name}\n"
                desc += f"<:money_athena:1501918414867005511> **Price:** A$ {price:,}\n\n"
            embed.description = desc if listings else "The trading floor is currently empty. List your properties with `/marketplace list`!"
            
        elif category == "Vehicles":
            cursor.execute("SELECT id, name, price, cooldown_reduction FROM market_vehicles")
            vehicles = cursor.fetchall()
            embed = discord.Embed(title="Athena Showroom", color=0xffffff)
            desc = "Luxury vehicles. Owning these reduces your `/work` cooldown.\n\n"
            for vid, name, price, bonus in vehicles:
                desc += f"**{name}** `[{vid}]`\n"
                desc += f"**Commute Bonus:** -{bonus}m On Work Cooldown\n"
                desc += f"<:money_athena:1501918414867005511> **Price:** A$ {price:,}\n\n"
            embed.description = desc
            
        else:
            cursor.execute("SELECT id, name, base_price, base_rent FROM market_properties WHERE category = ?", (category,))
            properties = cursor.fetchall()
            embed = discord.Embed(title=f"{category} Real Estate", color=0xffffff)
            desc = "Available deeds. Click **Buy** below to purchase.\n\n"
            for pid, name, price, rent in properties:
                desc += f"**{name}** `[{pid}]`\n"
                desc += f"**Price:** A$ {price:,}\n"
                desc += f"<:money_athena:1501918414867005511> **Base Rent:** A$ {rent:,} / day\n\n"
            embed.description = desc

        conn.close()
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
        if not cat: return
        
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        options_view = discord.ui.View(timeout=60)
        
        if cat == "Vehicles":
            c.execute("SELECT id FROM market_vehicles")
            for (vid,) in c.fetchall()[:25]:
                options_view.add_item(BuyOptionButton(vid, "vehicle"))
        elif cat == "P2P":
            c.execute("SELECT id FROM p2p_listings")
            for (lid,) in c.fetchall()[:25]:
                options_view.add_item(BuyOptionButton(str(lid), "p2p"))
        else:
            c.execute("SELECT id FROM market_properties WHERE category = ?", (cat,))
            for (pid,) in c.fetchall()[:25]:
                options_view.add_item(BuyOptionButton(pid, "property"))
                
        conn.close()
        
        if len(options_view.children) == 0:
            return await interaction.response.send_message("❌ No items available to buy in this category.", ephemeral=True)
            
        await interaction.response.send_message("🛒 **Select an asset code to purchase:**", view=options_view, ephemeral=True)


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
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        cursor.execute('CREATE TABLE IF NOT EXISTS market_properties (id TEXT PRIMARY KEY, name TEXT, category TEXT, base_price INTEGER, base_rent INTEGER)')
        cursor.execute('CREATE TABLE IF NOT EXISTS user_properties (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, property_id TEXT, quality INTEGER DEFAULT 20, needs_repair INTEGER DEFAULT 0, UNIQUE(user_id, property_id))')
        
        cursor.execute('CREATE TABLE IF NOT EXISTS market_vehicles (id TEXT PRIMARY KEY, name TEXT, price INTEGER, cooldown_reduction INTEGER)')
        cursor.execute('CREATE TABLE IF NOT EXISTS user_vehicles (user_id INTEGER, vehicle_id TEXT, needs_repair INTEGER DEFAULT 0, UNIQUE(user_id, vehicle_id))')
        
        cursor.execute('CREATE TABLE IF NOT EXISTS p2p_listings (id INTEGER PRIMARY KEY AUTOINCREMENT, seller_id INTEGER, item_id TEXT, price INTEGER)')
        
        try: cursor.execute("ALTER TABLE user_properties ADD COLUMN needs_repair INTEGER DEFAULT 0")
        except: pass
        try: cursor.execute("ALTER TABLE user_vehicles ADD COLUMN needs_repair INTEGER DEFAULT 0")
        except: pass

        vehicles = [
            ('CAR1', 'Mini Cooper S', 15000, 20),
            ('CAR2', 'Land Rover Defender', 45000, 30),
            ('CAR3', 'Jaguar F-Type', 95000, 45),
            ('CAR4', 'Aston Martin DB12', 185000, 60),
            ('CAR5', 'Rolls-Royce Cullinan', 350000, 90)
        ]
        cursor.executemany("INSERT OR REPLACE INTO market_vehicles VALUES (?, ?, ?, ?)", vehicles)
        
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
            ('ELI1', 'The Windsor Estate', 'Elite', 5000000, 250000),
            ('ELI2', 'Chelsea Penthouse', 'Elite', 8000000, 400000),
            ('ELI3', 'Buckingham Manor', 'Elite', 15000000, 750000)
        ]
        cursor.executemany("INSERT OR REPLACE INTO market_properties VALUES (?, ?, ?, ?, ?)", properties)
            
        conn.commit()
        conn.close()

    # ==========================================
    # 📉 AUTOMATED BACKGROUND TASKS
    # ==========================================
    @tasks.loop(hours=24)
    async def rent_collection(self):
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('''SELECT u.user_id, m.base_rent, u.quality 
                          FROM user_properties u JOIN market_properties m ON u.property_id = m.id 
                          WHERE u.needs_repair = 0''')
        for uid, base_rent, quality in cursor.fetchall():
            mult = 1.0 + (1.5 * (quality / 100.0))
            rent = int(base_rent * mult)
            cursor.execute("UPDATE wallets SET balance = balance + ?, highest_balance = MAX(highest_balance, balance + ?) WHERE user_id = ?", (rent, rent, uid))
        conn.commit()
        conn.close()

    @tasks.loop(hours=24)
    async def maintenance_sweep(self):
        conn = sqlite3.connect(DB_PATH); cursor = conn.cursor()
        
        cursor.execute("SELECT id FROM user_properties WHERE needs_repair = 0")
        for (pid,) in cursor.fetchall():
            if random.random() < 0.10: cursor.execute("UPDATE user_properties SET needs_repair = 1 WHERE id = ?", (pid,))
                
        cursor.execute("SELECT user_id, vehicle_id FROM user_vehicles WHERE needs_repair = 0")
        for uid, vid in cursor.fetchall():
            if random.random() < 0.10: cursor.execute("UPDATE user_vehicles SET needs_repair = 1 WHERE user_id = ? AND vehicle_id = ?", (uid, vid))
                
        conn.commit(); conn.close()

    @rent_collection.before_loop
    @maintenance_sweep.before_loop
    async def before_tasks(self): await self.bot.wait_until_ready()

    # ==========================================
    # 🔍 AUTOCOMPLETES
    # ==========================================
    async def owned_prop_auto(self, i: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
        conn = sqlite3.connect(DB_PATH); c = conn.cursor()
        c.execute("SELECT m.id, m.name FROM user_properties u JOIN market_properties m ON u.property_id = m.id WHERE u.user_id = ?", (i.user.id,))
        res = c.fetchall(); conn.close()
        return [app_commands.Choice(name=f"{n} ({id})", value=id) for id, n in res if current.lower() in n.lower()][:25]

    # ==========================================
    # 🛍️ COMMANDS
    # ==========================================
    market_group = app_commands.Group(name="marketplace", description="Buy assets and manage your empire")

    @market_group.command(name="browse", description="Browse real estate, vehicles, and player listings")
    async def browse(self, i: discord.Interaction):
        e = discord.Embed(title="Athena Marketplace", color=0xffffff, description="Select a category from the dropdown to view available listings.")
        await i.response.send_message(embed=e, view=MarketplaceView())

    @market_group.command(name="list", description="List a property on the P2P trading floor")
    @app_commands.autocomplete(property_id=owned_prop_auto)
    async def list_p2p(self, i: discord.Interaction, property_id: str, price: int):
        pid = property_id.upper()
        conn = sqlite3.connect(DB_PATH); c = conn.cursor()
        c.execute("SELECT base_price FROM market_properties WHERE id = ?", (pid,))
        cost = c.fetchone()[0]
        if price < cost: return await i.response.send_message(f"❌ Price cannot be lower than original cost (A$ {cost:,}).", ephemeral=True)
        
        c.execute("INSERT INTO p2p_listings (seller_id, item_id, price) VALUES (?, ?, ?)", (i.user.id, pid, price))
        c.execute("DELETE FROM user_properties WHERE user_id = ? AND property_id = ?", (i.user.id, pid))
        conn.commit(); conn.close()
        await i.response.send_message(embed=discord.Embed(title="<:house_athena:1501918600787922944> Asset Listed", description=f"Property listed for A$ {price:,} on the trading floor.", color=0xffffff))

    @market_group.command(name="repair", description="Pay A$ 500 per broken asset to restore your empire")
    async def repair_assets(self, i: discord.Interaction):
        conn = sqlite3.connect(DB_PATH); c = conn.cursor()
        c.execute("SELECT id FROM user_properties WHERE user_id = ? AND needs_repair = 1", (i.user.id,))
        broken_props = c.fetchall()
        c.execute("SELECT vehicle_id FROM user_vehicles WHERE user_id = ? AND needs_repair = 1", (i.user.id,))
        broken_vehs = c.fetchall()
        
        total_broken = len(broken_props) + len(broken_vehs)
        if total_broken == 0:
            conn.close()
            return await i.response.send_message("✅ All your assets are in perfect condition!", ephemeral=True)
            
        cost = total_broken * 500
        c.execute("SELECT balance FROM wallets WHERE user_id = ?", (i.user.id,))
        bal = c.fetchone()[0]
        if bal < cost:
            conn.close()
            return await i.response.send_message(f"❌ You need A$ {cost:,} to repair your {total_broken} broken assets.", ephemeral=True)
            
        c.execute("UPDATE wallets SET balance = balance - ? WHERE user_id = ?", (cost, i.user.id))
        c.execute("UPDATE user_properties SET needs_repair = 0 WHERE user_id = ?", (i.user.id,))
        c.execute("UPDATE user_vehicles SET needs_repair = 0 WHERE user_id = ?", (i.user.id,))
        conn.commit(); conn.close()
        
        e = discord.Embed(title="🔧 Maintenance Complete", description=f"You paid **A$ {cost:,}** to fully service your empire. Rent yields and work bonuses have resumed!", color=0xffffff)
        await i.response.send_message(embed=e)

    @market_group.command(name="renovate", description="Fund a renovation shift (+20% Quality)")
    @app_commands.autocomplete(property_id=owned_prop_auto)
    async def renovate(self, i: discord.Interaction, property_id: str):
        pid = property_id.upper()
        conn = sqlite3.connect(DB_PATH); c = conn.cursor()
        c.execute("SELECT u.quality, m.base_price, m.name FROM user_properties u JOIN market_properties m ON u.property_id = m.id WHERE u.user_id = ? AND u.property_id = ?", (i.user.id, pid))
        d = c.fetchone()
        if not d or d[0] >= 100: return await i.response.send_message("❌ Max quality reached or not owned.", ephemeral=True)
        cost = int(d[1] * 0.10)
        c.execute("SELECT balance FROM wallets WHERE user_id = ?", (i.user.id,))
        if c.fetchone()[0] < cost: return await i.response.send_message(f"❌ Needs A$ {cost:,}.", ephemeral=True)
        c.execute("UPDATE wallets SET balance = balance - ? WHERE user_id = ?", (cost, i.user.id))
        c.execute("UPDATE user_properties SET quality = quality + 20 WHERE user_id = ? AND property_id = ?", (i.user.id, pid))
        conn.commit(); conn.close()
        await i.response.send_message(embed=discord.Embed(title="🔨 Renovation Shift Complete", description=f"Invested into **{d[2]}**.\n{make_progress_bar(min(100, d[0]+20))}", color=0xffffff))

    @market_group.command(name="portfolio", description="View your real estate empire")
    async def portfolio(self, i: discord.Interaction):
        conn = sqlite3.connect(DB_PATH); c = conn.cursor()
        c.execute("SELECT m.name, u.quality, m.base_rent, u.needs_repair FROM user_properties u JOIN market_properties m ON u.property_id = m.id WHERE u.user_id = ?", (i.user.id,))
        properties = c.fetchall(); conn.close()
        if not properties: return await i.response.send_message("You do not own any real estate.", ephemeral=True)

        e = discord.Embed(title=f"{i.user.name}'s Real Estate", color=0xffffff)
        total_rent = 0
        desc = ""
        for name, quality, base_rent, repair in properties:
            actual_rent = int(base_rent * (1.0 + (1.5 * (quality / 100.0)))) if not repair else 0
            total_rent += actual_rent
            status = "🚨 **NEEDS SERVICE (Rent Paused)**" if repair else "✅ Active"
            desc += f"**{name}**\n{make_progress_bar(quality)}\n**Status:** {status}\n<:money_athena:1501918414867005511> **Daily Rent:** A$ {actual_rent:,}\n\n"
            
        desc += f"**Total Daily Rent:** `A$ {total_rent:,}`"
        e.description = desc
        await i.response.send_message(embed=e)

    @app_commands.command(name="garage", description="View your luxury vehicle collection")
    async def garage(self, i: discord.Interaction):
        conn = sqlite3.connect(DB_PATH); c = conn.cursor()
        c.execute("SELECT m.name, u.needs_repair, m.cooldown_reduction FROM user_vehicles u JOIN market_vehicles m ON u.vehicle_id = m.id WHERE u.user_id = ?", (i.user.id,))
        vehicles = c.fetchall(); conn.close()
        if not vehicles: return await i.response.send_message("You don't own any vehicles. Visit `/marketplace browse` to buy one!", ephemeral=True)

        e = discord.Embed(title=f"{i.user.name}'s Garage", color=0xffffff)
        desc = ""
        for name, repair, bonus in vehicles:
            status = "🚨 **NEEDS SERVICE (Bonus Paused)**" if repair else "Active"
            desc += f"<:car_athena:1501939281479073842> **{name}**\n**Status:** {status}\n**Commute Bonus:** -{bonus}m Work Cooldown\n\n"
            
        e.description = desc
        e.set_image(url="https://media.tenor.com/L7R86JpM-pUAAAAd/rolls-royce.gif")
        await i.response.send_message(embed=e)

    @app_commands.command(name="networth", description="Calculate your total empire valuation")
    async def networth(self, i: discord.Interaction, user: Optional[discord.Member] = None):
        t = user or i.user
        conn = sqlite3.connect(DB_PATH); c = conn.cursor()
        c.execute("SELECT balance FROM wallets WHERE user_id = ?", (t.id,)); bal_row = c.fetchone()
        bal = bal_row[0] if bal_row else 0
        c.execute("SELECT SUM(m.base_price) FROM user_properties u JOIN market_properties m ON u.property_id = m.id WHERE u.user_id = ?", (t.id,)); prop_v = c.fetchone()[0] or 0
        c.execute("SELECT SUM(m.price) FROM user_vehicles u JOIN market_vehicles m ON u.vehicle_id = m.id WHERE u.user_id = ?", (t.id,)); veh_v = c.fetchone()[0] or 0
        try:
            c.execute("SELECT SUM(p.shares * s.price) FROM portfolio p JOIN stocks s ON p.symbol = s.symbol WHERE p.user_id = ?", (t.id,))
            stock_v = c.fetchone()[0] or 0
        except: stock_v = 0
        conn.close()
        total = bal + prop_v + veh_v + stock_v
        e = discord.Embed(title=f"{t.name}'s Net Worth", color=0xffffff)
        e.add_field(name="Liquid Capital", value=f"<:money_athena:1501918414867005511> A$ {bal:,}\n\u200b", inline=False)
        e.add_field(name="Asset Valuation", value=f"<:house_athena:1501918600787922944> Real Estate: A$ {prop_v:,}\n<:car_athena:1501939281479073842> Vehicles: A$ {veh_v:,}\n<:stocks_athena:1501958537067364464> Stocks: A$ {stock_v:,}", inline=False)
        e.description = f"**Total Valuation:**\n# A$ {total:,}"; e.set_thumbnail(url=t.display_avatar.url)
        await i.response.send_message(embed=e)

    @app_commands.command(name="leaderboard", description="View the Top 10 High Net Worth Individuals")
    async def leaderboard(self, i: discord.Interaction):
        await i.response.defer()
        conn = sqlite3.connect(DB_PATH); c = conn.cursor()
        nw = {}
        c.execute("SELECT user_id, balance FROM wallets")
        for u, b in c.fetchall(): nw[u] = b
        c.execute("SELECT u.user_id, m.base_price FROM user_properties u JOIN market_properties m ON u.property_id = m.id")
        for u, p in c.fetchall(): nw[u] = nw.get(u,0) + p
        c.execute("SELECT u.user_id, m.price FROM user_vehicles u JOIN market_vehicles m ON u.vehicle_id = m.id")
        for u, p in c.fetchall(): nw[u] = nw.get(u,0) + p
        try:
            c.execute("SELECT p.user_id, p.shares, s.price FROM portfolio p JOIN stocks s ON p.symbol = s.symbol")
            for u, s, p in c.fetchall(): nw[u] = nw.get(u,0) + (s*p)
        except: pass
        conn.close()
        sorted_nw = sorted(nw.items(), key=lambda x: x[1], reverse=True)[:10]
        desc = ""
        for rank, (uid, val) in enumerate(sorted_nw, 1):
            user = self.bot.get_user(uid)
            desc += f"`#{rank}` **{user.name if user else 'Unknown'}**\n<:money_athena:1501918414867005511> A$ {val:,}\n\n"
        await i.followup.send(embed=discord.Embed(title="Wealth Leaderboard", description=desc or "No data.", color=0xffffff))

async def setup(bot): await bot.add_cog(Marketplace(bot))