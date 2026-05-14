import discord
from discord import app_commands
from discord.ext import commands, tasks
import sqlite3
import json
import time
import random
import asyncio
from datetime import datetime
from contextlib import contextmanager

# ==========================================
# 🌐 CONFIGURATION & CONSTANTS (RESTORED)
# ==========================================
BUSINESS_CHANNEL_ID = 1441473281420169367  # Set your #wall-street or #business channel
DB_PATH = "business.db"
ECO_DB = "economy.db"

# ✅ FIX: All missing constants restored
HQ_LEVELS = {
    0: {"name": "Startup Garage", "max_emp": 5, "cost": 0},
    1: {"name": "Leased Office Space", "max_emp": 50, "cost": 150_000},
    2: {"name": "Tech Campus", "max_emp": 500, "cost": 800_000},
    3: {"name": "Corporate Skyscraper", "max_emp": 2500, "cost": 3_000_000}
}

QUALITY_TIERS = {
    "Standard": {"cost_mult": 1.0, "price_mult": 1.0, "demand_elasticity": 1.0, "required_tech": 0},
    "Premium":  {"cost_mult": 1.4, "price_mult": 1.6, "demand_elasticity": 0.8, "required_tech": 5},
    "Luxury":   {"cost_mult": 2.0, "price_mult": 2.5, "demand_elasticity": 0.5, "required_tech": 15}
}

TECH_MILESTONES = {
    0:  "🔬 Basic R&D lab — Standard products only",
    5:  "⭐ Premium tier unlocked! Higher margins available",
    10: "📊 Market Analytics — 5% demand boost passive",
    15: "💎 Luxury tier unlocked! Elite products available",
    20: "🤖 Automation — 10% cost reduction on all production",
    25: "🌐 Global Reach — 10% reputation boost per cycle",
    30: "🏆 Industry 4.0 — All multipliers doubled from staff",
    50: "👑 Singularity — Maximum efficiency, maximum profit"
}

NAMES = ["Liam", "Emma", "Noah", "Olivia", "Oliver", "Ava", "Elijah", "Sophia", "Mateo", "Isabella",
         "Lucas", "Mia", "Arthur", "Kades", "Phoenix", "Declan", "Ezra", "Aiden", "Sarah", "James"]

DEFAULT_BANNER = "https://cdn.discordapp.com/attachments/1441473281420169367/1501576429761200290/0ac4c99804a08a107d2cf6f09d79655f.jpg"

SECTOR_CATALOGS = {
    "Tech": ["Cloud Sync Pro", "AthenaOS Suite", "NeuralNet AI", "CyberShield Firewall", "Quantum Compute Unit", "Smart Home Hub"],
    "Food": ["Gourmet Meal Kits", "Organic Snack Box", "Smart Vending Machine", "Premium Coffee Blend", "Farm-to-Table Delivery", "Plant-Based Protein"],
    "Luxury": ["Designer Handbags", "Swiss Timepieces", "Custom Yacht Interiors", "Private Jet Leasing", "Rare Gemstone Jewelry", "Haute Couture Line"],
    "Retail": ["Fast Fashion Line", "Home Decor Essentials", "Eco-Friendly Groceries", "Tech Gadget Store", "Seasonal Pop-Up Shop", "Subscription Box Service"],
    "Industrial": ["Heavy Machinery Parts", "Logistics Fleet", "Renewable Energy Grid", "Steel Manufacturing", "Chemical Processing Unit", "Warehouse Automation"]
}
SECTORS = list(SECTOR_CATALOGS.keys())

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
# 🔒 ATOMIC BALANCE & TRANSACTION HELPERS (Cross-Cog Safe)
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
            await i.response.send_message(f"<a:wt_toroexclaim:1480581004317036624> Injected A$ {amt:,}.", ephemeral=True)
        except ValueError:
            await i.response.send_message("<a:wt_torono:1480580892706603018> Invalid amount.", ephemeral=True)

