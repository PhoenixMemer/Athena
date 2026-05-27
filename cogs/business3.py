from __future__ import annotations
import discord
from discord import app_commands, Interaction
from discord.ext import commands, tasks
import sqlite3
import json
import time
import random
import asyncio
from datetime import datetime
from contextlib import contextmanager

# ==========================================
# CONFIGURATION & CONSTANTS
# ==========================================
BUSINESS_CHANNEL_ID = 1218599931837681734
DB_PATH = "business.db"
ECO_DB = "economy.db"
LOTTERY_COOLDOWN = 28800

HQ_LEVELS = {
    0: {"name": "Mother's Garage", "max_emp": 5, "cost": 0},
    1: {"name": "Leased Office Space", "max_emp": 50, "cost": 150_000},
    2: {"name": "Tel Aviv Campus", "max_emp": 500, "cost": 800_000},
    3: {"name": "Dubai Skyscraper", "max_emp": 2500, "cost": 3_000_000}
}

QUALITY_TIERS = {
    "Standard": {"cost_mult": 1.0, "price_mult": 1.0, "demand_elasticity": 1.0, "required_tech": 0},
    "Premium":  {"cost_mult": 1.4, "price_mult": 1.6, "demand_elasticity": 0.8, "required_tech": 5},
    "Luxury":   {"cost_mult": 2.0, "price_mult": 2.5, "demand_elasticity": 0.5, "required_tech": 15}
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

NAMES = ["Liam", "Emma", "Noah", "Olivia", "Trump", "Nova", "Elysia", "Sophia", "Mateo", "Isabella",
         "Lucas", "Labubu", "Arthur", "Yeo", "Phoenix", "Declan", "Ezra", "Chase", "Sarah", "Kyxrt"]

DEFAULT_BANNER = "https://i.pinimg.com/736x/32/8f/6c/328f6c628b745f20776421e73decf15e.jpg"

SECTOR_CATALOGS = {
    "Tech": ["Cloud Sync Pro", "AthenaOS Suite", "NeuralNet AI", "CyberShield Firewall", "Quantum Compute Unit", "Athens Smart Home Hub"],
    "Food": ["Gourmet Meal Kits", "Organic Snack Box", "Smart Vending Machine", "Premium Coffee Blend", "Farm to Table Delivery", "Plant Based Protein"],
    "Luxury": ["Designer Handbags", "Swiss Watches", "Custom Yacht Interiors", "Private Jet Leasing", "Rare Gemstone Jewelry", "Haute Couture Line"],
    "Retail": ["Fast Fashion Line", "Home Decor Essentials", "Eco Friendly Groceries", "Tech Gadget Store", "Seasonal Pop-Up Shop", "Subscription Box Service"],
    "Industrial": ["Heavy Machinery Parts", "Logistics Fleet", "Renewable Energy Grid", "Steel Manufacturing", "Chemical Processing Unit", "Warehouse Automation"],
    "Energy": ["Oil Extraction Pumps", "Disaster Coverup Guidebooks", "Anti Renewable Energy Pamphlets", "Enhanced Oil Recovery Techniques", "Gas Cylinder Technology", "Hydraulic Fracturing"]
}
SECTORS = list(SECTOR_CATALOGS.keys())

SECTOR_BASE_COSTS = {
    "Tech": 350,
    "Food": 250,
    "Luxury": 3000,
    "Retail": 300,
    "Industrial": 1200,
    "Energy": 1200
}

COUNTRY_TAX_RATES = {
    "USA": {
        "brackets": [
            (100000, 0.0),
            (500000, 0.05),
            (2000000, 0.15),
            (float('inf'), 0.30)
        ]
    },
    "UK": {
        "brackets": [
            (100000, 0.0),
            (500000, 0.07),
            (2000000, 0.18),
            (float('inf'), 0.35)
        ]
    },
    "Germany": {
        "brackets": [
            (100000, 0.0),
            (500000, 0.06),
            (2000000, 0.16),
            (float('inf'), 0.32)
        ]
    },
    "France": {
        "brackets": [
            (100000, 0.0),
            (500000, 0.08),
            (2000000, 0.19),
            (float('inf'), 0.37)
        ]
    },
    "Brazil": {
        "brackets": [
            (100000, 0.0),
            (500000, 0.09),
            (2000000, 0.20),
            (float('inf'), 0.40)
        ]
    },
    "China": {
        "brackets": [
            (100000, 0.0),
            (500000, 0.04),
            (2000000, 0.14),
            (float('inf'), 0.28)
        ]
    },
    "Vietnam": {
        "brackets": [
            (100000, 0.0),
            (500000, 0.03),
            (2000000, 0.12),
            (float('inf'), 0.15)
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
            await i.response.send_message("❌ Invalid entry. Please specify a clean integer amount of shares.", ephemeral=True)

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
            if amt <= 0: raise ValueError
            with get_db_cursor() as c:
                c.execute("SELECT capital FROM businesses WHERE user_id = ?", (i.user.id,))
                biz = c.fetchone()
                if not biz or biz[0] < amt:
                    return await i.response.send_message("<a:wt_torono:1480580892706603018> Insufficient capital.", ephemeral=True)
                boost = 1.0 + (amt / 100_000) * 0.1
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
        opts = [discord.SelectOption(label="Lead Engineer (A$ 15k)", value="Engineer"),
                discord.SelectOption(label="Quality Auditor (A$ 15k)", value="Auditor"),
                discord.SelectOption(label="Sales Shark (A$ 15k)", value="Shark")]
        super().__init__(placeholder="Hire Specialist...", options=opts)
    async def callback(self, i: discord.Interaction):
        with get_db_cursor() as c:
            c.execute("SELECT capital, hq_level FROM businesses WHERE user_id = ?", (i.user.id,))
            biz = c.fetchone()
            c.execute("SELECT COUNT(id) FROM employees WHERE user_id = ?", (i.user.id,))
            emps = c.fetchone()[0]
            if biz[0] < 15000: return await i.response.send_message("<a:wt_torocryflail:1480580960566378711> Not enough capital.", ephemeral=True)
            if emps >= HQ_LEVELS[biz[1]]["max_emp"]: return await i.response.send_message("<a:wt_torono:1480580892706603018> The HQ is full! Upgrade to a bigger campus to hire more employees.", ephemeral=True)
            c.execute("UPDATE businesses SET capital = capital - 15000 WHERE user_id = ?", (i.user.id,))
            c.execute("INSERT INTO employees (user_id, name, salary, morale, specialization) VALUES (?, ?, 4000, 100, ?)",
                (i.user.id, random.choice(NAMES), self.values[0]))
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
        with get_db_cursor() as c:
            c.execute("INSERT INTO businesses (user_id, name, capital, loan_balance, installments_left, reputation) VALUES (?, ?, ?, ?, ?, 100)",
                (i.user.id, self.b_name.value, capital, loan, inst))
        await i.response.send_message(f"<a:wt_toroleaf:1480580940785913967> {self.b_name.value} incorporated! Goodluck on your journey, make sure to read the guide.", ephemeral=True)

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
                atomic_eco_balance_update(c_eco, i.user.id, amt)
                
            await i.response.send_message(f"<a:wt_toroexclaim:1480581004317036624> Successfully wired A$ {amt:,} to your personal account.", ephemeral=False)
        except ValueError:
            await i.response.send_message("<a:wt_torono:1480580892706603018> Invalid amount.", ephemeral=True)

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

class ProductPerformanceView(discord.ui.View):
    def __init__(self, user_id): 
        super().__init__(timeout=180)
        self.user_id = user_id
        
    @discord.ui.button(label="Refresh", style=discord.ButtonStyle.secondary)
    async def refresh(self, i: discord.Interaction, btn): 
        await i.response.edit_message(embed=self.get_embed(), view=self)
        
    def get_embed(self):
        with get_db_cursor() as c:
            biz_row = c.execute("SELECT tech_level, sector FROM businesses WHERE user_id = ?", (self.user_id,)).fetchone()
            
            tech = biz_row[0] if biz_row else 0
            sector = biz_row[1] if biz_row else "Tech"
            cost_red = 0.1 if tech >= 20 else 0.0
            
            prods = c.execute("SELECT name, unit_price, cost_to_make, lifetime_revenue, quality_tier, production_target, lifetime_sold FROM business_products WHERE user_id = ?", (self.user_id,)).fetchall()
        
        embed = discord.Embed(title="꒰ა Product Analytics  ⸝⸝", color=0xffffff)
        if not prods: 
            embed.description = "No products launched."
            return embed
        
        desc = ""
        for name, price, cost, rev, tier, target, sold in prods:
            tier_data = QUALITY_TIERS.get(tier, QUALITY_TIERS['Standard'])
            adj_price = int(price * tier_data['price_mult'])
            adj_cost = int(cost * tier_data['cost_mult'] * (1 - cost_red))
            
            global_sector_base = SECTOR_BASE_COSTS.get(sector, 300)
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
                f"└ **Total Rev:** A$ {rev:,}\n"
                f"└ **Market Status:** {health}\n\n"
            )
            
        embed.description = desc
        return embed
    
    async def interaction_check(self, i: discord.Interaction) -> bool:
        if i.user.id != self.user_id:
            await i.response.send_message("<a:wt_torono:1480580892706603018> Access Denied. This terminal does not belong to you.", ephemeral=True)
            return False
        return True

class HRView(discord.ui.View):
    def __init__(self, user_id): 
        super().__init__(timeout=180)
        self.user_id = user_id
        self.add_item(FireEmployeeDropdown(user_id))
        self.add_item(HireSpecialistDropdown())

    async def interaction_check(self, i: discord.Interaction) -> bool:
        if i.user.id != self.user_id:
            await i.response.send_message("<a:wt_torono:1480580892706603018> Access Denied. This terminal does not belong to you.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Hire Staff (A$ 2k)", style=discord.ButtonStyle.secondary, row=2)
    async def hire(self, i: discord.Interaction, btn):
        with get_db_cursor() as c:
            biz = c.execute("SELECT capital, hq_level FROM businesses WHERE user_id = ?", (i.user.id,)).fetchone()
            emps = c.execute("SELECT COUNT(id) FROM employees WHERE user_id = ?", (i.user.id,)).fetchone()[0]
            if biz[0] < 2000: return await i.response.send_message("<a:wt_torono:1480580892706603018> Not enough capital, broke ahh.", ephemeral=True)
            if emps >= HQ_LEVELS[biz[1]]["max_emp"]: return await i.response.send_message("<a:wt_torono:1480580892706603018> Your HQ is full! Upgrade to a bigger campus.", ephemeral=True)
            c.execute("UPDATE businesses SET capital = capital - 2000 WHERE user_id = ?", (i.user.id,))
            c.execute("INSERT INTO employees (user_id, name, salary, morale, specialization) VALUES (?, ?, 1500, 80, 'None')", (i.user.id, random.choice(NAMES)))
        await i.response.send_message("<a:wt_toroexclaim:1480581004317036624> Wahoo, new staff hired!", ephemeral=True)

    @discord.ui.button(label="Host Event (A$ 5k)", style=discord.ButtonStyle.secondary, row=2)
    async def morale(self, i: discord.Interaction, btn):
        with get_db_cursor() as c:
            cap = c.execute("SELECT capital FROM businesses WHERE user_id = ?", (i.user.id,)).fetchone()[0]
            if cap < 5000: return await i.response.send_message("<a:wt_torono:1480580892706603018> Not enough capital. ||someone's not making it to Forbes 100||", ephemeral=True)
            c.execute("UPDATE businesses SET capital = capital - 5000 WHERE user_id = ?", (i.user.id,))
            c.execute("UPDATE employees SET morale = MIN(100, morale + 25) WHERE user_id = ?", (i.user.id,))
        await i.response.send_message("<a:wt_torolove:1480580899430203484> Morale boosted!", ephemeral=True)

class OpsView(discord.ui.View):
    def __init__(self, user_id):
        super().__init__(timeout=180)
        self.user_id = user_id
        self.add_item(PhilosophyDropdown())
        self.add_item(UpgradeProductDropdown(user_id))

    async def interaction_check(self, i: discord.Interaction) -> bool:
        if i.user.id != self.user_id:
            await i.response.send_message("<a:wt_torono:1480580892706603018> Access Denied. This terminal does not belong to you.", ephemeral=True)
            return False
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
                await it.response.send_message(f"📦 Great! Now select a base product type to develop for **{sector}**:", view=view2, ephemeral=False)
        
            sel.callback = sector_callback
            v = discord.ui.View()
            v.add_item(sel)
            return await i.response.send_message("🏭 You haven't chosen an industry yet! Select your business sector first:", view=v, ephemeral=False)
    
        sector = row[0]
        view3 = discord.ui.View(timeout=60)
        view3.add_item(ProductTypeDropdown(sector))
        await i.response.send_message(f"📦 Select a base product type to develop for your **{sector}** company:", view=view3, ephemeral=False)

    @discord.ui.button(label="CEO Payout", style=discord.ButtonStyle.secondary, row=3)
    async def payout_btn(self, i: discord.Interaction, btn):
        await i.response.send_modal(PayoutModal())

    @discord.ui.button(label="Edit Product", style=discord.ButtonStyle.secondary, row=2)
    async def edit_product_btn(self, i: discord.Interaction, btn):
        with get_db_cursor() as c:
            row = c.execute("SELECT sector FROM businesses WHERE user_id = ?", (i.user.id,)).fetchone()
        
        if not row or not row[0]:
            return await i.response.send_message("<a:wt_torono:1480580892706603018> You need a business sector first!", ephemeral=True)
            
        view = discord.ui.View()
        view.add_item(EditProductDropdown(i.user.id, row[0]))
        await i.response.send_message("<a:wt_torosilly:1480580853720551637> Select the product you wish to modify:", view=view, ephemeral=True)
    
    @discord.ui.button(label="Upgrade HQ", style=discord.ButtonStyle.secondary, row=2)
    async def hq(self, i: discord.Interaction, btn):
        with get_db_cursor() as c:
            biz = c.execute("SELECT capital, hq_level FROM businesses WHERE user_id = ?", (i.user.id,)).fetchone()
        nxt = biz[1] + 1
        if nxt not in HQ_LEVELS: return await i.response.send_message("<a:wt_torono:1480580892706603018> Max level.", ephemeral=True)
        cost = HQ_LEVELS[nxt]["cost"]
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
        super().__init__(timeout=60)
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
        super().__init__(timeout=86400)
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
            
        receipt = (
            "```diff\n"
            "--- CORPORATE BALANCE SHEET ---\n\n"
            f"  LIQUID CAPITAL : A$ {biz[0]:,}\n"
            f"  LOAN BALANCE   : A$ {biz[1]:,}\n\n"
            "--- LATEST CYCLE LEDGER ---\n"
            f"{biz[2]}\n```"
        )
        embed = discord.Embed(title="꒰ა chérie  ⸝⸝", color=0xffffff, description=receipt)
        await i.response.send_message(embed=embed, ephemeral=True)
    
    @discord.ui.button(label="Select Country", style=discord.ButtonStyle.secondary, row=3, emoji="<a:wt_toroleaf:1480580940785913967>")
    async def country_btn(self, i: discord.Interaction, btn):
        """Button to select country"""
        options = [
            discord.SelectOption(label="USA", description="United States of America", value="USA"),
            discord.SelectOption(label="UK", description="United Kingdom", value="UK"),
            discord.SelectOption(label="Germany", description="Federal Republic of Germany", value="Germany"),
            discord.SelectOption(label="France", description="French Republic", value="France"),
            discord.SelectOption(label="Brazil", description="Federative Republic of Brazil", value="Brazil"),
            discord.SelectOption(label="China", description="People's Republic of China", value="China"),
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
        with get_db_cursor() as c:
            emps = c.execute("SELECT name, salary, morale, specialization FROM employees WHERE user_id = ?", (i.user.id,)).fetchall()
        embed = discord.Embed(title="꒰ა ﹒chérie  ⸝⸝", color=0xffffff)
        if not emps: 
            embed.description = "No employees."
        else:
            desc = "👥 **Human Resources**\n"
            for n,s,m,sp in emps[:15]:
                desc += f"• **{n}** ({sp}) - A$ {s:,} | {m}% morale\n"
            if len(emps) > 15: desc += f"*...and {len(emps)-15} more.*\n"
            embed.description = desc
        await i.response.send_message(embed=embed, view=HRView(i.user.id), ephemeral=False)
    
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
            c_eco.execute("INSERT OR IGNORE INTO stocks (symbol, name, price, volatility, trend) VALUES (?, ?, ?, 3, 'FLAT')", (sym, biz[0], start_price))
            
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
            biz = c.execute("SELECT capital, owner_salary, days_open, last_report, sector, strike_active, last_audit, country, marketing_budget FROM businesses WHERE user_id = ?", (self.user_id,)).fetchone()
        
        now = time.time()
        if biz[6] and (now - biz[6]) < 14400:
            rem = int(14400 - (now - biz[6]))
            return await i.response.send_message(f"⏱️ Your corporate consultants are currently analyzing data. Come back in **{rem // 3600}h {(rem % 3600)//60}m**.", ephemeral=True)
            
        with get_db_cursor() as c:
            c.execute("UPDATE businesses SET last_audit = ? WHERE user_id = ?", (now, self.user_id))
            emps = c.execute("SELECT COUNT(id), SUM(salary), AVG(morale) FROM employees WHERE user_id = ?", (self.user_id,)).fetchone()
            prods = c.execute("SELECT name, unit_price, cost_to_make, production_target, quality_tier FROM business_products WHERE user_id = ? AND active = 1", (self.user_id,)).fetchall()
            tech_res = c.execute("SELECT tech_level FROM businesses WHERE user_id = ?", (self.user_id,)).fetchone()
        
        emp_count = emps[0] or 0
        avg_morale = emps[2] or 100
        advice = []
        
        if biz[5] == 1 or avg_morale < 20:
            advice.append("🚨 **CRITICAL: Worker Strike Active!** Morale is critically low (below 20%). Production is halted. Use the HR terminal to host an event immediately or settle the strike, otherwise your business will continue to bleed capital.")
        elif avg_morale < 25:
            advice.append("⚠️ **Warning: Low Morale.** Workers are unhappy (below 25%). A strike will occur if it drops below 20%. Invest in HR events to boost morale.")
        
        if not prods:
            advice.append("📦 **No Products:** You aren't producing anything. Launch a product in the Operations terminal to generate revenue.")
        else:
            total_target = sum(p[3] for p in prods)
            tech_level = tech_res[0] if tech_res else 0
            eng_mult = 1.0 + (tech_level * 0.02)
            factory_cap = int((emp_count * 50) * eng_mult) 
            
            if total_target > (factory_cap * 1.5):
                advice.append(f"⚠️ **Overproduction:** Your Daily Targets (approx {total_target:,}) vastly exceed your factory's capacity (approx {factory_cap:,}). You are paying baseline costs for units you physically cannot build. Lower your targets or hire more staff.")
            elif factory_cap > (total_target * 2):
                advice.append(f"⚠️ **Understaffed:** You have {emp_count} employees but low production targets. You are wasting capital on payroll for idle workers. Fire staff or increase production targets.")
            
            for p in prods:
                tier_data = QUALITY_TIERS.get(p[4], QUALITY_TIERS['Standard'])
                adj_cost = p[2] * tier_data['cost_mult']
                margin = p[1] / max(1, adj_cost)
                
                if margin > 4.0:
                    advice.append(f"🟥 **SEVERE OVERPRICING:** Your product **{p[0]}** is marked up by over 400%. You are losing 95% of your sales volume to buyer boycotts. Edit the price down immediately.")
                elif margin > 2.5:
                    advice.append(f"🟧 **High Price:** Your product **{p[0]}** is marked up over 2.5x. You are losing 70% of potential sales. Consider lowering to the 'Sweet Spot' (2.5x base cost).")
                elif margin > 1.5:
                    advice.append(f"🟨 **Good Pricing:** Your product **{p[0]}** is priced well. Consider increasing production to maximize revenue.")
                else:
                    advice.append(f"🟩 **Underpricing:** Your product **{p[0]}** is priced too low. You're missing out on potential profit. Consider increasing the price slightly.")
        
        if biz[0] < 50000:
            advice.append("📉 **Critical Capital Shortage:** Your liquid capital is dangerously low (below A$ 50,000). Consider injecting personal funds to stay afloat.")
        elif biz[0] < 100000:
            advice.append("⚠️ **Low Capital:** Your liquid capital is low (below A$ 100,000). Consider injecting personal funds to maintain operations.")
        
        if biz[1] > 0:
            debt_ratio = biz[1] / biz[0]
            if debt_ratio > 0.5:
                advice.append("⚠️ **High Debt Ratio:** Your debt is more than 50% of your capital. Consider paying down debt to improve your financial stability.")
            elif debt_ratio > 0.25:
                advice.append("⚠️ **Moderate Debt:** Your debt is more than 25% of your capital. Monitor your debt levels closely.")
        
        tax_rate = 0.0
        country = biz[7] or 'USA'
        brackets = COUNTRY_TAX_RATES.get(country, COUNTRY_TAX_RATES['USA'])['brackets']
        for threshold, rate in brackets:
            if biz[0] > threshold:
                tax_rate = rate
            else:
                break
        if tax_rate > 0.15:
            advice.append(f"⚠️ **High Tax Burden:** Your country's tax rate is {tax_rate*100:.1f}%. Consider expanding into countries with lower tax rates or optimizing your business structure to reduce your tax burden.")
        
        if tech_level < 10:
            advice.append(f"⚠️ **Underutilized R&D:** Your tech level is low ({tech_level}). Invest in R&D to unlock higher production efficiency and premium products.")
        
        if biz[8] < 5000:
            advice.append(f"💡 **Marketing Opportunity:** Your marketing budget is low (A$ {biz[8]:,}). Consider investing in marketing to boost demand for your products.")
        
        if biz[0] < 0:
            advice.append("🟥 **Negative Profit:** Your business is operating at a loss. Reassess your pricing, costs, and production targets immediately.")
        
        if biz[2] < 50:
            advice.append(f"⚠️ **Low Reputation:** Your brand reputation is low ({biz[2]}%). Consider investing in quality improvements and customer service to boost your reputation.")
        
        if emp_count > 0 and avg_morale < 70:
            advice.append(f"⚠️ **High Employee Turnover Risk:** Employee morale is low ({avg_morale}%). Consider hosting HR events to improve morale and reduce turnover.")
        
        if tech_level > 10 and not any(p[4] == 'Premium' or p[4] == 'Luxury' for p in prods):
            advice.append(f"💡 **Underutilized Tech:** You have high tech level ({tech_level}) but aren't producing premium or luxury products. Consider upgrading your products to unlock higher margins.")
        
        if country == 'China':
            advice.append("💡 **China Specific Opportunity:** Consider leveraging China's manufacturing advantages for cost-efficient production. However, be aware of potential trade restrictions.")
        elif country == 'USA':
            advice.append("💡 **USA Specific Opportunity:** Leverage the strong US market for premium products. Consider expanding into other Western markets for growth.")
        elif country == 'Germany':
            advice.append("💡 **Germany Specific Opportunity:** Germany is known for high-quality manufacturing. Consider positioning your brand as premium to leverage this reputation.")
        elif country == 'Vietnam':
            advice.append("💡 **Vietnam Specific Opportunity:** Vietnam offers low labor costs. Consider outsourcing production to Vietnam to reduce costs.")
        elif country == 'UK':
            advice.append("💡 **UK Specific Opportunity:** The UK has strong intellectual property protections. Consider registering patents here for your innovations.")
        elif country == 'France':
            advice.append("💡 **France Specific Opportunity:** France has strong luxury brand recognition. Consider positioning your products as premium luxury goods.")
        elif country == 'Brazil':
            advice.append("💡 **Brazil Specific Opportunity:** Brazil has a large domestic market. Consider focusing on local market penetration before expanding globally.")
        
        if not advice:
            advice.append("🟩 **Optimal Operations:** Your pricing, staffing, and morale look perfectly balanced! Keep up the good work, CEO.")
            
        embed = discord.Embed(title="ა Firm Analysis & Audit ⸝⸝", color=0xffffff)
        embed.description = "The corporate consultants have reviewed your operations:\n\n" + "\n\n".join(advice)
        embed.set_footer(text="Next audit available in 4 hours.")
        
        await i.response.send_message(embed=embed, ephemeral=True)
        
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("<a:wt_torono:1480580892706603018> Access Denied. This is classified corporate data.", ephemeral=True)
            return False
            
        if interaction.data.get('custom_id') == "strike_btn":
            embed = discord.Embed(title="꒰ა ﹒chérie  ⸝⸝", color=0xffffff, description="**UNION DEMANDS**")
            await interaction.response.send_message(embed=embed, view=SettlementView(interaction.user.id), ephemeral=True)
            return False
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
        super().__init__(timeout=60)
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
        # self.pick_reminder.start() # Commented out as loop task is not defined in this scope

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
                quarter INTEGER DEFAULT 1, next_board_meeting REAL DEFAULT 0, strike_active INTEGER DEFAULT 0,
                last_audit REAL DEFAULT 0
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
                production_target INTEGER DEFAULT 100, quality_tier TEXT DEFAULT 'Standard'
            )''')
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
        
        for table, col, dtype in [
            ("businesses", "sector", "TEXT"), 
            ("businesses", "last_audit", "REAL DEFAULT 0"), 
            ("businesses", "tech_level", "INTEGER DEFAULT 0"),
            ("businesses", "marketing_budget", "INTEGER DEFAULT 0"), 
            ("businesses", "quarter", "INTEGER DEFAULT 1"),
            ("businesses", "next_board_meeting", "REAL DEFAULT 0"), 
            ("businesses", "strike_active", "INTEGER DEFAULT 0"),
            ("business_products", "category", "TEXT"), 
            ("business_products", "quality_tier", "TEXT DEFAULT 'Standard'")
        ]:
            try: c.execute(f"ALTER TABLE {table} ADD COLUMN {col} {dtype}")
            except: pass

    async def _post_to_channel(self, embed: discord.Embed, view: discord.ui.View = None):
        channel = self.bot.get_channel(BUSINESS_CHANNEL_ID)
        if channel:
            try: 
                if view: await channel.send(embed=embed, view=view)
                else: await channel.send(embed=embed)
            except: pass

    @app_commands.command(name="help", description="View the bot's command help")
    async def help_cmd(self, i: discord.Interaction):
        """Displays a modal with all commands"""
        embed = discord.Embed(title="Athena Business Command Help", color=0xffffff)
        embed.description = "Here's a list of all available commands:"
        
        commands_list = [
            ("business", "Access your business terminal"),
            ("appoint", "Appoint a VP"),
            ("rename_company", "Rename your company"),
            ("set_banner", "Set the newspaper banner"),
            ("bizleaderboard", "View the top companies"),
            ("lottery", "Enter the daily lottery"),
            ("pick", "Pick a random item for a reward"),
            ("audit", "Run a business audit"),
            ("market", "View stock market prices"),
            ("buy", "Buy stocks"),
            ("sell", "Sell stocks"),
            ("portfolio", "View your investment portfolio"),
            ("heist", "Attempt a corporate heist"),
            ("daily", "Claim your daily allowance"),
            ("work", "Work at your job to earn money"),
            ("stake", "Stake money for guaranteed returns"),
            ("invest", "Invest in the stock market"),
            ("convert", "Convert between Mimu and Athena coins"),
            ("statement", "View your transaction history")
        ]
        
        for name, desc in commands_list:
            embed.add_field(name=f"/{name}", value=desc, inline=False)
        
        embed.set_footer(text="Use /business to start your business journey!")
        view = discord.ui.View()
        view.add_item(discord.ui.Button(label="Close", style=discord.ButtonStyle.danger, custom_id="close_help"))
        await i.response.send_message(embed=embed, view=view)

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

    def _simulate_company_cycle(self, c, c_eco, biz):
        uid = biz['user_id']
        c.execute("SELECT * FROM employees WHERE user_id = ?", (uid,))
        emps = c.fetchall()
        c.execute("SELECT * FROM business_products WHERE user_id = ? AND active = 1", (uid,))
        prods = c.fetchall()
        if not emps or not prods:
            return "⚠️ No active employees or products.", 0

        emp_count = len(emps)
        total_payroll = sum(e[3] for e in emps)
        avg_morale = sum(e[4] for e in emps) / max(1, emp_count)
        if biz['strike_active'] or avg_morale < 20:
            c.execute("UPDATE businesses SET strike_active = 1 WHERE user_id = ?", (uid,))
            return "🚨 STRIKE ACTIVE! Production halted. Listen to the workers.", 0

        tech = biz['tech_level']
        cost_red = 0.1 if tech >= 20 else 0.0
        dem_boost = 0.05 if tech >= 10 else 0.0
        rep_boost = 10 if tech >= 25 else 0

        eng_mult = 1.0 + (0.10 * sum(1 for e in emps if e[5]=='Engineer')) + (tech * 0.02)
        if tech >= 30: eng_mult *= 2.0
        aud_mult = 1.0 - min(0.30, 0.05 * sum(1 for e in emps if e[5]=='Auditor'))
        shark_mult = 1.0 + (0.15 * sum(1 for e in emps if e[5]=='Shark'))

        rep_mod = biz['reputation'] / 100.0
        if biz['philosophy'] == 'Artisan':
            demand = random.uniform(0.9, 1.2) * rep_mod * (biz['demand_boost'] + dem_boost) * shark_mult
            out_mult = 0.5 * eng_mult
            new_rep = min(100, biz['reputation'] + 2 + rep_boost)
        else:
            demand = random.uniform(1.0, 1.5) * rep_mod * (biz['demand_boost'] + dem_boost) * shark_mult
            out_mult = 1.5 * eng_mult
            new_rep = max(0, biz['reputation'] - 3 + rep_boost)

        factory_cap = int(sum(50 * (e[4]/100) for e in emps) * out_mult)
        total_targets = sum(max(1, p[8]) for p in prods)
        
        tot_rev = tot_cost = 0
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
            
            if margin_ratio > 8.0: sold = 0
            elif margin_ratio > 4.0: sold = int(base_sold * 0.05 * max(0.0, 1.0 - (margin_ratio - 4.0) / 4.0))
            elif margin_ratio > 2.5: sold = int(base_sold * 0.30)
            elif margin_ratio > 1.5: sold = int(base_sold * 0.80)
            else: sold = base_sold
            
            revenue = sold * adj_price
            tot_rev += revenue
            tot_cost += made * (adj_cost * aud_mult)
            c.execute("UPDATE business_products SET lifetime_revenue = lifetime_revenue + ?, lifetime_sold = lifetime_sold + ? WHERE id = ?", (revenue, sold, p_id))

        overhead = int((10000 + emp_count * 500) * aud_mult)
        loan_pay = biz['loan_balance'] // max(1, biz['installments_left']) if biz['installments_left'] > 0 else 0
        exec_pay = biz['owner_salary'] * (2 if biz['vp_id'] else 1)
        total_exp = total_payroll + overhead + tot_cost + loan_pay + exec_pay + (biz['marketing_budget'] * 2)
        
        net_profit = int(tot_rev - total_exp)
        
        country = biz.get('country', 'USA')
        if not country: country = 'USA'
        brackets = COUNTRY_TAX_RATES.get(country, COUNTRY_TAX_RATES['USA'])['brackets']

        tax_rate = 0.0
        for threshold, rate in brackets:
            if net_profit > threshold: tax_rate = rate
            else: break

        tax_bill = 0
        if net_profit > 0:
            tax_bill = int(net_profit * tax_rate)
            net_profit -= tax_bill
            log_business_event(c, uid, "TAX_PAID", f"Paid {tax_bill} in taxes")
            try:
                c.execute("UPDATE config SET value = CAST(value AS INTEGER) + ? WHERE key = 'central_reserve_pool'", (tax_bill,))
            except:
                c.execute("INSERT OR IGNORE INTO config (key, value) VALUES ('central_reserve_pool', ?)", (str(tax_bill),))
        
        new_cap = biz['capital'] + net_profit
        
        report = (
            f"+ Gross Revenue : A$ {tot_rev:,}\n"
            f"- Mfg Costs     : A$ {int(tot_cost):,}\n"
            f"- Staff Payroll : A$ {total_payroll:,}\n"
            f"- Facility Fees : A$ {overhead:,}\n"
            f"- Exec Salary   : A$ {exec_pay:,}\n"
        )
        if loan_pay > 0: report += f"- Loan Payment  : A$ {loan_pay:,}\n"
        if tax_bill > 0: report += f"- Corporate Tax : A$ {tax_bill:,}\n"
            
        report += f"==================================\n"
        if net_profit >= 0: report += f"+ NET PROFIT    : A$ {net_profit:,}"
        else: report += f"- NET LOSS      : A$ {abs(net_profit):,}"
        
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
                {"desc": "Air freight (Fast, -A$50k)", "capital": -50000, "rep": 5},
                {"desc": "Negotiate locally (Slow, +Rep)", "capital": 0, "rep": 15},
                {"desc": "Cut production (Save cash)", "capital": 20000, "rep": -10}
            ]},
            {"type": "Data Breach Scandal", "opts": [
                {"desc": "Full transparency (+Rep, -A$30k)", "capital": -30000, "rep": 20},
                {"desc": "Silence & PR spin (Risky)", "capital": -10000, "rep": -5},
                {"desc": "Blame intern (-Morale)", "capital": 0, "rep": -15}
            ]},
            {"type": "Competitor Price War", "opts": [
                {"desc": "Match prices (Margin hit)", "capital": -20000, "rep": 10},
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
            for sector in supplies:
                ratio = demands.get(sector, 0) / max(1, supplies[sector])
                boost = max(0.5, min(2.0, ratio))
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
                
                rpt, net = self._simulate_company_cycle(c, c_eco, biz)
                
                c.execute("UPDATE businesses SET demand_boost = MAX(0.8, demand_boost * 0.95), marketing_budget = MAX(0, marketing_budget - 5000), days_open = days_open + 1 WHERE user_id = ?", (uid,))
                
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

    @daily_cycle.before_loop
    @ticker_feed.before_loop
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
        embed.set_footer(text="Athena Central Reserve | Pending Taxes: %40 of Capital")
        
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