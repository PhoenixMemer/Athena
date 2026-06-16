from __future__ import annotations
import discord
from discord import app_commands, Interaction
from discord.ext import commands, tasks
import sqlite3
import json
import time
import random
import math
import re
import asyncio
from datetime import datetime
from contextlib import contextmanager

# ==========================================
# CONFIGURATION & CONSTANTS
# ==========================================
BUSINESS_CHANNEL_ID = 1218599931837681734
DB_PATH = "business.db"
ECO_DB = "economy.db"
TRANSACTION_FEE = 0.13          # 0.2% fee on every trade (goes to central reserve)
TRADE_COOLDOWN_SECONDS = 300     # 5 minutes cooldown per (user, symbol)
LOTTERY_COOLDOWN = 28800
SECURITY_SPECIALIST_WAGE = 12000   # deducted every cycle (5 hours)
MINIMUM_WAGE = 1800        # for regular staff
SPECIALIST_MIN_WAGE = 5500 # for Engineer/Auditor/Shark


BALANCE_BANNER_URL = "https://i.pinimg.com/1200x/2e/c9/25/2ec925bf38a3ec1c6456a4ef244a1252.jpg"
PARTNER_BANNER_URL = "https://i.pinimg.com/1200x/86/33/31/863331d9220141f0909b22f498e4e661.jpg"
CYBER_BANNER_URL = "https://i.pinimg.com/1200x/97/f3/d4/97f3d4d33569238df756a2424c9ac478.jpg"


def get_security_specialists_count(cursor, user_id: int, spec_type: str = None) -> int:
    """Returns total specialists, or count of offensive/defensive if spec_type given."""
    if spec_type:
        cursor.execute("SELECT COUNT(id) FROM security_specialists WHERE user_id = ? AND specialist_type = ?", (user_id, spec_type))
    else:
        cursor.execute("SELECT COUNT(id) FROM security_specialists WHERE user_id = ?", (user_id,))
    return cursor.fetchone()[0]

def get_max_specialists(cursor, user_id: int) -> int:
    """Max specialists = HQ max employees / 10 (rounded down)."""
    cursor.execute("SELECT hq_level FROM businesses WHERE user_id = ?", (user_id,))
    hq = cursor.fetchone()[0]
    max_emp = HQ_LEVELS[hq]["max_emp"]
    return max_emp // 10