class ProductModal(discord.ui.Modal, title='Launch New Product'):
    p_name = discord.ui.TextInput(label='Product Name', min_length=3, max_length=30)
    p_price = discord.ui.TextInput(label='Unit Price (A$)', placeholder='e.g., 500', max_length=7)
    p_cost = discord.ui.TextInput(label='Cost Per Unit (A$)', max_length=7)
    p_qty = discord.ui.TextInput(label='Daily Target Quantity', placeholder='e.g., 500', max_length=7)
    def __init__(self, sector: str):
        super().__init__()
        self.sector = sector
    async def on_submit(self, i: discord.Interaction):
        catalog = SECTOR_CATALOGS.get(self.sector, [])
        if self.p_name.value not in catalog:
            return await i.response.send_message(f"❌ Invalid product for {self.sector}. Choose from: {', '.join(catalog)}", ephemeral=True)
        try:
            price, cost, qty = int(self.p_price.value), int(self.p_cost.value), int(self.p_qty.value)
            if price <= 0 or cost < 0 or cost >= price or qty <= 0: raise ValueError
        except ValueError:
            return await i.response.send_message("❌ Invalid data. Price > Cost > 0.", ephemeral=True)
        with get_db_cursor() as c:
            c.execute("""INSERT INTO business_products
                (user_id, name, category, unit_price, cost_to_make, production_target, quality_tier, active)
                VALUES (?, ?, ?, ?, ?, ?, 'Standard', 1)""",
                (i.user.id, self.p_name.value, self.sector, price, cost, qty))
            c.execute("UPDATE businesses SET sector = ? WHERE user_id = ? AND sector IS NULL", (self.sector, i.user.id))
            log_business_event(c, i.user.id, "PRODUCT_LAUNCH", f"Launched {self.p_name.value}")
        await i.response.send_message(f"✅ **{self.p_name.value}** launched in the {self.sector} sector!", ephemeral=True)

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
        await i.response.send_message(f"<a:wt_toroexclaim:1480581004317036624> Product upgraded to {new_tier}!", ephemeral=True)

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
            await i.response.send_message(f"📢 Marketing blitz launched! Demand boosted by +{boost*100-100:.1f}%.", ephemeral=True)
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
                    return await i.response.send_message("<a:wt_torono:1480580892706603018> Company not public.", ephemeral=True)
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
                if not biz: return await i.response.send_message("No business.", ephemeral=True)
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
                msg += "\n\n🎉 Milestones Unlocked:\n" + "\n".join(unlocked)
            await i.response.send_message(msg, ephemeral=True)
        except ValueError:
            await i.response.send_message("<a:wt_torono:1480580892706603018> Invalid amount.", ephemeral=True)

class BannerModal(discord.ui.Modal, title='Set Newspaper Banner'):
    url = discord.ui.TextInput(label='Image URL', placeholder='https://i.imgur.com/...', max_length=300)
    async def on_submit(self, i: discord.Interaction):
        with get_db_cursor() as c:
            c.execute("INSERT OR REPLACE INTO config (key, value) VALUES ('newspaper_banner', ?)", (self.url.value,))
        await i.response.send_message("<a:wt_toroexclaim:1480581004317036624> Banner updated! Next newspaper will use this image.", ephemeral=True)

class PhilosophyDropdown(discord.ui.Select):
    def __init__(self):
        opts = [discord.SelectOption(label="Artisan / Premium", value="Artisan"),
                discord.SelectOption(label="Mass Market", value="Mass Market")]
        super().__init__(placeholder="Production Philosophy...", options=opts)
    async def callback(self, i: discord.Interaction):
        with get_db_cursor() as c:
            c.execute("UPDATE businesses SET philosophy = ? WHERE user_id = ?", (self.values[0], i.user.id))
        await i.response.send_message(f"<a:wt_toroexclaim:1480581004317036624> Philosophy set to {self.values[0]}.", ephemeral=True)

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
            if biz[0] < 15000: return await i.response.send_message("<a:wt_torono:1480580892706603018> Not enough capital.", ephemeral=True)
            if emps >= HQ_LEVELS[biz[1]]["max_emp"]: return await i.response.send_message("<a:wt_torono:1480580892706603018> HQ full.", ephemeral=True)
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
        await i.response.send_message("<a:wt_toroexclaim:1480581004317036624> Employee fired.", ephemeral=True)

class StartupModal(discord.ui.Modal, title='Incorporate New Business'):
    b_name = discord.ui.TextInput(label='Company Name', min_length=3, max_length=30)
    def __init__(self, use_loan: bool):
        super().__init__()
        self.use_loan = use_loan
    async def on_submit(self, i: discord.Interaction):
        with get_eco_cursor() as c_eco:
            c_eco.execute("SELECT balance FROM wallets WHERE user_id = ?", (i.user.id,))
            bal = c_eco.fetchone()
            if not self.use_loan:
                if not bal or bal[0] < 500_000:
                    return await i.response.send_message("<a:wt_torono:1480580892706603018> Need A$ 500k.", ephemeral=True)
                c_eco.execute("UPDATE wallets SET balance = balance - 500000 WHERE user_id = ?", (i.user.id,))
                capital, loan, inst = 500_000, 0, 0
            else:
                capital, loan, inst = 500_000, 550_000, 10
        with get_db_cursor() as c:
            c.execute("INSERT INTO businesses (user_id, name, capital, loan_balance, installments_left, reputation) VALUES (?, ?, ?, ?, ?, 100)",
                (i.user.id, self.b_name.value, capital, loan, inst))
        await i.response.send_message(f"<a:wt_toroexclaim:1480581004317036624> {self.b_name.value} incorporated!", ephemeral=True)

class VPTitleDropdown(discord.ui.Select):
    def __init__(self, vp_user):
        self.vp_user = vp_user
        opts = [discord.SelectOption(label=t, value=t) for t in ["COO", "CFO", "CMO", "VP"]]
        super().__init__(placeholder="Select title...", options=opts)
    async def callback(self, i: discord.Interaction):
        with get_db_cursor() as c:
            c.execute("UPDATE businesses SET vp_id = ?, vp_title = ? WHERE user_id = ?", (self.vp_user.id, self.values[0], i.user.id))
        await i.response.send_message(f"<a:wt_toroexclaim:1480581004317036624> {self.vp_user.name} appointed as {self.values[0]}.", ephemeral=False)

