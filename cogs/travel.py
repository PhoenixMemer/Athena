from __future__ import annotations
import discord
from discord import app_commands, Interaction
from discord.ext import commands, tasks
import sqlite3
import time
import random
import json
import asyncio
from datetime import datetime
from contextlib import contextmanager

# ==========================================
# CONFIGURATION & AESTHETICS
# ==========================================
TRAVEL_DB_PATH = "travel.db"
ECO_DB_PATH = "economy.db"
BIZ_DB_PATH = "business.db"
TRAVEL_CHANNEL_ID = 1441473281420169367

# The Chérie Aesthetic Emojis
E_DOT = "<:btb_white3:1375474689467748517>"
E_SUCCESS = "<a:wt_toroexclaim:1480581004317036624>"
E_ERROR = "<a:wt_torono:1480580892706603018>"
E_SPIN = "<a:wt_torospin:1480580977867624540>"
E_COIN = "<:athenacoin:1503804322280902767>"
E_LOCKED = "<:2locked:1504556425257550025>"
E_UNLOCKED = "<:1unlocked:1504556384535187528>"
E_PASSPORT = "<:w_mail:1435879826446745630>"
E_VISA = "<a:wt_toroleaf:1480580940785913967>"
E_VIP = "<:i_cupid:1426518951961038929>"
E_FLIGHT = "<a:w_tear:1375482116749529098>"

BANNER_URL = "https://i.pinimg.com/originals/24/31/3b/24313b2c6b4122d46e27308a0d7f2613.gif" # Luxury Jet GIF

CLASS_CONFIG = {
    "Economy":   {"cost_mult": 1.0, "time_mult": 1.0, "xp_mult": 1.0},
    "Business":  {"cost_mult": 2.5, "time_mult": 0.7, "xp_mult": 1.5},
    "First":     {"cost_mult": 6.0, "time_mult": 0.4, "xp_mult": 2.1},
}

VIP_WEEKLY_COST = 5_000_000

# ==========================================
# SAFE DATABASE CONTEXT MANAGERS
# ==========================================
@contextmanager
def get_travel_cursor():
    conn = sqlite3.connect(TRAVEL_DB_PATH, timeout=20, isolation_level=None)
    conn.execute('PRAGMA journal_mode=WAL;')
    conn.execute('PRAGMA temp_store = MEMORY;')
    cursor = conn.cursor()
    try:
        yield cursor
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()

@contextmanager
def get_eco_cursor():
    conn = sqlite3.connect(ECO_DB_PATH, timeout=20, isolation_level=None)
    conn.execute('PRAGMA journal_mode=WAL;')
    conn.execute('PRAGMA temp_store = MEMORY;')
    cursor = conn.cursor()
    try:
        yield cursor
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()

@contextmanager
def get_biz_cursor():
    conn = sqlite3.connect(BIZ_DB_PATH, timeout=20, isolation_level=None)
    conn.execute('PRAGMA journal_mode=WAL;')
    conn.execute('PRAGMA temp_store = MEMORY;')
    cursor = conn.cursor()
    try:
        yield cursor
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()