def get_hire_cost(cursor, user_id: int, staff_type: str = "regular") -> int:
        """Calculate hire cost based on current employee count."""
        if staff_type == "regular":
                cursor.execute("SELECT COUNT(id) FROM employees WHERE user_id = ? AND specialization = 'None'", (user_id,))
                count = cursor.fetchone()[0]
                base = 5000
                scaling = (count // 50) * 200
                return base + scaling
        elif staff_type == "specialist":
                cursor.execute("SELECT COUNT(id) FROM employees WHERE user_id = ? AND specialization IN ('Engineer','Auditor','Shark','Logistics')", (user_id,))
                count = cursor.fetchone()[0]
                base = 35000
                scaling = (count // 5) * 3000
                return base + scaling
        elif staff_type == "cyber":
                cursor.execute("SELECT COUNT(id) FROM security_specialists WHERE user_id = ?", (user_id,))
                count = cursor.fetchone()[0]
                base = 50000
                scaling = (count // 5) * 4000
                return base + scaling
        return 0

# ==========================================
# PARTNERSHIP EFFECTS (Global)
# ==========================================
def apply_partnership_effects(user_id: int, tier: str):
    tiers = {
        "temu": {"rep": 10, "demand": 0.10, "stock": 0.05, "duration": 5},
        "xiaomi": {"rep": 20, "demand": 0.20, "stock": 0.10, "duration": 10},
        "apple": {"rep": 35, "demand": 0.35, "stock": 0.20, "duration": 13},
        "google": {"rep": 50, "demand": 0.50, "stock": 0.50, "duration": 18}
    }
    data = tiers[tier]
    with get_db_cursor() as c:
        c.execute("SELECT reputation, demand_boost FROM businesses WHERE user_id = ?", (user_id,))
        orig_rep, orig_demand = c.fetchone()
        new_rep = min(100, orig_rep + data["rep"])
        new_rep = min(100, new_rep)
        new_demand = orig_demand + data["demand"]
        c.execute("UPDATE businesses SET reputation = ?, demand_boost = ? WHERE user_id = ?", (new_rep, new_demand, user_id))
        c.execute("SELECT name, is_public FROM businesses WHERE user_id = ?", (user_id,))
        name, is_public = c.fetchone()
        if is_public:
            sym = name[:4].upper()
            with get_eco_cursor() as eco:
                eco.execute("UPDATE stocks SET price = price + CAST(price * ? AS INTEGER) WHERE symbol = ?", (data["stock"], sym))
        end_time = time.time() + data["duration"] * 86400
        c.execute("INSERT OR REPLACE INTO active_partnerships (user_id, tier, start_time, end_time, original_reputation, original_demand_boost) VALUES (?, ?, ?, ?, ?, ?)",
                  (user_id, tier, time.time(), end_time, orig_rep, orig_demand))

HQ_LEVELS = {
    0: {"name": "Mother's Garage", "max_emp": 5, "cost": 0},
    1: {"name": "Sweatshop", "max_emp": 50, "cost": 150_000},
    2: {"name": "Tel Aviv Campus", "max_emp": 500, "cost": 800_000},
    3: {"name": "Dubai Skyscraper", "max_emp": 800, "cost": 3_000_000},
    4: {"name": "New York Tower", "max_emp": 1100, "cost": 5_000_000},
    5: {"name": "Oriental Pearl Tower Shanghai", "max_emp": 2100, "cost": 25_000_000}
}

QUALITY_TIERS = {
    "Standard": {"cost_mult": 1.0, "price_mult": 1.0, "demand_elasticity": 1.0, "required_tech": 0},
    "Premium":  {"cost_mult": 1.2, "price_mult": 1.5, "demand_elasticity": 0.8, "required_tech": 5},
    "Luxury":   {"cost_mult": 1.3, "price_mult": 1.8, "demand_elasticity": 0.6, "required_tech": 15}
}

TECH_MILESTONES = {
    0:  "<a:wb_bow15:1412784394631909509> Basic R&D lab — Standard products only",
    5:  "<a:wb_bow15:1412784394631909509> Premium tier — Higher margins available",
    10: "<a:wb_bow15:1412784394631909509> Market Analytics — 5% demand boost passive",
    15: "<a:wb_bow15:1412784394631909509> Luxury tier — Elite products available",
    20: "<a:wb_bow15:1412784394631909509> Automation — 10% cost reduction on all production",
    25: "<a:wb_bow15:1412784394631909509> Global Reach — 10% reputation boost per cycle",
    30: "<a:wb_bow15:1412784394631909509> Industry 4.0 — All multipliers doubled from staff",
    50: "<a:wb_bow15:1412784394631909509> Singularity — Maximum efficiency, maximum profit"
}

NAMES = ["Liam", "Emma", "Noah", "Olivia", "Trump", "Nova", "Elysia", "Sophia", "Kades", "Isabella",
         "Lucas", "Labubu", "Arthur", "Yeo", "Phoenix", "Declan", "Ezra", "Chase", "Sarah", "Kyxrt"]

DEFAULT_BANNER = "https://i.pinimg.com/1200x/45/b4/d3/45b4d3b026e6aa7d9096cc9e33a4a4f0.jpg"

SECTOR_CATALOGS = {
    "Tech": [
        "Cloud Sync Pro", "AthenaOS Suite", "NeuralNet AI", "CyberShield Firewall", 
        "Quantum Compute Unit", "Athens Smart Home Hub",
        "Blockchain Validator Node", "AR/VR Dev Kit", "Holographic Cuboid Displays"
    ],
    "Food": [
        "Gourmet Meal Kits", "Organic Snack Box", "Smart Vending Machine", 
        "Premium Coffee Blend", "Farm to Table Delivery", "Plant Based Protein",
        "Artisanal Fermented Foods", "Vertical Farming Module", "Edible Insect Protein Bar"
    ],
    "Luxury": [
        "Designer Handbags", "Swiss Watches", "Custom Yacht Interiors", 
        "Private Jet Leasing", "Rare Gemstone Jewelry", "Haute Couture Line",
        "Limited Edition Hypercar", "Private Island Resort Package", "Space Tourism Ticket"
    ],
    "Retail": [
        "Fast Fashion Line", "Home Decor Essentials", "Eco Friendly Groceries", 
        "Tech Gadget Store", "Seasonal Pop-Up Shop", "Subscription Box Service", 
        "Cheap Animal Food", "Genshin Funkopops",
        "Automated Checkout Kiosk", "Luxury Pet Boutique", "Augmented Reality Fitting Room"
    ],
    "Industrial": [
        "Heavy Machinery Parts", "Logistics Fleet", "Renewable Energy Grid", 
        "Steel Manufacturing", "Chemical Processing Unit", "Warehouse Automation",
        "3D Printing Industrial Hub", "Carbon Capture Plant", "Modular Housing Factory"
    ],
    "Energy": [
        "Oil Extraction Pumps", "Disaster Coverup Guidebooks", "Anti Renewable Energy Pamphlets", 
        "Enhanced Oil Recovery Techniques", "Gas Cylinder Technology", "Hydraulic Fracturing",
        "Floating Offshore Wind Turbine", "Small Modular Nuclear Reactor", "Green Hydrogen Electrolyzer"
    ],
    "Self Care": [
        "Liquid Foundation", "Matte Lipstick", "Volumizing Mascara", 
        "Liquid Concealer", "Setting Spray", "Eyeshadow Palette",
        "Highlighter Stick", "Blush Compact", "Brow Pencil",
        "Makeup Remover Wipes", "Primer", "Contour Kit"
    ]
}
SECTORS = list(SECTOR_CATALOGS.keys())

SECTOR_BASE_COSTS = {
    "Tech": 650,
    "Food": 550,
    "Luxury": 2900,
    "Retail": 600,
    "Self Care": 1900,
    "Industrial": 1500,
    "Energy": 1500
}

COUNTRY_TAX_RATES = {
    "USA": {
        "brackets": [
            (100000, 0.0),
            (500000, 0.05),
            (2000000, 0.25),
            (float('inf'), 0.45)
        ]
    },
    "UK": {
        "brackets": [
            (100000, 0.0),
            (500000, 0.07),
            (2000000, 0.28),
            (float('inf'), 0.43)
        ]
    },
    "Germany": {
        "brackets": [
            (100000, 0.0),
            (500000, 0.06),
            (2000000, 0.26),
            (float('inf'), 0.38)
        ]
    },
    "France": {
        "brackets": [
            (100000, 0.0),
            (500000, 0.08),
            (2000000, 0.29),
            (float('inf'), 0.40)
        ]
        
    },
    "Brazil": {
        "brackets": [
            (100000, 0.0),
            (500000, 0.09),
            (2000000, 0.25),
            (float('inf'), 0.50)
        ]
    },
    "China": {
        "brackets": [
            (100000, 0.0),
            (500000, 0.04),
            (2000000, 0.14),
            (float('inf'), 0.40)
        ]

    },
    "Singapore": {
        "brackets": [
            (100000, 0.0),
            (500000, 0.07),
            (2000000, 0.19),
            (float('inf'), 0.40)
        ]

    },
    "Canada": {
        "brackets": [
            (100000, 0.0),
            (500000, 0.09),
            (2000000, 0.18),
            (float('inf'), 0.40)
        ]

    },
    "Vietnam": {
        "brackets": [
            (100000, 0.0),
            (500000, 0.03),
            (2000000, 0.12),
            (float('inf'), 0.35)
        ]
    }
    
}

def calculate_progressive_tax(net_profit: int) -> int:
    """Calculates progressive tax. Startups under 100k are untouched."""
    if net_profit <= 100_000:
        return 0
    elif net_profit <= 500_000:
        return int(net_profit * 0.05)
    elif net_profit <= 2_000_000:
        return int(net_profit * 0.15)
    else:
        return int(net_profit * 0.30)

# ==========================================
# 🗄️ SAFE DATABASE CONTEXT MANAGERS
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

@contextmanager
def get_eco_cursor():
    conn = sqlite3.connect(ECO_DB, timeout=20, isolation_level=None)
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
def atomic_business_update(cursor, user_id: int, delta: int) -> bool:
    cursor.execute("SELECT capital FROM businesses WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    if row is None: return False
    old_cap = row[0] or 0
    new_cap = old_cap + delta
    cursor.execute("UPDATE businesses SET capital = ? WHERE user_id = ? AND capital = ?", (new_cap, user_id, old_cap))
    return cursor.rowcount > 0

def update_activity(user_id: int):
    """Stamps last_active on any business interaction so inactivity tracking works."""
    with get_db_cursor() as c:
        c.execute("UPDATE businesses SET last_active = ? WHERE user_id = ?", (time.time(), user_id))

def atomic_eco_balance_update(cursor, user_id: int, delta: int) -> bool:
    cursor.execute("SELECT balance FROM wallets WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    if row is None:
        cursor.execute("INSERT OR IGNORE INTO wallets (user_id, balance, active_card, highest_balance) VALUES (?, 0, 'silver', 0)", (user_id,))
        cursor.execute("UPDATE wallets SET balance = balance + ? WHERE user_id = ?", (delta, user_id))
        return True
    old_bal = row[0] or 0
    new_bal = old_bal + delta
    cursor.execute("UPDATE wallets SET balance = ? WHERE user_id = ? AND balance = ?", (new_bal, user_id, old_bal))
    return cursor.rowcount > 0

def log_business_event(cursor, user_id: int, event_type: str, description: str):
    cursor.execute("INSERT INTO business_logs (user_id, type, description) VALUES (?, ?, ?)", (user_id, event_type, description))

# ==========================================
# 📊 UI COMPONENTS & MODALS
# ==========================================

class DiluteSharesModal(discord.ui.Modal, title='Issue Corporate Shares'):
    shares = discord.ui.TextInput(label='Number of Shares to Mint & Sell', placeholder='e.g., 500')

    async def on_submit(self, i: discord.Interaction):
        try:
            shares_to_mint = int(self.shares.value)
            if shares_to_mint <= 0: raise ValueError
            
            with get_db_cursor() as c:
                c.execute("SELECT name, is_public, capital, reputation FROM businesses WHERE user_id = ?", (i.user.id,))
                biz = c.fetchone()
                if not biz or biz[1] == 0:
                    return await i.response.send_message("❌ Your company must be public (IPO) to dilute equity.", ephemeral=True)
                
                sym = biz[0][:4].upper()
                
                with get_eco_cursor() as c_eco:
                    c_eco.execute("SELECT price FROM stocks WHERE symbol = ?", (sym,))
                    stock_row = c_eco.fetchone()
                
                if not stock_row:
                    return await i.response.send_message("❌ Stock ticker profile data not found.", ephemeral=True)
                    
                current_stock_price = stock_row[0]
                
                capital_raised = shares_to_mint * current_stock_price
                
                rep_drop = max(1, shares_to_mint // 100)
                price_drop_pct = min(0.85, (shares_to_mint / 100) * 0.01)
                
                if rep_drop >= biz[3] or price_drop_pct >= 0.85:
                    return await i.response.send_message("❌ **The Athena Central Reserve blocked this issuance.** Minting this many shares would trigger a hyper-inflationary collapse of your brand equity.", ephemeral=True)

                c.execute("UPDATE businesses SET capital = capital + ?, reputation = MAX(1, reputation - ?) WHERE user_id = ?", (capital_raised, rep_drop, i.user.id))
                log_business_event(c, i.user.id, "SHARE_DILUTION", f"Minted {shares_to_mint} shares to raise A$ {capital_raised:,}")
                
                with get_eco_cursor() as c_eco:
                    new_stock_price = max(10, int(current_stock_price * (1.0 - price_drop_pct)))
                    c_eco.execute("UPDATE stocks SET price = ?, trend = '📉 DILUTED' WHERE symbol = ?", (new_stock_price, sym))
                    
            await i.response.send_message(
                f"**Equity Issuance Executed Successfully!**\n"
                f"You minted and sold **{shares_to_mint:,} shares** on the open market, raising **A$ {capital_raised:,}** in liquid corporate capital.\n\n"
                f"**Market Readjustments Applied:**\n"
                f"• Brand Reputation dropped by **-{rep_drop}%** due to dilution irritation.\n"
                f"• Stock Price shifted from A$ {current_stock_price:,} down to **A$ {new_stock_price:,}**.",
                ephemeral=False
            )

        except ValueError:
            await i.response.send_message("Invalid entry. Please specify a proper amount of shares.", ephemeral=True)

class DescriptionModal(discord.ui.Modal, title='Set Company Bio'):
    desc = discord.ui.TextInput(label='Company Description', style=discord.TextStyle.paragraph, max_length=150, placeholder='A rising corporate empire...')
    async def on_submit(self, i: discord.Interaction):
        with get_db_cursor() as c:
            c.execute("UPDATE businesses SET description = ? WHERE user_id = ?", (self.desc.value, i.user.id))
        await i.response.send_message("<a:wt_toroexclaim:1480581004317036624> Bio updated.", ephemeral=True)

class RenameCompanyModal(discord.ui.Modal, title='Rename Company'):
    name = discord.ui.TextInput(label='New Company Name', min_length=3, max_length=30)
    async def on_submit(self, i: discord.Interaction):
        with get_db_cursor() as c:
            c.execute("UPDATE businesses SET name = ? WHERE user_id = ?", (self.name.value, i.user.id))
        await i.response.send_message(f"<a:wt_toroexclaim:1480581004317036624> Company renamed to {self.name.value}.", ephemeral=True)

class SetSalaryModal(discord.ui.Modal, title='Executive Payroll'):
    salary = discord.ui.TextInput(label='Daily Personal Salary (A$)', placeholder='e.g., 5000', max_length=7)
    async def on_submit(self, i: discord.Interaction):
        try:
            amt = int(self.salary.value)
            if amt < 0: raise ValueError
            with get_db_cursor() as c:
                c.execute("UPDATE businesses SET owner_salary = ? WHERE user_id = ?", (amt, i.user.id))
            await i.response.send_message(f"<a:wt_toroexclaim:1480581004317036624> Salary set to A$ {amt:,}.", ephemeral=True)
        except ValueError:
            await i.response.send_message("<a:wt_torono:1480580892706603018> Invalid amount.", ephemeral=True)

class InvestModal(discord.ui.Modal, title='Inject Personal Capital'):
    amount = discord.ui.TextInput(label='Amount (A$)', placeholder='e.g., 100000')
    async def on_submit(self, i: discord.Interaction):
        try:
            amt = int(self.amount.value)
            if amt <= 0: raise ValueError
            with get_eco_cursor() as c_eco:
                c_eco.execute("SELECT balance FROM wallets WHERE user_id = ?", (i.user.id,))
                bal = c_eco.fetchone()
                if not bal or bal[0] < amt:
                    return await i.response.send_message("<a:wt_torono:1480580892706603018> Insufficient personal funds.", ephemeral=True)
                if bal[0] < 0:
                    return await i.response.send_message("Your wallet is in debt. Clear your debt before injecting.", ephemeral=True)
                c_eco.execute("UPDATE wallets SET balance = balance - ? WHERE user_id = ?", (amt, i.user.id))
            with get_db_cursor() as c:
                c.execute("UPDATE businesses SET capital = capital + ? WHERE user_id = ?", (amt, i.user.id))
            await i.response.send_message(f"<a:wt_toroexclaim:1480581004317036624> Injected A$ {amt:,}.", ephemeral=False)
        except ValueError:
            await i.response.send_message("<a:wt_torono:1480580892706603018> Invalid amount.", ephemeral=True)

class ProductModal(discord.ui.Modal):
    p_name = discord.ui.TextInput(label='Custom Product Name', min_length=3, max_length=30)
    p_price = discord.ui.TextInput(label='Unit Selling Price (A$)', placeholder='e.g. 500 (Must be > Base Cost)', max_length=7)
    p_qty = discord.ui.TextInput(label='Daily Target Quantity', placeholder='e.g. 500', max_length=7)

    def __init__(self, sector: str, product_type: str):
        self.base_cost = SECTOR_BASE_COSTS.get(sector, 100)
        super().__init__(title=f'Launch Product (Base Cost: A$ {self.base_cost})')
        self.sector = sector
        self.product_type = product_type

    async def on_submit(self, i: discord.Interaction):
        try:
            price, qty = int(self.p_price.value), int(self.p_qty.value)
            cost = self.base_cost
            if price <= cost or qty <= 0: raise ValueError
        except ValueError:
            return await i.response.send_message(f"<a:wt_torono:1480580892706603018> Invalid numbers! Your Selling Price must be strictly higher than the Base Cost (A$ {self.base_cost}).", ephemeral=True)
            
        with get_db_cursor() as c:
            full_name = f"{self.p_name.value} ({self.product_type})"
            c.execute("""INSERT INTO business_products
                (user_id, name, category, unit_price, cost_to_make, production_target, quality_tier, active)
                VALUES (?, ?, ?, ?, ?, ?, 'Standard', 1)""",
                (i.user.id, full_name, self.sector, price, cost, qty))
            c.execute("UPDATE businesses SET sector = ? WHERE user_id = ? AND sector IS NULL", (self.sector, i.user.id))
            log_business_event(c, i.user.id, "PRODUCT_LAUNCH", f"Launched {full_name}")
            
        await i.response.send_message(f"<a:wt_toroexclaim:1480581004317036624> **{full_name}** launched successfully in the {self.sector} sector!", ephemeral=True)


class EditProductModal(discord.ui.Modal):
    new_price = discord.ui.TextInput(label='New Unit Selling Price (A$)', placeholder='Enter new price...', max_length=7)
    new_qty = discord.ui.TextInput(label='New Daily Target Quantity', placeholder='Enter new production target...', max_length=7)

    def __init__(self, product_id: int, product_name: str, base_cost: int):
        short_name = product_name[:30] + "..." if len(product_name) > 30 else product_name
        super().__init__(title=f"Edit: {short_name}")
        self.product_id = product_id
        self.base_cost = base_cost

    async def on_submit(self, i: discord.Interaction):
        try:
            price = int(self.new_price.value)
            qty = int(self.new_qty.value)
            if price <= self.base_cost or qty < 0: raise ValueError
        except ValueError:
            return await i.response.send_message(f"<a:wt_torono:1480580892706603018> Invalid numbers! Price must be strictly higher than the Base Cost (A$ {self.base_cost}) and quantity cannot be negative.", ephemeral=True)

        with get_db_cursor() as c:
            c.execute("UPDATE business_products SET unit_price = ?, production_target = ? WHERE id = ?", (price, qty, self.product_id))
        
        await i.response.send_message(f"<a:wt_toroexclaim:1480581004317036624> **Product Configuration Updated!** New Price: A$ {price:,} | Daily Target: {qty:,} units.", ephemeral=False)


class ProductTypeDropdown(discord.ui.Select):
    def __init__(self, sector: str):
        self.sector = sector
        catalog = SECTOR_CATALOGS.get(sector, [])
        opts = [discord.SelectOption(label=item, value=item) for item in catalog]
        super().__init__(placeholder=f"Select base product type for {sector}...", options=opts)
        
    async def callback(self, i: discord.Interaction):
        product_type = self.values[0]
        await i.response.send_modal(ProductModal(self.sector, product_type))

class EditProductDropdown(discord.ui.Select):
    def __init__(self, user_id: int, sector: str):
        self.base_cost = SECTOR_BASE_COSTS.get(sector, 100)
        with get_db_cursor() as c:
            c.execute("SELECT id, name, unit_price, production_target FROM business_products WHERE user_id = ? AND active = 1", (user_id,))
            prods = c.fetchall()
        
        opts = [discord.SelectOption(label=f"{n}", description=f"Price: A$ {p:,} | Target: {q:,}/day", value=str(id)) for id, n, p, q in prods]
        if not opts: opts.append(discord.SelectOption(label="No products found", value="none"))
        
        super().__init__(placeholder="Select a product to configure...", options=opts)

    async def callback(self, i: discord.Interaction):
        if self.values[0] == "none": return
        
        product_id = int(self.values[0])
        product_name = [o.label for o in self.options if o.value == self.values[0]][0]
        
        await i.response.send_modal(EditProductModal(product_id, product_name, self.base_cost))

class UpgradeProductDropdown(discord.ui.Select):
    def __init__(self, user_id):
        self.user_id = user_id
        with get_db_cursor() as c:
            c.execute("SELECT id, name, quality_tier FROM business_products WHERE user_id = ? AND active = 1", (user_id,))
            prods = c.fetchall()
        opts = []
        for pid, name, tier in prods:
            next_tier = "Premium" if tier == "Standard" else "Luxury" if tier == "Premium" else None
            if next_tier:
                opts.append(discord.SelectOption(label=f"{name} → {next_tier}", description=f"Current: {tier}", value=f"{pid}:{next_tier}"))
        if not opts: opts.append(discord.SelectOption(label="No products to upgrade", value="none"))
        super().__init__(placeholder="Upgrade product tier...", options=opts)
    async def callback(self, i: discord.Interaction):
        if self.values[0] == "none": return
        pid, new_tier = self.values[0].split(":")
        with get_db_cursor() as c:
            c.execute("SELECT tech_level FROM businesses WHERE user_id = ?", (i.user.id,))
            tech = c.fetchone()[0]
            required = QUALITY_TIERS[new_tier]["required_tech"]
            if tech < required:
                return await i.response.send_message(f"<a:wt_torono:1480580892706603018> Need Tech Level {required} for {new_tier} tier.", ephemeral=True)
            c.execute("UPDATE business_products SET quality_tier = ? WHERE id = ?", (new_tier, int(pid)))
        await i.response.send_message(f"<a:wt_toroexclaim:1480581004317036624> Product upgraded to {new_tier}!", ephemeral=False)

class MarketingModal(discord.ui.Modal, title='Marketing Blitz'):
    amount = discord.ui.TextInput(label='Amount to spend (A$)', placeholder='e.g., 100000')
    async def on_submit(self, i: discord.Interaction):
        try:
            amt = int(self.amount.value)
            if amt <= 0:
                raise ValueError
            with get_db_cursor() as c:
                c.execute("SELECT capital FROM businesses WHERE user_id = ?", (i.user.id,))
                biz = c.fetchone()
                if not biz or biz[0] < amt:
                    return await i.response.send_message("<a:wt_torono:1480580892706603018> Insufficient capital.", ephemeral=True)

                # Diminishing returns for marketing
                if amt <= 100_000:
                    boost = 1.0 + (amt / 100_000) * 0.05
                elif amt <= 300_000:
                    boost = 1.05 + ((amt - 100_000) / 200_000) * 0.03
                else:
                    boost = 1.08 + ((amt - 300_000) / 200_000) * 0.01
                boost = min(1.3, boost)  # hard cap at +30%

                c.execute("UPDATE businesses SET capital = capital - ?, demand_boost = demand_boost + ?, marketing_budget = marketing_budget + ? WHERE user_id = ?",
                          (amt, boost, amt, i.user.id))
            await i.response.send_message(f"<a:wt_toroexclaim:1480581004317036624> Marketing blitz launched! Demand boosted by +{boost*100-100:.1f}%.", ephemeral=False)
        except ValueError:
            await i.response.send_message("<a:wt_torono:1480580892706603018> Invalid amount.", ephemeral=True)

class DividendModal(discord.ui.Modal, title='Pay Dividends'):
    amount = discord.ui.TextInput(label='Amount to distribute (A$)', placeholder='e.g., 50000')
    async def on_submit(self, i: discord.Interaction):
        try:
            amt = int(self.amount.value)
            if amt <= 0: raise ValueError
            with get_db_cursor() as c:
                c.execute("SELECT name, capital, is_public FROM businesses WHERE user_id = ?", (i.user.id,))
                biz = c.fetchone()
                if not biz or not biz[2]:
                    return await i.response.send_message("<a:wt_torono:1480580892706603018> You company is not public. To go public through an IPO, your company needs A$2,000,000!", ephemeral=True)
                if biz[1] < amt:
                    return await i.response.send_message("<a:wt_torono:1480580892706603018> Insufficient capital.", ephemeral=True)
                c.execute("UPDATE businesses SET capital = capital - ? WHERE user_id = ?", (amt, i.user.id))
            with get_eco_cursor() as c_eco:
                c_eco.execute("SELECT user_id, shares FROM portfolio WHERE symbol = ?", (biz[0][:4].upper(),))
                shareholders = c_eco.fetchall()
                total_shares = sum(s[1] for s in shareholders) if shareholders else 0
                if total_shares == 0:
                    return await i.response.send_message("No shareholders to pay.", ephemeral=True)
                for uid, sh in shareholders:
                    payout = int(amt * (sh / total_shares))
                    c_eco.execute("INSERT INTO wallets (user_id, balance, active_card) VALUES (?, ?, 'silver') ON CONFLICT DO UPDATE SET balance = balance + ?", (uid, payout, payout))
            await i.response.send_message(f"💸 Paid A$ {amt:,} in dividends to {len(shareholders)} shareholders.", ephemeral=False)
        except ValueError:
            await i.response.send_message("<a:wt_torono:1480580892706603018> Invalid amount.", ephemeral=True)

class RndInvestModal(discord.ui.Modal, title='Invest in R&D'):
    amount = discord.ui.TextInput(label='Amount to invest (A$)', placeholder='e.g., 50000')
    async def on_submit(self, i: discord.Interaction):
        try:
            amt = int(self.amount.value)
            if amt <= 0: raise ValueError
            with get_db_cursor() as c:
                c.execute("SELECT capital, tech_level FROM businesses WHERE user_id = ?", (i.user.id,))
                biz = c.fetchone()
                if not biz: return await i.response.send_message("<a:wt_torono:1480580892706603018> No business.", ephemeral=True)
                if biz[0] < amt: return await i.response.send_message("<a:wt_torono:1480580892706603018> Insufficient capital.", ephemeral=True)
                old_tech = biz[1]
                pts = amt // 5000
                new_tech = old_tech + pts
                c.execute("UPDATE businesses SET capital = capital - ?, tech_level = tech_level + ? WHERE user_id = ?", (amt, pts, i.user.id))
            unlocked = []
            for milestone, desc in TECH_MILESTONES.items():
                if old_tech < milestone <= new_tech:
                    unlocked.append(f"Tech {milestone}: {desc}")
            msg = f"<a:wt_toroexclaim:1480581004317036624> Invested A$ {amt:,} → +{pts} tech points (Total: {new_tech})."
            if unlocked:
                msg += "\n\n Milestones Unlocked:\n" + "\n".join(unlocked)
            await i.response.send_message(msg, ephemeral=False)
        except ValueError:
            await i.response.send_message("<a:wt_torono:1480580892706603018> Invalid amount.", ephemeral=True)

class BannerModal(discord.ui.Modal, title='Set Banner'):
    url = discord.ui.TextInput(label='Image URL', placeholder='e.g https://i.imgur.com/...', max_length=300)
    async def on_submit(self, i: discord.Interaction):
        with get_db_cursor() as c:
            c.execute("INSERT OR REPLACE INTO config (key, value) VALUES ('newspaper_banner', ?)", (self.url.value,))
        await i.response.send_message("<a:wt_toroexclaim:1480581004317036624> Banner updated!", ephemeral=True)

class PhilosophyDropdown(discord.ui.Select):
    def __init__(self):
        opts = [discord.SelectOption(label="Artisan / Premium", value="Artisan"),
                discord.SelectOption(label="Mass Market", value="Mass Market")]
        super().__init__(placeholder="Production Philosophy...", options=opts)
    async def callback(self, i: discord.Interaction):
        with get_db_cursor() as c:
            c.execute("UPDATE businesses SET philosophy = ? WHERE user_id = ?", (self.values[0], i.user.id))
        await i.response.send_message(f"<a:wt_toroexclaim:1480581004317036624> Philosophy set to {self.values[0]}.", ephemeral=False)

class HireSpecialistDropdown(discord.ui.Select):
    def __init__(self):
        opts = [
            discord.SelectOption(label="Lead Engineer (A$ 35k)", value="Engineer"),
            discord.SelectOption(label="Quality Auditor (A$ 35k)", value="Auditor"),
            discord.SelectOption(label="Sales Shark (A$ 35k)", value="Shark"),
            discord.SelectOption(label="Logistics Intern (A$ 35k)", value="Logistics")
        ]
        super().__init__(placeholder="Hire Specialist...", options=opts)
    async def callback(self, i: discord.Interaction):
        with get_db_cursor() as c:
            c.execute("SELECT capital, hq_level FROM businesses WHERE user_id = ?", (i.user.id,))
            biz = c.fetchone()
            c.execute("SELECT COUNT(id) FROM employees WHERE user_id = ?", (i.user.id,))
            cost_per = get_hire_cost(c, i.user.id, "specialist")
            if biz[0] < cost_per:
                return await i.response.send_message(f"<a:wt_torocryflail:1480580960566378711> Not enough capital. Need A$ {cost_per:,}.", ephemeral=True)
            if not atomic_business_update(c, i.user.id, -cost_per):
                return await i.response.send_message("❌ Balance updated concurrently.", ephemeral=True)
            c.execute("INSERT INTO employees (user_id, name, salary, morale, specialization) VALUES (?, ?, ?, 100, ?)",         
                (i.user.id, random.choice(NAMES), SPECIALIST_MIN_WAGE, self.values[0]))
        await i.response.send_message(f"<a:wt_toroexclaim:1480581004317036624> {self.values[0]} hired.", ephemeral=True)

class FireEmployeeDropdown(discord.ui.Select):
    def __init__(self, user_id):
        self.user_id = user_id
        with get_db_cursor() as c:
            c.execute("SELECT id, name, salary FROM employees WHERE user_id = ?", (user_id,))
            emps = c.fetchall()
        opts = [discord.SelectOption(label=f"Fire {n}", description=f"A$ {s:,}", value=str(eid)) for eid,n,s in emps[:25]]
        if not opts: opts.append(discord.SelectOption(label="No employees", value="none"))
        super().__init__(placeholder="Terminate staff...", options=opts)
    async def callback(self, i: discord.Interaction):
        if self.values[0] == "none": return
        with get_db_cursor() as c:
            c.execute("DELETE FROM employees WHERE id = ?", (int(self.values[0]),))
        await i.response.send_message("<a:wt_torosoul:1480580991503306865> Employee has been fired! Careful so they don't hunt you down..", ephemeral=True)

class StartupModal(discord.ui.Modal, title='Incorporate New Business'):
    b_name = discord.ui.TextInput(label='Company Name', min_length=3, max_length=30)
    
    def __init__(self, use_loan: bool):
        super().__init__()
        self.use_loan = use_loan

    async def on_submit(self, i: discord.Interaction):
        with get_eco_cursor() as c_eco:
            bal = c_eco.execute("SELECT balance FROM wallets WHERE user_id = ?", (i.user.id,)).fetchone()
            if not self.use_loan:
                if not bal or bal[0] < 500_000:
                    return await i.response.send_message("<a:wt_torono:1480580892706603018> You need at least <:athenacoin:1503804322280902767> A$ 500,000 to start a business.", ephemeral=True)
                c_eco.execute("UPDATE wallets SET balance = balance - 500000 WHERE user_id = ?", (i.user.id,))
                capital, loan, inst = 500_000, 0, 0
            else:
                capital, loan, inst = 500_000, 550_000, 10

            # ----- RE-ESTABLISHMENT FEE CHECK -----
            re_fee = 0
            row = c_eco.execute("SELECT last_large_withdrawal FROM user_flags WHERE user_id = ?", (i.user.id,)).fetchone()
            if row and row[0] and (time.time() - row[0]) < 7 * 86400:
                re_fee = 500_000
                bal_row = c_eco.execute("SELECT balance FROM wallets WHERE user_id = ?", (i.user.id,)).fetchone()
                if bal_row and bal_row[0] >= re_fee:
                    atomic_eco_balance_update(c_eco, i.user.id, -re_fee)
                    c_eco.execute("INSERT INTO transactions (user_id, amount, type, description) VALUES (?, ?, ?, ?)",
                                  (i.user.id, -re_fee, "FEE", "Re-establishment fee for starting new business after large withdrawal"))
                else:
                    await i.response.send_message(f"⚠️ You have a re-establishment fee of A$ {re_fee:,} pending due to a recent large withdrawal, but your wallet balance is insufficient. Please deposit funds.", ephemeral=True)
                    return

        with get_db_cursor() as c:
            c.execute("INSERT INTO businesses (user_id, name, capital, loan_balance, installments_left, reputation) VALUES (?, ?, ?, ?, ?, 100)",
                      (i.user.id, self.b_name.value, capital, loan, inst))
            if re_fee:
                log_business_event(c, i.user.id, "REESTABLISHMENT_FEE", f"Deducted A$ {re_fee:,} for restarting after large withdrawal")

        msg = f"<a:wt_toroleaf:1480580940785913967> {self.b_name.value} incorporated! Goodluck on your journey, make sure to read the guide."
        if re_fee:
            msg += f"\n\n⚠️ A re-establishment fee of **A$ {re_fee:,}** was deducted from your wallet because you recently withdrew a large sum before starting a new business."
        await i.response.send_message(msg, ephemeral=True)

class VPTitleDropdown(discord.ui.Select):
    def __init__(self, vp_user):
        self.vp_user = vp_user
        opts = [discord.SelectOption(label=t, value=t) for t in ["Chief Operating Officer (COO)", "Chief Financial Officer (CFO)", "Chief Marketing Officer (CMO)", "Vice President (VP)"]]
        super().__init__(placeholder="Select title...", options=opts)
    async def callback(self, i: discord.Interaction):
        with get_db_cursor() as c:
            c.execute("UPDATE businesses SET vp_id = ?, vp_title = ? WHERE user_id = ?", (self.vp_user.id, self.values[0], i.user.id))
        await i.response.send_message(f"Congrats! <a:wt_toroexclaim:1480581004317036624> {self.vp_user.name} has been appointed as {self.values[0]}.", ephemeral=False)

# ==========================================
# 📊 NEW: EARNINGS CALL VIEW (Fixed Crash)
# ==========================================
class EarningsCallView(discord.ui.View):
    def __init__(self, user_id: int, quarter: int):
        super().__init__(timeout=86400)
        self.user_id = user_id
        self.quarter = quarter

    async def interaction_check(self, i: discord.Interaction) -> bool:
        if i.user.id != self.user_id:
            await i.response.send_message("<a:wt_torono:1480580892706603018> You are NOT the CEO of this company, stay away.", ephemeral=False)
            return False
        return True

    @discord.ui.button(label="Highlight Growth (+Demand)", style=discord.ButtonStyle.secondary, emoji="<:stockup_athena:1503776772850712616>")
    async def opt1(self, i: discord.Interaction, btn: discord.ui.Button):
        with get_db_cursor() as c:
            c.execute("UPDATE businesses SET demand_boost = demand_boost + 0.15 WHERE user_id = ?", (self.user_id,))
        for child in self.children: child.disabled = True
        await i.response.edit_message(content="<a:wt_toroexclaim:1480581004317036624> Investors loved the growth strategy! Demand for your products will be boosted.", view=self)

    @discord.ui.button(label="Focus on Margins (+Capital)", style=discord.ButtonStyle.secondary, emoji="<:athenacoin:1503804322280902767>")
    async def opt2(self, i: discord.Interaction, btn: discord.ui.Button):
        with get_db_cursor() as c:
            c.execute("UPDATE businesses SET capital = capital + 150000 WHERE user_id = ?", (self.user_id,))
        for child in self.children: child.disabled = True
        await i.response.edit_message(content="<a:wt_toroexclaim:1480581004317036624> Investors appreciated the frugal approach! They have injected A$ 150,000 into your business.", view=self)

    @discord.ui.button(label="Promise Returns (+Reputation)", style=discord.ButtonStyle.secondary, emoji="<:s_white2:1382052523166142486>")
    async def opt3(self, i: discord.Interaction, btn: discord.ui.Button):
        with get_db_cursor() as c:
            c.execute("UPDATE businesses SET reputation = MIN(100, reputation + 15) WHERE user_id = ?", (self.user_id,))
        for child in self.children: child.disabled = True
        await i.response.edit_message(content="<a:wt_toroexclaim:1480581004317036624> Investors trust your vision. Reputation has skyrocketed!", view=self)


class PayoutModal(discord.ui.Modal, title='CEO Capital Withdrawal'):
    amount = discord.ui.TextInput(label='Amount to Withdraw (A$)', placeholder='e.g., 50000')
    async def on_submit(self, i: discord.Interaction):
        try:
            amt = int(self.amount.value)
            if amt <= 0: raise ValueError
            with get_db_cursor() as c:
                biz = c.execute("SELECT capital FROM businesses WHERE user_id = ?", (i.user.id,)).fetchone()
                if not biz or biz[0] < amt:
                    return await i.response.send_message("<a:wt_torono:1480580892706603018> Insufficient corporate capital.", ephemeral=True)
                c.execute("UPDATE businesses SET capital = capital - ? WHERE user_id = ?", (amt, i.user.id))
            
            with get_eco_cursor() as c_eco:
                bal_row = c_eco.execute("SELECT balance FROM wallets WHERE user_id = ?", (i.user.id,)).fetchone()
                if not bal_row:
                    return await i.response.send_message("❌ No wallet found.", ephemeral=True)
                if bal_row[0] < 0:
                    return await i.response.send_message("❌ Your wallet is in debt. Clear your debt before withdrawing.", ephemeral=True)
                atomic_eco_balance_update(c_eco, i.user.id, amt)
                
            await i.response.send_message(f"<a:wt_toroexclaim:1480581004317036624> Successfully wired A$ {amt:,} to your personal account.", ephemeral=False)
        except ValueError:
            await i.response.send_message("<a:wt_torono:1480580892706603018> Invalid amount.", ephemeral=True)
            # Track large withdrawals for re‑establishment fee
            if amt >= 10_000_000:
                with get_eco_cursor() as eco:
                    eco.execute("INSERT OR REPLACE INTO user_flags (user_id, last_large_withdrawal) VALUES (?, ?)",
                                (i.user.id, time.time()))

# ----- sub-views -----
class BusinessGuideView(discord.ui.View):
    def __init__(self, embeds):
        super().__init__(timeout=300)
        self.embeds = embeds
        self.current_page = 0
        self.update_buttons()

    def update_buttons(self):
        self.prev_btn.disabled = self.current_page == 0
        self.next_btn.disabled = self.current_page == len(self.embeds) - 1

    @discord.ui.button(label="Previous", style=discord.ButtonStyle.secondary, emoji="<:w_arrowleft:1272235695137751162>")
    async def prev_btn(self, i: discord.Interaction, btn: discord.ui.Button):
        self.current_page -= 1
        self.update_buttons()
        await i.response.edit_message(embed=self.embeds[self.current_page], view=self)

    @discord.ui.button(label="Next", style=discord.ButtonStyle.secondary, emoji="<:w_arrowright:1272235711721898005>")
    async def next_btn(self, i: discord.Interaction, btn: discord.ui.Button):
        self.current_page += 1
        self.update_buttons()
        await i.response.edit_message(embed=self.embeds[self.current_page], view=self)


class StaffPaginator(discord.ui.View):
    def __init__(self, user_id: int, employees: list):
        super().__init__(timeout=180)
        self.user_id = user_id
        self.employees = employees
        self.items_per_page = 10
        self.current_page = 0
        self.max_pages = (len(employees) + self.items_per_page - 1) // self.items_per_page
        self.update_buttons()

    def update_buttons(self):
        self.prev_btn.disabled = self.current_page == 0
        self.next_btn.disabled = self.current_page >= self.max_pages - 1

    def get_embed(self):
        start = self.current_page * self.items_per_page
        end = start + self.items_per_page
        page_employees = self.employees[start:end]

        embed = discord.Embed(title="꒰ა Human Resources  ⸝⸝", color=0xffffff)
        if not page_employees:
            embed.description = "No employees found."
            return embed

        desc = ""
        for name, salary, morale, spec in page_employees:
            morale_emoji = "<a:wt_torohearts:1480580920737005672>" if morale >= 70 else "<a:2b_torono:1511037719956947016>" if morale >= 40 else "<a:wt_torosob:1480580873782034483>"
            desc += f"• **{name}** ({spec}) – A$ {salary:,} | {morale_emoji} {morale}% morale\n"
        embed.description = desc
        embed.set_footer(text=f"Page {self.current_page + 1}/{self.max_pages}")
        return embed

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("<a:wt_torono:1480580892706603018> Access Denied. This terminal does not belong to you.", ephemeral=True)
            return 
        update_activity(interaction.user.id)
        return True

    @discord.ui.button(label="Previous", emoji="<:w_arrowleft:1272235695137751162>", style=discord.ButtonStyle.secondary)
    async def prev_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page -= 1
        self.update_buttons()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    @discord.ui.button(label="Next", emoji="<:w_arrowright:1272235711721898005>", style=discord.ButtonStyle.secondary)
    async def next_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page += 1
        self.update_buttons()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)


class ProductPerformanceView(discord.ui.View):
    def __init__(self, user_id): 
        super().__init__(timeout=180)
        self.user_id = user_id
        self.items_per_page = 5
        self.current_page = 0
        self.products = []
        self.load_products()

    def load_products(self):
        with get_db_cursor() as c:
            biz_row = c.execute("SELECT tech_level, sector FROM businesses WHERE user_id = ?", (self.user_id,)).fetchone()
            self.tech = biz_row[0] if biz_row else 0
            self.sector = biz_row[1] if biz_row else "Tech"
            self.cost_red = 0.10 if self.tech >= 20 else 0.0
            self.products = c.execute(
                "SELECT name, unit_price, cost_to_make, lifetime_revenue, quality_tier, production_target, lifetime_sold, last_cycle_sold, last_cycle_revenue FROM business_products WHERE user_id = ?",
                (self.user_id,)
            ).fetchall()
        self.max_pages = (len(self.products) + self.items_per_page - 1) // self.items_per_page if self.products else 1
        self.update_buttons()

    def update_buttons(self):
        self.prev_btn.disabled = self.current_page == 0
        self.next_btn.disabled = self.current_page >= self.max_pages - 1

    def get_embed(self):
        embed = discord.Embed(title="꒰ა Product Analytics ⸝⸝", color=0xffffff)
        if not self.products:
            embed.description = "No products launched."
            return embed

        start = self.current_page * self.items_per_page
        end = start + self.items_per_page
        page_products = self.products[start:end]

        desc = ""
        for name, price, cost, rev, tier, target, sold, last_sold, last_rev in page_products:
            tier_data = QUALITY_TIERS.get(tier, QUALITY_TIERS['Standard'])
            adj_price = int(price * tier_data['price_mult'])
            adj_cost = int(cost * tier_data['cost_mult'] * (1 - self.cost_red))
            global_sector_base = SECTOR_BASE_COSTS.get(self.sector, 300)
            margin = adj_price - adj_cost
            margin_ratio = price / max(1, global_sector_base)
            if margin_ratio > 8.0: health = "⬛ Total Boycott"
            elif margin_ratio > 4.0: health = "🟥 Severe Overpricing"
            elif margin_ratio > 2.5: health = "🟧 High Price"
            elif margin_ratio > 1.5: health = "🟨 Moderate Price"
            else: health = "🟩 Optimal Pricing"

            desc += (
                f"<a:wt_torosilly:1480580853720551637> **{name}** (`{tier}`)\n"
                f"└ **Sell Price:** A$ {price:,} | **Base Cost:** A$ {cost:,}\n"
                f"└ **Adj. Margin:** A$ {margin:,} *(True Ratio: {margin_ratio:.2f}x)*\n"
                f"└ **Target:** {target:,}/day | **Lifetime Sold:** {sold:,} units\n"
                f"└ **Last Cycle:** {last_sold:,} units sold | A$ {last_rev:,} revenue\n"
                f"└ **Total Rev:** A$ {rev:,}\n"
                f"└ **Market Status:** {health}\n\n"
            )
        embed.description = desc
        embed.set_footer(text=f"Page {self.current_page + 1}/{self.max_pages}")
        return embed

    async def interaction_check(self, i: discord.Interaction) -> bool:
        if i.user.id != self.user_id:
            await i.response.send_message("<a:wt_torono:1480580892706603018> Access Denied. This terminal does not belong to you.", ephemeral=True)
            return False
        update_activity(i.user.id)
        return True

    @discord.ui.button(label="Previous", emoji="<:w_arrowleft:1272235695137751162>", style=discord.ButtonStyle.secondary)
    async def prev_btn(self, i: discord.Interaction, btn: discord.ui.Button):
        self.current_page -= 1
        self.update_buttons()
        await i.response.edit_message(embed=self.get_embed(), view=self)

    @discord.ui.button(label="Next", emoji="<:w_arrowright:1272235711721898005>", style=discord.ButtonStyle.secondary)
    async def next_btn(self, i: discord.Interaction, btn: discord.ui.Button):
        self.current_page += 1
        self.update_buttons()
        await i.response.edit_message(embed=self.get_embed(), view=self)

    @discord.ui.button(label="Refresh", style=discord.ButtonStyle.secondary)
    async def refresh(self, i: discord.Interaction, btn):
        self.load_products()
        self.current_page = 0
        self.update_buttons()
        await i.response.edit_message(embed=self.get_embed(), view=self)


class DepartmentSwitcher(discord.ui.Select):
    def __init__(self, current_user_id: int):
        self.current_user_id = current_user_id
        options = [
            discord.SelectOption(label="Human Resources", value="hr", emoji="<:i_ghouls:1426522093620826112>"),
            discord.SelectOption(label="Cybersecurity", value="cyber", emoji="<:i_lucifer:1426518321544564798>"),
            discord.SelectOption(label="Sales & Partnerships", value="sales", emoji="<:i_satan:1426518223133737000>")
        ]
        super().__init__(placeholder="Switch department...", options=options)

    async def callback(self, i: discord.Interaction):
        if i.user.id != self.current_user_id:
            return await i.response.send_message("Sybau this menu is not for you", ephemeral=True)
        if self.values[0] == "hr":
            view = HRView(self.current_user_id)
            await i.response.edit_message(embed=view.get_embed(), view=view)
        elif self.values[0] == "cyber":
            view = CybersecurityView(self.current_user_id)
            embed = await view.get_embed()
            await i.response.edit_message(embed=embed, view=view)
        elif self.values[0] == "sales":
            view = SalesView(self.current_user_id)
            embed = await view.get_embed()
            await i.response.edit_message(embed=embed, view=view)


class HRView(discord.ui.View):
    def __init__(self, user_id: int):
        super().__init__(timeout=180)
        self.user_id = user_id
        # Fetch all employees once
        with get_db_cursor() as c:
            self.employees = c.execute(
                "SELECT name, salary, morale, specialization FROM employees WHERE user_id = ?",
                (user_id,)
            ).fetchall()
        self.items_per_page = 10
        self.current_page = 0
        self.max_pages = (len(self.employees) + self.items_per_page - 1) // self.items_per_page if self.employees else 1
        self.add_item(DepartmentSwitcher(user_id))
        
        # Add the dropdowns
        self.add_item(FireEmployeeDropdown(user_id))
        self.add_item(HireSpecialistDropdown())
        self.update_buttons()

    def update_buttons(self):
        # Enable/disable prev/next based on current page
        for child in self.children:
            if isinstance(child, discord.ui.Button) and child.custom_id in ("hr_prev", "hr_next"):
                if child.custom_id == "hr_prev":
                    child.disabled = self.current_page == 0
                elif child.custom_id == "hr_next":
                    child.disabled = self.current_page >= self.max_pages - 1

    def get_embed(self):
        embed = discord.Embed(title="꒰ა Human Resources ⸝⸝", color=0xffffff)
        if not self.employees:
            embed.description = "No employees."
            return embed

        start = self.current_page * self.items_per_page
        end = start + self.items_per_page
        page_employees = self.employees[start:end]

        desc = ""
        for name, salary, morale, spec in page_employees:
            morale_emoji = "<a:wt_torohearts:1480580920737005672>" if morale >= 70 else "<a:2b_torono:1511037719956947016>" if morale >= 40 else "<a:wt_torosob:1480580873782034483>"
            desc += f"• **{name}** ({spec}) – A$ {salary:,} | {morale_emoji} {morale}% morale\n"
        embed.description = desc
        embed.set_footer(text=f"Page {self.current_page + 1}/{self.max_pages}")
        return embed

    async def interaction_check(self, i: discord.Interaction) -> bool:
         
        if i.user.id != self.user_id:
            await i.response.send_message("<a:wt_torono:1480580892706603018> Access Denied. This terminal does not belong to you.", ephemeral=True)
            return False
        update_activity(i.user.id)
        return True

    @discord.ui.button(label="Previous", emoji="<:w_arrowleft:1272235695137751162>", style=discord.ButtonStyle.secondary, custom_id="hr_prev")
    async def prev_btn(self, i: discord.Interaction, btn: discord.ui.Button):
        self.current_page -= 1
        self.update_buttons()
        await i.response.edit_message(embed=self.get_embed(), view=self)

    @discord.ui.button(label="Next", emoji="<:w_arrowright:1272235711721898005>", style=discord.ButtonStyle.secondary, custom_id="hr_next")
    async def next_btn(self, i: discord.Interaction, btn: discord.ui.Button):
        self.current_page += 1
        self.update_buttons()
        await i.response.edit_message(embed=self.get_embed(), view=self)

    @discord.ui.button(label="Hire Staff", style=discord.ButtonStyle.secondary, row=2)
    async def hire(self, i: discord.Interaction, btn):
        with get_db_cursor() as c:
            biz = c.execute("SELECT capital, hq_level FROM businesses WHERE user_id = ?", (i.user.id,)).fetchone()
            emps = c.execute("SELECT COUNT(id) FROM employees WHERE user_id = ?", (i.user.id,)).fetchone()[0]
            cost_per = get_hire_cost(c, i.user.id, "regular")
            if biz[0] < cost_per:
                return await i.response.send_message(f"<a:wt_torono:1480580892706603018> Not enough capital. Need A$ {cost_per:,}.", ephemeral=True)
            if emps >= HQ_LEVELS[biz[1]]["max_emp"]:
                return await i.response.send_message("<a:wt_torono:1480580892706603018> Your HQ is full! Upgrade to a bigger campus.", ephemeral=True)
            if not atomic_business_update(c, i.user.id, -cost_per):
                return await i.response.send_message("❌ Balance updated concurrently. Please try again.", ephemeral=True)
            c.execute("INSERT INTO employees (user_id, name, salary, morale, specialization) VALUES (?, ?, 1500, 80, 'None')",
                      (i.user.id, random.choice(NAMES)))
        # Refresh employee list
        with get_db_cursor() as c:
            self.employees = c.execute("SELECT name, salary, morale, specialization FROM employees WHERE user_id = ?", (i.user.id,)).fetchall()
        self.max_pages = (len(self.employees) + self.items_per_page - 1) // self.items_per_page if self.employees else 1
        self.update_buttons()
        await i.response.edit_message(embed=self.get_embed(), view=self)

    @discord.ui.button(label="Host Event (A$ 5k)", style=discord.ButtonStyle.secondary, row=2)
    async def morale(self, i: discord.Interaction, btn):
        with get_db_cursor() as c:
            cap = c.execute("SELECT capital FROM businesses WHERE user_id = ?", (i.user.id,)).fetchone()[0]
            if cap < 5000:
                return await i.response.send_message("<a:wt_torono:1480580892706603018> Not enough capital.", ephemeral=True)
            if not atomic_business_update(c, i.user.id, -5000):
                return await i.response.send_message("❌ Balance updated concurrently. Please try again.", ephemeral=True)
            c.execute("UPDATE employees SET morale = MIN(100, morale + 25) WHERE user_id = ?", (i.user.id,))
        # Refresh employee list
        with get_db_cursor() as c:
            self.employees = c.execute("SELECT name, salary, morale, specialization FROM employees WHERE user_id = ?", (i.user.id,)).fetchall()
        await i.response.edit_message(embed=self.get_embed(), view=self)

    @discord.ui.button(label="Mass Actions", style=discord.ButtonStyle.secondary, row=2)
    async def mass_action(self, i: discord.Interaction, btn: discord.ui.Button):
        await i.response.send_message("Select action from the dropdown below:", view=MassActionView(i.user.id), ephemeral=True)

    @discord.ui.button(label="Salary Edit", style=discord.ButtonStyle.secondary, row=2)
    async def mass_salary(self, i: discord.Interaction, btn):
        try:
            await i.response.send_modal(MassSalaryModal(self.user_id))
        except Exception as e:
            await i.response.send_message(f"Error opening modal: {e}", ephemeral=True)


class SalesView(discord.ui.View):
    def __init__(self, user_id: int):
        super().__init__(timeout=None)
        self.user_id = user_id
        self.add_item(DepartmentSwitcher(user_id))

    async def get_embed(self) -> discord.Embed:
        with get_db_cursor() as c:
            c.execute("SELECT tier, end_time FROM active_partnerships WHERE user_id = ?", (self.user_id,))
            active = c.fetchone()
            c.execute("SELECT capital FROM businesses WHERE user_id = ?", (self.user_id,))
            capital = c.fetchone()[0]

        embed = discord.Embed(title="꒰ა Sales & Partnerships ⸝⸝", color=0xffffff)
        if active:
            tier, end_time = active
            remaining = max(0, end_time - time.time())
            days = int(remaining // 86400)
            hours = int((remaining % 86400) // 3600)
            embed.add_field(name="Active Partnership", value=f"**{tier.capitalize()}** – {days}d {hours}h remaining", inline=False)
        else:
            embed.description = "No active partnership. Choose a company below to boost reputation, demand, and stock price.\n"

        tiers_info = {
            "Temu": {"cost": 5_000_000, "rep": 10, "demand": 10, "stock": 5, "duration": 5},
            "Xiaomi": {"cost": 15_000_000, "rep": 20, "demand": 20, "stock": 10, "duration": 10},
            "Apple": {"cost": 50_000_000, "rep": 35, "demand": 35, "stock": 20, "duration": 13},
            "Google": {"cost": 100_000_000, "rep": 50, "demand": 50, "stock": 40, "duration": 18}
        }
        cost_mult = max(1.0, capital / 150_000_000)
        desc = ""
        for tier, info in tiers_info.items():
            adjusted_cost = int(info["cost"] * cost_mult)
            desc += f"<:w_swan:1445531829628178442> **{tier}**\n"
            desc += f"└ <:athenacoin:1503804322280902767> Cost: A$ {adjusted_cost:,}\n"
            desc += f"└ <:s_white2:1382052523166142486> +{info['rep']}% Rep | +{info['demand']}% Demand | +{info['stock']}% Stock\n"
            desc += f"└ <:w_moon:1412477166666514493> Duration: {info['duration']} days\n\n"
        embed.description = (embed.description or "") + desc
        embed.set_image(url=PARTNER_BANNER_URL)
        return embed

    @discord.ui.button(label="Buy Partnership", style=discord.ButtonStyle.success, row=0)
    async def buy_partnership(self, i: discord.Interaction, btn):
        view = PartnershipButtonsView(self.user_id)
        await i.response.send_message("Select partnership tier:", view=view, ephemeral=True)

class PartnershipButtonsView(discord.ui.View):
    def __init__(self, user_id: int):
        super().__init__(timeout=6000)
        self.user_id = user_id

    @discord.ui.button(label="Temu", style=discord.ButtonStyle.secondary, emoji="<:w_moth2:1380799242515386368>")
    async def temu_btn(self, i: discord.Interaction, btn: discord.ui.Button):
        await self.process_tier(i, "temu")

    @discord.ui.button(label="Xiaomi", style=discord.ButtonStyle.secondary, emoji="<:w_moth:1380579893577777264>")
    async def xiaomi_btn(self, i: discord.Interaction, btn: discord.ui.Button):
        await self.process_tier(i, "xiaomi")

    @discord.ui.button(label="Apple", style=discord.ButtonStyle.secondary, emoji="<:w_moth2:1380799242515386368>")
    async def apple_btn(self, i: discord.Interaction, btn: discord.ui.Button):
        await self.process_tier(i, "apple")

    @discord.ui.button(label="Google", style=discord.ButtonStyle.secondary, emoji="<:w_moth:1380579893577777264>")
    async def google_btn(self, i: discord.Interaction, btn: discord.ui.Button):
        await self.process_tier(i, "google")

    async def process_tier(self, i: discord.Interaction, tier: str):
        await i.response.defer(ephemeral=True)
        with get_db_cursor() as c:
            if c.execute("SELECT 1 FROM active_partnerships WHERE user_id = ?", (self.user_id,)).fetchone():
                return await i.followup.send("You already have an active partnership. Wait for it to expire before buying another.", ephemeral=True)
            c.execute("SELECT capital FROM businesses WHERE user_id = ?", (self.user_id,))
            capital = c.fetchone()[0]
            cost_mult = max(1.0, capital / 150_000_000)
            base_costs = {"temu": 5_000_000, "xiaomi": 15_000_000, "apple": 50_000_000, "google": 100_000_000}
            cost = int(base_costs[tier] * cost_mult)
            if capital < cost:
                return await i.followup.send(f"Insufficient capital (need A$ {cost:,}).", ephemeral=True)
            if not atomic_business_update(c, self.user_id, -cost):
                return await i.followup.send("Balance updated concurrently. Please try again.", ephemeral=True)
            # Call the global function
            apply_partnership_effects(self.user_id, tier)
            log_business_event(c, self.user_id, "PARTNERSHIP", f"Bought {tier} partnership for A$ {cost:,}")
        await i.followup.send(f"{tier.capitalize()} partnership activated! Your reputation, demand, and stock price have been boosted.", ephemeral=False)
        self.stop()

class CybersecurityView(discord.ui.View):
    def __init__(self, user_id: int):
        super().__init__(timeout=None)
        self.user_id = user_id

        self.add_item(DepartmentSwitcher(user_id))

        self.hire_offensive_btn = discord.ui.Button(
            label="Hire Offensive (A$50k)", style=discord.ButtonStyle.secondary, row=1
        )
        self.hire_offensive_btn.callback = self.hire_offensive_callback
        self.add_item(self.hire_offensive_btn)

        self.hire_defensive_btn = discord.ui.Button(
            label="Hire Defensive (A$50k)", style=discord.ButtonStyle.secondary, row=1
        )
        self.hire_defensive_btn.callback = self.hire_defensive_callback
        self.add_item(self.hire_defensive_btn)

        self.fire_dropdown = discord.ui.Select(
            placeholder="Fire Specialist", row=2
        )
        self.fire_dropdown.callback = self.fire_dropdown_callback
        self.add_item(self.fire_dropdown)

        # Mass Hire button
        self.mass_hire_btn = discord.ui.Button(
                label="Mass Hire Cyber", style=discord.ButtonStyle.secondary, row=3
        )
        self.mass_hire_btn.callback = self.mass_hire_callback
        self.add_item(self.mass_hire_btn)

        # Mass Fire button
        self.mass_fire_btn = discord.ui.Button(
                label="Mass Fire Cyber", style=discord.ButtonStyle.secondary, row=3
        )
        self.mass_fire_btn.callback = self.mass_fire_callback
        self.add_item(self.mass_fire_btn)

        # NEW BUTTONS
        self.attack_btn = discord.ui.Button(
            label="Launch Attack", style=discord.ButtonStyle.secondary, row=3
        )
        self.attack_btn.callback = self.attack_callback
        self.add_item(self.attack_btn)

        self.logs_btn = discord.ui.Button(
            label="Attack Logs", style=discord.ButtonStyle.secondary, row=3
        )
        self.logs_btn.callback = self.logs_callback
        self.add_item(self.logs_btn)

        self.update_fire_dropdown()

    def update_fire_dropdown(self):
        options = []
        with get_db_cursor() as c:
            c.execute("""
                SELECT id, specialist_type, hired_at
                FROM security_specialists
                WHERE user_id = ?
                ORDER BY hired_at DESC
                LIMIT 25
            """, (self.user_id,))
            specialists = c.fetchall()
        for sid, stype, hired in specialists:
            date = datetime.fromtimestamp(hired).strftime("%Y-%m-%d")
            options.append(
                discord.SelectOption(
                    label=f"{stype.capitalize()} specialist",
                    description=f"Hired {date} | Wage: A$9k",
                    value=str(sid)
                )
            )
        if not options:
            options.append(discord.SelectOption(label="No specialists", value="none", default=True))
        self.fire_dropdown.options = options
        self.fire_dropdown.disabled = (len(options) == 1 and options[0].value == "none")

    async def hire_offensive_callback(self, i: discord.Interaction):
        await self._hire_specialist(i, "offensive")

    async def hire_defensive_callback(self, i: discord.Interaction):
        await self._hire_specialist(i, "defensive")

    async def _hire_specialist(self, i: discord.Interaction, spec_type: str):
        await i.response.defer(ephemeral=True)
        with get_db_cursor() as c:
            current = get_security_specialists_count(c, self.user_id)
            max_spec = get_max_specialists(c, self.user_id)
            if current >= max_spec:
                return await i.followup.send(f"Max specialists reached ({max_spec}).", ephemeral=True)
            cost_per = get_hire_cost(c, self.user_id, "cyber")
            cap_row = c.execute("SELECT capital FROM businesses WHERE user_id = ?", (self.user_id,)).fetchone()
            if cap_row[0] < cost_per:
                return await i.followup.send(f"Insufficient capital (need A$ {cost_per:,}).", ephemeral=True)
            success = False
            for _ in range(3):
                if atomic_business_update(c, self.user_id, -cost_per):
                    success = True
                    break
                await asyncio.sleep(0.1)
            if not success:
                return await i.followup.send("Transaction conflict, please try again.", ephemeral=True)
            c.execute("INSERT INTO security_specialists (user_id, specialist_type, hired_at, wage) VALUES (?, ?, ?, ?)",
                      (self.user_id, spec_type, time.time(), SECURITY_SPECIALIST_WAGE))
            log_business_event(c, self.user_id, "HIRE_SPECIALIST", f"Hired {spec_type} specialist")
        self.update_fire_dropdown()
        embed = await self.get_embed()
        await i.edit_original_response(embed=embed, view=self)
        await i.followup.send(f"{spec_type.capitalize()} specialist hired for A$ 50,000.", ephemeral=False)

    async def attack_callback(self, i: discord.Interaction):
        await i.response.send_modal(AttackModal(self.user_id))

    async def mass_hire_callback(self, i: discord.Interaction):
        await i.response.send_modal(MassCyberSpecialistModal(self.user_id, self))

    async def mass_fire_callback(self, i: discord.Interaction):
        await i.response.send_modal(MassCyberFireModal(self.user_id, self))

    async def logs_callback(self, i: discord.Interaction):
        await self.attack_logs(i)

    async def attack_logs(self, i: discord.Interaction):
        with get_db_cursor() as c:
            c.execute("""
                SELECT attacker_id, target_id, attack_type, success, amount, employees_poached, timestamp
                FROM attack_logs
                WHERE attacker_id = ? OR target_id = ?
                ORDER BY timestamp DESC
            """, (self.user_id, self.user_id))
            logs = c.fetchall()

        if not logs:
            return await i.response.send_message("No attack history found.", ephemeral=True)

        formatted = []
        for att, tgt, atype, suc, amt, emp_json, ts in logs:
            direction = "→" if att == self.user_id else "←"
            timestamp = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
            if suc:
                if atype == "capital":
                    detail = f"stole A$ {amt:,}"
                elif atype == "poach":
                    emp_list = json.loads(emp_json) if emp_json else []
                    if emp_list:
                        names = ", ".join([e["name"] for e in emp_list])
                        if len(names) > 100:
                            names = names[:97] + "..."
                        detail = f"poached {len(emp_list)} employees: {names}"
                    else:
                        detail = "poached employees (none found)"
                elif atype == "sabotage":
                    detail = f"reduced reputation by {amt}%"
                else:
                    detail = ""
                formatted.append(f"🟢 {timestamp} **{atype.upper()}** {direction} – {detail}")
            else:
                formatted.append(f"🔴 {timestamp} **{atype.upper()}** {direction} – Failed")

        # Pagination view
        class AttackLogsPaginator(discord.ui.View):
            def __init__(self, entries, user_id):
                super().__init__(timeout=120)
                self.entries = entries
                self.user_id = user_id
                self.page = 0
                self.items_per_page = 10
                self.max_page = (len(entries) + self.items_per_page - 1) // self.items_per_page
                self.update_buttons()

            def update_buttons(self):
                self.prev.disabled = (self.page == 0)
                self.next.disabled = (self.page >= self.max_page - 1)

            def get_embed(self):
                start = self.page * self.items_per_page
                end = start + self.items_per_page
                page_entries = self.entries[start:end]
                embed = discord.Embed(title="꒰ა Attack Logs ⸝⸝", color=0xffffff)
                description = "\n\n".join(page_entries)
                # Discord limit is 4096, leave room for footer
                if len(description) > 4000:
                    description = description[:3997] + "..."
                embed.description = description if description else "No logs on this page."
                embed.set_footer(text=f"Page {self.page + 1}/{self.max_page}")
                return embed

            @discord.ui.button(label="Previous", style=discord.ButtonStyle.secondary, emoji="<:w_arrowleft:1272235695137751162>")
            async def prev(self, inter: discord.Interaction, button: discord.ui.Button):
                self.page -= 1
                self.update_buttons()
                await inter.response.edit_message(embed=self.get_embed(), view=self)

            @discord.ui.button(label="Next", style=discord.ButtonStyle.secondary, emoji="<:w_arrowright:1272235711721898005>")
            async def next(self, inter: discord.Interaction, button: discord.ui.Button):
                self.page += 1
                self.update_buttons()
                await inter.response.edit_message(embed=self.get_embed(), view=self)

        view = AttackLogsPaginator(formatted, self.user_id)
        await i.response.send_message(embed=view.get_embed(), view=view, ephemeral=True)

    async def fire_dropdown_callback(self, i: discord.Interaction):
        selected = self.fire_dropdown.values
        if not selected or selected[0] == "none":
            return await i.response.send_message("No specialist selected.", ephemeral=True)
        spec_id = int(selected[0])
        view = ConfirmFireView(self.user_id, spec_id, self)
        await i.response.send_message("Are you sure you want to fire this specialist? They will be removed immediately.", view=view, ephemeral=True)

    async def get_embed(self) -> discord.Embed:
        with get_db_cursor() as c:
            offensive = get_security_specialists_count(c, self.user_id, 'offensive')
            defensive = get_security_specialists_count(c, self.user_id, 'defensive')
            max_spec = get_max_specialists(c, self.user_id)
            c.execute("SELECT COUNT(*) FROM attack_logs WHERE attacker_id = ? AND success = 1", (self.user_id,))
            attacks_won = c.fetchone()[0]
            c.execute("SELECT COUNT(*) FROM attack_logs WHERE attacker_id = ? AND success = 0", (self.user_id,))
            attacks_lost = c.fetchone()[0]
            c.execute("SELECT COUNT(*) FROM attack_logs WHERE target_id = ?", (self.user_id,))
            times_hacked = c.fetchone()[0]
            c.execute("SELECT last_attack_time FROM businesses WHERE user_id = ?", (self.user_id,))
            row = c.fetchone()
            last_attack = row[0] if row else 0
            cooldown_left = max(0, 21600 - (time.time() - last_attack)) if last_attack else 0

        embed = discord.Embed(title="꒰ა Cybersecurity Directorate ⸝⸝", color=0xffffff)
        embed.set_image(url=CYBER_BANNER_URL)
        embed.description = (
            f"<:w_knife:1375478992655876179> **Offensive Specialists:** {offensive} / {max_spec}\n"
            f"<:w_knife:1375478992655876179> **Defensive Specialists:** {defensive} / {max_spec}\n\n"
            f"<:w_flower2:1375477010226217072> **Attack Record:** {attacks_won} wins / {attacks_lost} losses\n"
            f"<:w_flowe1r:1375475305061552160> **Times Hacked:** {times_hacked}\n"
            f"<:w_flower2:1375477010226217072> **Attack Cooldown:** " + (
                f"{cooldown_left//3600}h {(cooldown_left%3600)//60}m remaining"
                if cooldown_left else "Ready To Launch"
            )
        )
        return embed

    async def interaction_check(self, i: discord.Interaction) -> bool:
        if i.user.id != self.user_id:
            await i.response.send_message("Access denied.", ephemeral=True)
            return False
        update_activity(i.user.id)
        return True


class ConfirmFireView(discord.ui.View):
    def __init__(self, user_id: int, spec_id: int, parent_view: CybersecurityView):
        super().__init__(timeout=30)
        self.user_id = user_id
        self.spec_id = spec_id
        self.parent_view = parent_view

    @discord.ui.button(label="Yes, Fire", style=discord.ButtonStyle.danger)
    async def confirm(self, i: discord.Interaction, button: discord.ui.Button):
        if i.user.id != self.user_id:
            return await i.response.send_message("Not your business.", ephemeral=True)
        with get_db_cursor() as c:
            c.execute("SELECT specialist_type FROM security_specialists WHERE id = ? AND user_id = ?", (self.spec_id, self.user_id))
            row = c.fetchone()
            if not row:
                return await i.response.send_message("Specialist already fired or not found.", ephemeral=True)
            spec_type = row[0]
            c.execute("DELETE FROM security_specialists WHERE id = ?", (self.spec_id,))
            log_business_event(c, self.user_id, "FIRE_SPECIALIST", f"Fired {spec_type} specialist")
        self.parent_view.update_fire_dropdown()
        embed = await self.parent_view.get_embed()
        await i.response.edit_message(embed=embed, view=self.parent_view)
        await i.followup.send(f"{spec_type.capitalize()} specialist fired.", ephemeral=False)
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, i: discord.Interaction, button: discord.ui.Button):
        await i.response.edit_message(content="Firing cancelled.", view=None, embed=None)
        self.stop()

class HireSpecialistTypeView(discord.ui.View):
    def __init__(self, user_id: int):
        super().__init__(timeout=600)
        self.user_id = user_id

    @discord.ui.button(label="Offensive", style=discord.ButtonStyle.primary, emoji="⚔️")
    async def offensive_btn(self, i: discord.Interaction, btn: discord.ui.Button):
        await self.hire_specialist(i, "offensive")

    @discord.ui.button(label="Defensive", style=discord.ButtonStyle.primary, emoji="🛡️")
    async def defensive_btn(self, i: discord.Interaction, btn: discord.ui.Button):
        await self.hire_specialist(i, "defensive")

    async def hire_specialist(self, i: discord.Interaction, spec_type: str):
        with get_db_cursor() as c:
            current = get_security_specialists_count(c, self.user_id)
            max_spec = get_max_specialists(c, self.user_id)
            if current >= max_spec:
                return await i.response.send_message(f"Max specialists reached ({max_spec}).", ephemeral=True)
            # Check capital
            c.execute("SELECT capital FROM businesses WHERE user_id = ?", (self.user_id,))
            cap = c.fetchone()[0]
            cost_per = get_hire_cost(c, self.user_id, "cyber")
            if cap < cost_per:
                return await i.response.send_message(f"Insufficient capital (need A$ {cost_per:,}).", ephemeral=True)
            if not atomic_business_update(c, self.user_id, -cost_per):
                return await i.response.send_message("Balance updated concurrently. Please try again.", ephemeral=True)
            c.execute("INSERT INTO security_specialists (user_id, specialist_type, hired_at) VALUES (?, ?, ?)",
                      (self.user_id, spec_type, time.time()))
            log_business_event(c, self.user_id, "HIRE_SPECIALIST", f"Hired {spec_type} specialist")
        await i.response.send_message(f"{spec_type.capitalize()} specialist hired for A$ {cost_per:,}.", ephemeral=False)
        self.stop()


class AttackModal(discord.ui.Modal, title="Corporate Cyber Attack"):
    target_id = discord.ui.TextInput(label="Target User ID", placeholder="e.g., 123456789", required=True)
    attack_type = discord.ui.TextInput(label="Attack Type", placeholder="capital, poach, sabotage", required=True)

    def __init__(self, user_id: int):
        super().__init__()
        self.user_id = user_id

    async def on_submit(self, i: discord.Interaction):
        try:
            target_uid = int(self.target_id.value)
            atype = self.attack_type.value.strip().lower()
            if atype not in ("capital", "poach", "sabotage"):
                return await i.response.send_message("Invalid attack type. Use: capital, poach, sabotage", ephemeral=True)
            if target_uid == self.user_id:
                return await i.response.send_message("You cannot attack yourself.", ephemeral=True)
        except ValueError:
            return await i.response.send_message("Invalid target ID.", ephemeral=True)

        await i.response.defer(ephemeral=True)

        # Cooldown bypass check
        bypass_role_id = 1396074626571829371
        has_bypass = False
        if i.guild:
            member = i.guild.get_member(self.user_id)
            if member:
                has_bypass = any(role.id == bypass_role_id for role in member.roles)

        with get_db_cursor() as c:
            # 1. Check cooldown (unless bypass)
            c.execute("SELECT last_attack_time FROM businesses WHERE user_id = ?", (self.user_id,))
            row = c.fetchone()
            last_attack = row[0] if row else 0
            now = time.time()
            if not has_bypass and last_attack and (now - last_attack) < 21600:
                remaining = int(21600 - (now - last_attack))
                return await i.followup.send(f"Attack on cooldown. Try again in {remaining//3600}h {(remaining%3600)//60}m.", ephemeral=True)

            # 2. Fetch attacker and target businesses
            att_biz = c.execute("SELECT name, capital, reputation FROM businesses WHERE user_id = ?", (self.user_id,)).fetchone()
            tgt_biz = c.execute("SELECT name, capital, reputation FROM businesses WHERE user_id = ?", (target_uid,)).fetchone()
            if not att_biz or not tgt_biz:
                return await i.followup.send("One of the businesses does not exist.", ephemeral=True)

            # 3. Calculate success chance
            offensive = get_security_specialists_count(c, self.user_id, 'offensive')
            defensive = get_security_specialists_count(c, target_uid, 'defensive')
            base_chance = 0.30
            success_chance = max(0.05, min(0.95, base_chance + (offensive * 0.03) - (defensive * 0.03)))

            cost = 100_000 + int(tgt_biz[1] * 0.001)
            if att_biz[1] < cost:
                return await i.followup.send(f"Insufficient capital (need A$ {cost:,}).", ephemeral=True)

            # 4. Deduct cost with retry
            success = False
            for _ in range(3):
                if atomic_business_update(c, self.user_id, -cost):
                    success = True
                    break
                await asyncio.sleep(0.1)
            if not success:
                return await i.followup.send("Balance updated concurrently. Please try again.", ephemeral=True)

            # 5. Roll success
            attack_success = random.random() < success_chance
            msg = ""
            amount_stolen = 0
            employees_poached = []

            if attack_success:
                if atype == "capital":
                    amount_stolen = int(tgt_biz[1] * random.uniform(0.005, 0.02))
                    amount_stolen = min(amount_stolen, 5_000_000)
                    atomic_business_update(c, self.user_id, amount_stolen)
                    atomic_business_update(c, target_uid, -amount_stolen)
                    msg = f"Success! Stole A$ {amount_stolen:,} from {tgt_biz[0]}."
                elif atype == "poach":
                    c.execute("SELECT id, name FROM employees WHERE user_id = ? ORDER BY RANDOM() LIMIT ?", (target_uid, random.randint(1, 3)))
                    to_poach = c.fetchall()
                    employees_poached = [{"id": eid, "name": name} for eid, name in to_poach]
                    for eid, _ in to_poach:
                        c.execute("UPDATE employees SET user_id = ? WHERE id = ?", (self.user_id, eid))
                    if to_poach:
                        names = ", ".join([name for _, name in to_poach])
                        msg = f"Success! Poached {len(to_poach)} employees from {tgt_biz[0]}: {names}"
                    else:
                        msg = f"Success! No employees found to poach from {tgt_biz[0]}."
                elif atype == "sabotage":
                    rep_loss = random.randint(10, 25)
                    c.execute("UPDATE businesses SET reputation = MAX(0, reputation - ?) WHERE user_id = ?", (rep_loss, target_uid))
                    msg = f"Success! Reduced {tgt_biz[0]}'s reputation by {rep_loss}%."
            else:
                # Failure penalty
                c.execute("UPDATE businesses SET reputation = MAX(0, reputation - 10) WHERE user_id = ?", (self.user_id,))
                msg = f"Attack failed! Your reputation dropped by 10%."

            # 6. Record attack log
            c.execute("""
                INSERT INTO attack_logs (attacker_id, target_id, attack_type, success, amount, employees_poached, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (self.user_id, target_uid, atype, 1 if attack_success else 0, amount_stolen, json.dumps(employees_poached), time.time()))

            # 7. Update last_attack_time
            c.execute("UPDATE businesses SET last_attack_time = ? WHERE user_id = ?", (now, self.user_id))

        await i.followup.send(msg, ephemeral=False)

class EditProductPaginationView(discord.ui.View):
    def __init__(self, user_id: int, sector: str, products: list):
        super().__init__(timeout=1200)
        self.user_id = user_id
        self.sector = sector
        self.products = products  # list of (id, name, price, target)
        self.chunk_size = 25
        self.total_pages = (len(products) + self.chunk_size - 1) // self.chunk_size
        self.current_page = 0
        self.update_dropdown()

    def update_dropdown(self):
        start = self.current_page * self.chunk_size
        end = start + self.chunk_size
        page_products = self.products[start:end]
        options = []
        for pid, name, price, target in page_products:
            options.append(
                discord.SelectOption(
                    label=name[:50],
                    description=f"Price: A${price:,} | Target: {target:,}/day",
                    value=str(pid)
                )
            )
        # Replace the existing select with a new one
        self.clear_items()
        if options:
            select = discord.ui.Select(placeholder="Select product to edit", options=options)
            select.callback = self.select_callback
            self.add_item(select)
        else:
            # Fallback – should not happen
            self.add_item(discord.ui.Button(label="No products", disabled=True))
        # Add navigation buttons
        if self.total_pages > 1:
            self.add_item(self.prev_button)
            self.add_item(self.next_button)
            self.update_buttons()

    def update_buttons(self):
        self.prev_button.disabled = (self.current_page == 0)
        self.next_button.disabled = (self.current_page >= self.total_pages - 1)

    async def select_callback(self, interaction: discord.Interaction):
        product_id = int(interaction.data["values"][0])
        with get_db_cursor() as c:
            row = c.execute("SELECT name, cost_to_make FROM business_products WHERE id = ?", (product_id,)).fetchone()
            if not row:
                return await interaction.response.send_message("Product not found.", ephemeral=True)
            name, base_cost = row
        # Send modal – view stays alive for further selections
        await interaction.response.send_modal(EditProductModal(product_id, name, base_cost))

    @discord.ui.button(label="Previous", style=discord.ButtonStyle.secondary, emoji="<:w_arrowleft:1272235695137751162>")
    async def prev_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page -= 1
        self.update_dropdown()
        await interaction.response.edit_message(view=self)

    @discord.ui.button(label="Next", style=discord.ButtonStyle.secondary, emoji="<:w_arrowright:1272235711721898005>")
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page += 1
        self.update_dropdown()
        await interaction.response.edit_message(view=self)


class MassSalaryModal(discord.ui.Modal, title="Mass Salary Adjustment"):
    regular_salary = discord.ui.TextInput(
        label="New salary for regular staff (A$)",
        placeholder=f"Minimum A$ {MINIMUM_WAGE:,} recommended",
        required=True
    )
    specialist_salary = discord.ui.TextInput(
        label="New salary for specialists (A$)",
        placeholder=f"Minimum A$ {SPECIALIST_MIN_WAGE:,} recommended",
        required=True
    )

    def __init__(self, user_id: int):
        super().__init__()
        self.user_id = user_id

    async def on_submit(self, i: discord.Interaction):
        try:
            new_reg = int(self.regular_salary.value)
            new_spec = int(self.specialist_salary.value)
            if new_reg <= 0 or new_spec <= 0:
                raise ValueError
        except ValueError:
            return await i.response.send_message("<a:2b_torono:1511037719956947016> Invalid salary amounts. Must be positive numbers.", ephemeral=True)

        with get_db_cursor() as c:
            # Update salaries
            c.execute(
                "UPDATE employees SET salary = ? WHERE user_id = ? AND specialization = 'None'",
                (new_reg, self.user_id)
            )
            c.execute(
                "UPDATE employees SET salary = ? WHERE user_id = ? AND specialization IN ('Engineer', 'Auditor', 'Shark')",
                (new_spec, self.user_id)
            )

            morale_penalty = 0
            if new_reg < MINIMUM_WAGE:
                morale_penalty += 15
                c.execute(
                    "UPDATE employees SET morale = MAX(0, morale - 15) WHERE user_id = ? AND specialization = 'None'",
                    (self.user_id,)
                )
            if new_spec < SPECIALIST_MIN_WAGE:
                morale_penalty += 15
                c.execute(
                    "UPDATE employees SET morale = MAX(0, morale - 15) WHERE user_id = ? AND specialization IN ('Engineer', 'Auditor', 'Shark')",
                    (self.user_id,)
                )
            log_business_event(c, self.user_id, "MASS_SALARY", f"Regular: A${new_reg:,}, Specialist: A${new_spec:,}")

        msg = "All salaries updated!"
        if morale_penalty:
            msg += f"\nSalaries below minimum wage."
        await i.response.send_message(msg, ephemeral=False)

        # Refresh the HR view
        new_view = HRView(self.user_id)
        await i.edit_original_response(embed=new_view.get_embed(), view=new_view)


class OpsView(discord.ui.View):
    def __init__(self, user_id):
        super().__init__(timeout=1800)
        self.user_id = user_id
        self.add_item(PhilosophyDropdown())
        self.add_item(UpgradeProductDropdown(user_id))

    async def interaction_check(self, i: discord.Interaction) -> bool:
         
        if i.user.id != self.user_id:
            await i.response.send_message("<a:wt_torono:1480580892706603018> Access Denied. This terminal does not belong to you.", ephemeral=True)
            return False
        update_activity(i.user.id)
        return True
        
    @discord.ui.button(label="Launch Product", style=discord.ButtonStyle.secondary, row=2)
    async def prod(self, i: discord.Interaction, btn):
        with get_db_cursor() as c:
            row = c.execute("SELECT sector FROM businesses WHERE user_id = ?", (i.user.id,)).fetchone()
    
        if not row or not row[0]:
            opts = [discord.SelectOption(label=s, value=s) for s in SECTORS]
            sel = discord.ui.Select(placeholder="Select your overarching business sector...", options=opts)
        
            async def sector_callback(it):
                sector = sel.values[0]
                with get_db_cursor() as c2:
                    c2.execute("UPDATE businesses SET sector = ? WHERE user_id = ?", (sector, it.user.id))
                
                view2 = discord.ui.View(timeout=60)
                view2.add_item(ProductTypeDropdown(sector))
                await it.response.send_message(f"<a:wt_torohiding:1480580886402568254> Now select a base product type to develop for **{sector}**:", view=view2, ephemeral=False)
        
            sel.callback = sector_callback
            v = discord.ui.View()
            v.add_item(sel)
            return await i.response.send_message("<a:wt_torohiding:1480580886402568254> You haven't chosen an industry yet! Select your business sector first:", view=v, ephemeral=False)
    
        sector = row[0]
        view3 = discord.ui.View(timeout=90)
        view3.add_item(ProductTypeDropdown(sector))
        await i.response.send_message(f"<a:wt_torohiding:1480580886402568254> Select a base product type to develop for your **{sector}** company:", view=view3, ephemeral=False)

    @discord.ui.button(label="CEO Payout", style=discord.ButtonStyle.secondary, row=3)
    async def payout_btn(self, i: discord.Interaction, btn):
        await i.response.send_modal(PayoutModal())

    @discord.ui.button(label="Edit Product", style=discord.ButtonStyle.secondary, row=2)
    async def edit_product_btn(self, i: discord.Interaction, btn):
        try:
            with get_db_cursor() as c:
                row = c.execute("SELECT sector FROM businesses WHERE user_id = ?", (i.user.id,)).fetchone()
                if not row or not row[0]:
                    return await i.response.send_message("<a:wt_torono:1480580892706603018> You need a business sector first!", ephemeral=True)
                sector = row[0]
                prods = c.execute(
                    "SELECT id, name, unit_price, production_target FROM business_products WHERE user_id = ? AND active = 1",
                    (i.user.id,)
                ).fetchall()
                if not prods:
                    return await i.response.send_message("You have no active products.", ephemeral=True)
            view = EditProductPaginationView(i.user.id, sector, prods)
            await i.response.send_message(
                "<a:wt_torosilly:1480580853720551637> Select the product you wish to modify:",
                view=view, ephemeral=True
            )
        except Exception as e:
            await i.response.send_message(f"An error occurred: {e}", ephemeral=True)
    
    @discord.ui.button(label="Upgrade HQ", style=discord.ButtonStyle.secondary, row=2)
    async def hq(self, i: discord.Interaction, btn):
        with get_db_cursor() as c:
            biz = c.execute("SELECT capital, hq_level FROM businesses WHERE user_id = ?", (i.user.id,)).fetchone()
        nxt = biz[1] + 1
        if nxt not in HQ_LEVELS: return await i.response.send_message("<a:wt_torono:1480580892706603018> Max level.", ephemeral=True)
        base_cost = HQ_LEVELS[nxt]["cost"]
        # Scale cost based on capital (at 50M it doubles, at 100M triples, cap at 5x)
        cost_mult = 1.0 + (biz[0] / 50_000_000)
        cost = int(base_cost * min(cost_mult, 5.0))  # cap at 5x
        if biz[0] < cost: return await i.response.send_message(f"<a:wt_torono:1480580892706603018> Need A$ {cost:,}.", ephemeral=True)
        with get_db_cursor() as c:
            if not atomic_business_update(c, i.user.id, -cost): return await i.response.send_message("<a:wt_torono:1480580892706603018> Balance updated concurrently.", ephemeral=True)
            c.execute("UPDATE businesses SET hq_level = ? WHERE user_id = ?", (nxt, i.user.id))
        await i.response.send_message("<a:wt_toroexclaim:1480581004317036624> HQ Upgraded!", ephemeral=False)
        
    @discord.ui.button(label="Set Bio", style=discord.ButtonStyle.secondary, row=3)
    async def bio(self, i: discord.Interaction, btn): await i.response.send_modal(DescriptionModal())

    @discord.ui.button(label="Set Salary", style=discord.ButtonStyle.secondary, row=3)
    async def sal(self, i: discord.Interaction, btn): await i.response.send_modal(SetSalaryModal())

    @discord.ui.button(label="Inject Capital", style=discord.ButtonStyle.secondary, row=3)
    async def inject(self, i: discord.Interaction, btn): await i.response.send_modal(InvestModal())

class SettlementView(discord.ui.View):
    def __init__(self, user_id): 
        super().__init__(timeout=180)
        self.user_id = user_id

    @discord.ui.button(label="Pay A$ 100k Settlement", style=discord.ButtonStyle.danger)
    async def pay(self, i: discord.Interaction, btn):
        with get_db_cursor() as c:
            cap = c.execute("SELECT capital FROM businesses WHERE user_id = ?", (self.user_id,)).fetchone()
            if not cap or cap[0] < 100_000: return await i.response.send_message("<a:wt_torono:1480580892706603018> Insufficient funds, might as well give up now.", ephemeral=True)
            c.execute("UPDATE businesses SET capital = capital - 100000 WHERE user_id = ?", (self.user_id,))
            c.execute("UPDATE employees SET morale = 50 WHERE user_id = ?", (self.user_id,))
            c.execute("UPDATE businesses SET strike_active = 0 WHERE user_id = ?", (self.user_id,))
        await i.response.send_message("<a:wt_toroexclaim:1480581004317036624> Strike settled.", ephemeral=False)
        
    @discord.ui.button(label="Grant 15% Raise", style=discord.ButtonStyle.danger)
    async def raise_(self, i: discord.Interaction, btn):
        with get_db_cursor() as c:
            c.execute("UPDATE employees SET salary = CAST(salary * 1.15 AS INTEGER), morale = 80 WHERE user_id = ?", (self.user_id,))
            c.execute("UPDATE businesses SET strike_active = 0 WHERE user_id = ?", (self.user_id,))
        await i.response.send_message("<a:wt_toroexclaim:1480581004317036624> Strike settled with raises.", ephemeral=False)

    async def interaction_check(self, i: discord.Interaction) -> bool:
        if i.user.id != self.user_id:
            await i.response.send_message("<a:wt_torono:1480580892706603018> Access Denied. This terminal does not belong to you.", ephemeral=True)
            return False
        return True


class BoardMeetingView(discord.ui.View):
    def __init__(self, user_id: int, crisis: dict):
        super().__init__(timeout=None)
        self.user_id = user_id
        self.crisis = crisis

    async def interaction_check(self, i: discord.Interaction) -> bool:
        if i.user.id != self.user_id:
            await i.response.send_message("<a:wt_torono:1480580892706603018> You are not the CEO. Mind your own business.", ephemeral=True)
            return False
        return True

    async def handle_choice(self, i: discord.Interaction, option_index: int):
        opt = self.crisis['opts'][option_index]
        cap_change = opt['capital']
        rep_change = opt['rep']
        
        with get_db_cursor() as c:
            if cap_change < 0:
                current_cap = (c.execute("SELECT capital FROM businesses WHERE user_id = ?", (self.user_id,)).fetchone() or [0])[0]
                if current_cap < abs(cap_change):
                    return await i.response.send_message(f"<a:wt_torono:1480580892706603018> Insufficient capital to execute this strategy. You need A$ {abs(cap_change):,}.", ephemeral=True)

            if cap_change != 0:
                atomic_business_update(c, self.user_id, cap_change)
            
            if rep_change != 0:
                c.execute("UPDATE businesses SET reputation = MAX(0, MIN(100, reputation + ?)) WHERE user_id = ?", (rep_change, self.user_id))

        for child in self.children:
            child.disabled = True
            
        result_msg = f"<a:wt_toroexclaim:1480581004317036624> **Strategy Executed:** {opt['desc']}\n"
        if cap_change < 0: result_msg += f"<:stockdown_athena:1503776838789501171> Capital: -A$ {abs(cap_change):,}\n"
        elif cap_change > 0: result_msg += f"<:stockup_athena:1503776772850712616> Capital: +A$ {cap_change:,}\n"
        
        if rep_change < 0: result_msg += f"<:stockdown_athena:1503776838789501171> Reputation: {rep_change}%\n"
        elif rep_change > 0: result_msg += f"<:stockup_athena:1503776772850712616> Reputation: +{rep_change}%\n"

        await i.response.edit_message(content=result_msg, embed=None, view=self)

    @discord.ui.button(label="Option 1", style=discord.ButtonStyle.primary, custom_id="bm_opt_1", emoji="<:sweetie_61blueflower:1504579938010009773>")
    async def btn_opt1(self, i: discord.Interaction, btn: discord.ui.Button):
        await self.handle_choice(i, 0)

    @discord.ui.button(label="Option 2", style=discord.ButtonStyle.primary, custom_id="bm_opt_2", emoji="<:sweetie_61purpleflower:1504579885111181414>")
    async def btn_opt2(self, i: discord.Interaction, btn: discord.ui.Button):
        await self.handle_choice(i, 1)

    @discord.ui.button(label="Option 3", style=discord.ButtonStyle.primary, custom_id="bm_opt_3", emoji="<:sweetie_61greenflower:1504579837543846098>")
    async def btn_opt3(self, i: discord.Interaction, btn: discord.ui.Button):
        await self.handle_choice(i, 2)

# ==========================================
# 🔄 AUTO-REFRESH DASHBOARD HELPER
# ==========================================
async def get_dashboard(bot, user_id):
    with get_db_cursor() as c:
        c.execute("SELECT name, capital, reputation, description, hq_level, sector, is_public, tech_level, marketing_budget FROM businesses WHERE user_id = ?", (user_id,))
        biz = c.fetchone()
        if not biz:
            return None, None
        c.execute("SELECT COUNT(id), AVG(morale) FROM employees WHERE user_id = ?", (user_id,))
        emps = c.fetchone()
        
    hq_lvl = biz[4] if biz[4] is not None else 0
    embed = discord.Embed(title=f"꒰ა {biz[0]}  ⸝⸝", color=0xffffff)
    desc = f"*{biz[3]}*\n\n"
    desc += f"<:athenacoin:1503804322280902767> **Liquid Capital:** A$ {biz[1]:,}\n"
    desc += f"└ **Brand Reputation:** {biz[2]}%\n\n"
    desc += f"<:btb_white3:1375474689467748517> **HQ Level:** {HQ_LEVELS[hq_lvl]['name']}\n"
    desc += f"└ **Workforce:** {emps[0] or 0} Staff (Morale: {int(emps[1]) if emps[1] else 100}%)\n\n"
    desc += f"<:w_mail:1435879826446745630> **Market Sector:** {biz[5] or 'Unassigned'}\n"
    desc += f"└ **R&D Level:** {biz[7]}  | **Marketing:** A$ {biz[8]:,}\n\n"
    embed.description = desc
    
    with get_db_cursor() as c:
        c.execute("SELECT value FROM config WHERE key = 'newspaper_banner'")
        row = c.fetchone()
        banner_url = row[0] if row else DEFAULT_BANNER
    embed.set_image(url=banner_url)
    embed.set_footer(text="Athena Central Reserve | Pending Taxes: %40 of Capital")
    
    return embed, TerminalView(bot, user_id)


class ShareBalanceView(discord.ui.View):
    def __init__(self, user_id: int, biz: tuple):
        super().__init__(timeout=1200)
        self.user_id = user_id
        self.biz = biz   # (capital, loan_balance, last_report)

    @discord.ui.button(label="Share Sheet", style=discord.ButtonStyle.secondary, emoji="<a:whitehearts:1511959604626460783>")
    async def share_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("Sybau this isn't your balance sheet.", ephemeral=True)

        embed = build_balance_embed(self.user_id, self.biz, include_banner=True)
        await interaction.response.send_message(embed=embed, ephemeral=False)

        button.disabled = True
        await interaction.edit_original_response(view=self)
        self.stop()

def build_balance_embed(user_id: int, biz: tuple, include_banner: bool = False) -> discord.Embed:
    """Builds the balance sheet embed. If include_banner is True, sets the banner image."""
    capital, loan_balance, last_report = biz
    report = last_report or ""

    # Parse values from the report
    gross_rev = mfg_costs = storage_fees = payroll = facility = exec_salary = specialist_wage = loan_payment = tax = net = 0
    for line in report.split("\n"):
        line = line.strip()
        if "Gross Revenue" in line:
            gross_rev = int(line.split(":")[1].replace("A$", "").replace(",", "").strip())
        elif "Mfg Costs" in line:
            mfg_costs = int(line.split(":")[1].replace("A$", "").replace(",", "").strip())
        elif "Storage Fees" in line:
            storage_fees = int(line.split(":")[1].replace("A$", "").replace(",", "").strip())
        elif "Staff Payroll" in line:
            payroll = int(line.split(":")[1].replace("A$", "").replace(",", "").strip())
        elif "IT Nerds" in line:
            specialist_wage = int(line.split(":")[1].replace("A$", "").replace(",", "").strip())
        elif "Facility Fees" in line:
            facility = int(line.split(":")[1].replace("A$", "").replace(",", "").strip())
        elif "Exec Salary" in line:
            exec_salary = int(line.split(":")[1].replace("A$", "").replace(",", "").strip())
        elif "Loan Payment" in line:
            loan_payment = int(line.split(":")[1].replace("A$", "").replace(",", "").strip())
        elif "Corporate Tax" in line:
            tax = int(line.split(":")[1].replace("A$", "").replace(",", "").strip())
        elif "NET PROFIT" in line:
            net = int(line.split(":")[1].replace("A$", "").replace(",", "").strip())
        elif "NET LOSS" in line:
            net = -int(line.split(":")[1].replace("A$", "").replace(",", "").strip())

    embed = discord.Embed(
        title="꒰ა Corporate Balance Sheet ⸝⸝",
        color=0xffffff if net >= 0 else 0xffffff
    )

    embed.add_field(name="<:athenacoin:1503804322280902767> Liquid Capital", value=f"└ A$ {capital:,}", inline=True)
    embed.add_field(name="<a:2b_torono:1511037719956947016> Loan Balance", value=f"└ A$ {loan_balance:,}", inline=True)
    embed.add_field(name="<:income_athena:1503894488299343892> Gross Revenue", value=f"+A$ {gross_rev:,}", inline=False)

    costs_desc = ""
    if mfg_costs > 0:
        costs_desc += f"└ Manufacturing: **-A$ {mfg_costs:,}**\n"
    if storage_fees > 0:
        costs_desc += f"└ Storage Fees: **-A$ {storage_fees:,}**\n"
    if payroll > 0:
        costs_desc += f"└ Staff Payroll: **-A$ {payroll:,}**\n"
    if facility > 0:
        costs_desc += f"└ Facility Fees: **-A$ {facility:,}**\n"
    if specialist_wage > 0:
        costs_desc += f"└ IT Nerds: **-A$ {specialist_wage:,}**\n"
    if exec_salary > 0:
        costs_desc += f"└ Executive Salary: **-A$ {exec_salary:,}**\n"
    if loan_payment > 0:
        costs_desc += f"└ Loan Payment: **-A$ {loan_payment:,}**\n"
    if tax > 0:
        costs_desc += f"└ Corporate Tax: **-A$ {tax:,}**\n"

    if costs_desc:
        embed.add_field(name="<:expense_athena:1503894540220760226> Operating Expenses", value=costs_desc, inline=False)

    if net >= 0:
        embed.add_field(name="<:stockup_athena:1503776772850712616> Net Profit", value=f"+A$ {net:,}", inline=False)
    else:
        embed.add_field(name="<:stockdown_athena:1503776838789501171> Net Loss", value=f"-A$ {abs(net):,}", inline=False)

    if include_banner:
        embed.set_image(url=BALANCE_BANNER_URL)

    #embed.set_footer(text="Athena Central Reserve")
    return embed


class DepartmentsView(discord.ui.View):
    def __init__(self, user_id: int):
        super().__init__(timeout=600)
        self.user_id = user_id
        self.add_item(DepartmentDropdown(user_id))

class DepartmentDropdown(discord.ui.Select):
    def __init__(self, user_id: int):
        options = [
            discord.SelectOption(label="Human Resources", value="hr", emoji="<:i_ghouls:1426522093620826112>"),
            discord.SelectOption(label="Cybersecurity", value="cyber", emoji="<:i_lucifer:1426518321544564798>"),
            discord.SelectOption(label="Sales & Partnerships", value="sales", emoji="<:i_satan:1426518223133737000>")
        ]
        super().__init__(placeholder="Choose a department...", options=options)
        self.user_id = user_id

    async def callback(self, i: discord.Interaction):
        if i.user.id != self.user_id:
            return await i.response.send_message("This menu is not for you. Get lost.", ephemeral=True)

        if self.values[0] == "hr":
            view = HRView(self.user_id)
            await i.response.send_message(embed=view.get_embed(), view=view, ephemeral=False)
        elif self.values[0] == "cyber":
            view = CybersecurityView(self.user_id)
            embed = await view.get_embed()
            await i.response.send_message(embed=embed, view=view, ephemeral=False)
        elif self.values[0] == "sales":
            view = SalesView(self.user_id)
            embed = await view.get_embed()
            await i.response.send_message(embed=embed, view=view, ephemeral=False)


class TerminalView(discord.ui.View):
    def __init__(self, bot, user_id):
        super().__init__(timeout=None)
        self.bot = bot
        self.user_id = user_id
        
        with get_db_cursor() as c:
            row = c.execute("SELECT AVG(morale), strike_active FROM employees LEFT JOIN businesses b ON b.user_id = employees.user_id WHERE employees.user_id = ?", (user_id,)).fetchone()
            avg = row[0] if row else None
            strike = row[1] if row else 0
            
        if strike == 1 or (avg is not None and avg < 20):
            self.add_item(discord.ui.Button(label="RESOLVE STRIKE", style=discord.ButtonStyle.danger, custom_id="strike_btn", row=4))

    @discord.ui.button(label="Balance Sheet", style=discord.ButtonStyle.secondary, row=0, emoji="<:i_cupid:1426518951961038929>")
    async def balance(self, i: discord.Interaction, btn):
        with get_db_cursor() as c:
            biz = c.execute("SELECT capital, loan_balance, last_report FROM businesses WHERE user_id = ?", (i.user.id,)).fetchone()
            if not biz:
                return await i.response.send_message("No business found.", ephemeral=True)
        embed = build_balance_embed(i.user.id, biz, include_banner=False)
        view = ShareBalanceView(i.user.id, biz)
        await i.response.send_message(embed=embed, view=view, ephemeral=True)
    
    @discord.ui.button(label="Refresh", style=discord.ButtonStyle.secondary, emoji="<a:bl_vinyl:1375013151099195526>", custom_id="term_refresh", row=4)
    async def refresh_dash(self, i: discord.Interaction, btn):
         
        await i.response.defer()
        update_activity(i.user.id)
        embed, view = await get_dashboard(i.client, i.user.id)
        await i.edit_original_response(embed=embed, view=view)


    @discord.ui.button(label="Select Country", style=discord.ButtonStyle.secondary, row=3, emoji="<a:black:1509321860104458457>")
    async def country_btn(self, i: discord.Interaction, btn):
        """Button to select country"""
        options = [
            discord.SelectOption(label="USA", description="United States of America", value="USA"),
            discord.SelectOption(label="UK", description="United Kingdom", value="UK"),
            discord.SelectOption(label="Germany", description="Federal Republic of Germany", value="Germany"),
            discord.SelectOption(label="France", description="French Republic", value="France"),
            discord.SelectOption(label="Brazil", description="Federative Republic of Brazil", value="Brazil"),
            discord.SelectOption(label="China", description="People's Republic of China", value="China"),
            discord.SelectOption(label="Singapore", description="Republik Singapura", value="Singapore"),
            discord.SelectOption(label="Canada", description="Canada", value="Canada"),
            discord.SelectOption(label="Vietnam", description="Socialist Republic of Vietnam", value="Vietnam")
        ]
        
        class CountryDropdown(discord.ui.Select):
            def __init__(self):
                super().__init__(placeholder="Select your business country", options=options)
            
            async def callback(self, interaction: discord.Interaction):
                country = self.values[0]
                with get_db_cursor() as c:
                    c.execute("UPDATE businesses SET country = ? WHERE user_id = ?", (country, interaction.user.id))
                
                embed = discord.Embed(title="ა Country Updated", color=0xffffff)
                embed.description = f"Your business is now registered in {country}.\nTax rates will be applied based on this country's regulations."
                await interaction.response.send_message(embed=embed, ephemeral=True)
        
        view = discord.ui.View()
        view.add_item(CountryDropdown())
        await i.response.send_message("Select your business country:", view=view, ephemeral=True)

    @discord.ui.button(label="Operations", style=discord.ButtonStyle.secondary, row=0, emoji="<a:i_devils:1426518576784736287>")
    async def ops(self, i: discord.Interaction, btn):
        embed = discord.Embed(title="꒰ა ﹒chérie  ⸝⸝", color=0xffffff, description="**Operational Control**")
        await i.response.send_message(embed=embed, view=OpsView(i.user.id), ephemeral=False)
    
    @discord.ui.button(label="HR", style=discord.ButtonStyle.secondary, row=0, emoji="<:i_ghouls:1426522093620826112>")
    async def hr(self, i: discord.Interaction, btn):
        view = HRView(i.user.id)
        await i.response.send_message(embed=view.get_embed(), view=view, ephemeral=False)
    
    @discord.ui.button(label="Departments", style=discord.ButtonStyle.secondary, row=0, emoji="<a:0096_blackbow:1514308974609043608>")
    async def departments(self, i: discord.Interaction, btn):
        """Opens a dropdown to choose a department."""
        view = DepartmentsView(i.user.id)
        await i.response.send_message("Select a department:", view=view, ephemeral=True)


    @discord.ui.button(label="R&D Hub", style=discord.ButtonStyle.secondary, row=1, emoji="<:i_incubus:1426520255462903869>")
    async def rnd(self, i: discord.Interaction, btn):
        with get_db_cursor() as c:
            tech = c.execute("SELECT tech_level FROM businesses WHERE user_id = ?", (i.user.id,)).fetchone()[0]
        embed = discord.Embed(title="<:research:1504543523628781790> R&D Tech Tree", color=0xffffff)
        desc = f"**Current Tech Level:** {tech}\n\n"
        for milestone, label in TECH_MILESTONES.items():
            desc += f"{'<:1unlocked:1504556384535187528>' if tech >= milestone else '<:2locked:1504556425257550025>'} **Tech {milestone}:** {label}\n"
        desc += "\n*Invest capital in R&D to unlock new tiers and bonuses!*"
        embed.description = desc
        view = ProductPerformanceView(i.user.id)
        await i.response.send_message(embed=embed, view=view, ephemeral=False)
    
    @discord.ui.button(label="Rename", style=discord.ButtonStyle.secondary, row=1, emoji="<a:i_pm:1426519079673659493>")
    async def rename(self, i: discord.Interaction, btn):
        await i.response.send_modal(RenameCompanyModal())
    
    @discord.ui.button(label="IPO", style=discord.ButtonStyle.secondary, row=1, emoji="<:w_moth2:1380799242515386368>")
    async def ipo(self, i: discord.Interaction, btn):
        with get_db_cursor() as c:
            biz = c.execute("SELECT name, capital, is_public FROM businesses WHERE user_id = ?", (i.user.id,)).fetchone()
            if not biz: return await i.response.send_message("No business found.", ephemeral=True)
            if biz[2] == 1: return await i.response.send_message("Silly, your business is already public!", ephemeral=True)
            if biz[1] < 2_000_000: return await i.response.send_message("You need at least A$ 2,000,000 to IPO.", ephemeral=True)
            
            emp_count = c.execute("SELECT COUNT(id) FROM employees WHERE user_id = ?", (i.user.id,)).fetchone()[0]
            ipo_bonus = int(biz[1] * 0.20)
            start_price = max(500, int((biz[1] * 0.001) + (emp_count * 10)))
            sym = biz[0][:4].upper()
            
            c.execute("UPDATE businesses SET is_public = 1, capital = capital + ? WHERE user_id = ?", (ipo_bonus, i.user.id))
            
        with get_eco_cursor() as c_eco:
            c_eco.execute(
                "INSERT OR IGNORE INTO stocks (symbol, name, price, volatility, trend, base_price, momentum, floor_price, ceil_price) "
                "VALUES (?, ?, ?, 3, '➖ FLAT', ?, 0, 500, 33000)",
                (sym, biz[0], start_price, start_price)
            )
            
        await i.response.send_message(f"<a:wt_torojumping:1480580859042992209> **IPO SUCCESSFUL!**\nYour company is now trading as **{sym}** at A$ {start_price:,}.\n\nInstitutional underwriters have injected **A$ {ipo_bonus:,}** into your corporate capital! Don't forget your day ones when you get rich.", ephemeral=False)
    
    @discord.ui.button(label="Issue Shares (Dilute)", style=discord.ButtonStyle.secondary, row=1, emoji="<a:w_tear:1375482116749529098>")
    async def dilute_btn(self, i: discord.Interaction, btn):
        with get_db_cursor() as c:
            is_pub = c.execute("SELECT is_public FROM businesses WHERE user_id = ?", (i.user.id,)).fetchone()
            if not is_pub or is_pub[0] == 0:
                return await i.response.send_message("❌ You must IPO first before you can issue new shares to the public market.", ephemeral=True)
        await i.response.send_modal(DiluteSharesModal())
    
    @discord.ui.button(label="Marketing", style=discord.ButtonStyle.secondary, row=2, emoji="<:i_satan:1426518223133737000>")
    async def market(self, i: discord.Interaction, btn):
        await i.response.send_modal(MarketingModal())
    
    @discord.ui.button(label="Pay Dividends", style=discord.ButtonStyle.secondary, row=2, emoji="<:i_succubus:1426518422975549500>")
    async def dividend(self, i: discord.Interaction, btn):
        await i.response.send_modal(DividendModal())
    
    @discord.ui.button(label="Invest in R&D", style=discord.ButtonStyle.secondary, row=2, emoji="<:i_trialmod:1426518688911069184>")
    async def invest_rnd(self, i: discord.Interaction, btn):
        await i.response.send_modal(RndInvestModal())
    
    @discord.ui.button(label="Espionage", style=discord.ButtonStyle.secondary, row=3, emoji="<:i_lucifer:1426518321544564798>")
    async def espionage(self, i: discord.Interaction, btn):
        await i.response.send_modal(EspionageModal())

    @discord.ui.button(label="Audit", style=discord.ButtonStyle.secondary, row=3, emoji="<a:c_rolling:1218512150549499904>")
    async def audit(self, i: discord.Interaction, btn):
        with get_db_cursor() as c:
            biz = c.execute("""
                SELECT capital, owner_salary, days_open, last_report, sector,
                       strike_active, last_audit, country, marketing_budget, reputation,
                       tech_level, philosophy, demand_boost, hq_level, cached_audit
                FROM businesses WHERE user_id = ?
            """, (self.user_id,)).fetchone()
            if not biz:
                return await i.response.send_message("❌ No business found.", ephemeral=True)

        now = time.time()
        # Cooldown bypass for specific role
        bypass_role_id = 1396074626571829371
        has_bypass = False
        if i.guild:
            member = i.guild.get_member(i.user.id)
            if member:
                has_bypass = any(role.id == bypass_role_id for role in member.roles)

        last_audit_ts = biz[6] or 0
        cached_audit = biz[14] or ""

        # If cached audit exists and is recent (4h) and no bypass, show cached version
        if not has_bypass and cached_audit and (now - last_audit_ts) < 14400:
            embed = discord.Embed(title="ა Firm Analysis & Audit ⸝⸝", color=0xffffff)
            embed.description = cached_audit
            remaining = int(14400 - (now - last_audit_ts))
            embed.set_footer(text=f"Last audit: {datetime.fromtimestamp(last_audit_ts).strftime('%Y-%m-%d %H:%M')}\nNext update in {remaining // 3600}h {(remaining % 3600)//60}m.")
            # Truncate to Discord limit
            await i.response.send_message(embed=embed, ephemeral=True)
            return

        # Otherwise, generate a fresh audit (full existing logic follows)
        with get_db_cursor() as c:
            c.execute("UPDATE businesses SET last_audit = ? WHERE user_id = ?", (now, self.user_id))

            # Employees
            emps = c.execute("SELECT salary, morale, specialization FROM employees WHERE user_id = ?", (self.user_id,)).fetchall()
            emp_count = len(emps)
            avg_morale = sum(e[1] for e in emps) / max(1, emp_count)
            engineer_count = sum(1 for e in emps if e[2] == 'Engineer')
            auditor_count = sum(1 for e in emps if e[2] == 'Auditor')
            shark_count = sum(1 for e in emps if e[2] == 'Shark')

            # Products
            prods = c.execute("""
                SELECT name, unit_price, cost_to_make, production_target, quality_tier
                FROM business_products WHERE user_id = ? AND active = 1
            """, (self.user_id,)).fetchall()

            tech_level = biz[10]
            philosophy = biz[11]
            demand_boost = biz[12]
            capital = biz[0]
            owner_salary = biz[1]
            reputation = biz[9]
            sector = biz[4]
            country = biz[7]
            marketing_budget = biz[8]
            strike_active = biz[5]

            loan_row = c.execute("SELECT loan_balance FROM businesses WHERE user_id = ?", (self.user_id,)).fetchone()
            loan_balance = loan_row[0] if loan_row else 0

        # ---------- CAPACITY CALCULATION ----------
        tech_bonus = min(0.5, tech_level * 0.005)
        eng_mult = 1.0 + (0.20 * engineer_count) + tech_bonus
        if philosophy == 'Artisan':
            out_mult = 0.5 * eng_mult
        else:
            out_mult = min(1.2, 1.0 * eng_mult)
        factory_cap = int(sum(12 * (e[1] / 100) for e in emps) * out_mult)

        total_target = sum(p[3] for p in prods) if prods else 0
        capacity_ratio = total_target / max(1, factory_cap)

        # ---------- HEALTH RATING (0-100) ----------
        health_score = 0
        health_details = []

        # 1. Capacity utilisation (ideal 80-100%)
        if capacity_ratio >= 0.8 and capacity_ratio <= 1.0:
            health_score += 20
            health_details.append("<:014White_Dot:1509293534799331408> Capacity: Optimal (80-100%)")
        elif capacity_ratio > 1.0:
            health_score += 10
            health_details.append("<:014White_Dot:1509293534799331408> Capacity: Overproducing")
        elif capacity_ratio >= 0.5:
            health_score += 15
            health_details.append("<:014White_Dot:1509293534799331408> Capacity: Underutilised (50-80%)")
        else:
            health_score += 5
            health_details.append("<:014White_Dot:1509293534799331408> Capacity: Severely underutilised (<50%)")

        # 2. Morale
        if avg_morale >= 70:
            health_score += 20
            health_details.append("<:014White_Dot:1509293534799331408> Morale: High (≥70%)")
        elif avg_morale >= 50:
            health_score += 12
            health_details.append("<:014White_Dot:1509293534799331408> Morale: Moderate (50-69%)")
        elif avg_morale >= 25:
            health_score += 6
            health_details.append("<:014White_Dot:1509293534799331408> Morale: Low (25-49%)")
        else:
            health_score += 0
            health_details.append("<:014White_Dot:1509293534799331408> Morale: Critical (<25%)")

        # 3. Reputation
        if reputation >= 80:
            health_score += 15
            health_details.append("<:014White_Dot:1509293534799331408> Reputation: Strong (≥80%)")
        elif reputation >= 50:
            health_score += 10
            health_details.append("<:014White_Dot:1509293534799331408> Reputation: Moderate (50-79%)")
        else:
            health_score += 3
            health_details.append("<:014White_Dot:1509293534799331408> Reputation: Weak (<50%)")

        # 4. Capital
        if capital >= 500_000:
            health_score += 15
            health_details.append("<:014White_Dot:1509293534799331408> Capital: Strong (≥500k)")
        elif capital >= 100_000:
            health_score += 10
            health_details.append("<:014White_Dot:1509293534799331408> Capital: Adequate (100-500k)")
        elif capital >= 50_000:
            health_score += 5
            health_details.append("<:014White_Dot:1509293534799331408> Capital: Low (50-100k)")
        else:
            health_score += 0
            health_details.append("<:014White_Dot:1509293534799331408> Capital: Critical (<50k)")

        # 5. Debt ratio
        debt_ratio = loan_balance / max(1, capital)
        if debt_ratio == 0:
            health_score += 10
            health_details.append("<:014White_Dot:1509293534799331408> Debt: None")
        elif debt_ratio < 0.25:
            health_score += 7
            health_details.append("<:014White_Dot:1509293534799331408> Debt: Low (<25% of capital)")
        elif debt_ratio < 0.5:
            health_score += 3
            health_details.append("<:014White_Dot:1509293534799331408> Debt: Moderate (25-50%)")
        else:
            health_score += 0
            health_details.append("<:014White_Dot:1509293534799331408> Debt: High (>50%)")

        # 6. Pricing health
        pricing_issues = 0
        for p in prods:
            base_cost = SECTOR_BASE_COSTS.get(sector, 300)
            margin_ratio = p[1] / max(1, base_cost)
            if margin_ratio > 4.0 or margin_ratio < 1.2:
                pricing_issues += 1
        if pricing_issues == 0 and prods:
            health_score += 10
            health_details.append("<:014White_Dot:1509293534799331408> Pricing: All products well-priced")
        elif pricing_issues <= len(prods) // 2:
            health_score += 5
            health_details.append("<:014White_Dot:1509293534799331408> Pricing: Some products need adjustment")
        else:
            health_score += 0
            health_details.append("<:014White_Dot:1509293534799331408> Pricing: Many products mispriced")

        # 7. Tech utilisation
        has_premium_luxury = any(p[4] in ('Premium', 'Luxury') for p in prods)
        if tech_level >= 15 and has_premium_luxury:
            health_score += 10
            health_details.append("<:014White_Dot:1509293534799331408> Tech: Fully utilised (Premium/Luxury unlocked)")
        elif tech_level >= 10:
            health_score += 7
            health_details.append("<:014White_Dot:1509293534799331408> Tech: Moderate – consider upgrading products")
        elif tech_level >= 5:
            health_score += 4
            health_details.append("<:014White_Dot:1509293534799331408> Tech: Basic – invest in R&D")
        else:
            health_score += 2
            health_details.append("<:014White_Dot:1509293534799331408> Tech: Very low")

        health_score = min(100, health_score)
        if health_score >= 90:
            grade = "A+ (Excellent)"
        elif health_score >= 80:
            grade = "A (Very Good)"
        elif health_score >= 70:
            grade = "B (Good)"
        elif health_score >= 60:
            grade = "C (Fair)"
        elif health_score >= 50:
            grade = "D (Poor)"
        else:
            grade = "F (Critical)"

        # ---------- BUILD ADVICE LIST ----------
        advice = []

        # Strike / Morale override
        if strike_active == 1 or avg_morale < 20:
            advice.insert(0, "<a:013Pink_Caution:1509406197323923729> **CRITICAL: Worker Strike Active!** Production halted. Resolve via HR terminal.")
        elif avg_morale < 25:
            advice.append("<a:013Pink_Caution:1509406197323923729> **Low Morale** (<25%). Strike risk. Host HR events.")
        elif avg_morale < 50:
            advice.append("<a:013Pink_Caution:1509406197323923729> **Low Morale** – consider boosting morale.")

        # Products / capacity
        if not prods:
            advice.append("📦 **No Products:** Launch a product in the Operations terminal.")
        else:
            if capacity_ratio > 1.5:
                advice.append(f"<a:013Pink_Caution:1509406197323923729> **Overproduction:** Targets {total_target:,} exceed capacity {factory_cap:,} by {int((capacity_ratio-1)*100)}%. Lower targets or hire more staff.")
            elif capacity_ratio < 0.5:
                advice.append(f"<a:013Pink_Caution:1509406197323923729> **Underutilised Workforce:** Capacity {factory_cap:,} vs targets {total_target:,} ({int(capacity_ratio*100)}% usage). Increase targets or fire excess staff.")
            elif capacity_ratio < 0.8:
                advice.append(f"<a:cattojump:1509406633992917146> **Idle Capacity:** Running at {int(capacity_ratio*100)}%. Raise targets.")
            else:
                advice.append(f"<a:cattojump:1509406633992917146> **Good Capacity:** {int(capacity_ratio*100)}% utilisation.")

        # Pricing advice
        for p in prods:
            p_name, price, _, _, _ = p
            base_cost = SECTOR_BASE_COSTS.get(sector, 300)
            margin_ratio = price / max(1, base_cost)
            if margin_ratio > 8.0:
                advice.append(f"<:h_gray:1408478249625059328> **SEVERE OVERPRICING:** `{p_name}` – markup >800%.")
            elif margin_ratio > 4.0:
                advice.append(f"<:h_gray:1408478249625059328> **Severe Overpricing:** `{p_name}` – >400% markup.")
            elif margin_ratio > 2.5:
                advice.append(f"<:h_gray:1408478249625059328> **High Price:** `{p_name}` – >2.5x markup, 70% sales loss.")
            elif margin_ratio < 1.2:
                advice.append(f"<:h_gray:1408478249625059328> **Underpricing:** `{p_name}` – too low, increase to 2–2.5x base cost.")

        # Financial & misc
        if capital < 50_000:
            advice.append("<a:cattojump:1509406633992917146> **Critical Capital Shortage** (<50k). Inject funds immediately.")
        elif capital < 100_000:
            advice.append("<a:013Pink_Caution:1509406197323923729> **Low Capital** (<100k). Consider injection.")
        if debt_ratio > 0.5:
            advice.append(f"<a:013Pink_Caution:1509406197323923729> **High Debt:** Loan {loan_balance:,} is {int(debt_ratio*100)}% of capital. Pay down debt.")
        elif debt_ratio > 0.25:
            advice.append(f"<a:013Pink_Cat2:1509374529926070372> **Moderate Debt** – monitor.")
        if owner_salary > 0:
            advice.append(f"**<a:013Pink_Cat2:1509374529926070372> Executive Salary:** A$ {owner_salary:,}/cycle.")
        if reputation < 50:
            advice.append(f"<a:013Pink_Caution:1509406197323923729> **Low Reputation** ({reputation}%) – improve quality.")
        if marketing_budget > 0:
            boost = min(2.5, demand_boost)
            advice.append(f"<a:cattojump:1509406633992917146> **Marketing Boost:** +{int((boost-1)*100)}% demand. Budget A$ {marketing_budget:,}.")
        else:
            advice.append("<a:cattojump:1509406633992917146> **No Marketing** – a small spend increases demand.")

        # Tech / Specialists
        if tech_level > 10 and not has_premium_luxury:
            advice.append(f"<a:cattojump:1509406633992917146> **Underutilised Tech:** Level {tech_level} allows Premium/Luxury. Upgrade products.")
        if engineer_count > 0:
            advice.append(f"<a:013Pink_Cat2:1509374529926070372> **Engineers ({engineer_count})** – increases production capacity (effect capped at +20%).")
        if auditor_count > 0:
            advice.append(f"<a:cattojump:1509406633992917146> **Auditors ({auditor_count})** – reduce manufacturing costs.")
        if shark_count > 0:
            advice.append(f"<a:013Pink_Cat2:1509374529926070372> **Sales Sharks ({shark_count})** – increase demand.")

        # Country opportunity
        country_tips = {
            'Singapore': "Low taxes, financial hub.",
            'Canada': "Natural resources, stable banking.",
            'USA': "Strong premium market.",
            'China': "Manufacturing advantages.",
            'Germany': "High‑quality manufacturing.",
            'Vietnam': "Low labour costs.",
            'UK': "Strong IP protections.",
            'France': "Luxury brand recognition.",
            'Brazil': "Large domestic market."
        }
        if country in country_tips:
            advice.append(f"<a:013Pink_Caution:1509406197323923729> **{country} Opportunity:** {country_tips[country]}")

        # Summary line
        summary = f"**<a:013Pink_Cat2:1509374529926070372> Summary:** {emp_count} employees, {len(prods)} products, capacity {factory_cap:,}/day vs targets {total_target:,}/day."
        advice.insert(0, summary)

        # Health rating block
        health_block = f"**<a:013Pink_Cat2:1509374529926070372> Corporate Health Rating:** {health_score}/100 ({grade})\n"
        for detail in health_details:
            health_block += f"   {detail}\n"
        advice.insert(1, health_block)

        embed = discord.Embed(title="ა Firm Analysis & Audit ⸝⸝", color=0xffffff)
        embed.description = "Your corporate consultants have reviewed your operations:\n\n" + "\n\n".join(advice)
        embed.set_footer(text="Next audit available in 4 hours." + (" (bypassed for you)" if has_bypass else ""))
        if len(embed.description) > 4096:
            embed.description = embed.description[:4093] + "..."
        with get_db_cursor() as c:
            c.execute("UPDATE businesses SET cached_audit = ? WHERE user_id = ?", (embed.description, self.user_id))

        await i.response.send_message(embed=embed, ephemeral=True)
        
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            try:
                await interaction.response.send_message(
                    "<a:wt_torono:1480580892706603018> Access Denied. This is classified corporate data.",
                    ephemeral=True
                )
            except discord.NotFound:
                pass
            return False

        if interaction.data.get('custom_id') == "strike_btn":
            embed = discord.Embed(title="꒰ა ﹒chérie  ⸝⸝", color=0xffffff, description="**UNION DEMANDS**")
            await interaction.response.send_message(
                embed=embed, view=SettlementView(interaction.user.id), ephemeral=True
            )
            return False

        update_activity(interaction.user.id)
        return True

class EspionageTypeDropdown(discord.ui.Select):
    def __init__(self, target_id: int):
        self.target_id = target_id
        opts = [
            discord.SelectOption(label="Steal Tech Points", description="Steal 3 tech points from rival", value="steal_tech", emoji="🔬"),
            discord.SelectOption(label="Sabotage Reputation", description="Reduce rival reputation by 15", value="sabotage_rep", emoji="📉")
        ]
        super().__init__(placeholder="Select operation type...", options=opts)
    
    async def callback(self, i: discord.Interaction):
        op = self.values[0]
        cost = 50000 if op == 'steal_tech' else 30000
        
        with get_db_cursor() as c:
            if not atomic_business_update(c, i.user.id, -cost):
                return await i.response.send_message("<a:wt_torono:1480580892706603018> Insufficient capital.", ephemeral=True)
            
            target = c.execute("SELECT tech_level, reputation FROM businesses WHERE user_id = ?", (self.target_id,)).fetchone()
            if not target:
                return await i.response.send_message("<a:wt_torono:1480580892706603018> Target business not found.", ephemeral=True)
            
            success_chance = max(0.1, min(0.75, 0.3 + (0.01 * (target[0]/5)) - (0.005 * target[1])))
            
            if random.random() < success_chance:
                if op == 'steal_tech':
                    c.execute("UPDATE businesses SET tech_level = tech_level + 3 WHERE user_id = ?", (i.user.id,))
                    c.execute("UPDATE businesses SET tech_level = MAX(0, tech_level - 3) WHERE user_id = ?", (self.target_id,))
                    msg = "<a:wt_toroexclaim:1480581004317036624> Espionage successful! +3 Tech points transferred."
                else:
                    c.execute("UPDATE businesses SET reputation = MAX(0, reputation - 15) WHERE user_id = ?", (self.target_id,))
                    msg = "<a:wt_toroexclaim:1480581004317036624> Sabotage successful! Rival reputation -15."
                log_business_event(c, i.user.id, "ESPIONAGE_SUCCESS", f"{op} on {self.target_id}")
            else:
                c.execute("UPDATE businesses SET reputation = MAX(0, reputation - 10) WHERE user_id = ?", (i.user.id,))
                msg = "<a:wt_torono:1480580892706603018> Espionage failed! You were caught and reputation dropped."
                log_business_event(c, i.user.id, "ESPIONAGE_FAIL", f"Caught during {op}")
        
        await i.response.send_message(msg, ephemeral=True)

class EspionageView(discord.ui.View):
    def __init__(self, attacker_id: int, target_id: int):
        super().__init__(timeout=600)
        self.attacker_id = attacker_id
        self.add_item(EspionageTypeDropdown(target_id))

    async def interaction_check(self, i: discord.Interaction) -> bool:
        if i.user.id != self.attacker_id:
            await i.response.send_message("<a:wt_torono:1480580892706603018> This is a private black-ops channel.", ephemeral=True)
            return False
        return True


class EspionageModal(discord.ui.Modal, title='Corporate Espionage'):
    target_id = discord.ui.TextInput(label='Target User ID', placeholder='e.g. 123456789')
    
    async def on_submit(self, i: discord.Interaction):
        try:
            tid = int(self.target_id.value)
        except:
            return await i.response.send_message("<a:wt_torono:1480580892706603018> Invalid User ID.", ephemeral=True)
        
        if tid == i.user.id:
            return await i.response.send_message("<a:wt_torono:1480580892706603018> Cannot target yourself, don't bring your personal self sabotaging habits to your business!", ephemeral=True)
        
        await i.response.send_message("Select operation type:", view=EspionageView(i.user.id, tid), ephemeral=True)

class MassQuantityModal(discord.ui.Modal, title='Mass Staff Action'):
    quantity = discord.ui.TextInput(
        label="Number of employees",
        placeholder="e.g., 10",
        min_length=1,
        max_length=3,
        required=True
    )

    def __init__(self, user_id: int, action: str):
        super().__init__()
        self.user_id = user_id
        self.action = action

    async def on_submit(self, i: discord.Interaction):
        try:
            qty = int(self.quantity.value)
            if qty <= 0:
                raise ValueError
        except ValueError:
            return await i.response.send_message("❌ Invalid quantity. Please enter a positive number.", ephemeral=True)

        # Send immediate placeholder response to keep interaction alive
        await i.response.send_message("⏳ Processing mass action...", ephemeral=True)

        try:
            with get_db_cursor() as c:
                c.execute("SELECT capital, hq_level, strike_active FROM businesses WHERE user_id = ?", (i.user.id,))
                biz = c.fetchone()
                if not biz:
                    return await i.edit_original_response(content="❌ No business found.")
                capital, hq_level, strike = biz
                if strike == 1:
                    return await i.edit_original_response(content="❌ Cannot manage staff while a strike is active! Resolve it first.")

                if self.action == "hire":
                    # Check capacity
                    c.execute("SELECT COUNT(id) FROM employees WHERE user_id = ?", (i.user.id,))
                    current_emps = c.fetchone()[0]
                    max_emps = HQ_LEVELS[hq_level]["max_emp"]
                    if current_emps + qty > max_emps:
                        return await i.edit_original_response(content=f"❌ Not enough HQ capacity! You can only hire up to {max_emps - current_emps} more employees.")

                    # Get cost per employee based on current count
                    cost_per = get_hire_cost(c, i.user.id, "regular")
                    total_cost = cost_per * qty
                    if capital < total_cost:
                        return await i.edit_original_response(content=f"❌ Insufficient capital. Need A$ {total_cost:,} to hire {qty} staff.")
                    # Retry atomic update up to 3 times
                    success = False
                    for attempt in range(3):
                        if atomic_business_update(c, i.user.id, -total_cost):
                            success = True
                            break
                        await asyncio.sleep(0.1)
                    if not success:
                        return await i.edit_original_response(content="❌ Balance updated concurrently after multiple attempts. Please try again.")
                    # Batch insert
                    names = [random.choice(NAMES) for _ in range(qty)]
                    c.executemany(
                        "INSERT INTO employees (user_id, name, salary, morale, specialization) VALUES (?, ?, 1500, 80, 'None')",
                        [(i.user.id, name) for name in names]
                    )
                    log_business_event(c, i.user.id, "MASS_HIRE", f"Hired {qty} staff for A$ {total_cost:,}")

                elif self.action == "fire":
                    c.execute("SELECT id FROM employees WHERE user_id = ?", (i.user.id,))
                    employees = c.fetchall()
                    if len(employees) < qty:
                        return await i.edit_original_response(content=f"❌ You only have {len(employees)} employees. Cannot fire {qty}.")
                    to_fire = random.sample(employees, qty)
                    for (eid,) in to_fire:
                        c.execute("DELETE FROM employees WHERE id = ?", (eid,))
                    log_business_event(c, i.user.id, "MASS_FIRE", f"Fired {qty} employees (random)")

            # Success: show result and re‑open the dropdown for another action
            await i.edit_original_response(content="Action completed! Select another action below:", view=MassActionView(i.user.id))

        except Exception as e:
            await i.edit_original_response(content=f"An error occurred: {e}. Use `/report` if needed.")


class MassSpecialistModal(discord.ui.Modal, title="Mass Hire Specialists"):
    quantity = discord.ui.TextInput(
        label="Number of specialists to hire",
        placeholder="e.g., 5",
        min_length=1,
        max_length=3,
        required=True
    )
    specialist_type = discord.ui.TextInput(
        label="Specialist type",
        placeholder="Engineer, Auditor, or Shark",
        max_length=10,
        required=True
    )

    def __init__(self, user_id: int):
        super().__init__()
        self.user_id = user_id

    async def on_submit(self, i: discord.Interaction):
        try:
            qty = int(self.quantity.value)
            spec_type = self.specialist_type.value.strip().capitalize()
            if qty <= 0 or spec_type not in ("Engineer", "Auditor", "Shark", "Logistics"):
                raise ValueError
        except ValueError:
            return await i.response.send_message("<a:2b_torono:1381530244984475761> Invalid input. Quantity must be >0, type must be Engineer, Auditor, or Shark.", ephemeral=True)

        # Send placeholder to avoid timeout
        await i.response.send_message("⏳ Hiring specialists...", ephemeral=True)

        with get_db_cursor() as c:
            # Fetch business data
            biz = c.execute("SELECT capital, hq_level, strike_active FROM businesses WHERE user_id = ?", (self.user_id,)).fetchone()
            if not biz:
                return await i.edit_original_response(content="<a:wt_toroconfused:1480580932367945918> No business found.")
            capital, hq_level, strike = biz
            if strike == 1:
                return await i.edit_original_response(content="<a:2b_torono:1381530244984475761> Cannot hire during a strike! Resolve it first.")

            # Check HQ capacity
            current_emps = c.execute("SELECT COUNT(id) FROM employees WHERE user_id = ?", (self.user_id,)).fetchone()[0]
            max_emps = HQ_LEVELS[hq_level]["max_emp"]
            if current_emps + qty > max_emps:
                return await i.edit_original_response(content=f"<a:2b_torono:1381530244984475761> Not enough HQ capacity! Max {max_emps} employees, you have {current_emps}.")

            cost_per = get_hire_cost(c, self.user_id, "specialist")
            total_cost = cost_per * qty
            if capital < total_cost:
                return await i.edit_original_response(content=f"Insufficient capital. Need A$ {total_cost:,} to hire {qty} specialists.")
            # Atomic update with retry
            success = False
            for _ in range(3):
                if atomic_business_update(c, self.user_id, -total_cost):
                    success = True
                    break
                await asyncio.sleep(0.1)
            if not success:
                return await i.edit_original_response(content="Balance updated concurrently. Please try again.")
            # Batch insert specialists
            names = [random.choice(NAMES) for _ in range(qty)]
            c.executemany(
            "INSERT INTO employees (user_id, name, salary, morale, specialization) VALUES (?, ?, ?, 100, ?)",
            [(self.user_id, name, SPECIALIST_MIN_WAGE, spec_type) for name in names]
            )
            log_business_event(c, self.user_id, "MASS_SPECIALIST_HIRE", f"Hired {qty} {spec_type}(s) for A$ {total_cost:,}")

        await i.edit_original_response(content=f"Successfully hired {qty} **{spec_type}**(s) for A$ {total_cost:,}.")
        # Optionally refresh the HR view – but not necessary because the view is ephemeral


class MassFireSpecialistsModal(discord.ui.Modal, title="Mass Fire Specialists"):
    quantity = discord.ui.TextInput(
        label="Number of specialists to fire (randomly)",
        placeholder="e.g., 5",
        min_length=1,
        max_length=3,
        required=True
    )

    def __init__(self, user_id: int):
        super().__init__()
        self.user_id = user_id

    async def on_submit(self, i: discord.Interaction):
        try:
            qty = int(self.quantity.value)
            if qty <= 0:
                raise ValueError
        except ValueError:
            return await i.response.send_message("Invalid quantity. Must be >0.", ephemeral=True)

        await i.response.send_message("⏳ Firing specialists...", ephemeral=True)

        with get_db_cursor() as c:
            # Get all specialist ids (Engineer, Auditor, Shark, Logistics)
            c.execute("SELECT id FROM employees WHERE user_id = ? AND specialization IN ('Engineer','Auditor','Shark','Logistics')", (self.user_id,))
            spec_ids = [row[0] for row in c.fetchall()]
            if not spec_ids:
                return await i.edit_original_response(content="No specialists to fire.")
            if len(spec_ids) < qty:
                return await i.edit_original_response(content=f"Only {len(spec_ids)} specialists available. Cannot fire {qty}.")

            to_fire = random.sample(spec_ids, qty)
            for sid in to_fire:
                c.execute("DELETE FROM employees WHERE id = ?", (sid,))
            log_business_event(c, self.user_id, "MASS_SPECIALIST_FIRE", f"Fired {qty} specialists (random)")

        await i.edit_original_response(content=f"Successfully fired {qty} specialists.")

class MassCyberSpecialistModal(discord.ui.Modal, title="Mass Hire Cyber Specialists"):
    specialist_type = discord.ui.TextInput(
            label="Specialist type",
            placeholder="offensive or defensive",
            max_length=10,
            required=True
    )
    quantity = discord.ui.TextInput(
            label="Number to hire",
            placeholder="e.g., 5",
            min_length=1,
            max_length=3,
            required=True
    )

    def __init__(self, user_id: int, view: CybersecurityView):
            super().__init__()
            self.user_id = user_id
            self.view = view

    async def on_submit(self, i: discord.Interaction):
            try:
                    qty = int(self.quantity.value)
                    spec_type = self.specialist_type.value.strip().lower()
                    if qty <= 0 or spec_type not in ("offensive", "defensive"):
                            raise ValueError
            except ValueError:
                    return await i.response.send_message("Invalid input. Quantity must be >0, type must be offensive or defensive.", ephemeral=True)

            await i.response.send_message("⏳ Hiring cyber specialists...", ephemeral=True)

            with get_db_cursor() as c:
                    biz = c.execute("SELECT capital, hq_level, strike_active FROM businesses WHERE user_id = ?", (self.user_id,)).fetchone()
                    if not biz:
                            return await i.edit_original_response(content="No business found.")
                    capital, hq_level, strike = biz
                    if strike == 1:
                            return await i.edit_original_response(content="Cannot hire during a strike! Resolve it first.")

                    current_spec = get_security_specialists_count(c, self.user_id)
                    max_spec = get_max_specialists(c, self.user_id)
                    if current_spec + qty > max_spec:
                            return await i.edit_original_response(content=f"Not enough capacity! Max {max_spec} specialists, you have {current_spec}.")

                    cost_per = get_hire_cost(c, self.user_id, "cyber")
                    total_cost = cost_per * qty
                    if capital < total_cost:
                            return await i.edit_original_response(content=f"Insufficient capital. Need A$ {total_cost:,} to hire {qty} specialists.")

                    success = False
                    for _ in range(3):
                            if atomic_business_update(c, self.user_id, -total_cost):
                                    success = True
                                    break
                            await asyncio.sleep(0.1)
                    if not success:
                            return await i.edit_original_response(content="Balance updated concurrently. Please try again.")

                    for _ in range(qty):
                            c.execute("INSERT INTO security_specialists (user_id, specialist_type, hired_at, wage) VALUES (?, ?, ?, ?)",
                                      (self.user_id, spec_type, time.time(), SECURITY_SPECIALIST_WAGE))
                    log_business_event(c, self.user_id, "MASS_CYBER_HIRE", f"Hired {qty} {spec_type} cyber specialists for A$ {total_cost:,}")

            # Refresh the Cybersecurity view
            self.view.update_fire_dropdown()
            embed = await self.view.get_embed()
            await i.message.edit(embed=embed, view=self.view)
            await i.edit_original_response(content=f"Successfully hired {qty} **{spec_type}** cyber specialists for A$ {total_cost:,}.")

class MassCyberFireModal(discord.ui.Modal, title="Mass Fire Cyber Specialists"):
    quantity = discord.ui.TextInput(
            label="Number to fire (randomly)",
            placeholder="e.g., 5",
            min_length=1,
            max_length=3,
            required=True
    )

    def __init__(self, user_id: int, view: CybersecurityView):
            super().__init__()
            self.user_id = user_id
            self.view = view

    async def on_submit(self, i: discord.Interaction):
            try:
                    qty = int(self.quantity.value)
                    if qty <= 0:
                            raise ValueError
            except ValueError:
                    return await i.response.send_message("Invalid quantity. Must be >0.", ephemeral=True)

            await i.response.send_message("⏳ Firing cyber specialists...", ephemeral=True)

            with get_db_cursor() as c:
                    c.execute("SELECT id FROM security_specialists WHERE user_id = ?", (self.user_id,))
                    spec_ids = [row[0] for row in c.fetchall()]
                    if not spec_ids:
                            return await i.edit_original_response(content="No cyber specialists to fire.")
                    if len(spec_ids) < qty:
                            return await i.edit_original_response(content=f"Only {len(spec_ids)} specialists available. Cannot fire {qty}.")

                    to_fire = random.sample(spec_ids, qty)
                    for sid in to_fire:
                            c.execute("DELETE FROM security_specialists WHERE id = ?", (sid,))
                    log_business_event(c, self.user_id, "MASS_CYBER_FIRE", f"Fired {qty} cyber specialists (random)")

            # Refresh the Cybersecurity view
            self.view.update_fire_dropdown()
            embed = await self.view.get_embed()
            await i.message.edit(embed=embed, view=self.view)
            await i.edit_original_response(content=f"Successfully fired {qty} cyber specialists.")


class MassActionView(discord.ui.View):
    def __init__(self, user_id: int):
        super().__init__(timeout=600)
        self.user_id = user_id

    async def interaction_check(self, i: discord.Interaction) -> bool:
        if i.user.id != self.user_id:
            await i.response.send_message("This action is not for you. Stop it. Get help.", ephemeral=True)
            return False
        return True

    @discord.ui.select(placeholder="Select action", options=[
        discord.SelectOption(label="Mass Hire", value="hire", description="Hire multiple regular staff"),
        discord.SelectOption(label="Mass Hire Specialists", value="hire_specialists", description="Hire multiple Engineers/Auditors/Sharks/Logistics"),
        discord.SelectOption(label="Mass Fire", value="fire", description="Fire multiple regular employees randomly"),
        discord.SelectOption(label="Mass Fire Specialists", value="fire_specialists", description="Fire multiple specialists randomly")
    ])
    async def action_select(self, i: discord.Interaction, select: discord.ui.Select):
        action = select.values[0]
        if action == "hire_specialists":
            await i.response.send_modal(MassSpecialistModal(i.user.id))
        elif action == "fire_specialists":
            await i.response.send_modal(MassFireSpecialistsModal(i.user.id))
        else:
            await i.response.send_modal(MassQuantityModal(i.user.id, action))
        self.stop()

# ==========================================
# 🏙️ THE BUSINESS COG (Main Logic)
# ==========================================
class Business(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.setup_db()
        self.daily_cycle.start()
        self.ticker_feed.start()
        self.lottery_cycle.start()
        self.inactivity_scanner.start()
        self.partnership_decay.start()

    def setup_db(self):
        with get_db_cursor() as c:
            c.execute('''CREATE TABLE IF NOT EXISTS businesses (
                user_id INTEGER PRIMARY KEY, name TEXT, capital INTEGER DEFAULT 0,
                owner_salary INTEGER DEFAULT 0, loan_balance INTEGER DEFAULT 0,
                installments_left INTEGER DEFAULT 0, days_open INTEGER DEFAULT 0,
                last_report TEXT DEFAULT 'No reports.', vp_id INTEGER, vp_title TEXT,
                demand_boost REAL DEFAULT 1.0, hq_level INTEGER DEFAULT 0,
                philosophy TEXT DEFAULT 'Mass Market', reputation INTEGER DEFAULT 100,
                is_public INTEGER DEFAULT 0, description TEXT DEFAULT '*A rising corporate empire.*',
                sector TEXT, tech_level INTEGER DEFAULT 0, marketing_budget INTEGER DEFAULT 0,
                quarter INTEGER DEFAULT 1, next_board_meeting REAL DEFAULT 0,
                strike_active INTEGER DEFAULT 0, last_audit REAL DEFAULT 0,
                last_active REAL DEFAULT 0
            )''')
            c.execute('''CREATE TABLE IF NOT EXISTS lottery (
                id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, entry_time REAL, country TEXT
            )''')
            c.execute('''CREATE TABLE IF NOT EXISTS employees (
                id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, name TEXT,
                salary INTEGER, morale INTEGER, specialization TEXT DEFAULT 'None'
            )''')
            c.execute('''CREATE TABLE IF NOT EXISTS business_products (
                id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, name TEXT,
                category TEXT, unit_price INTEGER, cost_to_make INTEGER,
                active INTEGER DEFAULT 1, lifetime_revenue INTEGER DEFAULT 0,
                lifetime_sold INTEGER DEFAULT 0,
                production_target INTEGER DEFAULT 100, quality_tier TEXT DEFAULT 'Standard'
            )''')

            try:
                c.execute("ALTER TABLE businesses ADD COLUMN last_restructure REAL DEFAULT 0")
            except sqlite3.OperationalError:
                pass

            c.execute('''CREATE TABLE IF NOT EXISTS market_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT, event_text TEXT,
                sector TEXT, modifier_json TEXT, days_remaining INTEGER
            )''')
            c.execute('''CREATE TABLE IF NOT EXISTS config (key TEXT PRIMARY KEY, value TEXT)''')
            c.execute('''CREATE TABLE IF NOT EXISTS business_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER,
                type TEXT, description TEXT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )''')
            c.execute('''CREATE TABLE IF NOT EXISTS quarterly_reports (
                user_id INTEGER, quarter INTEGER, revenue_modifier REAL DEFAULT 1.0,
                PRIMARY KEY(user_id, quarter)
            )''')

                        # --- New tables for Cybersecurity & Sales ---
            c.execute('''CREATE TABLE IF NOT EXISTS security_specialists (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                specialist_type TEXT CHECK(specialist_type IN ('offensive', 'defensive')),
                hired_at REAL,
                FOREIGN KEY(user_id) REFERENCES businesses(user_id)
            )''')

            try:
                c.execute("ALTER TABLE security_specialists ADD COLUMN wage INTEGER DEFAULT 9000")
            except sqlite3.OperationalError:
                pass

            try:
                c.execute("ALTER TABLE businesses ADD COLUMN cached_audit TEXT DEFAULT ''")
            except sqlite3.OperationalError:
                pass

            c.execute('''CREATE TABLE IF NOT EXISTS attack_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                attacker_id INTEGER,
                target_id INTEGER,
                attack_type TEXT,
                success INTEGER,
                amount INTEGER,
                employees_poached TEXT,
                timestamp REAL,
                FOREIGN KEY(attacker_id) REFERENCES businesses(user_id),
                FOREIGN KEY(target_id) REFERENCES businesses(user_id)
            )''')

            try:
                c.execute("ALTER TABLE businesses ADD COLUMN last_restructure REAL DEFAULT 0")
            except sqlite3.OperationalError:
                pass

            c.execute('''CREATE TABLE IF NOT EXISTS trade_cooldowns (
                user_id INTEGER,
                symbol TEXT,
                last_trade REAL,
                PRIMARY KEY(user_id, symbol)
            )''')

            c.execute('''CREATE TABLE IF NOT EXISTS active_partnerships (
                user_id INTEGER PRIMARY KEY,
                tier TEXT CHECK(tier IN ('temu','xiaomi','apple','google')),
                start_time REAL,
                end_time REAL,
                original_reputation INTEGER,
                original_demand_boost REAL,
                FOREIGN KEY(user_id) REFERENCES businesses(user_id)
            )''')

            # Migrate old partnership table if it exists with wrong constraint
            c.execute("PRAGMA table_info(active_partnerships)")
            columns = [col[1] for col in c.fetchall()]
            if 'tier' in columns:
                # Check if the constraint already uses the new values
                c.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='active_partnerships'")
                create_sql = c.fetchone()[0]
                if "CHECK(tier IN ('temu','xiaomi','apple','google'))" not in create_sql:
                    # Rename old table, create new one, copy data
                    c.execute("ALTER TABLE active_partnerships RENAME TO active_partnerships_old")
                    c.execute('''CREATE TABLE active_partnerships (
                        user_id INTEGER PRIMARY KEY,
                        tier TEXT CHECK(tier IN ('temu','xiaomi','apple','google')),
                        start_time REAL,
                        end_time REAL,
                        original_reputation INTEGER,
                        original_demand_boost REAL,
                        FOREIGN KEY(user_id) REFERENCES businesses(user_id)
                    )''')
                    c.execute('''INSERT INTO active_partnerships (user_id, tier, start_time, end_time, original_reputation, original_demand_boost)
                                 SELECT user_id, tier, start_time, end_time, original_reputation, original_demand_boost FROM active_partnerships_old''')
                    c.execute("DROP TABLE active_partnerships_old")

        # Re-establishment fee tracking (in economy.db)
        try:
            with get_eco_cursor() as eco_c:
                eco_c.execute('''CREATE TABLE IF NOT EXISTS user_flags (
                    user_id INTEGER PRIMARY KEY,
                    last_large_withdrawal REAL DEFAULT 0
                )''')
        except Exception:
            pass

            columns_to_add = [
                ("businesses", "sector", "TEXT"),
                ("businesses", "last_audit", "REAL DEFAULT 0"),
                ("businesses", "tech_level", "INTEGER DEFAULT 0"),
                ("businesses", "last_attack_time", "REAL DEFAULT 0"),
                ("businesses", "marketing_budget", "INTEGER DEFAULT 0"),
                ("businesses", "quarter", "INTEGER DEFAULT 1"),
                ("businesses", "next_board_meeting", "REAL DEFAULT 0"),
                ("businesses", "strike_active", "INTEGER DEFAULT 0"),
                ("businesses", "country", "TEXT DEFAULT 'USA'"),
                ("businesses", "last_active", "REAL DEFAULT 0"),
                ("business_products", "category", "TEXT"),
                ("business_products", "quality_tier", "TEXT DEFAULT 'Standard'"),
                ("business_products", "lifetime_sold", "INTEGER DEFAULT 0"),
                ("business_products", "last_cycle_sold", "INTEGER DEFAULT 0"),
                ("business_products", "last_cycle_revenue", "INTEGER DEFAULT 0"),
            ]
            for table, col, dtype in columns_to_add:
                try:
                    c.execute(f"ALTER TABLE {table} ADD COLUMN {col} {dtype}")
                except sqlite3.OperationalError as e:
                    if "duplicate column name" not in str(e):
                        print(f"⚠️ Failed to add {col} to {table}: {e}")


    async def _post_to_channel(self, embed: discord.Embed, view: discord.ui.View = None):
        channel = self.bot.get_channel(BUSINESS_CHANNEL_ID)
        if channel:
            try: 
                if view: await channel.send(embed=embed, view=view)
                else: await channel.send(embed=embed)
            except: pass


    async def liquidate_company(self, user_id: int, name: str):
        """Full bankruptcy: wipes business, hits wallet, portfolio, and properties."""
        user = self.bot.get_user(user_id)
        wallet_deduction = 0
        portfolio_proceeds = 0

        # 1. Wipe all business data
        with get_db_cursor() as c:
            c.execute("DELETE FROM businesses WHERE user_id = ?", (user_id,))
            c.execute("DELETE FROM employees WHERE user_id = ?", (user_id,))
            c.execute("DELETE FROM business_products WHERE user_id = ?", (user_id,))
            c.execute("DELETE FROM business_logs WHERE user_id = ?", (user_id,))

        # 2. Deduct 25% of wallet or A$1M minimum, whichever is higher
        with get_eco_cursor() as c_eco:
            row = c_eco.execute("SELECT balance FROM wallets WHERE user_id = ?", (user_id,)).fetchone()
            if row:
                wallet_bal = row[0] or 0
                wallet_deduction = max(1_000_000, int(wallet_bal * 0.25))
                wallet_deduction = min(wallet_deduction, max(0, wallet_bal))
                if wallet_deduction > 0:
                    atomic_eco_balance_update(c_eco, user_id, -wallet_deduction)

        # 3. Sell 20% of stock portfolio and confiscate proceeds
        with get_eco_cursor() as c_eco:
            holdings = c_eco.execute("SELECT symbol, shares FROM portfolio WHERE user_id = ?", (user_id,)).fetchall()
            for symbol, shares in holdings:
                shares_to_sell = max(1, int(shares * 0.20))
                price_row = c_eco.execute("SELECT price FROM stocks WHERE symbol = ?", (symbol,)).fetchone()
                if price_row:
                    portfolio_proceeds += shares_to_sell * price_row[0]
                    new_shares = shares - shares_to_sell
                    if new_shares <= 0:
                        c_eco.execute("DELETE FROM portfolio WHERE user_id = ? AND symbol = ?", (user_id, symbol))
                    else:
                        c_eco.execute("UPDATE portfolio SET shares = ? WHERE user_id = ? AND symbol = ?", (new_shares, user_id, symbol))

        # 4. Property penalty: delete one random Elite property, or halve quality on all
        try:
            with get_eco_cursor() as c_eco:
                elite = c_eco.execute("SELECT id FROM properties WHERE user_id = ? AND tier = 'Elite' ORDER BY RANDOM() LIMIT 1", (user_id,)).fetchone()
                if elite:
                    c_eco.execute("DELETE FROM properties WHERE id = ?", (elite[0],))
                else:
                    c_eco.execute("UPDATE properties SET quality = MAX(1, CAST(quality * 0.5 AS INTEGER)) WHERE user_id = ?", (user_id,))
        except Exception:
            pass

        # 5. DM the bankrupted CEO
        if user:
            try:
                dm_embed = discord.Embed(title="BANKRUPTCY DECLARED", color=0xcf0606)
                dm_embed.description = (
                    f"**{name}** has been officially liquidated by the Athena Central Reserve.\n\n"
                    f"**Consequences Enforced:**\n"
                    f"• All employees, products, and business logs seized\n"
                    f"• **A$ {wallet_deduction:,}** deducted from your personal wallet\n"
                    f"• **20% of your stock portfolio** sold & confiscated (A$ {portfolio_proceeds:,} seized)\n"
                    f"• Property assets downgraded\n"
                )
                await user.send(embed=dm_embed)
            except Exception:
                pass

        # 6. Public announcement
        channel = self.bot.get_channel(BUSINESS_CHANNEL_ID)
        if channel:
            pub_embed = discord.Embed(title="Corporate Bankruptcy Notice", color=0xcf0606)
            pub_embed.description = f"The Athena Central Reserve has officially liquidated **{name}** (<@{user_id}>).\nThe company failed to maintain active operations and all assets have been seized."
            await channel.send(embed=pub_embed)

    def log_transaction(self, cursor, user_id, amount, type, description):
        cursor.execute(
            "INSERT INTO transactions (user_id, amount, type, description, timestamp) VALUES (?, ?, ?, ?, ?)",
            (user_id, amount, type, description, time.time())
        )

    async def sector_autocomplete(self, interaction: discord.Interaction, current: str):
        return [
            app_commands.Choice(name=s, value=s)
            for s in SECTORS
            if current.lower() in s.lower()
        ][:25]

    async def sector_autocomplete(self, interaction: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
        return [
            app_commands.Choice(name=s, value=s)
            for s in SECTORS
            if current.lower() in s.lower()
        ][:25]

    @app_commands.command(name="restructure", description="Change your company's industry sector (costly, resets many things)")
    @app_commands.autocomplete(new_sector=sector_autocomplete)
    async def restructure_company(self, i: discord.Interaction, new_sector: str):
        if new_sector not in SECTORS:
            return await i.response.send_message(f"❌ Invalid sector. Choose from: {', '.join(SECTORS)}", ephemeral=True)

        with get_db_cursor() as c:
            c.execute("""
                UPDATE businesses 
                SET capital = ?, reputation = 70, sector = ?, 
                    last_restructure = ?, hq_level = ?,
                    tech_level = 0, marketing_budget = 0, demand_boost = 1.0,
                    cached_audit = ''
                WHERE user_id = ?
            """, (new_capital, new_sector, now, new_hq_level, i.user.id))

            # Delete all existing products (they are sector-specific)
            c.execute("DELETE FROM business_products WHERE user_id = ?", (i.user.id,))
            row = c.fetchone()
            if not row:
                return await i.response.send_message("You don't own a business.", ephemeral=True)
                
            capital, reputation, strike_active, last_restructure, current_sector, current_hq = row

            if current_sector == new_sector:
                return await i.response.send_message(f"Your company is already in the {new_sector} sector.", ephemeral=False)

            if capital < 50_000_000:
                return await i.response.send_message(f"Restructuring requires at least A$ 50,000,000 capital. You have A$ {capital:,}.", ephemeral=False)

            if strike_active:
                return await i.response.send_message("Cannot restructure during an active worker strike. Resolve it first.", ephemeral=False)

            now = time.time()
            if last_restructure and (now - last_restructure) < 30 * 86400:
                remaining = int(30 * 86400 - (now - last_restructure))
                days = remaining // 86400
                hours = (remaining % 86400) // 3600
                return await i.response.send_message(f"Restructuring is on cooldown. Available again in {days}d {hours}h.", ephemeral=False)

            # --- Calculate Penalties ---
            new_capital = int(capital * 0.80) # Lose 20% of liquid capital
            
            # Downgrade HQ by 1 or 2 levels randomly, but NEVER go below level 1 (Leased Office Space)
            downgrade_amount = random.choice([1, 2])
            new_hq_level = max(1, current_hq - downgrade_amount)

            # --- Apply Changes to Database ---
            c.execute("""
                UPDATE businesses 
                SET capital = ?, reputation = 70, sector = ?, last_restructure = ?, hq_level = ?
                WHERE user_id = ?
            """, (new_capital, new_sector, now, new_hq_level, i.user.id))

        await i.response.send_message(
            f"**Corporate Restructuring Complete!**\n"
            f"You have successfully pivoted your company to the **{new_sector}** sector.\n\n"
            f"**Restructuring Penalties Applied:**\n"
            f"• **Capital:** Lost 20% of your liquid capital (A$ {capital:,} → A$ {new_capital:,})\n"
            f"• **Reputation:** Reset to 70%.\n"
            f"• **HQ Downgrade:** Downgraded by {current_hq - new_hq_level} level(s) to **{HQ_LEVELS[new_hq_level]['name']}**.\n\n"
            f"*You may restructure again in 30 days.*",
            ephemeral=False
        )


    @app_commands.command(name="calculate", description="Estimate employees needed for target production")
    @app_commands.describe(
        desired_output="How many units you want to produce per day",
        philosophy="Your production philosophy (affects output multiplier)",
        tech_level="Your current tech level (default: your actual tech level)",
        engineers="Number of Lead Engineers hired (capped at 10 in simulation, default: 0)",
        avg_morale="Average employee morale % (default: 100)"
    )
    @app_commands.choices(philosophy=[
        app_commands.Choice(name="Mass Market (capped at 1.2x output)", value="Mass Market"),
        app_commands.Choice(name="Artisan (0.5x output multiplier)", value="Artisan")
    ])
    async def biz_calc(self, i: discord.Interaction, desired_output: int, philosophy: app_commands.Choice[str],
                       tech_level: int = None, engineers: int = 0, avg_morale: int = 100):
        # Get their actual tech level if not provided
        if tech_level is None:
            with get_db_cursor() as c:
                c.execute("SELECT tech_level FROM businesses WHERE user_id = ?", (i.user.id,))
                row = c.fetchone()
                tech_level = row[0] if row else 0

        # Validate inputs
        if desired_output <= 0:
            return await i.response.send_message("❌ Desired output must be greater than 0.", ephemeral=True)
        if engineers < 0:
            return await i.response.send_message("❌ Engineers cannot be negative.", ephemeral=True)
        if not (0 <= avg_morale <= 100):
            return await i.response.send_message("❌ Morale must be between 0 and 100.", ephemeral=True)

        # Cap engineers at 10 (simulation hard cap)
        engineers = min(engineers, 10)

        # Calculate multipliers exactly as in _simulate_company_cycle
        tech_bonus = min(0.5, tech_level * 0.005)
        eng_mult = 1.0 + min(0.20, 0.05 * engineers) + tech_bonus   # each engineer +5% up to 20%, tech bonus up to 50%

        if philosophy.value == "Artisan":
            out_mult = 0.5 * eng_mult
        else:  # Mass Market
            out_mult = min(1.2, 1.0 * eng_mult)   # cap at 1.2x

        # Each employee produces 12 units per cycle, adjusted by morale and out_mult
        capacity_per_employee = 12 * (avg_morale / 100) * out_mult

        # Calculate employees needed (round up)
        import math
        employees_needed = math.ceil(desired_output / capacity_per_employee)

        # Calculate actual capacity with that many employees
        actual_capacity = int(employees_needed * capacity_per_employee)

        # Build the response
        embed = discord.Embed(title="Business Capacity Calculator (v2)", color=0xffffff)

        embed.add_field(name="Your Settings", value=(
            f"**Desired Output:** {desired_output:,} units/day\n"
            f"**Philosophy:** {philosophy.name}\n"
            f"**Tech Level:** {tech_level}\n"
            f"**Engineers Hired:** {engineers} (capped at 10)\n"
            f"**Avg Morale:** {avg_morale}%"
        ), inline=False)

        embed.add_field(name="Calculated Multipliers", value=(
            f"**Tech Bonus:** +{tech_bonus*100:.1f}%\n"
            f"**Engineer Multiplier:** {eng_mult:.2f}x\n"
            f"**Output Multiplier:** {out_mult:.2f}x\n"
            f"**Capacity per Employee:** {capacity_per_employee:.1f} units"
        ), inline=False)

        embed.add_field(name="Review", value=(
            f"**Employees Needed:** {employees_needed}\n"
            f"**Actual Capacity:** {actual_capacity:,} units/day\n"
            f"*Note: This assumes all employees maintain {avg_morale}% morale and engineers are capped at 10.*"
        ), inline=False)

        embed.set_footer(text="Tip: Use this to plan your hiring and product targets.")

        await i.response.send_message(embed=embed, ephemeral=False)

    @app_commands.command(name="fixcountry", description="ADMIN: Add missing country column to businesses table")
    @app_commands.default_permissions(administrator=True)
    async def fix_country_column(self, i: discord.Interaction):
        await i.response.defer(ephemeral=True)
        with get_db_cursor() as c:
            try:
                c.execute("ALTER TABLE businesses ADD COLUMN country TEXT DEFAULT 'USA'")
                await i.followup.send("<a:wt_toroexclaim:1480581004317036624> `country` column added successfully!", ephemeral=True)
            except sqlite3.OperationalError as e:
                if "duplicate column name" in str(e):
                    await i.followup.send("✅ Column already exists.", ephemeral=True)
                else:
                    await i.followup.send(f"❌ Error: {e}", ephemeral=True)

    @app_commands.command(name="attacks", description="View your recent cyber attack(s) history")
    async def attacks(self, i: discord.Interaction):
        with get_db_cursor() as c:
            c.execute("""
                SELECT attacker_id, target_id, attack_type, success, amount, timestamp
                FROM attack_logs
                WHERE attacker_id = ? OR target_id = ?
                ORDER BY timestamp DESC LIMIT 15
            """, (i.user.id, i.user.id))
            logs = c.fetchall()
        if not logs:
            return await i.response.send_message("No attack history found.", ephemeral=True)
        desc = ""
        for att, tgt, atype, suc, amt, ts in logs:
            direction = "→" if att == i.user.id else "←"
            date = datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
            if suc:
                desc += f"🟢 {date} {atype.upper()} {direction} {amt or '?'}\n"
            else:
                desc += f"🔴 {date} {atype.upper()} {direction} FAILED\n"
        embed = discord.Embed(title="Attack History", description=desc, color=0xffffff)
        await i.response.send_message(embed=embed, ephemeral=True)


    @commands.command(name="updatesalaries")
    @commands.is_owner()
    async def update_salaries(self, ctx):
        with get_db_cursor() as c:
            c.execute("UPDATE employees SET salary = 1800 WHERE specialization = 'None'")
            c.execute("UPDATE employees SET salary = 5500 WHERE specialization IN ('Engineer', 'Auditor', 'Shark')")
            await ctx.send(f"✅ Updated salaries for {c.rowcount} employees.")


    @app_commands.command(name="fix_restructured", description="ADMIN: Wipe products & reset tech/marketing for companies that already restructured")
    @app_commands.default_permissions(administrator=True)
    async def fix_restructured(self, i: discord.Interaction):
            await i.response.defer(ephemeral=True)
            with get_db_cursor() as c:
                        # Find all businesses that have ever restructured
                    c.execute("SELECT user_id, name FROM businesses WHERE last_restructure IS NOT NULL AND last_restructure > 0")
                    rows = c.fetchall()
                    if not rows:
                            return await i.followup.send("No businesses have restructured yet.", ephemeral=True)

                    fixed = []
                    for uid, name in rows:
                                # Delete all products
                            c.execute("DELETE FROM business_products WHERE user_id = ?", (uid,))
                                # Reset tech, marketing, demand boost, cached audit
                            c.execute("""
                                    UPDATE businesses 
                                    SET tech_level = 0, 
                                        marketing_budget = 0, 
                                        demand_boost = 1.0, 
                                        cached_audit = ''
                                        WHERE user_id = ?
                            """, (uid,))
                            fixed.append(f"• {name} (user {uid})")

                    await i.followup.send(
                            f"✅ **Cleaned up {len(fixed)} restructured companies:**\n" +
                            "\n".join(fixed[:10]) + (f"\n... and {len(fixed)-10} more" if len(fixed) > 10 else ""),
                            ephemeral=True
                    )

    @app_commands.command(name="bp", description="Force bankruptcy")
    @app_commands.default_permissions(administrator=True)
    async def force_bankruptcy(self, i: discord.Interaction, user: str):
        await i.response.defer(ephemeral=True)
        import re
        # Try to convert to int (user ID) else try to get member from mention
        try:
            uid = int(user)
            member = i.guild.get_member(uid) if i.guild else None
        except ValueError:
            # assume it's a mention <@...>
            match = re.match(r"<@!?(\d+)>", user)
            if match:
                uid = int(match.group(1))
                member = i.guild.get_member(uid) if i.guild else None
            else:
                return await i.followup.send("Invalid user format. Use user ID or mention.", ephemeral=True)

        with get_db_cursor() as c:
            biz = c.execute("SELECT name, capital FROM businesses WHERE user_id = ?", (uid,)).fetchone()
            if not biz:
                return await i.followup.send(f"User `{uid}` does not own a business.", ephemeral=True)
            name, capital = biz
        await self.liquidate_company(uid, name)
        await i.followup.send(f"**Bankruptcy executed!** <@{uid}>'s company `{name}` has been liquidated.", ephemeral=False)


    @app_commands.command(name="penalty", description="..")
    async def exploit_penalty(self, i: discord.Interaction, user: str, amount: int, liquidate: bool = False, reason: str = "Exploitation"):
        if i.user.id != 743411894416834590:
            return await i.response.send_message("Only the bot owner can use this command.", ephemeral=True)

        await i.response.defer(ephemeral=True)
        import re

        # Parse user (same as above)
        try:
            uid = int(user)
        except ValueError:
            match = re.match(r"<@!?(\d+)>", user)
            if match:
                uid = int(match.group(1))
            else:
                return await i.followup.send("Invalid user format.", ephemeral=True)

        # Deduct from wallet
        with get_eco_cursor() as eco:
            if amount > 0:
                # check if they have enough to avoid excessive debt (optional)
                bal_row = eco.execute("SELECT balance FROM wallets WHERE user_id = ?", (uid,)).fetchone()
                if bal_row and bal_row[0] + amount < -10_000_000:
                    return await i.followup.send("Amount would cause excessive debt. Reduce the penalty.", ephemeral=True)
                if not atomic_eco_balance_update(eco, uid, -amount):
                    return await i.followup.send("Failed to deduct funds (balance conflict).", ephemeral=True)
                self.log_transaction(eco, uid, -amount, "EXPLOIT_PENALTY", f"{reason}: -A${amount:,}")

        # Optionally liquidate the business
        if liquidate:
            with get_db_cursor() as biz_c:
                biz = biz_c.execute("SELECT name FROM businesses WHERE user_id = ?", (uid,)).fetchone()
                if biz:
                    await self.liquidate_company(uid, biz[0])
                    await i.followup.send(f"✅ Penalty applied: **-A${amount:,}** and business **{biz[0]}** liquidated for {reason}.", ephemeral=False)
                else:
                    await i.followup.send(f"✅ Penalty applied: **-A${amount:,}** (no business to liquidate).", ephemeral=False)
        else:
            await i.followup.send(f"✅ Penalty applied: **-A${amount:,}** for {reason}.", ephemeral=False)


    @app_commands.command(name="cap_tech", description="ADMIN: Cap all tech levels at 100 to rebalance")
    @app_commands.default_permissions(administrator=True)
    async def cap_tech(self, i: discord.Interaction):
        await i.response.defer(ephemeral=True)
        with get_db_cursor() as c:
            c.execute("UPDATE businesses SET tech_level = 100 WHERE tech_level > 100")
            count = c.rowcount
        await i.followup.send(f"✅ Capped tech levels for {count} businesses to 100.", ephemeral=True)


    @app_commands.command(name="bizmerge", description="ADMIN: Merge an alt business into a main business (transfers ONLY capital, then deletes alt)")
    @app_commands.default_permissions(administrator=True)
    async def biz_merge(self, i: discord.Interaction, alt_user: discord.Member, main_user: discord.Member):
        await i.response.defer(ephemeral=True)

        with get_db_cursor() as c:
            # Check if both users have businesses
            alt_biz = c.execute("SELECT name, capital FROM businesses WHERE user_id = ?", (alt_user.id,)).fetchone()
            main_biz = c.execute("SELECT name, capital FROM businesses WHERE user_id = ?", (main_user.id,)).fetchone()
            if not alt_biz:
                return await i.followup.send(f"{alt_user.mention} does not own a business.", ephemeral=True)
            if not main_biz:
                return await i.followup.send(f"{main_user.mention} does not own a business.", ephemeral=True)

            alt_name, alt_cap = alt_biz
            main_name, _ = main_biz

            # Transfer ONLY capital
            c.execute("UPDATE businesses SET capital = capital + ? WHERE user_id = ?", (alt_cap, main_user.id))

            # Delete the alt business entirely (employees, products, logs will be orphaned, but we also delete them)
            c.execute("DELETE FROM employees WHERE user_id = ?", (alt_user.id,))
            c.execute("DELETE FROM business_products WHERE user_id = ?", (alt_user.id,))
            c.execute("DELETE FROM business_logs WHERE user_id = ?", (alt_user.id,))
            c.execute("DELETE FROM businesses WHERE user_id = ?", (alt_user.id,))

            # Log the event (only on main business)
            log_business_event(c, main_user.id, "BUSINESS_MERGE", f"Merged capital A${alt_cap:,} from {alt_name} into {main_name}")

        await i.followup.send(
            f"Successfully transferred **A${alt_cap:,}** from **{alt_name}** (owned by {alt_user.mention}) to **{main_name}** (owned by {main_user.mention}).\n"
            f"The alt business has been deleted.",
            ephemeral=True
        )

    @app_commands.command(name="guidebiz", description="Read the official Athena Business Manual")
    async def bizguide(self, i: discord.Interaction):
        pages = []
        
        p1 = discord.Embed(title="꒰ა Athena Executive Manual  ⸝⸝", color=0xffffff)
        p1.description = (
            "Welcome to the Central Reserve's corporate sector. Here is everything you need to know about running a successful empire.\n"
            "\n"
            "<a:wb_bow15:1412784394631909509> **Incorporating**\n"
            "└ You need A$ 500,000 to start a business. If you are broke, you can take a corporate loan, but you will pay interest every quarter.\n\n"
            "<a:wb_bow15:1412784394631909509> **The Daily Cycle**\n"
            "└ Every few hours, the market simulates supply, demand, and payroll. Your products will sell, your employees will be paid, and your net profit (or loss) will be added to your Capital.\n\n"
            "<a:wb_bow15:1412784394631909509> **Executive Salary**\n"
            "└ Set a daily salary for yourself! If your business turns a profit, this amount is wired directly into your personal `/bal` wallet."
        )
        p1.set_image(url="https://i.pinimg.com/736x/85/0a/4f/850a4f1db62ca84991bca6d959f25892.jpg")
        p1.set_footer(text="Page 1 of 4 • Basics")
        pages.append(p1)

        p2 = discord.Embed(title="꒰ა Operations & Staffing  ⸝⸝", color=0xffffff)
        p2.description = (
            "\n\n"
            "<a:wb_bow15:1412784394631909509> **Human Resources**\n"
            "└ Employees generate production capacity. More staff = more products made daily. However, you must pay their salaries and keep their morale high.\n\n"
            "<a:wb_bow15:1412784394631909509> **Strikes & Morale**\n"
            "└ If Employee Morale drops below 20%, they will go on strike! Production will halt completely, bleeding you dry until you settle the strike via the Terminal.\n\n"
            "<a:wb_bow15:1412784394631909509> **Upgrading HQ**\n"
            "└ Upgrading from a Garage to an Office (and beyond) increases your maximum employee limit, allowing you to scale."
        )
        p2.set_footer(text="Page 2 of 4 • Operations")
        p2.set_image(url="https://i.pinimg.com/736x/85/0a/4f/850a4f1db62ca84991bca6d959f25892.jpg")
        pages.append(p2)

        p3 = discord.Embed(title="꒰ა R&D and Market Demand  ⸝⸝", color=0xffffff)
        p3.description = (
            "\n\n"
            "<a:wb_bow15:1412784394631909509> **Tech Levels (R&D)**\n"
            "└ Invest capital into R&D to increase your Tech Level. High tech levels reduce production costs, boost demand, and unlock the ability to make 'Premium' and 'Luxury' goods.\n\n"
            "<a:wb_bow15:1412784394631909509> **Launching Products**\n"
            "└ You set the Unit Price, Cost, and Target Output. Careful: If you overprice your goods (more than a 4x markup), demand will crater and you won't sell anything.\n\n"
            "<a:wb_bow15:1412784394631909509> **Marketing Blitz**\n"
            "└ Spend capital on Marketing to temporarily hyper-boost demand for your products. Great for clearing out excess capacity."
        )
        p3.set_footer(text="Page 3 of 4 • R&D")
        p3.set_image(url="https://i.pinimg.com/736x/85/0a/4f/850a4f1db62ca84991bca6d959f25892.jpg")
        pages.append(p3)

        p4 = discord.Embed(title="꒰ა Going Public (IPO)  ⸝⸝", color=0xffffff)
        p4.description = (
            "\n\n"
            "<a:wb_bow15:1412784394631909509> **Initial Public Offering**\n"
            "└ Once your company holds A$ 2,000,000 in Capital, you can hit the IPO button. This permanently lists your company on the Athena Stock Exchange (`/invest`).\n\n"
            "<a:wb_bow15:1412784394631909509> **Stock Value**\n"
            "└ Your stock price will physically rise and fall based on your actual corporate performance. If you hoard cash, your stock goes up. If you bleed money, it crashes.\n\n"
            "<a:wb_bow15:1412784394631909509> **Appointing a VP**\n"
            "└ You can appoint another player as your VP, CFO, or COO. They will automatically receive your daily Executive Salary as well!"
        )
        p4.set_footer(text="Page 4 of 4 • End Game")
        p4.set_image(url="https://i.pinimg.com/736x/85/0a/4f/850a4f1db62ca84991bca6d959f25892.jpg")
        pages.append(p4)

        view = BusinessGuideView(pages)
        await i.response.send_message(embed=pages[0], view=view, ephemeral=False)

    @app_commands.command(name="biz_repair_market", description="ADMIN: Global database sync to fix all legacy/corrupted base costs")
    @app_commands.default_permissions(administrator=True)
    async def biz_repair_market(self, i: discord.Interaction):
        await i.response.defer(ephemeral=True)
        updated_count = 0
        with get_db_cursor() as c:
            for sector, correct_cost in SECTOR_BASE_COSTS.items():
                c.execute("UPDATE business_products SET cost_to_make = ? WHERE category = ? AND cost_to_make != ?", (correct_cost, sector, correct_cost))
                updated_count += c.rowcount
        await i.followup.send(f"🔬 **Market Core Cleansed!** Successfully re-aligned **{updated_count}** corrupted product base costs across all server conglomerates to match official Central Reserve guidelines.")


    @tasks.loop(hours=24)
    async def partnership_decay(self):
        """Once per day, remove expired partnerships and subtract their specific buffs."""
        tiers_data = {
            "temu": {"rep": 10, "demand": 0.10},
            "xiaomi": {"rep": 20, "demand": 0.20},
            "apple": {"rep": 35, "demand": 0.35},
            "google": {"rep": 50, "demand": 0.50}
        }
        with get_db_cursor() as c:
            c.execute("SELECT user_id, tier FROM active_partnerships WHERE end_time <= ?", (time.time(),))
            expired = c.fetchall()
            for uid, tier in expired:
                data = tiers_data.get(tier, {"rep": 0, "demand": 0})
            # Subtract the partnership's specific buff instead of hard-resetting
                c.execute("UPDATE businesses SET reputation = MAX(0, reputation - ?), demand_boost = MAX(1.0, demand_boost - ?) WHERE user_id = ?", 
                          (data["rep"], data["demand"], uid))
                c.execute("DELETE FROM active_partnerships WHERE user_id = ?", (uid,))
                log_business_event(c, uid, "PARTNERSHIP_EXPIRED", f"{tier.capitalize()} partnership ended.")


    @tasks.loop(hours=8)
    async def lottery_cycle(self):
        """Runs every 8 hours to draw lottery winners"""
        with get_db_cursor() as c:
            entries = c.execute("SELECT user_id, country FROM lottery").fetchall()
            if not entries: return
            winner = random.choice(entries)
            user_id, country = winner
            prize = random.randint(5000, 11000)
            c.execute("DELETE FROM lottery")
            
            with get_eco_cursor() as c_eco:
                atomic_eco_balance_update(c_eco, user_id, prize)
            
            user = self.bot.get_user(user_id)
            if user:
                try: await user.send(f"🎉 **Lottery Winner!** You've won A$ {prize:,} in the Athena Central Reserve lottery!")
                except: pass
            
            channel = self.bot.get_channel(BUSINESS_CHANNEL_ID)
            if channel:
                embed = discord.Embed(title="Lottery Winner!", color=0xffffff)
                embed.description = f"Congratulations <@{user_id}>! You've won A$ {prize:,} in the Athena Central Reserve lottery!"
                await channel.send(embed=embed)

    @commands.command(name="lottery")
    async def lottery_cmd(self, ctx):
        """Enters the user into the lottery (button-based entry)"""
        with get_db_cursor() as c:
            if c.execute("SELECT 1 FROM lottery WHERE user_id = ?", (ctx.author.id,)).fetchone():
                return await ctx.send("You're already entered in the lottery! Wait for the next draw.")
            country_row = c.execute("SELECT country FROM businesses WHERE user_id = ?", (ctx.author.id,)).fetchone()
            country = country_row[0] if country_row else "USA"
            c.execute("INSERT INTO lottery (user_id, entry_time, country) VALUES (?, ?, ?)", (ctx.author.id, time.time(), country))
            await ctx.send("You've entered the lottery! Good luck! The next draw is in 8 hours.")

    @app_commands.command(name="biz_setcapital", description="ADMIN: Forcefully set a business's capital")
    @app_commands.default_permissions(administrator=True)
    async def biz_setcapital(self, i: discord.Interaction, user: discord.Member, amount: int):
        with get_db_cursor() as c:
            biz = c.execute("SELECT name FROM businesses WHERE user_id = ?", (user.id,)).fetchone()
            if not biz:
                return await i.response.send_message(f"<a:wt_torono:1480580892706603018> {user.name} does not own an active corporation.", ephemeral=True)
            c.execute("UPDATE businesses SET capital = ? WHERE user_id = ?", (amount, user.id))
        await i.response.send_message(f"<a:wt_toroexclaim:1480581004317036624> Successfully adjusted **{biz[0]}**'s capital to A$ {amount:,}.", ephemeral=True)

    @app_commands.command(name="downgrade_hq", description="ADMIN: Downgrade a company's HQ by one level, fire excess employees, refund cost difference")
    @app_commands.default_permissions(administrator=True)
    async def downgrade_hq(self, i: discord.Interaction, user: discord.Member):
        await i.response.defer(ephemeral=True)

        with get_db_cursor() as c:
            # Fetch current HQ level and capital
            row = c.execute("SELECT hq_level, capital FROM businesses WHERE user_id = ?", (user.id,)).fetchone()
            if not row:
                return await i.followup.send(f"{user.mention} does not own a business.", ephemeral=True)

            current_hq, capital = row
            if current_hq <= 0:
                return await i.followup.send(f"{user.mention} is already at the lowest HQ level (Mother's Garage). Cannot downgrade further.", ephemeral=True)

            new_hq = current_hq - 1
            # Get costs from HQ_LEVELS
            current_cost = HQ_LEVELS[current_hq]["cost"]
            new_cost = HQ_LEVELS[new_hq]["cost"]
            refund = current_cost - new_cost

            # Get max employees for new HQ
            new_max_emp = HQ_LEVELS[new_hq]["max_emp"]

            # Count current employees
            c.execute("SELECT id FROM employees WHERE user_id = ?", (user.id,))
            emp_ids = [row[0] for row in c.fetchall()]
            emp_count = len(emp_ids)

            # Fire excess employees if any
            fired_count = 0
            if emp_count > new_max_emp:
                to_fire = random.sample(emp_ids, emp_count - new_max_emp)
                for eid in to_fire:
                    c.execute("DELETE FROM employees WHERE id = ?", (eid,))
                fired_count = len(to_fire)

            # Update HQ level and refund capital
            c.execute("UPDATE businesses SET hq_level = ?, capital = capital + ? WHERE user_id = ?", (new_hq, refund, user.id))

            # Log the event
            log_business_event(c, user.id, "HQ_DOWNGRADE", f"Downgraded from level {current_hq} to {new_hq}, refunded A$ {refund:,}, fired {fired_count} employees")
            c.execute("INSERT INTO business_logs (user_id, type, description) VALUES (?, ?, ?)", (user.id, "HQ_DOWNGRADE", f"Admin {i.user.name} downgraded HQ from level {current_hq} to {new_hq}, refunded A$ {refund:,}, fired {fired_count} employees"))

        await i.followup.send(
            f"**HQ Downgrade Complete** for {user.mention}\n"
            f"• **Old HQ:** {HQ_LEVELS[current_hq]['name']} (Level {current_hq})\n"
            f"• **New HQ:** {HQ_LEVELS[new_hq]['name']} (Level {new_hq})\n"
            f"• **Refunded:** A$ {refund:,}\n"
            f"• **Employees Fired:** {fired_count} (to fit {new_max_emp} capacity)\n"
            f"*The refund has been added to the company's capital.*",
            ephemeral=True
        )

    @commands.command(name="cyclenext")
    @commands.is_owner()
    async def cyclenext(self, ctx):
        await ctx.send("⚙️ **Manual Override:** Forcing the Central Reserve corporate cycle to execute...")
        with get_db_cursor() as c:
            c.execute("INSERT OR REPLACE INTO config (key, value) VALUES ('last_daily_cycle', '0')")
        await self.daily_cycle.coro(self)
        await ctx.send("✅ **Cycle Executed!** Ledgers, products, and market statuses have been successfully updated.")

    @app_commands.command(name="biz_credit_legacy_ipos", description="ADMIN: Grant the retroactive 20% IPO underwriting capital bonus to existing public companies")
    @app_commands.default_permissions(administrator=True)
    async def biz_credit_legacy_ipos(self, i: discord.Interaction):
        await i.response.defer(ephemeral=True)
        credited_companies = []
        with get_db_cursor() as c:
            public_congloms = c.execute("SELECT user_id, name, capital FROM businesses WHERE is_public = 1").fetchall()
            for uid, name, capital in public_congloms:
                bonus = int(capital * 0.20)
                c.execute("UPDATE businesses SET capital = capital + ? WHERE user_id = ?", (bonus, uid))
                log_business_event(c, uid, "LEGACY_IPO_CREDIT", f"Received retroactive IPO injection of A$ {bonus:,}")
                credited_companies.append(f"• **{name}** -> Injected +A$ {bonus:,}")
                
        if not credited_companies:
            return await i.followup.send("No active public corporations found to credit.")
        report = "🏛️ **Institutional Underwriting Adjustment Complete!**\n\n" + "\n".join(credited_companies)
        await i.followup.send(report)

    @app_commands.command(name="bizawardcar", description="Gift an exclusive luxury corporate vehicle to a CEO")
    @app_commands.default_permissions(administrator=True)
    @app_commands.choices(car=[
        app_commands.Choice(name="Mercedes Maybach S680", value="Mercedes-Maybach S680"),
        app_commands.Choice(name="Rolls Royce Phantom", value="Rolls-Royce Phantom"),
        app_commands.Choice(name="Bentley Flying Spur", value="Bentley Flying Spur"),
        app_commands.Choice(name="BMW 760i xDrive", value="BMW 760i xDrive"),
        app_commands.Choice(name="Audi RS6 Avant", value="Audi RS6 Avant")
    ])
    async def biz_awardcar(self, i: discord.Interaction, user: discord.Member, car: app_commands.Choice[str]):
        with get_db_cursor() as c:
            biz = c.execute("SELECT name FROM businesses WHERE user_id = ?", (user.id,)).fetchone()
            if not biz:
                return await i.response.send_message(f"<a:wt_torono:1480580892706603018> {user.name} does not own an active corporation. They are not worthy of this car.", ephemeral=True)
                
        with get_eco_cursor() as c_eco:
            c_eco.execute('''CREATE TABLE IF NOT EXISTS inventory (user_id INTEGER, item_name TEXT, quantity INTEGER DEFAULT 1, PRIMARY KEY(user_id, item_name))''')
            c_eco.execute('''INSERT INTO inventory (user_id, item_name, quantity) VALUES (?, ?, 1) ON CONFLICT(user_id, item_name) DO UPDATE SET quantity = quantity + 1''', (user.id, car.value))
            
        await i.response.send_message(f"<a:wt_toroexclaim:1480581004317036624> **The Athena Central Reserve** has officially gifted an exclusive **{car.value}** to the CEO of **{biz[0]}**!", ephemeral=False)

    def _calculate_sector_supply_demand(self, c):
        c.execute("SELECT category, SUM(production_target * unit_price) as total_supply FROM business_products WHERE active = 1 GROUP BY category")
        supplies = {row[0]: row[1] for row in c.fetchall()}
        sector_demand = {}
        for sector, supply in supplies.items():
            base_demand = supply * random.uniform(0.8, 1.4)
            events = c.execute("SELECT modifier_json FROM market_events WHERE sector = ? AND days_remaining > 0", (sector,)).fetchall()
            for (mod_json,) in events:
                base_demand *= json.loads(mod_json).get("demand_mult", 1.0)
            sector_demand[sector] = base_demand
        return supplies, sector_demand

    def _update_stock_prices_from_businesses(self, c_eco, c):
        c.execute("SELECT user_id, name, capital, is_public FROM businesses WHERE is_public = 1")
        for uid, name, cap, _ in c.fetchall():
            sym = name[:4].upper()
            row = c_eco.execute("SELECT price FROM stocks WHERE symbol = ?", (sym,)).fetchone()
            if row:
                change = 1.03 if cap > 500000 else 0.97 if cap < 200000 else 1.0
                new_price = max(10, int(row[0] * change))
                trend = "<:stockup_athena:1503776772850712616> UP" if new_price > row[0] else "<:stockdown_athena:1503776838789501171> DOWN"
                c_eco.execute("UPDATE stocks SET price = ?, trend = ? WHERE symbol = ?", (new_price, trend, sym))

    def _simulate_company_cycle(self, c, c_eco, biz, sector_boosts=None):
        uid = biz['user_id']
        c.execute("SELECT * FROM employees WHERE user_id = ?", (uid,))
        emps = c.fetchall()
        c.execute("SELECT * FROM business_products WHERE user_id = ? AND active = 1", (uid,))
        prods = c.fetchall()
        if not emps or not prods:
            return "⚠️ No active employees or products.", 0
        emp_count = len(emps)
        # Management overhead: +0.25% per employee beyond 20 (capped at +100%)
        emp_count = len(emps)
        management_mult = 1.0 + min(1.0, max(0, (emp_count - 20) * 0.005))
        total_payroll = int(sum(e[3] * management_mult for e in emps))
        avg_morale = sum(e[4] for e in emps) / max(1, emp_count)
        if biz['strike_active'] or avg_morale < 20:
            c.execute("UPDATE businesses SET strike_active = 1 WHERE user_id = ?", (uid,))
            return "🚨 STRIKE ACTIVE! Production halted. Listen to the workers.", 0
        # Security specialists wage
        c.execute("SELECT COUNT(id) FROM security_specialists WHERE user_id = ?", (uid,))
        specialist_count = c.fetchone()[0]
        specialist_wage_total = specialist_count * SECURITY_SPECIALIST_WAGE

        tech = biz['tech_level']
        cost_red = 0.05 if tech >= 20 else 0.0        # 10% → 5%
        dem_boost = 0.02 if tech >= 10 else 0.0       # 5% → 2%
        rep_boost = 5 if tech >= 25 else 0            # 10% → 5%

        # Hard caps on specialist counts (max 10 each)
        engineer_count = min(sum(1 for e in emps if e[5] == 'Engineer'), 20)
        auditor_count  = min(sum(1 for e in emps if e[5] == 'Auditor'), 20)
        shark_count    = min(sum(1 for e in emps if e[5] == 'Shark'), 20)
        
        logistics_count = min(sum(1 for e in emps if e[5] == 'Logistics'), 10)
        storage_reduction = 1.0 - min(0.20, 0.02 * logistics_count)  # multiplier

        tech_bonus = min(0.5, tech * 0.005) 
        eng_mult = 1.0 + min(0.40, 0.02 * engineer_count) + tech_bonus   # Caps at 20 engineers (0.02 × 20 = 0.40)
        aud_mult = 1.0 - min(0.30, 0.015 * auditor_count)                # Caps at 20 auditors (0.015 × 20 = 0.30)
        shark_mult = 1.0 + min(0.40, 0.02 * shark_count)                 # Caps at 20 sharks (0.02 × 20 = 0.40)

        # Calculate the global sector multiplier on the fly without overwriting the DB
        sector_mult = sector_boosts.get(biz.get('sector'), 1.0) if sector_boosts else 1.0

        rep_mod = biz['reputation'] / 100.0
        if biz['philosophy'] == 'Artisan':
            demand = random.uniform(0.9, 1.2) * rep_mod * (biz['demand_boost'] + dem_boost) * shark_mult * sector_mult
            out_mult = 0.5 * eng_mult
            new_rep = min(100, biz['reputation'] + 2 + rep_boost)
        else:
            demand = random.uniform(1.0, 1.5) * rep_mod * (biz['demand_boost'] + dem_boost) * shark_mult * sector_mult
            out_mult = min(1.2, 1.0 * eng_mult)
            new_rep = max(0, biz['reputation'] - 3 + rep_boost)

        demand = min(3, demand)   # never exceed 2.5x base demand

        factory_cap = int(sum(12 * (e[4]/100) for e in emps) * out_mult)
        total_targets = sum(max(1, p[8]) for p in prods)
        
        tot_rev = tot_cost = 0
        storage_total = 0
        for p in prods:
            p_id, name, sector, price, cost, active, rev, target, tier = p[0], p[2], p[3], p[4], p[5], p[6], p[7], p[8], p[9]
            tier_data = QUALITY_TIERS.get(tier, QUALITY_TIERS['Standard'])
            adj_price = int(price * tier_data['price_mult'])
            adj_cost = int(cost * tier_data['cost_mult'] * (1 - cost_red))
            
            allocated_cap = max(1, int(factory_cap * (max(1, target) / max(1, total_targets))))
            made = min(target, allocated_cap)
            
            prod_dem = demand * tier_data['demand_elasticity']
            base_sold = min(made, int(made * prod_dem))
            margin_ratio = price / max(1, SECTOR_BASE_COSTS.get(sector, 300))
            
            if margin_ratio > 3.0:
                sold = 0
            elif margin_ratio > 2.5:
                sold = int(base_sold * 0.15)
            elif margin_ratio > 2.0:
                sold = int(base_sold * 0.40)
            elif margin_ratio > 1.5:
                sold = int(base_sold * 0.65)
            else:
                sold = base_sold
            
            # Storage cost for unsold inventory (10% of cost per unsold unit)
            unsold = made - sold
            if unsold > 0:
                storage_cost = int(unsold * adj_cost * 0.27 * storage_reduction)
                tot_cost += storage_cost
                storage_total += storage_cost

            revenue = sold * adj_price
            tot_rev += revenue
            tot_cost += made * (adj_cost * aud_mult)
            c.execute("UPDATE business_products SET lifetime_revenue = lifetime_revenue + ?, lifetime_sold = lifetime_sold + ? WHERE id = ?", (revenue, sold, p_id))
            c.execute("UPDATE business_products SET last_cycle_sold = ?, last_cycle_revenue = ? WHERE id = ?", (sold, revenue, p_id))

        overhead = int((10000 + emp_count * 500) * aud_mult)
        loan_pay = biz['loan_balance'] // max(1, biz['installments_left']) if biz['installments_left'] > 0 else 0
        if loan_pay > 0:
            new_loan_balance = biz['loan_balance'] - loan_pay
            new_installments = biz['installments_left'] - 1
            if new_installments <= 0:
                new_loan_balance = 0
                new_installments = 0
            c.execute(
                "UPDATE businesses SET loan_balance = ?, installments_left = ? WHERE user_id = ?",
                (new_loan_balance, new_installments, uid)
            )
        exec_pay = biz['owner_salary'] * (2 if biz['vp_id'] else 1)
        total_exp = total_payroll + overhead + tot_cost + loan_pay + exec_pay
        total_exp += specialist_wage_total

        net_profit = int(tot_rev - total_exp)
        
        country = biz.get('country', 'USA')
        if not country: country = 'USA'
        brackets = COUNTRY_TAX_RATES.get(country, COUNTRY_TAX_RATES['USA'])['brackets']

        # Marginal tax calculation
        tax_bill = 0
        if net_profit > 0:
            remaining = net_profit
            prev_threshold = 0
            for threshold, rate in brackets:
                if remaining <= 0:
                    break
                taxable = min(remaining, threshold - prev_threshold)
                tax_bill += int(taxable * rate)
                remaining -= taxable
                prev_threshold = threshold
            net_profit -= tax_bill
            log_business_event(c, uid, "TAX_PAID", f"Paid {tax_bill} in taxes")
            try:
                c.execute("UPDATE config SET value = CAST(value AS INTEGER) + ? WHERE key = 'central_reserve_pool'", (tax_bill,))
            except:
                c.execute("INSERT OR IGNORE INTO config (key, value) VALUES ('central_reserve_pool', ?)", (str(tax_bill),))
        
        new_cap = biz['capital'] + net_profit
        
        # Build report with separate storage line
        report = (
            f"+ Gross Revenue : A$ {tot_rev:,}\n"
            f"- Mfg Costs     : A$ {int(tot_cost - storage_total):,}\n"
        )
        if storage_total > 0:
            report += f"- Storage Fees  : A$ {int(storage_total):,}\n"
        report += (
            f"- Staff Payroll : A$ {total_payroll:,}\n"
            f"- IT Nerds : A$ {specialist_wage_total:,}\n"
            f"- Facility Fees : A$ {overhead:,}\n"
            f"- Exec Salary   : A$ {exec_pay:,}\n"
        )

        if loan_pay > 0:
            report += f"- Loan Payment  : A$ {loan_pay:,}\n"
        if tax_bill > 0:
            report += f"- Corporate Tax : A$ {tax_bill:,}\n"
        report += f"==================================\n"
        if net_profit >= 0:
            report += f"+ NET PROFIT    : A$ {net_profit:,}"
        else:
            report += f"- NET LOSS      : A$ {abs(net_profit):,}"
        
        c.execute("UPDATE businesses SET capital = ?, reputation = ?, last_report = ? WHERE user_id = ?", (new_cap, new_rep, report, uid))
        
        if biz['owner_salary'] > 0 and new_cap >= exec_pay:
            with get_eco_cursor() as ec:
                if atomic_eco_balance_update(ec, uid, biz['owner_salary']):
                    log_business_event(c, uid, "SALARY_PAYOUT", f"Executive salary") 
                if biz['vp_id']:
                    atomic_eco_balance_update(ec, biz['vp_id'], biz['owner_salary'])
        c.execute("UPDATE employees SET morale = MAX(10, morale - 5) WHERE user_id = ?", (uid,))
        return f"Net: A$ {net_profit:,}", net_profit

    def _trigger_board_meeting(self, c, user_id):
        crises = [
            {"type": "Supply Chain Disruption", "opts": [
                {"desc": "Air freight (Fast, -A$80k)", "capital": -80000, "rep": 5},
                {"desc": "Negotiate locally (Slow, +Rep)", "capital": 0, "rep": 15},
                {"desc": "Cut production (Save cash)", "capital": 50000, "rep": -10}
            ]},
            {"type": "Data Breach Scandal", "opts": [
                {"desc": "Full transparency (+Rep, -A$90k)", "capital": -90000, "rep": 20},
                {"desc": "Silence & PR spin (Risky)", "capital": -70000, "rep": -5},
                {"desc": "Blame intern (-Morale)", "capital": 0, "rep": -15}
            ]},
            {"type": "Competitor Price War", "opts": [
                {"desc": "Match prices (Margin hit)", "capital": -40000, "rep": 10},
                {"desc": "Hold premium (Risk share)", "capital": 0, "rep": -5},
                {"desc": "Marketing blitz (A$40k)", "capital": -40000, "rep": 15}
            ]}
        ]
        crisis = random.choice(crises)
        next_meeting = time.time() + 3600 * random.randint(12, 48)
        c.execute("UPDATE businesses SET next_board_meeting = ? WHERE user_id = ?", (next_meeting, user_id))
        
        embed = discord.Embed(title=f"꒰ა Board Meeting Required  ⸝⸝", color=0xffffff)
        desc = (
            f"<@{user_id}>, your board of directors has called an emergency session to address a developing situation.\n"
            f"\n\n"
            f"**Crisis Type:** {crisis['type']}\n"
            f"└ *Your decision will immediately impact your capital and global reputation.*\n\n"
            f"**Proposed Strategies:**\n"
            f"<a:w_sparkles3:1375479757730222081> **Option 1:** {crisis['opts'][0]['desc']}\n"
            f"<a:w_sparkles2:1375479642760282173> **Option 2:** {crisis['opts'][1]['desc']}\n"
            f"<a:w_sparkles1:1375479535847477249> **Option 3:** {crisis['opts'][2]['desc']}\n\n"
        )
        embed.description = desc
        embed.set_footer(text="Decision Mandatory • Athena Central Reserve")
        
        view = BoardMeetingView(user_id, crisis)
        asyncio.create_task(self._post_to_channel(embed, view))

    def _generate_market_events(self, c):
        if random.random() < 0.4:
            sector = random.choice(SECTORS)
            events = [
                ("<a:wt_torocellphone:1503815758730366976> Viral Trend", {"demand_mult": 1.3}, 2),
                ("<a:wt_torosob:1480580873782034483> Supply Chain Crisis", {"demand_mult": 0.7}, 2),
                ("<a:wt_toroconfetti:1480580928719028396> Tax Break", {"demand_mult": 1.2}, 3),
                ("<a:wt_toronerd:1480580983593111602> Tech Breakthrough", {"demand_mult": 1.15}, 1),
            ]
            text, mod, dur = random.choice(events)
            c.execute("INSERT INTO market_events (event_text, sector, modifier_json, days_remaining) VALUES (?, ?, ?, ?)",
                      (f"{text} in {sector} sector!", sector, json.dumps(mod), dur))

    @tasks.loop(minutes=5)
    async def daily_cycle(self):
        with get_db_cursor() as c, get_eco_cursor() as c_eco:
            c.execute("SELECT value FROM config WHERE key = 'last_daily_cycle'")
            row = c.fetchone()
            now = time.time()
            
            if not row:
                c.execute("INSERT OR REPLACE INTO config (key, value) VALUES ('last_daily_cycle', ?)", (str(now),))
                return 
                
            if (now - float(row[0])) < (5 * 3600):
                return
                
            c.execute("INSERT OR REPLACE INTO config (key, value) VALUES ('last_daily_cycle', ?)", (str(now),))

            supplies, demands = self._calculate_sector_supply_demand(c)
            sector_boosts = {}
            for sector in supplies:
                ratio = demands.get(sector, 0) / max(1, supplies[sector])
                sector_boosts[sector] = max(0.5, min(2.0, ratio))
                c.execute("UPDATE businesses SET demand_boost = ? WHERE sector = ?", (boost, sector))

            c.execute("SELECT * FROM businesses")
            cols = [desc[0] for desc in c.description]
            for r in c.fetchall():
                biz = dict(zip(cols, r))
                with get_eco_cursor() as c_eco_car:
                    c_eco_car.execute("SELECT 1 FROM user_vehicles u JOIN market_vehicles m ON u.vehicle_id = m.id WHERE u.user_id = ? AND m.price >= 200000", (biz['user_id'],))
                    has_luxury = c_eco_car.fetchone()
                
                rep_bonus = 1 if has_luxury else 0
                c.execute("UPDATE businesses SET reputation = MIN(100, reputation + ?) WHERE user_id = ?", (rep_bonus, biz['user_id']))

            c.execute("SELECT * FROM businesses")
            cols = [desc[0] for desc in c.description]
            for r in c.fetchall():
                biz = dict(zip(cols, r))
                uid = biz['user_id']
                sym = biz['name'][:4].upper()
                
                with get_eco_cursor() as c_eco_loop:
                    stock_res = c_eco_loop.execute("SELECT price FROM stocks WHERE symbol = ?", (sym,)).fetchone()
                
                stock_price = stock_res[0] if stock_res else 1000
                if stock_price >= 8000: confidence_mult = 1.25
                elif stock_price >= 5000: confidence_mult = 1.15
                elif stock_price >= 2500: confidence_mult = 1.05
                elif stock_price < 200: confidence_mult = 0.70
                else: confidence_mult = 1.0
                
                c.execute("UPDATE businesses SET demand_boost = demand_boost * ? WHERE user_id = ?", (confidence_mult, uid))
                
                rpt, net = self._simulate_company_cycle(c, c_eco, biz, sector_boosts)

                c.execute("UPDATE businesses SET demand_boost = MIN(2.5, demand_boost) WHERE user_id = ?", (uid,))
                
                # Demand boost decays 15% per cycle, marketing budget decays faster
                c.execute("UPDATE businesses SET marketing_budget = MAX(0, marketing_budget - 10000), days_open = days_open + 1 WHERE user_id = ?", (uid,))
                
                # Reset audit timer so a new audit can be generated next cycle
                c.execute("UPDATE businesses SET last_audit = 0 WHERE user_id = ?", (uid,))

                if biz['days_open'] % 28 == 0:
                    biz['quarter'] += 1
                    c.execute("UPDATE businesses SET quarter = ?, days_open = 0 WHERE user_id = ?", (biz['quarter'], biz['user_id']))
                    embed = discord.Embed(title="꒰ა Quarterly Earnings Call  ⸝⸝", color=0xffffff)
                    embed.description = f"<@{biz['user_id']}>, your Q{biz['quarter']} financial results are in. How will you present the company's trajectory to your shareholders?"
                    view = EarningsCallView(biz['user_id'], biz['quarter'])
                    asyncio.create_task(self._post_to_channel(embed, view))
                
                if biz['next_board_meeting'] <= time.time():
                    self._trigger_board_meeting(c, biz['user_id'])
                    
            self._update_stock_prices_from_businesses(c_eco, c)
            self._generate_market_events(c)

    @tasks.loop(minutes=5)
    async def ticker_feed(self):
        with get_db_cursor() as c:
            c.execute("SELECT value FROM config WHERE key = 'last_ticker_feed'")
            row = c.fetchone()
            now = time.time()
            
            if not row:
                c.execute("INSERT OR REPLACE INTO config (key, value) VALUES ('last_ticker_feed', ?)", (str(now),))
                return
                
            if (now - float(row[0])) < 3600:
                return
                
            c.execute("INSERT OR REPLACE INTO config (key, value) VALUES ('last_ticker_feed', ?)", (str(now),))

            top = c.execute("SELECT name, capital, sector FROM businesses ORDER BY capital DESC LIMIT 3").fetchall()
            if not top: return
            
            embed = discord.Embed(title="꒰ა Live Market Ticker  ⸝⸝", color=0xffffff)
            embed.description = "The most valuable conglomerates currently operating on the Athena Exchange."
            for i, (n, cap, sec) in enumerate(top, 1):
                embed.add_field(name=f"`#{i}` {n}", value=f"<:athenacoin:1503804322280902767> **A$ {cap:,}**\n<:wb_bow1:1276928697173147770> {sec}", inline=True)
            await self._post_to_channel(embed)


    @tasks.loop(hours=6)
    async def inactivity_scanner(self):
        now = time.time()

        with get_db_cursor() as c:
            businesses = c.execute(
                "SELECT user_id, name, capital, last_active FROM businesses"
            ).fetchall()

        to_liquidate = []

        for uid, name, capital, last_active in businesses:
            # Skip brand-new companies where last_active was never stamped
            if not last_active or last_active == 0:
                continue

            days_inactive = (now - last_active) / 86400

            # Only penalise shell companies — those with NO employees AND NO products
            with get_db_cursor() as c:
                emp_count = c.execute(
                    "SELECT COUNT(id) FROM employees WHERE user_id = ?", (uid,)
                ).fetchone()[0]
                prod_count = c.execute(
                    "SELECT COUNT(id) FROM business_products WHERE user_id = ? AND active = 1", (uid,)
                ).fetchone()[0]

            if emp_count > 0 or prod_count > 0:
                continue  # Active company — no action needed

            user = self.bot.get_user(uid)

            # If company has employees or products but still inactive for 14+ days
            if (emp_count > 0 or prod_count > 0) and days_inactive >= 14:
                penalty = max(5000, int(capital * 0.01))
                new_capital = capital - penalty
                with get_db_cursor() as c:
                    c.execute("UPDATE businesses SET capital = capital - ? WHERE user_id = ?", (penalty, uid))
                    log_business_event(c, uid, "INACTIVITY_PENALTY_ACTIVE",
                                       f"Company inactive for {int(days_inactive)} days (has staff/products) -> -A$ {penalty:,}")
                if user:
                    try:
                        e = discord.Embed(title="Inactivity Penalty", color=0xffffff)
                        e.description = f"**{name}** has been inactive for {int(days_inactive)} days despite having employees/products. Penalty: **A$ {penalty:,}**.\nRemaining capital: A$ {new_capital:,}."
                        await user.send(embed=e)
                    except:
                        pass

            # --- Day 3 warning ---
            if 3 <= days_inactive < 4:
                if user:
                    try:
                        e = discord.Embed(title="⚠️ Inactivity Warning — Day 3", color=0xffa500)
                        e.description = (
                            f"**{name}** has had no employees or products for **3 days**.\n\n"
                            f"Daily capital penalties begin on **Day 7**. Use `/business` to "
                            f"hire staff and launch products before then."
                        )
                        await user.send(embed=e)
                    except Exception:
                        pass

            # --- Day 5 warning ---
            elif 5 <= days_inactive < 6:
                if user:
                    try:
                        e = discord.Embed(title="⚠️ Inactivity Warning — Day 5", color=0xff6600)
                        e.description = (
                            f"**{name}** has had no activity for **5 days**.\n\n"
                            f"You have **2 days** before daily 5% capital fines begin. "
                            f"Log in and get your company running immediately."
                        )
                        await user.send(embed=e)
                    except Exception:
                        pass

            # --- Day 6 final warning ---
            elif 6 <= days_inactive < 7:
                if user:
                    try:
                        e = discord.Embed(title="🚨 FINAL WARNING — Bankruptcy Imminent", color=0xff0000)
                        e.description = (
                            f"**{name}** will begin incurring **5% daily capital penalties** "
                            f"in less than 24 hours.\n\n"
                            f"If capital reaches zero the company will be **forcibly liquidated** — "
                            f"your wallet, stocks, and properties will all take hits.\n\n"
                            f"Use `/business` NOW."
                        )
                        await user.send(embed=e)
                    except Exception:
                        pass

            # --- Day 7+ : apply 5% daily penalty ---
            elif days_inactive >= 7:
                penalty = max(1000, int(capital * 0.05))
                new_capital = capital - penalty

                with get_db_cursor() as c:
                    c.execute(
                        "UPDATE businesses SET capital = capital - ? WHERE user_id = ?",
                        (penalty, uid)
                    )
                    log_business_event(
                        c, uid, "INACTIVITY_PENALTY",
                        f"Shell company penalty (Day {int(days_inactive)}): -A$ {penalty:,}"
                    )

                if user:
                    try:
                        e = discord.Embed(title="📉 Inactivity Penalty Applied", color=0xff0000)
                        e.description = (
                            f"**{name}** has been fined **A$ {penalty:,}** (5% of capital) "
                            f"for {int(days_inactive)} days of inactivity with no staff or products.\n\n"
                            f"**Remaining Capital:** A$ {new_capital:,}\n\n"
                            f"*Hire employees and launch products to stop these deductions.*"
                        )
                        await user.send(embed=e)
                    except Exception:
                        pass

                # Queue for bankruptcy — avoids modifying DB mid-iteration
                if new_capital <= 0:
                    to_liquidate.append((uid, name))

        # Process all bankruptcies after the loop finishes
        for uid, name in to_liquidate:
            await self.liquidate_company(uid, name)


    @daily_cycle.before_loop
    @ticker_feed.before_loop
    @inactivity_scanner.before_loop
    async def before_loops(self):
        await self.bot.wait_until_ready()

    @app_commands.command(name="business")
    async def business_hub(self, i: discord.Interaction):
        with get_db_cursor() as c:
            biz = c.execute("SELECT name, capital, reputation, description, hq_level, sector, is_public, tech_level, marketing_budget FROM businesses WHERE user_id = ?", (i.user.id,)).fetchone()
            if not biz:
                v = discord.ui.View()
                v.add_item(discord.ui.Button(label="Fund It Yourself (500k)", style=discord.ButtonStyle.secondary, custom_id="f_out", emoji="<:w_moon:1412477166666514493>"))
                v.add_item(discord.ui.Button(label="Secure Central Reserve Loan", style=discord.ButtonStyle.secondary, custom_id="f_loan", emoji="<:s_white2:1382052523166142486>"))
                async def call(ix): await ix.response.send_modal(StartupModal(ix.data['custom_id']=="f_loan"))
                for child in v.children: child.callback = call
                return await i.response.send_message(embed=discord.Embed(title="꒰ა chérie  ⸝⸝", color=0xffffff, description="Establish your business for A$ 500k."), view=v, ephemeral=False)
             
            emps = c.execute("SELECT COUNT(id), AVG(morale) FROM employees WHERE user_id = ?", (i.user.id,)).fetchone()
            
        await i.response.send_message("<a:wt_torospin:1480580977867624540> *Accessing CEO Terminal...*", ephemeral=False)
        await asyncio.sleep(1.5)
        
        hq_lvl = biz[4] if biz[4] is not None else 0
        
        embed = discord.Embed(title=f"꒰ა {biz[0]}  ⸝⸝", color=0xffffff)
        desc = f"*{biz[3]}*\n\n"
        desc += f"<:athenacoin:1503804322280902767> **Liquid Capital:** A$ {biz[1]:,}\n"
        desc += f"└ **Brand Reputation:** {biz[2]}%\n\n"
        desc += f"<:btb_white3:1375474689467748517> **HQ Level:** {HQ_LEVELS[hq_lvl]['name']}\n"
        desc += f"└ **Workforce:** {emps[0] or 0} Staff (Morale: {int(emps[1]) if emps[1] else 100}%)\n\n"
        desc += f"<:w_mail:1435879826446745630> **Market Sector:** {biz[5] or 'Unassigned'}\n"
        desc += f"└ **R&D Level:** {biz[7]}  | **Marketing:** A$ {biz[8]:,}\n\n"
        embed.description = desc
        
        with get_db_cursor() as c:
            row = c.execute("SELECT value FROM config WHERE key = 'newspaper_banner'").fetchone()
            banner_url = row[0] if row else DEFAULT_BANNER
            
        embed.set_image(url=banner_url)
        embed.set_thumbnail(url=i.user.display_avatar.url)
        embed.set_footer(text="Athena Central Reserve")
        
        await i.edit_original_response(content=None, embed=embed, view=TerminalView(self.bot, i.user.id))

    @app_commands.command(name="appoint")
    async def appoint_vp(self, i: discord.Interaction, user: discord.Member):
        if user.bot or user.id == i.user.id: return await i.response.send_message("<a:wt_torono:1480580892706603018> Invalid user.", ephemeral=True)
        with get_db_cursor() as c:
            if not c.execute("SELECT 1 FROM businesses WHERE user_id = ?", (i.user.id,)).fetchone():
                return await i.response.send_message("<a:wt_torono:1480580892706603018> No business.", ephemeral=True)
        v = discord.ui.View()
        v.add_item(VPTitleDropdown(user))
        await i.response.send_message(f"Select title for {user.name}:", view=v, ephemeral=True)

    @app_commands.command(name="rename_company", description="Rename your company")
    async def rename_cmd(self, i: discord.Interaction):
        with get_db_cursor() as c:
            if not c.execute("SELECT 1 FROM businesses WHERE user_id = ?", (i.user.id,)).fetchone():
                return await i.response.send_message("<a:wt_torono:1480580892706603018> No business found.", ephemeral=True)
        await i.response.send_modal(RenameCompanyModal())

    @app_commands.command(name="set_banner", description="ADMIN: Set the newspaper embed banner image")
    @app_commands.default_permissions(administrator=True)
    async def set_banner(self, i: discord.Interaction, url: str):
        with get_db_cursor() as c:
            c.execute("INSERT OR REPLACE INTO config (key, value) VALUES ('newspaper_banner', ?)", (url,))
        await i.response.send_message("<a:wt_toroexclaim:1480581004317036624> Newspaper banner updated!")

    @app_commands.command(name="bizleaderboard", description="Top companies by capital")
    async def leaderboard(self, i: discord.Interaction):
        await i.response.defer()
        with get_db_cursor() as c:
            rows = c.execute("SELECT name, capital, reputation, sector, user_id FROM businesses ORDER BY capital DESC LIMIT 10").fetchall()
            
        e = discord.Embed(title="꒰ა Corporate Leaderboard  ⸝⸝", color=0xffffff)
        e.description = "*The Top 10 most highly valued conglomerates in the Central Reserve.*\n\n"
        
        desc = ""
        for rank, (n, cap, rep, sec, uid) in enumerate(rows, 1):
            user = self.bot.get_user(uid)
            ceo_name = user.name.upper() if user else "UNKNOWN CEO"
            
            if rank == 1: medal = "<:firstplace:1504526139199197444>"
            elif rank == 2: medal = "<:secondplace:1504526178688569394>"
            elif rank == 3: medal = "<:thirdplace:1504526220103127070>"
            else: medal = f"`#{rank}`"
                
            desc += f"{medal} **{n.upper()}** (CEO: {ceo_name})\n"
            desc += f"└ <:athenacoin:1503804322280902767> **A$ {cap:,}** | <:wb_bow11:1378053767294881874> {rep}% Rep | <:w_mail:1435879826446745630> {sec or 'N/A'}\n\n"
            
        e.description += desc if desc else "*No corporations established yet.*"
        e.set_footer(text="Athena Central Reserve")
        
        if i.guild and i.guild.icon: e.set_thumbnail(url=i.guild.icon.url)
        await i.followup.send(embed=e)

async def setup(bot):
    await bot.add_cog(Business(bot))