# ----- sub-views -----
class ProductPerformanceView(discord.ui.View):
    def __init__(self, user_id): super().__init__(timeout=180); self.user_id = user_id
    @discord.ui.button(label="Refresh", style=discord.ButtonStyle.secondary)
    async def refresh(self, i: discord.Interaction, btn): await i.response.edit_message(embed=self.get_embed(), view=self)
    def get_embed(self):
        with get_db_cursor() as c:
            c.execute("SELECT name, unit_price, cost_to_make, lifetime_revenue, quality_tier FROM business_products WHERE user_id = ?", (self.user_id,))
            prods = c.fetchall()
        embed = discord.Embed(title="꒰ა ﹒chérie  ⸝", color=0xffffff)
        if not prods: embed.description = "No products."; return embed
        max_rev = max(p[3] for p in prods)
        desc = ""
        for name, price, cost, rev, tier in prods:
            margin = price - cost
            chart = "█" * int((rev / max_rev) * 12) + "░" * (12 - int((rev / max_rev) * 12))
            desc += f"🔹 {name} ({tier})\n `{chart}` A$ {rev:,} | Margin A$ {margin:,}\n\n"
        embed.description = desc; return embed

class HRView(discord.ui.View):
    def __init__(self, user_id): super().__init__(timeout=180); self.add_item(FireEmployeeDropdown(user_id)); self.add_item(HireSpecialistDropdown())
    @discord.ui.button(label="Hire Staff (A$ 2k)", style=discord.ButtonStyle.secondary, row=2)
    async def hire(self, i: discord.Interaction, btn):
        with get_db_cursor() as c:
            c.execute("SELECT capital, hq_level FROM businesses WHERE user_id = ?", (i.user.id,)); biz = c.fetchone()
            c.execute("SELECT COUNT(id) FROM employees WHERE user_id = ?", (i.user.id,)); emps = c.fetchone()[0]
            if biz[0] < 2000: return await i.response.send_message("<a:wt_torono:1480580892706603018> Not enough capital.", ephemeral=True)
            if emps >= HQ_LEVELS[biz[1]]["max_emp"]: return await i.response.send_message("<a:wt_torono:1480580892706603018> HQ full.", ephemeral=True)
            c.execute("UPDATE businesses SET capital = capital - 2000 WHERE user_id = ?", (i.user.id,))
            c.execute("INSERT INTO employees (user_id, name, salary, morale, specialization) VALUES (?, ?, 1500, 80, 'None')", (i.user.id, random.choice(NAMES)))
        await i.response.send_message("<a:wt_toroexclaim:1480581004317036624> Staff hired.", ephemeral=True)
    @discord.ui.button(label="Host Event (A$ 5k)", style=discord.ButtonStyle.secondary, row=2)
    async def morale(self, i: discord.Interaction, btn):
        with get_db_cursor() as c:
            c.execute("SELECT capital FROM businesses WHERE user_id = ?", (i.user.id,)); cap = c.fetchone()[0]
            if cap < 5000: return await i.response.send_message("<a:wt_torono:1480580892706603018> Not enough capital.", ephemeral=True)
            c.execute("UPDATE businesses SET capital = capital - 5000 WHERE user_id = ?", (i.user.id,))
            c.execute("UPDATE employees SET morale = MIN(100, morale + 25) WHERE user_id = ?", (i.user.id,))
        await i.response.send_message("<a:wt_torolove:1480580899430203484> Morale boosted!", ephemeral=True)

class OpsView(discord.ui.View):
    def __init__(self, user_id):
        super().__init__(timeout=180)
        self.user_id = user_id
        self.add_item(PhilosophyDropdown())
        self.add_item(UpgradeProductDropdown(user_id))
    @discord.ui.button(label="Launch Product", style=discord.ButtonStyle.secondary, row=2)
    async def prod(self, i: discord.Interaction, btn):
        with get_db_cursor() as c:
            c.execute("SELECT sector FROM businesses WHERE user_id = ?", (i.user.id,))
            row = c.fetchone()
    
    # If no sector set, prompt user to select one
        if not row or not row[0]:
            opts = [discord.SelectOption(label=c, value=c) for c in SECTORS]
            sel = discord.ui.Select(placeholder="Select your business sector...", options=opts)
        
            async def sector_callback(it):
                sector = sel.values[0]
                with get_db_cursor() as c2:
                    c2.execute("UPDATE businesses SET sector = ? WHERE user_id = ?", (sector, it.user.id))
            # Now show product modal
                view2 = discord.ui.View(timeout=60)
                view2.add_item(ProductDropdown(sector))
                await it.response.send_message(f"📦 Select a product to launch for **{sector}**:", view=view2, ephemeral=True)
        
            sel.callback = sector_callback
            v = discord.ui.View()
            v.add_item(sel)
            return await i.response.send_message("🏭 First, select your business sector:", view=v, ephemeral=True)
    
    # Sector already exists, show products
        sector = row[0]
        view = discord.ui.View(timeout=60)
        view.add_item(ProductDropdown(sector))
        await i.response.send_message(f"📦 Select a product to launch for **{sector}**:", view=view, ephemeral=True)
    
    @discord.ui.button(label="Upgrade HQ", style=discord.ButtonStyle.secondary, row=2)
    async def hq(self, i: discord.Interaction, btn):
        with get_db_cursor() as c:
            c.execute("SELECT capital, hq_level FROM businesses WHERE user_id = ?", (i.user.id,))
            biz = c.fetchone()
        nxt = biz[1] + 1
        if nxt not in HQ_LEVELS: return await i.response.send_message("❌ Max level.", ephemeral=True)
        cost = HQ_LEVELS[nxt]["cost"]
        if biz[0] < cost: return await i.response.send_message(f"❌ Need A$ {cost:,}.", ephemeral=True)
        with get_db_cursor() as c:
            if not atomic_business_update(c, i.user.id, -cost): return await i.response.send_message("❌ Balance updated concurrently.", ephemeral=True)
            c.execute("UPDATE businesses SET hq_level = ? WHERE user_id = ?", (nxt, i.user.id))
        await i.response.send_message("✅ HQ Upgraded!", ephemeral=True)
    @discord.ui.button(label="Set Bio", style=discord.ButtonStyle.secondary, row=3)
    async def bio(self, i: discord.Interaction, btn): await i.response.send_modal(DescriptionModal())
    @discord.ui.button(label="Set Salary", style=discord.ButtonStyle.secondary, row=3)
    async def sal(self, i: discord.Interaction, btn): await i.response.send_modal(SetSalaryModal())
    @discord.ui.button(label="Inject Capital", style=discord.ButtonStyle.secondary, row=3)
    async def inject(self, i: discord.Interaction, btn): await i.response.send_modal(InvestModal())