def atomic_business_update(cursor, user_id: int, delta: int) -> bool:
    cursor.execute("SELECT capital FROM businesses WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    if row is None: return False
    old_cap = row[0] or 0
    new_cap = old_cap + delta
    cursor.execute("UPDATE businesses SET capital = ? WHERE user_id = ? AND capital = ?", (new_cap, user_id, old_cap))
    return cursor.rowcount > 0

# ==========================================
# ✈️ TRAVEL COG & DB SETUP
# ==========================================
class Travel(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.setup_db()
        self.travel_checker.start()

    def setup_db(self):
        with get_travel_cursor() as c:
            c.execute('''CREATE TABLE IF NOT EXISTS travel_passports (
                user_id INTEGER PRIMARY KEY, level INTEGER DEFAULT 1, xp INTEGER DEFAULT 0,
                current_location TEXT DEFAULT 'Athena Central', travel_end_time REAL DEFAULT 0,
                travel_destination_id INTEGER, travel_class TEXT, using_private_vehicle INTEGER DEFAULT 0,
                visa_countries TEXT DEFAULT '[]', vip_expiry REAL DEFAULT 0, vip_weekly_express_used REAL DEFAULT 0
            )''')
            c.execute('''CREATE TABLE IF NOT EXISTS travel_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, destination_id INTEGER,
                travel_class TEXT, used_private_vehicle INTEGER, start_time REAL, end_time REAL, xp_gained INTEGER
            )''')
            c.execute('''CREATE TABLE IF NOT EXISTS travel_destinations (
                id INTEGER PRIMARY KEY, name TEXT, country_code TEXT, base_travel_hours INTEGER,
                visa_required INTEGER DEFAULT 1, visa_cost INTEGER, min_capital INTEGER DEFAULT 0,
                min_reputation INTEGER DEFAULT 0, required_vehicle_type TEXT, perks_json TEXT,
                goods_name TEXT, goods_buy_price INTEGER, goods_sell_price INTEGER, goods_max_per_trip INTEGER
            )''')

            if c.execute("SELECT COUNT(*) FROM travel_destinations").fetchone()[0] == 0:
                destinations = [
                    (1, "Tokyo, Japan", "JP", 5, 1, 250000, 500000, 60, None, '{"demand_boost": 0.10, "duration_hours": 24}', "Tech Components", 50000, 90000, 10),
                    (2, "Paris, France", "FR", 4, 1, 200000, 300000, 50, None, '{"reputation_boost": 15, "duration_hours": 48}', "Haute Couture", 75000, 120000, 8),
                    (3, "Dubai, UAE", "AE", 6, 1, 300000, 1000000, 70, "Jet", '{"tax_reduction": 5, "duration_days": 7}', "Crude Oil Barrels", 150000, 250000, 5),
                    (4, "Singapore", "SG", 3, 1, 150000, 200000, 40, None, '{"demand_boost": 0.05, "duration_hours": 12}', "Semiconductors", 30000, 55000, 15),
                    (5, "São Paulo, Brazil", "BR", 7, 1, 100000, 50000, 30, None, '{"product_unlock": "Coffee Beans"}', "Raw Coffee Beans", 10000, 18000, 20),
                ]
                c.executemany('''INSERT INTO travel_destinations VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''', destinations)

    @app_commands.command(name="travel", description="Access the Global Flight Terminal")
    async def travel_terminal(self, i: discord.Interaction):
        with get_travel_cursor() as c:
            c.execute("INSERT OR IGNORE INTO travel_passports (user_id) VALUES (?)", (i.user.id,))
        
        await i.response.send_message(f"{E_SPIN} *Connecting to Global Air Traffic Control...*", ephemeral=False)
        await asyncio.sleep(1.5)

        embed = await self.get_terminal_embed(i.user.id)
        view = TravelTerminalView(self, i.user.id)
        await i.edit_original_response(content=None, embed=embed, view=view)

    async def get_terminal_embed(self, user_id: int) -> discord.Embed:
        with get_travel_cursor() as c:
            row = c.execute("SELECT level, xp, current_location, travel_end_time, vip_expiry, visa_countries FROM travel_passports WHERE user_id = ?", (user_id,)).fetchone()
            level, xp, location, travel_end, vip_expiry, visas_json = row if row else (1, 0, "Athena Central", 0, 0, "[]")
            visas = json.loads(visas_json) if visas_json else []

        xp_needed = 1000 * (level ** 1.3)
        progress = int((xp / xp_needed) * 100) if xp_needed > 0 else 0

        embed = discord.Embed(title="꒰ა Global Aviation Terminal ⸝⸝", color=0xffffff)
        desc = (
            f"{E_DOT} **Current Region:** {location}\n"
            f"{E_PASSPORT} **SkyTeam Miles:** {xp:,} / {int(xp_needed):,} *(Level {level})* `{progress}%`\n"
            f"{E_VISA} **Active Visas:** {len(visas)}\n\n"
        )
        
        if travel_end > time.time():
            rem = int(travel_end - time.time())
            desc += f"{E_FLIGHT} **Flight Status:** Airborne. Touching down in {rem//3600}h {(rem%3600)//60}m\n"
        else:
            desc += f"{E_FLIGHT} **Flight Status:** Awaiting Departure\n"

        if vip_expiry > time.time():
            days = int((vip_expiry - time.time()) // 86400)
            desc += f"{E_VIP} **VIP Lounge:** Active ({days} days remaining)\n"
        else:
            desc += f"{E_VIP} **VIP Lounge:** Inactive\n"

        embed.description = desc
        embed.set_image(url=BANNER_URL)
        embed.set_footer(text="Athena Central Reserve • Secure Aviation Network")
        return embed

    async def get_destinations_embed(self, user_id: int) -> discord.Embed:
        with get_travel_cursor() as c:
            with get_biz_cursor() as biz_c:
                biz = biz_c.execute("SELECT capital, reputation FROM businesses WHERE user_id = ?", (user_id,)).fetchone()
                capital, reputation = (biz[0], biz[1]) if biz else (0, 0)
            visas_row = c.execute("SELECT visa_countries FROM travel_passports WHERE user_id = ?", (user_id,)).fetchone()
            visas = json.loads(visas_row[0]) if visas_row and visas_row[0] else []
            destinations = c.execute("SELECT id, name, country_code, base_travel_hours, visa_required, visa_cost, min_capital, min_reputation, required_vehicle_type, perks_json FROM travel_destinations").fetchall()

        embed = discord.Embed(title="꒰ა Live Departures Board ⸝⸝", color=0xffffff)
        desc = ""
        for dest in destinations:
            did, name, code, hours, visa_req, visa_cost, min_cap, min_rep, req_veh, perks_json = dest
            perks = json.loads(perks_json)
            locked_reasons = []
            
            if visa_req and code not in visas:
                locked_reasons.append(f"Requires {code} Visa (A$ {visa_cost:,})")
            if capital < min_cap:
                locked_reasons.append(f"Requires A$ {min_cap:,} Capital")
            if reputation < min_rep:
                locked_reasons.append(f"Requires {min_rep}% Rep")

            status = f"{E_LOCKED} **RESTRICTED AIRSPACE**" if locked_reasons else f"{E_UNLOCKED} **CLEARED FOR DEPARTURE**"
            
            desc += f"**{name}** ({code}) — {status}\n"
            desc += f"└ ⌛ **Base Flight Time:** {hours} hours\n"
            if locked_reasons:
                desc += f"└ ⚠️ **Restrictions:** {', '.join(locked_reasons)}\n\n"
            else:
                perk_str = ", ".join([f"{k.replace('_', ' ').title()}: {v}" for k, v in perks.items()])
                desc += f"└ ✨ **Regional Perks:** {perk_str}\n\n"

        embed.description = desc if desc else "No flights available."
        return embed

    async def apply_visa(self, i: discord.Interaction, user_id: int):
        with get_travel_cursor() as c:
            row = c.execute("SELECT visa_countries FROM travel_passports WHERE user_id = ?", (user_id,)).fetchone()
            owned_visas = json.loads(row[0]) if row and row[0] else []
            destinations = c.execute("SELECT id, name, country_code, visa_cost, min_capital, min_reputation FROM travel_destinations WHERE visa_required = 1").fetchall()

        available = []
        for did, name, code, cost, min_cap, min_rep in destinations:
            if code not in owned_visas:
                with get_biz_cursor() as biz_c:
                    biz = biz_c.execute("SELECT capital, reputation FROM businesses WHERE user_id = ?", (user_id,)).fetchone()
                    if biz and biz[0] >= min_cap and biz[1] >= min_rep:
                        available.append((code, name, cost))

        if not available:
            return await i.response.send_message(f"{E_ERROR} You already own all available visas, or your corporation lacks the clearance to apply for them.", ephemeral=True)

        class VisaDropdown(discord.ui.Select):
            def __init__(self, options, uid, cog):
                self.uid = uid
                self.cog = cog
                opts = [discord.SelectOption(label=f"Visa: {name}", value=code, description=f"Cost: A$ {cost:,}") for code, name, cost in options]
                super().__init__(placeholder="Select an embassy to apply...", options=opts)

            async def callback(self, inter: discord.Interaction):
                code = self.values[0]
                cost = next((c for c_code, _, c in available if c_code == code), 0)
                name = next((n for c_code, n, _ in available if c_code == code), code)

                with get_biz_cursor() as biz_c:
                    cap = biz_c.execute("SELECT capital FROM businesses WHERE user_id = ?", (self.uid,)).fetchone()
                    if not cap or cap[0] < cost:
                        return await inter.response.send_message(f"{E_ERROR} Application denied. Insufficient corporate capital.", ephemeral=True)
                    atomic_business_update(biz_c, self.uid, -cost)

                with get_travel_cursor() as c2:
                    v_row = c2.execute("SELECT visa_countries FROM travel_passports WHERE user_id = ?", (self.uid,)).fetchone()
                    current_visas = json.loads(v_row[0]) if v_row and v_row[0] else []
                    current_visas.append(code)
                    c2.execute("UPDATE travel_passports SET visa_countries = ? WHERE user_id = ?", (json.dumps(current_visas), self.uid))

                await inter.response.edit_message(content=f"{E_SUCCESS} **Embassy Approval!** You successfully purchased the **{name}** travel visa for A$ {cost:,}.", view=None)
                new_embed = await self.cog.get_terminal_embed(self.uid)
                await inter.edit_original_response(embed=new_embed, view=TravelTerminalView(self.cog, self.uid))

        view = discord.ui.View()
        view.add_item(VisaDropdown(available, user_id, self))
        await i.response.send_message("Select an international embassy to submit your visa application:", view=view, ephemeral=True)

    @tasks.loop(minutes=2)
    async def travel_checker(self):
        now = time.time()
        with get_travel_cursor() as c:
            rows = c.execute("SELECT user_id, travel_destination_id, travel_class, using_private_vehicle FROM travel_passports WHERE travel_end_time > 0 AND travel_end_time <= ?", (now,)).fetchall()
            for uid, dest_id, travel_class, used_private in rows:
                dest = c.execute("SELECT name, perks_json, base_travel_hours FROM travel_destinations WHERE id = ?", (dest_id,)).fetchone()
                if not dest: continue
                dest_name, perks_json, base_hours = dest
                perks = json.loads(perks_json)

                with get_biz_cursor() as biz_c:
                    if "demand_boost" in perks:
                        biz_c.execute("UPDATE businesses SET demand_boost = demand_boost + ? WHERE user_id = ?", (perks["demand_boost"], uid))
                    if "reputation_boost" in perks:
                        biz_c.execute("UPDATE businesses SET reputation = MIN(100, reputation + ?) WHERE user_id = ?", (perks["reputation_boost"], uid))

                base_xp = 250
                class_mult = CLASS_CONFIG.get(travel_class, CLASS_CONFIG["Economy"])["xp_mult"]
                vehicle_bonus = 2.0 if used_private else 1.0
                xp_gained = int(base_xp * class_mult * vehicle_bonus)

                c.execute("UPDATE travel_passports SET xp = xp + ?, current_location = ?, travel_end_time = 0, travel_destination_id = NULL, travel_class = NULL, using_private_vehicle = 0 WHERE user_id = ?", (xp_gained, dest_name, uid))
                
                # Check for Level Up
                row = c.execute("SELECT level, xp FROM travel_passports WHERE user_id = ?", (uid,)).fetchone()
                if row:
                    level, current_xp = row
                    needed = 1000 * (level ** 1.3)
                    while current_xp >= needed:
                        level += 1
                        current_xp -= needed
                        needed = 1000 * (level ** 1.3)
                    c.execute("UPDATE travel_passports SET level = ?, xp = ? WHERE user_id = ?", (level, current_xp, uid))

                user = self.bot.get_user(uid)
                if user:
                    embed = discord.Embed(title="꒰ა Flight Landed ⸝⸝", color=0xffffff)
                    embed.description = f"{E_SUCCESS} **Touchdown Confirmed!** You have safely landed in **{dest_name}**.\n└ Earned **{xp_gained}** SkyTeam Miles."
                    try: await user.send(embed=embed)
                    except: pass

    @travel_checker.before_loop
    async def before_travel_checker(self):
        await self.bot.wait_until_ready()

# ==========================================
# TERMINAL UI CONTROLS
# ==========================================
class TravelTerminalView(discord.ui.View):
    def __init__(self, cog: Travel, user_id: int):
        super().__init__(timeout=None)
        self.cog = cog
        self.user_id = user_id

    @discord.ui.button(label="Departures Board", style=discord.ButtonStyle.secondary, row=0, emoji="<:i_ghouls:1426522093620826112>")
    async def destinations_callback(self, i: discord.Interaction, btn):
        embed = await self.cog.get_destinations_embed(self.user_id)
        await i.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="Book Flight", style=discord.ButtonStyle.primary, row=0, emoji="<a:w_tear:1375482116749529098>")
    async def travel_callback(self, i: discord.Interaction, btn):
        with get_travel_cursor() as c:
            row = c.execute("SELECT travel_end_time FROM travel_passports WHERE user_id = ?", (self.user_id,)).fetchone()
            if row and row[0] > time.time():
                return await i.response.send_message(f"{E_ERROR} You are currently airborne!", ephemeral=True)
        view = TravelSetupView(self.cog, self.user_id)
        await i.response.send_message("Configure your flight itinerary:", view=view, ephemeral=True)

    @discord.ui.button(label="VIP Lounge", style=discord.ButtonStyle.secondary, row=0, emoji="<:i_cupid:1426518951961038929>")
    async def vip_callback(self, i: discord.Interaction, btn):
        with get_travel_cursor() as c:
            exp = c.execute("SELECT vip_expiry FROM travel_passports WHERE user_id = ?", (self.user_id,)).fetchone()[0]
        
        embed = discord.Embed(title="꒰ა VIP Airport Lounge ⸝⸝", color=0xffffff)
        if exp > time.time():
            embed.description = f"Your VIP SkyTeam membership is active until <t:{int(exp)}:F>.\n\n**Benefits:**\n• Fast-track arrival (1x/week)\n• +50% Bonus SkyMiles per flight\n• Priority Customs Clearance"
        else:
            embed.description = f"Purchase VIP Access for **A$ 5,000,000 / week**.\n\n**Benefits:**\n• Fast-track arrival (1x/week)\n• +50% Bonus SkyMiles per flight\n• Priority Customs Clearance"
        
        class VIPBuy(discord.ui.View):
            def __init__(self, uid):
                super().__init__(timeout=60)
                self.uid = uid
            @discord.ui.button(label="Purchase VIP", style=discord.ButtonStyle.success)
            async def buy(self, inter, b):
                # ✅ FIXED: Correct context manager variable name (bc instead of biz_c)
                with get_biz_cursor() as bc:
                    cap = bc.execute("SELECT capital FROM businesses WHERE user_id = ?", (self.uid,)).fetchone()
                    if not cap or cap[0] < VIP_WEEKLY_COST: 
                        return await inter.response.send_message(f"{E_ERROR} Insufficient corporate funds.", ephemeral=True)
                    atomic_business_update(bc, self.uid, -VIP_WEEKLY_COST)
                
                with get_travel_cursor() as tc:
                    # ✅ FIXED: 7 Days (604800 seconds) instead of 30 days
                    nx = max(time.time(), (tc.execute("SELECT vip_expiry FROM travel_passports WHERE user_id = ?", (self.uid,)).fetchone() or [0])[0]) + 604800
                    tc.execute("UPDATE travel_passports SET vip_expiry = ? WHERE user_id = ?", (nx, self.uid))
                await inter.response.edit_message(content=f"{E_SUCCESS} VIP Access Granted! You are now a premium member for 7 days.", embed=None, view=None)
                
        await i.response.send_message(embed=embed, view=VIPBuy(self.user_id), ephemeral=True)

    @discord.ui.button(label="Embassies", style=discord.ButtonStyle.secondary, row=1, emoji="<a:wt_toroleaf:1480580940785913967>")
    async def visa_callback(self, i: discord.Interaction, btn):
        await self.cog.apply_visa(i, self.user_id)

    @discord.ui.button(label="Cargo & Logistics", style=discord.ButtonStyle.secondary, row=1, emoji="<a:black:1509321860104458457>")
    async def trade_callback(self, i: discord.Interaction, btn):
        await i.response.send_message(f"{E_ERROR} Global Logistics Hub is currently undergoing maintenance. Check back later.", ephemeral=True)


class TravelSetupView(discord.ui.View):
    def __init__(self, cog: Travel, user_id: int):
        super().__init__(timeout=120)
        self.cog = cog
        self.user_id = user_id
        self.selected_dest_id = None
        self.selected_class = "Economy"
        self.selected_vehicle = "Commercial Airliner"

        with get_travel_cursor() as c:
            with get_biz_cursor() as biz_c:
                biz = biz_c.execute("SELECT capital, reputation FROM businesses WHERE user_id = ?", (user_id,)).fetchone()
                capital, reputation = (biz[0], biz[1]) if biz else (0, 0)
            visas_row = c.execute("SELECT visa_countries FROM travel_passports WHERE user_id = ?", (user_id,)).fetchone()
            visas = json.loads(visas_row[0]) if visas_row and visas_row[0] else []
            destinations = c.execute("SELECT id, name, country_code, visa_required FROM travel_destinations").fetchall()

        options = []
        for did, name, code, visa_req in destinations:
            if visa_req and code not in visas: continue
            options.append(discord.SelectOption(label=name, value=str(did), description=f"Fly to {code}"))

        if not options:
            options.append(discord.SelectOption(label="No cleared destinations", value="none", default=True))

        self.dest_select = discord.ui.Select(placeholder="1. Select Destination", options=options)
        self.dest_select.callback = self.dest_cb
        self.add_item(self.dest_select)

        self.class_select = discord.ui.Select(placeholder="2. Select Ticket Class", options=[
            discord.SelectOption(label="Economy Class", value="Economy", description="Standard fare"),
            discord.SelectOption(label="Business Class", value="Business", description="2.5x Cost | Faster | +50% Miles"),
            discord.SelectOption(label="First Class", value="First", description="6x Cost | Fastest | +110% Miles"),
        ])
        self.class_select.callback = self.class_cb
        self.add_item(self.class_select)

        # ✅ FIXED: Vehicle Dropdown logic mapping to Economy.db perfectly
        v_opts = [discord.SelectOption(label="Commercial Airlines", value="Commercial Airliner", description="Public Transit (Standard Luggage)")]
        with get_eco_cursor() as eco_c:
            for name, cat in eco_c.execute("SELECT m.name, m.category FROM user_vehicles u JOIN market_vehicles m ON u.vehicle_id = m.id WHERE u.user_id = ? AND m.category IN ('Jet', 'Yacht', 'Helicopter')", (user_id,)).fetchall():
                if cat == "Jet": perk = "-40% Time, Bypasses Visas"
                elif cat == "Yacht": perk = "+10x Cargo Limit, Slow Travel"
                else: perk = "Private Vehicle"
                v_opts.append(discord.SelectOption(label=name, value=name, description=perk))
        
        if len(v_opts) > 1:
            self.veh_select = discord.ui.Select(placeholder="3. Select Aircraft/Ship", options=v_opts)
            self.veh_select.callback = self.veh_cb
            self.add_item(self.veh_select)

        btn = discord.ui.Button(label="Print Boarding Pass", style=discord.ButtonStyle.success, row=3)
        btn.callback = self.confirm_cb
        self.add_item(btn)

    async def dest_cb(self, i): 
        self.selected_dest_id = int(self.dest_select.values[0]) if self.dest_select.values[0] != "none" else None
        await i.response.defer()
    async def class_cb(self, i): 
        self.selected_class = self.class_select.values[0]
        await i.response.defer()
    async def veh_cb(self, i): 
        self.selected_vehicle = self.veh_select.values[0]
        await i.response.defer()

    async def confirm_cb(self, i: discord.Interaction):
        if not self.selected_dest_id: return await i.response.send_message(f"{E_ERROR} Select a valid destination.", ephemeral=True)

        with get_travel_cursor() as c:
            dest = c.execute("SELECT name, base_travel_hours, visa_cost, country_code FROM travel_destinations WHERE id = ?", (self.selected_dest_id,)).fetchone()
            dest_name, base_hours, visa_cost, dest_code = dest

        time_mult, cost_mult = CLASS_CONFIG[self.selected_class]["time_mult"], CLASS_CONFIG[self.selected_class]["cost_mult"]
        
        # Flight dynamics logic based on Vehicle chosen
        use_priv = self.selected_vehicle != "Commercial Airliner"
        
        if use_priv:
            time_mult *= 0.60
            cost_mult *= 0.30
            # Private jets bypass visa processing fees completely at the border
            actual_visa_cost = 0 
        else:
            actual_visa_cost = visa_cost

        travel_sec = int(base_hours * 3600 * time_mult)
        cost = int(actual_visa_cost + (base_hours * 50000 * cost_mult))

        with get_biz_cursor() as biz_c:
            cap = biz_c.execute("SELECT capital FROM businesses WHERE user_id = ?", (self.user_id,)).fetchone()
            if not cap or cap[0] < cost: return await i.response.send_message(f"{E_ERROR} Flight declined. Need A$ {cost:,} corporate capital.", ephemeral=True)
            atomic_business_update(biz_c, self.user_id, -cost)

        with get_travel_cursor() as c:
            c.execute("UPDATE travel_passports SET travel_end_time = ?, travel_destination_id = ?, travel_class = ?, using_private_vehicle = ? WHERE user_id = ?", (time.time() + travel_sec, self.selected_dest_id, self.selected_class, 1 if use_priv else 0, self.user_id))

        # ASCII Boarding Pass
        ticket_id = f"{random.randint(1000,9999)}-{dest_code}"
        e = discord.Embed(title="꒰ა Boarding Pass Confirmed ⸝⸝", color=0xffffff)
        e.description = (
            f"```yaml\n"
            f"ATC CLEARED FOR TAKEOFF [{ticket_id}]\n"
            f"----------------------------------------\n"
            f"PASSENGER : CEO {i.user.name.upper()}\n"
            f"TO        : {dest_name.upper()}\n"
            f"AIRCRAFT  : {self.selected_vehicle.upper()}\n"
            f"CLASS     : {self.selected_class.upper()}\n\n"
            f"FLIGHT TIME : {travel_sec/3600:.1f} HOURS\n"
            f"FLIGHT COST : A$ {cost:,}\n"
            f"----------------------------------------\n```\n"
            f"*Your corporate ledgers have been billed. Have a safe flight, Executive.*"
        )
        await i.response.edit_message(content=None, embed=e, view=None)
        
        # Refresh background terminal
        new_embed = await self.cog.get_terminal_embed(self.user_id)
        await i.edit_original_response(embed=new_embed, view=TravelTerminalView(self.cog, self.user_id))

async def setup(bot):
    await bot.add_cog(Travel(bot))