class SettlementView(discord.ui.View):
    def __init__(self, user_id): super().__init__(timeout=60); self.user_id = user_id
    @discord.ui.button(label="Pay A$ 100k Settlement", style=discord.ButtonStyle.danger)
    async def pay(self, i: discord.Interaction, btn):
        with get_db_cursor() as c:
            c.execute("SELECT capital FROM businesses WHERE user_id = ?", (self.user_id,))
            if c.fetchone()[0] < 100_000: return await i.response.send_message("<a:wt_torono:1480580892706603018> Insufficient funds.", ephemeral=True)
            c.execute("UPDATE businesses SET capital = capital - 100000 WHERE user_id = ?", (self.user_id,))
            c.execute("UPDATE employees SET morale = 50 WHERE user_id = ?", (self.user_id,))
        await i.response.send_message("<a:wt_toroexclaim:1480581004317036624> Strike settled.", ephemeral=False)
    @discord.ui.button(label="Grant 15% Raise", style=discord.ButtonStyle.danger)
    async def raise_(self, i: discord.Interaction, btn):
        with get_db_cursor() as c:
            c.execute("UPDATE employees SET salary = CAST(salary * 1.15 AS INTEGER), morale = 80 WHERE user_id = ?", (self.user_id,))
        await i.response.send_message("<a:wt_toroexclaim:1480581004317036624> Strike settled with raises.", ephemeral=False)

class TerminalView(discord.ui.View):
    def __init__(self, bot, user_id):
        super().__init__(timeout=None)
        self.bot = bot
        with get_db_cursor() as c:
            c.execute("SELECT AVG(morale) FROM employees WHERE user_id = ?", (user_id,))
            avg = c.fetchone()[0]
        if avg is not None and avg < 20:
            self.add_item(discord.ui.Button(label="RESOLVE STRIKE", style=discord.ButtonStyle.danger, custom_id="strike_btn", row=4))
    @discord.ui.button(label="Balance Sheet", style=discord.ButtonStyle.secondary, row=0)
    async def balance(self, i: discord.Interaction, btn):
        with get_db_cursor() as c:
            c.execute("SELECT capital, loan_balance, owner_salary, last_report, vp_title FROM businesses WHERE user_id = ?", (i.user.id,))
            biz = c.fetchone()
            c.execute("SELECT SUM(salary), COUNT(id) FROM employees WHERE user_id = ?", (i.user.id,))
            emps = c.fetchone()
        emp_count, total_payroll = emps[1] or 0, emps[0] or 0
        overhead = 10000 + (emp_count * 500)
        receipt = (
            "```receipt\n"
            "==================================\n"
            "       FINANCIAL STATEMENT        \n"
            "==================================\n"
            f"LIQUID CAPITAL : A$ {biz[0]:,}\n"
            f"LOAN BALANCE   : A$ {biz[1]:,}\n"
            "----------------------------------\n"
            "       DAILY EXPENDITURES         \n"
            "----------------------------------\n"
            f"EXEC SALARY    : A$ {biz[2]:,}\n"
            f"STAFF PAYROLL  : A$ {total_payroll:,}\n"
            f"FIXED OVERHEAD : A$ {overhead:,}\n"
            "==================================\n"
            f"LATEST REPORT:\n{biz[3]}\n```"
        )
        embed = discord.Embed(title="꒰ა chérie  ⸝⸝", color=0xffffff, description=receipt)
        await i.response.send_message(embed=embed, ephemeral=True)
    @discord.ui.button(label="Operations", style=discord.ButtonStyle.secondary, row=0)
    async def ops(self, i: discord.Interaction, btn):
        embed = discord.Embed(title="꒰ა ﹒chérie  ⸝", color=0xffffff, description="**Operational Control**")
        await i.response.send_message(embed=embed, view=OpsView(i.user.id), ephemeral=True)
    @discord.ui.button(label="HR", style=discord.ButtonStyle.secondary, row=0)
    async def hr(self, i: discord.Interaction, btn):
        with get_db_cursor() as c:
            c.execute("SELECT name, salary, morale, specialization FROM employees WHERE user_id = ?", (i.user.id,))
            emps = c.fetchall()
        embed = discord.Embed(title="꒰ა ﹒chérie  ⸝", color=0xffffff)
        if not emps: embed.description = "No employees."
        else:
            desc = "👥 **Human Resources**\n"
            for n,s,m,sp in emps[:15]:
                desc += f"• **{n}** ({sp}) - A$ {s:,} | {m}% morale\n"
            if len(emps) > 15: desc += f"*...and {len(emps)-15} more.*\n"
            embed.description = desc
        await i.response.send_message(embed=embed, view=HRView(i.user.id), ephemeral=True)
    @discord.ui.button(label="R&D Hub", style=discord.ButtonStyle.secondary, row=1)
    async def rnd(self, i: discord.Interaction, btn):
        with get_db_cursor() as c:
            c.execute("SELECT tech_level FROM businesses WHERE user_id = ?", (i.user.id,))
            tech = c.fetchone()[0]
        embed = discord.Embed(title="🔬 R&D Tech Tree", color=0xffffff)
        desc = f"**Current Tech Level:** {tech}\n\n"
        for milestone, label in TECH_MILESTONES.items():
            desc += f"{'✅' if tech >= milestone else '🔒'} **Tech {milestone}:** {label}\n"
        desc += "\n*Invest capital in R&D to unlock new tiers and bonuses!*"
        embed.description = desc
        view = ProductPerformanceView(i.user.id)
        await i.response.send_message(embed=embed, view=view, ephemeral=True)
    @discord.ui.button(label="Rename", style=discord.ButtonStyle.secondary, row=1)
    async def rename(self, i: discord.Interaction, btn):
        await i.response.send_modal(RenameCompanyModal())
    @discord.ui.button(label="IPO", style=discord.ButtonStyle.success, row=1)
    async def ipo(self, i: discord.Interaction, btn):
        with get_db_cursor() as c:
            c.execute("SELECT name, capital, is_public FROM businesses WHERE user_id = ?", (i.user.id,))
            biz = c.fetchone()
            if not biz: return await i.response.send_message("❌ No business found.", ephemeral=True)
            if biz[2] == 1: return await i.response.send_message("❌ Already public.", ephemeral=True)
            if biz[1] < 2_000_000: return await i.response.send_message("❌ A$ 2M required.", ephemeral=True)
            c.execute("SELECT COUNT(id) FROM employees WHERE user_id = ?", (i.user.id,))
            emp_count = c.fetchone()[0]
            start_price = max(500, int((biz[1] * 0.001) + (emp_count * 10)))
            sym = biz[0][:4].upper()
            c.execute("UPDATE businesses SET is_public = 1 WHERE user_id = ?", (i.user.id,))
        with get_eco_cursor() as c_eco:
            c_eco.execute("INSERT OR IGNORE INTO stocks (symbol, name, price, volatility, trend) VALUES (?, ?, ?, 15, 'FLAT')", (sym, biz[0], start_price))
        await i.response.send_message(f"✅ **IPO SUCCESSFUL!** Trading as **{sym}** at A$ {start_price:,}.", ephemeral=False)
    @discord.ui.button(label="Marketing", style=discord.ButtonStyle.primary, row=2)
    async def market(self, i: discord.Interaction, btn):
        await i.response.send_modal(MarketingModal())
    @discord.ui.button(label="Pay Dividends", style=discord.ButtonStyle.primary, row=2)
    async def dividend(self, i: discord.Interaction, btn):
        await i.response.send_modal(DividendModal())
    @discord.ui.button(label="Invest in R&D", style=discord.ButtonStyle.primary, row=2)
    async def invest_rnd(self, i: discord.Interaction, btn):
        await i.response.send_modal(RndInvestModal())
    @discord.ui.button(label="Espionage", style=discord.ButtonStyle.danger, row=3)
    async def espionage(self, i: discord.Interaction, btn):
        await i.response.send_modal(EspionageModal())
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.data.get('custom_id') == "strike_btn":
            embed = discord.Embed(title="꒰ა ﹒chérie  ⸝", color=0xffffff, description="**UNION DEMANDS**")
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
                return await i.response.send_message("❌ Insufficient capital.", ephemeral=True)
            
            c.execute("SELECT tech_level, reputation FROM businesses WHERE user_id = ?", (self.target_id,))
            target = c.fetchone()
            if not target:
                return await i.response.send_message("❌ Target business not found.", ephemeral=True)
            
            success_chance = max(0.1, min(0.75, 0.3 + (0.01 * (target[0]/5)) - (0.005 * target[1])))
            
            if random.random() < success_chance:
                if op == 'steal_tech':
                    c.execute("UPDATE businesses SET tech_level = tech_level + 3 WHERE user_id = ?", (i.user.id,))
                    c.execute("UPDATE businesses SET tech_level = MAX(0, tech_level - 3) WHERE user_id = ?", (self.target_id,))
                    msg = "✅ Espionage successful! +3 Tech points transferred."
                else:
                    c.execute("UPDATE businesses SET reputation = MAX(0, reputation - 15) WHERE user_id = ?", (self.target_id,))
                    msg = "✅ Sabotage successful! Rival reputation -15."
                log_business_event(c, i.user.id, "ESPIONAGE_SUCCESS", f"{op} on {self.target_id}")
            else:
                c.execute("UPDATE businesses SET reputation = MAX(0, reputation - 10) WHERE user_id = ?", (i.user.id,))
                msg = "❌ Espionage failed! You were caught and reputation dropped."
                log_business_event(c, i.user.id, "ESPIONAGE_FAIL", f"Caught during {op}")
        
        await i.response.send_message(msg, ephemeral=True)

class EspionageView(discord.ui.View):
    def __init__(self, target_id: int):
        super().__init__(timeout=60)
        self.add_item(EspionageTypeDropdown(target_id))

class EspionageModal(discord.ui.Modal, title='Corporate Espionage'):
    target_id = discord.ui.TextInput(label='Target User ID', placeholder='e.g. 123456789')
    
    async def on_submit(self, i: discord.Interaction):
        try:
            tid = int(self.target_id.value)
        except:
            return await i.response.send_message("❌ Invalid User ID.", ephemeral=True)
        
        if tid == i.user.id:
            return await i.response.send_message("❌ Cannot target yourself.", ephemeral=True)
        
        await i.response.send_message("Select operation type:", view=EspionageView(tid), ephemeral=True)

# ==========================================
# 🏙️ THE BUSINESS COG (Main Logic)
# ==========================================
class Business(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.setup_db()
        self.daily_cycle.start()
        self.ticker_feed.start()

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
                quarter INTEGER DEFAULT 1, next_board_meeting REAL DEFAULT 0, strike_active INTEGER DEFAULT 0
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
                ("businesses", "sector", "TEXT"), ("businesses", "tech_level", "INTEGER DEFAULT 0"),
                ("businesses", "marketing_budget", "INTEGER DEFAULT 0"), ("businesses", "quarter", "INTEGER DEFAULT 1"),
                ("businesses", "next_board_meeting", "REAL DEFAULT 0"), ("businesses", "strike_active", "INTEGER DEFAULT 0"),
                ("business_products", "category", "TEXT"), ("business_products", "quality_tier", "TEXT DEFAULT 'Standard'")
            ]:
                try: c.execute(f"ALTER TABLE {table} ADD COLUMN {col} {dtype}")
                except: pass

    async def _post_to_channel(self, embed: discord.Embed, view: discord.ui.View = None):
        channel = self.bot.get_channel(BUSINESS_CHANNEL_ID)
        if channel:
            try: 
                if view:
                    await channel.send(embed=embed, view=view)
                else:
                    await channel.send(embed=embed)
            except: pass

    # ==========================================
    # 📉 REACTIVE MARKET ENGINE
    # ==========================================
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
            c_eco.execute("SELECT price FROM stocks WHERE symbol = ?", (sym,))
            row = c_eco.fetchone()
            if row:
                change = 1.03 if cap > 500000 else 0.97 if cap < 200000 else 1.0
                new_price = max(10, int(row[0] * change))
                trend = "📈 UP" if new_price > row[0] else "📉 DOWN"
                c_eco.execute("UPDATE stocks SET price = ?, trend = ? WHERE symbol = ?", (new_price, trend, sym))

    # ==========================================
    # 📊 SIMULATION CYCLE (Quarters, Board Meetings, Market)
    # ==========================================
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
        avg_morale = sum(e[4] for e in emps) / emp_count
        if biz['strike_active'] or avg_morale < 20:
            c.execute("UPDATE businesses SET strike_active = 1 WHERE user_id = ?", (uid,))
            return "🚨 STRIKE ACTIVE! Production halted.", 0

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
        remaining = factory_cap
        tot_rev = tot_cost = 0
        for p in prods:
            p_id, name, sector, price, cost, active, rev, target, tier = p[0], p[2], p[3], p[4], p[5], p[6], p[7], p[8], p[9]
            tier_data = QUALITY_TIERS.get(tier, QUALITY_TIERS['Standard'])
            adj_price = int(price * tier_data['price_mult'])
            adj_cost = int(cost * tier_data['cost_mult'] * (1 - cost_red))
            made = min(target, remaining)
            remaining -= made
            prod_dem = demand * tier_data['demand_elasticity']
            margin_ratio = adj_price / max(1, adj_cost)
            if margin_ratio > 4: prod_dem *= 0.2
            elif margin_ratio > 2.5: prod_dem *= 0.6
            sold = min(made, int(made * prod_dem))
            revenue = sold * adj_price
            tot_rev += revenue
            tot_cost += made * (adj_cost * aud_mult)
            c.execute("UPDATE business_products SET lifetime_revenue = lifetime_revenue + ? WHERE id = ?", (revenue, p_id))

        overhead = int((10000 + emp_count * 500) * aud_mult)
        loan_pay = biz['loan_balance'] // max(1, biz['installments_left']) if biz['installments_left'] > 0 else 0
        if loan_pay:
            c.execute("UPDATE businesses SET loan_balance = loan_balance - ?, installments_left = installments_left - 1 WHERE user_id = ?", (loan_pay, uid))
        exec_pay = biz['owner_salary'] * (2 if biz['vp_id'] else 1)
        total_exp = total_payroll + overhead + tot_cost + loan_pay + exec_pay
        net = int(tot_rev - total_exp)
        new_cap = biz['capital'] + net
        c.execute("UPDATE businesses SET capital = ?, reputation = ?, last_report = ? WHERE user_id = ?", (new_cap, new_rep, f"Rev: A$ {tot_rev:,} | Exp: A$ {int(total_exp):,} | Net: A$ {net:,}", uid))
        if biz['owner_salary'] > 0 and new_cap >= exec_pay:
            with get_eco_cursor() as ec:
                if atomic_eco_balance_update(ec, uid, biz['owner_salary']):
                    log_business_event(ec, uid, "SALARY_PAYOUT", f"Executive salary")
                if biz['vp_id']:
                    atomic_eco_balance_update(ec, biz['vp_id'], biz['owner_salary'])
        c.execute("UPDATE employees SET morale = MAX(10, morale - 5) WHERE user_id = ?", (uid,))
        return f"Net: A$ {net:,}", net

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
        embed = discord.Embed(title=f"🚨 BOARD MEETING REQUIRED", color=0xffaa00)
        embed.description = f"**Crisis:** {crisis['type']}\n\nReply with 1, 2, or 3 to choose your strategy.\n1️⃣ {crisis['opts'][0]['desc']}\n2️⃣ {crisis['opts'][1]['desc']}\n3️⃣ {crisis['opts'][2]['desc']}"
        asyncio.create_task(self._post_to_channel(embed))

    def _generate_market_events(self, c):
        if random.random() < 0.4:
            sector = random.choice(SECTORS)
            events = [
                ("📈 Viral Trend", {"demand_mult": 1.3}, 2),
                ("📉 Supply Chain Crisis", {"demand_mult": 0.7}, 2),
                ("💰 Tax Break", {"demand_mult": 1.2}, 3),
                ("🔧 Tech Breakthrough", {"demand_mult": 1.15}, 1),
            ]
            text, mod, dur = random.choice(events)
            c.execute("INSERT INTO market_events (event_text, sector, modifier_json, days_remaining) VALUES (?, ?, ?, ?)",
                      (f"{text} in {sector} sector!", sector, json.dumps(mod), dur))

    # ==========================================
    # 📡 BACKGROUND TASKS
    # ==========================================
    @tasks.loop(hours=5)
    async def daily_cycle(self):
        with get_db_cursor() as c, get_eco_cursor() as c_eco:
            supplies, demands = self._calculate_sector_supply_demand(c)
            for sector in supplies:
                ratio = demands.get(sector, 0) / max(1, supplies[sector])
                boost = max(0.5, min(2.0, ratio))
                c.execute("UPDATE businesses SET demand_boost = ? WHERE sector = ?", (boost, sector))

            c.execute("SELECT * FROM businesses")
            cols = [desc[0] for desc in c.description]
            for row in c.fetchall():
                biz = dict(zip(cols, row))
                rpt, net = self._simulate_company_cycle(c, c_eco, biz)
                c.execute("UPDATE businesses SET demand_boost = MAX(0.8, demand_boost * 0.95), marketing_budget = MAX(0, marketing_budget - 5000), days_open = days_open + 1 WHERE user_id = ?", (biz['user_id'],))
                if biz['days_open'] % 28 == 0:
                    biz['quarter'] += 1
                    c.execute("UPDATE businesses SET quarter = ?, days_open = 0 WHERE user_id = ?", (biz['quarter'], biz['user_id']))
                    embed = discord.Embed(title="📞 QUARTERLY EARNINGS CALL", color=0x00aaff)
                    embed.description = f"<@{biz['user_id']}> Q{biz['quarter']} results are in. How do you present to shareholders?"
                    view = EarningsCallView(biz['user_id'], biz['quarter'])
                    asyncio.create_task(self._post_to_channel(embed, view))
                if biz['next_board_meeting'] <= time.time():
                    self._trigger_board_meeting(c, biz['user_id'])
            self._update_stock_prices_from_businesses(c_eco, c)
            self._generate_market_events(c)

    @tasks.loop(hours=1)
    async def ticker_feed(self):
        with get_db_cursor() as c:
            c.execute("SELECT name, capital, sector FROM businesses ORDER BY capital DESC LIMIT 3")
            top = c.fetchall()
            if not top: return
            embed = discord.Embed(title="📈 LIVE MARKET TICKER", color=0x00ff00)
            for i, (n, cap, sec) in enumerate(top, 1):
                embed.add_field(name=f"#{i} {n}", value=f"💰 A$ {cap:,}\n🏢 {sec}", inline=True)
            await self._post_to_channel(embed)

    @daily_cycle.before_loop
    @ticker_feed.before_loop
    async def before_loops(self):
        await self.bot.wait_until_ready()

    # ==========================================
    # 🎮 COMMANDS
    # ==========================================
    @app_commands.command(name="business")
    async def business_hub(self, i: discord.Interaction):
        with get_db_cursor() as c:
            c.execute("SELECT name, capital, reputation, description, hq_level, sector, is_public, tech_level, marketing_budget FROM businesses WHERE user_id = ?", (i.user.id,))
            biz = c.fetchone()
            if not biz:
                v = discord.ui.View()
                v.add_item(discord.ui.Button(label="Fund Outright (500k)", style=discord.ButtonStyle.secondary, custom_id="f_out"))
                v.add_item(discord.ui.Button(label="Secure Loan", style=discord.ButtonStyle.secondary, custom_id="f_loan"))
                async def call(ix): await ix.response.send_modal(StartupModal(ix.data['custom_id']=="f_loan"))
                for child in v.children: child.callback = call
                return await i.response.send_message(embed=discord.Embed(title="꒰ა chérie  ⸝", color=0xffffff, description="Incorporate for A$ 500k."), view=v, ephemeral=False)
            c.execute("SELECT COUNT(id), AVG(morale) FROM employees WHERE user_id = ?", (i.user.id,))
            emps = c.fetchone()
        await i.response.send_message("🔄 *Accessing CEO Terminal...*", ephemeral=False)
        await asyncio.sleep(1.5)
        
        # ✅ FIX: Safe fallback for hq_level (index 4) in case it's NULL for new rows
        hq_lvl = biz[4] if biz[4] is not None else 0
        embed = discord.Embed(title=f"꒰ა {biz[0]}  ⸝⸝", color=0xffffff)
        embed.description = (
            f"*{biz[3]}*\n\n"
            f"💰 **Capital:** A$ {biz[1]:,}\n"
            f"🌟 **Reputation:** {biz[2]}%\n"
            f"🏢 **HQ:** {HQ_LEVELS[hq_lvl]['name']}\n"  # ✅ FIX: HQ_LEVELS now defined
            f"🏭 **Sector:** {biz[5] or 'None'}\n"
            f"👥 **Employees:** {emps[0] or 0} | Morale: {int(emps[1]) if emps[1] else 100}%\n"
            f"🔬 **Tech Level:** {biz[7]} | 📢 Marketing: A$ {biz[8]:,}\n"
        )
        with get_db_cursor() as c:
            c.execute("SELECT value FROM config WHERE key = 'newspaper_banner'")
            row = c.fetchone()
            banner_url = row[0] if row else DEFAULT_BANNER
        embed.set_image(url=banner_url)
        await i.edit_original_response(content=None, embed=embed, view=TerminalView(self.bot, i.user.id))

    @app_commands.command(name="appoint")
    async def appoint_vp(self, i: discord.Interaction, user: discord.Member):
        if user.bot or user.id == i.user.id: return await i.response.send_message("❌ Invalid user.", ephemeral=True)
        with get_db_cursor() as c:
            if not c.execute("SELECT 1 FROM businesses WHERE user_id = ?", (i.user.id,)).fetchone():
                return await i.response.send_message("❌ No business.", ephemeral=True)
        v = discord.ui.View(); v.add_item(VPTitleDropdown(user))
        await i.response.send_message(f"Select title for {user.name}:", view=v, ephemeral=True)

    @app_commands.command(name="rename_company", description="Rename your company")
    async def rename_cmd(self, i: discord.Interaction):
        with get_db_cursor() as c:
            if not c.execute("SELECT 1 FROM businesses WHERE user_id = ?", (i.user.id,)).fetchone():
                return await i.response.send_message("❌ No business found.", ephemeral=True)
        await i.response.send_modal(RenameCompanyModal())

    @app_commands.command(name="set_banner", description="ADMIN: Set the newspaper embed banner image")
    @app_commands.default_permissions(administrator=True)
    async def set_banner(self, i: discord.Interaction, url: str):
        with get_db_cursor() as c:
            c.execute("INSERT OR REPLACE INTO config (key, value) VALUES ('newspaper_banner', ?)", (url,))
        await i.response.send_message("✅ Newspaper banner updated!")

    @app_commands.command(name="bizleaderboard", description="Top companies by capital")
    async def leaderboard(self, i: discord.Interaction):
        with get_db_cursor() as c:
            c.execute("SELECT name, capital, reputation, sector FROM businesses ORDER BY capital DESC LIMIT 10")
            rows = c.fetchall()
        embed = discord.Embed(title="Business Moguls", color=0xffffff)
        desc = ""
        for n, cap, rep, sec in rows:
            desc += f"**{n}** ({sec or 'N/A'}) - A$ {cap:,} | {rep}% rep\n\n"
        embed.description = desc or "No companies yet."
        await i.response.send_message(embed=embed)

async def setup(bot):
    await bot.add_cog(Business(bot))