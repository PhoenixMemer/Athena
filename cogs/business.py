import discord
from discord import app_commands
from discord.ext import commands, tasks
import sqlite3
import json
import time
import random
import asyncio
from datetime import datetime

DB_PATH = "business.db"
ECO_DB = "economy.db"

# ----- universal connection helpers -----
def get_db_connection():
    conn = sqlite3.connect(DB_PATH, isolation_level=None)
    conn.execute('PRAGMA journal_mode=WAL;')
    conn.execute('PRAGMA temp_store = MEMORY;')
    conn.execute('PRAGMA synchronous = NORMAL;')
    return conn

def get_eco_connection():
    conn = sqlite3.connect(ECO_DB, isolation_level=None)
    conn.execute('PRAGMA journal_mode=WAL;')
    conn.execute('PRAGMA temp_store = MEMORY;')
    conn.execute('PRAGMA synchronous = NORMAL;')
    return conn

# ----- constants -----
HQ_LEVELS = {
    0: {"name": "Startup Garage", "max_emp": 5, "cost": 0},
    1: {"name": "Leased Office Space", "max_emp": 50, "cost": 150_000},
    2: {"name": "Tech Campus", "max_emp": 500, "cost": 800_000},
    3: {"name": "Corporate Skyscraper", "max_emp": 2500, "cost": 3_000_000}
}

SECTORS = ["Tech", "Food", "Luxury", "Retail", "Industrial"]
QUALITY_TIERS = {
    "Standard": {"cost_mult": 1.0, "price_mult": 1.0, "demand_elasticity": 1.0, "required_tech": 0},
    "Premium":  {"cost_mult": 1.4, "price_mult": 1.6, "demand_elasticity": 0.8, "required_tech": 5},
    "Luxury":    {"cost_mult": 2.0, "price_mult": 2.5, "demand_elasticity": 0.5, "required_tech": 15}
}

# Tech tree milestones
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

NAMES = ["Liam","Emma","Noah","Olivia","Oliver","Ava","Elijah","Sophia","Mateo","Isabella",
         "Lucas","Mia","Arthur","Kades","Phoenix","Declan","Ezra","Aiden","Sarah","James"]

# ----- aesthetic helpers -----
def make_progress_bar(current: int, total: int = 100) -> str:
    fill_left = "<:fillleft:1502707988761153567>"
    fill_mid = "<:fillmid:1502707936823087246>"
    fill_right = "<:fillright:1502707911560794192>"
    empty_left = "<:emptyleft:1502707971363311767>"
    empty_mid = "<:emptymid:1502707866744651948>"
    empty_right = "<:emptyright:1502707890664771717>"
    segments = 10
    percent = current / total if total > 0 else 0
    visual = min(max(int(percent * segments), 0), segments)
    bar = ""
    for i in range(segments):
        if i == 0: bar += fill_left if i < visual else empty_left
        elif i == segments - 1: bar += fill_right if i < visual else empty_right
        else: bar += fill_mid if i < visual else empty_mid
    return f"{bar}  **({current}%)**"

def ascii_bar(value, max_value, length=12):
    if max_value <= 0: return "░" * length
    filled = int((value / max_value) * length)
    return "█" * filled + "░" * (length - filled)

# ----- default newspaper banner -----
DEFAULT_BANNER = "https://cdn.discordapp.com/attachments/1441473281420169367/1501576429761200290/0ac4c99804a08a107d2cf6f09d79655f.jpg"

# ============================================
# 🧩 UI COMPONENTS (modals, dropdowns, views)
# ============================================
class DescriptionModal(discord.ui.Modal, title='Set Company Bio'):
    desc = discord.ui.TextInput(label='Company Description', style=discord.TextStyle.paragraph, max_length=150, placeholder='A rising corporate empire...')
    async def on_submit(self, i: discord.Interaction):
        conn = get_db_connection(); c = conn.cursor()
        c.execute("UPDATE businesses SET description = ? WHERE user_id = ?", (self.desc.value, i.user.id))
        conn.commit(); conn.close()
        await i.response.send_message("<a:wt_toroexclaim:1480581004317036624> Bio updated.", ephemeral=True)

class RenameCompanyModal(discord.ui.Modal, title='Rename Company'):
    name = discord.ui.TextInput(label='New Company Name', min_length=3, max_length=30)
    async def on_submit(self, i: discord.Interaction):
        conn = get_db_connection(); c = conn.cursor()
        c.execute("UPDATE businesses SET name = ? WHERE user_id = ?", (self.name.value, i.user.id))
        conn.commit(); conn.close()
        await i.response.send_message(f"<a:wt_toroexclaim:1480581004317036624> Company renamed to **{self.name.value}**.", ephemeral=True)

class SetSalaryModal(discord.ui.Modal, title='Executive Payroll'):
    salary = discord.ui.TextInput(label='Daily Personal Salary (A$)', placeholder='e.g., 5000', max_length=7)
    async def on_submit(self, i: discord.Interaction):
        try:
            amt = int(self.salary.value)
            if amt < 0: raise ValueError
            conn = get_db_connection(); c = conn.cursor()
            c.execute("UPDATE businesses SET owner_salary = ? WHERE user_id = ?", (amt, i.user.id))
            conn.commit(); conn.close()
            await i.response.send_message(f"<a:wt_toroexclaim:1480581004317036624> Salary set to A$ {amt:,}.", ephemeral=True)
        except ValueError:
            await i.response.send_message("<a:wt_torono:1480580892706603018> Invalid amount.", ephemeral=True)

class InvestModal(discord.ui.Modal, title='Inject Personal Capital'):
    amount = discord.ui.TextInput(label='Amount (A$)', placeholder='e.g., 100000')
    async def on_submit(self, i: discord.Interaction):
        try:
            amt = int(self.amount.value)
            if amt <= 0: raise ValueError
            conn_eco = get_eco_connection(); c_eco = conn_eco.cursor()
            c_eco.execute("SELECT balance FROM wallets WHERE user_id = ?", (i.user.id,))
            bal = c_eco.fetchone()
            if not bal or bal[0] < amt:
                conn_eco.close()
                return await i.response.send_message("<a:wt_torono:1480580892706603018> Insufficient personal funds.", ephemeral=True)
            c_eco.execute("UPDATE wallets SET balance = balance - ? WHERE user_id = ?", (amt, i.user.id))
            conn_eco.commit(); conn_eco.close()
            conn = get_db_connection(); c = conn.cursor()
            c.execute("UPDATE businesses SET capital = capital + ? WHERE user_id = ?", (amt, i.user.id))
            conn.commit(); conn.close()
            await i.response.send_message(f"<a:wt_toroexclaim:1480581004317036624> Injected A$ {amt:,}.", ephemeral=True)
        except ValueError:
            await i.response.send_message("<a:wt_torono:1480580892706603018> Invalid amount.", ephemeral=True)

class ProductModal(discord.ui.Modal, title='Launch New Product'):
    p_name = discord.ui.TextInput(label='Product Name', min_length=3, max_length=30)
    p_price = discord.ui.TextInput(label='Unit Price (A$)', placeholder='e.g., 500', max_length=7)
    p_cost = discord.ui.TextInput(label='Cost Per Unit (A$)', max_length=7)
    p_qty = discord.ui.TextInput(label='Daily Target Quantity', placeholder='e.g., 500', max_length=7)
    def __init__(self, category: str):
        super().__init__(); self.category = category
    async def on_submit(self, i: discord.Interaction):
        try:
            price, cost, qty = int(self.p_price.value), int(self.p_cost.value), int(self.p_qty.value)
            if price <= 0 or cost < 0 or cost >= price or qty <= 0: raise ValueError
            conn = get_db_connection(); c = conn.cursor()
            c.execute("""INSERT INTO business_products 
                         (user_id, name, category, unit_price, cost_to_make, production_target, quality_tier, active)
                         VALUES (?, ?, ?, ?, ?, ?, 'Standard', 1)""",
                      (i.user.id, self.p_name.value, self.category, price, cost, qty))
            c.execute("UPDATE businesses SET sector = ? WHERE user_id = ? AND sector IS NULL",
                      (self.category, i.user.id))
            conn.commit(); conn.close()
            await i.response.send_message(f"<a:wt_toroexclaim:1480581004317036624> **{self.p_name.value}** launched.", ephemeral=True)
        except:
            await i.response.send_message("<a:wt_torono:1480580892706603018> Invalid data.", ephemeral=True)

class UpgradeProductDropdown(discord.ui.Select):
    def __init__(self, user_id):
        self.user_id = user_id
        conn = get_db_connection(); c = conn.cursor()
        c.execute("SELECT id, name, quality_tier FROM business_products WHERE user_id = ? AND active = 1", (user_id,))
        prods = c.fetchall(); conn.close()
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
        conn = get_db_connection(); c = conn.cursor()
        c.execute("SELECT tech_level FROM businesses WHERE user_id = ?", (i.user.id,))
        tech = c.fetchone()[0]
        required = QUALITY_TIERS[new_tier]["required_tech"]
        if tech < required:
            conn.close()
            return await i.response.send_message(f"<a:wt_torono:1480580892706603018> Need Tech Level {required} for {new_tier} tier.", ephemeral=True)
        c.execute("UPDATE business_products SET quality_tier = ? WHERE id = ?", (new_tier, int(pid)))
        conn.commit(); conn.close()
        await i.response.send_message(f"<a:wt_toroexclaim:1480581004317036624> Product upgraded to **{new_tier}**!", ephemeral=True)

class MarketingModal(discord.ui.Modal, title='Marketing Blitz'):
    amount = discord.ui.TextInput(label='Amount to spend (A$)', placeholder='e.g., 100000')
    async def on_submit(self, i: discord.Interaction):
        try:
            amt = int(self.amount.value)
            if amt <= 0: raise ValueError
            conn = get_db_connection(); c = conn.cursor()
            c.execute("SELECT capital FROM businesses WHERE user_id = ?", (i.user.id,))
            biz = c.fetchone()
            if not biz or biz[0] < amt:
                conn.close()
                return await i.response.send_message("<a:wt_torono:1480580892706603018> Insufficient capital.", ephemeral=True)
            boost = 1.0 + (amt / 100_000) * 0.1
            c.execute("UPDATE businesses SET capital = capital - ?, demand_boost = demand_boost + ?, marketing_budget = marketing_budget + ? WHERE user_id = ?",
                      (amt, boost, amt, i.user.id))
            conn.commit(); conn.close()
            await i.response.send_message(f"📢 Marketing blitz launched! Demand boosted by +{boost*100-100:.1f}%.", ephemeral=True)
        except ValueError:
            await i.response.send_message("<a:wt_torono:1480580892706603018> Invalid amount.", ephemeral=True)

class DividendModal(discord.ui.Modal, title='Pay Dividends'):
    amount = discord.ui.TextInput(label='Amount to distribute (A$)', placeholder='e.g., 50000')
    async def on_submit(self, i: discord.Interaction):
        try:
            amt = int(self.amount.value)
            if amt <= 0: raise ValueError
            conn = get_db_connection(); c = conn.cursor()
            c.execute("SELECT name, capital, is_public FROM businesses WHERE user_id = ?", (i.user.id,))
            biz = c.fetchone()
            if not biz or not biz[2]:
                conn.close()
                return await i.response.send_message("<a:wt_torono:1480580892706603018> Company not public.", ephemeral=True)
            if biz[1] < amt:
                conn.close()
                return await i.response.send_message("<a:wt_torono:1480580892706603018> Insufficient capital.", ephemeral=True)
            c.execute("UPDATE businesses SET capital = capital - ? WHERE user_id = ?", (amt, i.user.id))
            conn.commit()
            conn_eco = get_eco_connection(); c_eco = conn_eco.cursor()
            c_eco.execute("SELECT user_id, shares FROM portfolio WHERE symbol = ?", (biz[0][:4].upper(),))
            shareholders = c_eco.fetchall()
            total_shares = sum(s[1] for s in shareholders) if shareholders else 0
            if total_shares == 0:
                conn_eco.close(); conn.close()
                return await i.response.send_message("No shareholders to pay.", ephemeral=True)
            for uid, sh in shareholders:
                payout = int(amt * (sh / total_shares))
                c_eco.execute("INSERT INTO wallets (user_id, balance, active_card) VALUES (?, ?, 'silver') ON CONFLICT DO UPDATE SET balance = balance + ?", (uid, payout, payout))
            conn_eco.commit(); conn_eco.close()
            conn.close()
            await i.response.send_message(f"💸 Paid A$ {amt:,} in dividends to {len(shareholders)} shareholders.", ephemeral=False)
        except ValueError:
            await i.response.send_message("<a:wt_torono:1480580892706603018> Invalid amount.", ephemeral=True)

class RndInvestModal(discord.ui.Modal, title='Invest in R&D'):
    amount = discord.ui.TextInput(label='Amount to invest (A$)', placeholder='e.g., 50000')
    async def on_submit(self, i: discord.Interaction):
        try:
            amt = int(self.amount.value)
            if amt <= 0: raise ValueError
            conn = get_db_connection(); c = conn.cursor()
            c.execute("SELECT capital, tech_level FROM businesses WHERE user_id = ?", (i.user.id,))
            biz = c.fetchone()
            if not biz: conn.close(); return await i.response.send_message("No business.", ephemeral=True)
            if biz[0] < amt: conn.close(); return await i.response.send_message("<a:wt_torono:1480580892706603018> Insufficient capital.", ephemeral=True)
            old_tech = biz[1]
            pts = amt // 5000
            new_tech = old_tech + pts
            c.execute("UPDATE businesses SET capital = capital - ?, tech_level = tech_level + ? WHERE user_id = ?", (amt, pts, i.user.id))
            conn.commit(); conn.close()
            # Check for milestone unlocks
            unlocked = []
            for milestone, desc in TECH_MILESTONES.items():
                if old_tech < milestone <= new_tech:
                    unlocked.append(f"**Tech {milestone}:** {desc}")
            msg = f"<a:wt_toroexclaim:1480581004317036624> Invested A$ {amt:,} → +{pts} tech points (Total: {new_tech})."
            if unlocked:
                msg += "\n\n🎉 **Milestones Unlocked:**\n" + "\n".join(unlocked)
            await i.response.send_message(msg, ephemeral=True)
        except ValueError:
            await i.response.send_message("<a:wt_torono:1480580892706603018> Invalid amount.", ephemeral=True)

class BannerModal(discord.ui.Modal, title='Set Newspaper Banner'):
    url = discord.ui.TextInput(label='Image URL', placeholder='https://i.imgur.com/...', max_length=300)
    async def on_submit(self, i: discord.Interaction):
        conn = get_db_connection(); c = conn.cursor()
        c.execute("INSERT OR REPLACE INTO config (key, value) VALUES ('newspaper_banner', ?)", (self.url.value,))
        conn.commit(); conn.close()
        await i.response.send_message("<a:wt_toroexclaim:1480581004317036624> Banner updated! Next newspaper will use this image.", ephemeral=True)

class PhilosophyDropdown(discord.ui.Select):
    def __init__(self):
        opts = [discord.SelectOption(label="Artisan / Premium", value="Artisan"),
                discord.SelectOption(label="Mass Market", value="Mass Market")]
        super().__init__(placeholder="Production Philosophy...", options=opts)
    async def callback(self, i: discord.Interaction):
        conn = get_db_connection(); c = conn.cursor()
        c.execute("UPDATE businesses SET philosophy = ? WHERE user_id = ?", (self.values[0], i.user.id))
        conn.commit(); conn.close()
        await i.response.send_message(f"<a:wt_toroexclaim:1480581004317036624> Philosophy set to **{self.values[0]}**.", ephemeral=True)

class HireSpecialistDropdown(discord.ui.Select):
    def __init__(self):
        opts = [discord.SelectOption(label="Lead Engineer (A$ 15k)", value="Engineer"),
                discord.SelectOption(label="Quality Auditor (A$ 15k)", value="Auditor"),
                discord.SelectOption(label="Sales Shark (A$ 15k)", value="Shark")]
        super().__init__(placeholder="Hire Specialist...", options=opts)
    async def callback(self, i: discord.Interaction):
        conn = get_db_connection(); c = conn.cursor()
        c.execute("SELECT capital, hq_level FROM businesses WHERE user_id = ?", (i.user.id,))
        biz = c.fetchone()
        c.execute("SELECT COUNT(id) FROM employees WHERE user_id = ?", (i.user.id,))
        emps = c.fetchone()[0]
        if biz[0] < 15000: return await i.response.send_message("<a:wt_torono:1480580892706603018> Not enough capital.", ephemeral=True)
        if emps >= HQ_LEVELS[biz[1]]["max_emp"]: return await i.response.send_message("<a:wt_torono:1480580892706603018> HQ full.", ephemeral=True)
        c.execute("UPDATE businesses SET capital = capital - 15000 WHERE user_id = ?", (i.user.id,))
        c.execute("INSERT INTO employees (user_id, name, salary, morale, specialization) VALUES (?, ?, 4000, 100, ?)",
                  (i.user.id, random.choice(NAMES), self.values[0]))
        conn.commit(); conn.close()
        await i.response.send_message(f"<a:wt_toroexclaim:1480581004317036624> **{self.values[0]}** hired.", ephemeral=True)

class FireEmployeeDropdown(discord.ui.Select):
    def __init__(self, user_id):
        self.user_id = user_id
        conn = get_db_connection(); c = conn.cursor()
        c.execute("SELECT id, name, salary FROM employees WHERE user_id = ?", (user_id,))
        emps = c.fetchall(); conn.close()
        opts = [discord.SelectOption(label=f"Fire {n}", description=f"A$ {s:,}", value=str(eid)) for eid,n,s in emps[:25]]
        if not opts: opts.append(discord.SelectOption(label="No employees", value="none"))
        super().__init__(placeholder="Terminate staff...", options=opts)
    async def callback(self, i: discord.Interaction):
        if self.values[0] == "none": return
        conn = get_db_connection(); c = conn.cursor()
        c.execute("DELETE FROM employees WHERE id = ?", (int(self.values[0]),))
        conn.commit(); conn.close()
        await i.response.send_message("<a:wt_toroexclaim:1480581004317036624> Employee fired.", ephemeral=True)

class StartupModal(discord.ui.Modal, title='Incorporate New Business'):
    b_name = discord.ui.TextInput(label='Company Name', min_length=3, max_length=30)
    def __init__(self, use_loan: bool):
        super().__init__(); self.use_loan = use_loan
    async def on_submit(self, i: discord.Interaction):
        conn_eco = get_eco_connection(); c_eco = conn_eco.cursor()
        c_eco.execute("SELECT balance FROM wallets WHERE user_id = ?", (i.user.id,))
        bal = c_eco.fetchone()
        if not self.use_loan:
            if not bal or bal[0] < 500_000:
                conn_eco.close()
                return await i.response.send_message("<a:wt_torono:1480580892706603018> Need A$ 500k.", ephemeral=True)
            c_eco.execute("UPDATE wallets SET balance = balance - 500000 WHERE user_id = ?", (i.user.id,))
            capital, loan, inst = 500_000, 0, 0
        else:
            capital, loan, inst = 500_000, 550_000, 10
        conn_eco.commit(); conn_eco.close()
        conn = get_db_connection(); c = conn.cursor()
        c.execute("INSERT INTO businesses (user_id, name, capital, loan_balance, installments_left, reputation) VALUES (?, ?, ?, ?, ?, 100)",
                  (i.user.id, self.b_name.value, capital, loan, inst))
        conn.commit(); conn.close()
        await i.response.send_message(f"<a:wt_toroexclaim:1480581004317036624> **{self.b_name.value}** incorporated!", ephemeral=True)

class VPTitleDropdown(discord.ui.Select):
    def __init__(self, vp_user):
        self.vp_user = vp_user
        opts = [discord.SelectOption(label=t, value=t) for t in ["COO", "CFO", "CMO", "VP"]]
        super().__init__(placeholder="Select title...", options=opts)
    async def callback(self, i: discord.Interaction):
        conn = get_db_connection(); c = conn.cursor()
        c.execute("UPDATE businesses SET vp_id = ?, vp_title = ? WHERE user_id = ?", (self.vp_user.id, self.values[0], i.user.id))
        conn.commit(); conn.close()
        await i.response.send_message(f"<a:wt_toroexclaim:1480581004317036624> **{self.vp_user.name}** appointed as {self.values[0]}.", ephemeral=False)

# ----- sub-views -----
class ProductPerformanceView(discord.ui.View):
    def __init__(self, user_id): super().__init__(timeout=180); self.user_id = user_id
    @discord.ui.button(label="Refresh", style=discord.ButtonStyle.secondary)
    async def refresh(self, i: discord.Interaction, btn): await i.response.edit_message(embed=self.get_embed(), view=self)
    def get_embed(self):
        conn = get_db_connection(); c = conn.cursor()
        c.execute("SELECT name, unit_price, cost_to_make, lifetime_revenue, quality_tier FROM business_products WHERE user_id = ?", (self.user_id,))
        prods = c.fetchall(); conn.close()
        embed = discord.Embed(title="꒰ა ﹒chérie  ⸝⸝", color=0xffffff)
        if not prods: embed.description = "No products."; return embed
        max_rev = max(p[3] for p in prods)
        desc = ""
        for name, price, cost, rev, tier in prods:
            margin = price - cost
            chart = ascii_bar(rev, max_rev)
            desc += f"**<:s_white2:1382052523166142486> {name}** ({tier})\n`{chart}` A$ {rev:,} | Margin A$ {margin:,}\n\n"
        embed.description = desc; return embed

class HRView(discord.ui.View):
    def __init__(self, user_id): super().__init__(timeout=180); self.add_item(FireEmployeeDropdown(user_id)); self.add_item(HireSpecialistDropdown())
    @discord.ui.button(label="Hire Staff (A$ 2k)", style=discord.ButtonStyle.secondary, row=2)
    async def hire(self, i: discord.Interaction, btn):
        conn = get_db_connection(); c = conn.cursor()
        c.execute("SELECT capital, hq_level FROM businesses WHERE user_id = ?", (i.user.id,)); biz = c.fetchone()
        c.execute("SELECT COUNT(id) FROM employees WHERE user_id = ?", (i.user.id,)); emps = c.fetchone()[0]
        if biz[0] < 2000: return await i.response.send_message("<a:wt_torono:1480580892706603018> Not enough capital.", ephemeral=True)
        if emps >= HQ_LEVELS[biz[1]]["max_emp"]: return await i.response.send_message("<a:wt_torono:1480580892706603018> HQ full.", ephemeral=True)
        c.execute("UPDATE businesses SET capital = capital - 2000 WHERE user_id = ?", (i.user.id,))
        c.execute("INSERT INTO employees (user_id, name, salary, morale, specialization) VALUES (?, ?, 1500, 80, 'None')", (i.user.id, random.choice(NAMES)))
        conn.commit(); conn.close()
        await i.response.send_message("<a:wt_toroexclaim:1480581004317036624> Staff hired.", ephemeral=True)
    @discord.ui.button(label="Host Event (A$ 5k)", style=discord.ButtonStyle.secondary, row=2)
    async def morale(self, i: discord.Interaction, btn):
        conn = get_db_connection(); c = conn.cursor()
        c.execute("SELECT capital FROM businesses WHERE user_id = ?", (i.user.id,)); cap = c.fetchone()[0]
        if cap < 5000: return await i.response.send_message("<a:wt_torono:1480580892706603018> Not enough capital.", ephemeral=True)
        c.execute("UPDATE businesses SET capital = capital - 5000 WHERE user_id = ?", (i.user.id,))
        c.execute("UPDATE employees SET morale = MIN(100, morale + 25) WHERE user_id = ?", (i.user.id,))
        conn.commit(); conn.close()
        await i.response.send_message("<a:wt_torolove:1480580899430203484> Morale boosted!", ephemeral=True)

class OpsView(discord.ui.View):
    def __init__(self, user_id):
        super().__init__(timeout=180)
        self.user_id = user_id
        self.add_item(PhilosophyDropdown())
        self.add_item(UpgradeProductDropdown(user_id))
    @discord.ui.button(label="Launch Product", style=discord.ButtonStyle.secondary, row=2)
    async def prod(self, i: discord.Interaction, btn):
        opts = [discord.SelectOption(label=c, value=c) for c in SECTORS]
        sel = discord.ui.Select(placeholder="Market Sector...", options=opts)
        async def call(it): await it.response.send_modal(ProductModal(sel.values[0]))
        sel.callback = call
        v = discord.ui.View(); v.add_item(sel)
        await i.response.send_message(view=v, ephemeral=True)
    @discord.ui.button(label="Upgrade HQ", style=discord.ButtonStyle.secondary, row=2)
    async def hq(self, i: discord.Interaction, btn):
        conn = get_db_connection(); c = conn.cursor()
        c.execute("SELECT capital, hq_level FROM businesses WHERE user_id = ?", (i.user.id,)); biz = c.fetchone()
        nxt = biz[1] + 1
        if nxt not in HQ_LEVELS: return await i.response.send_message("<a:wt_torono:1480580892706603018> Max level.", ephemeral=True)
        cost = HQ_LEVELS[nxt]["cost"]
        if biz[0] < cost: return await i.response.send_message(f"<a:wt_torono:1480580892706603018> Need A$ {cost:,}.", ephemeral=True)
        c.execute("UPDATE businesses SET capital = capital - ?, hq_level = ? WHERE user_id = ?", (cost, nxt, i.user.id))
        conn.commit(); conn.close()
        await i.response.send_message("<a:wt_toroexclaim:1480581004317036624> HQ Upgraded!", ephemeral=True)
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
        conn = get_db_connection(); c = conn.cursor()
        c.execute("SELECT capital FROM businesses WHERE user_id = ?", (self.user_id,))
        if c.fetchone()[0] < 100_000: return await i.response.send_message("<a:wt_torono:1480580892706603018> Insufficient funds.", ephemeral=True)
        c.execute("UPDATE businesses SET capital = capital - 100000 WHERE user_id = ?", (self.user_id,))
        c.execute("UPDATE employees SET morale = 50 WHERE user_id = ?", (self.user_id,))
        conn.commit(); conn.close()
        await i.response.send_message("<a:wt_toroexclaim:1480581004317036624> Strike settled.", ephemeral=False)
    @discord.ui.button(label="Grant 15% Raise", style=discord.ButtonStyle.danger)
    async def raise_(self, i: discord.Interaction, btn):
        conn = get_db_connection(); c = conn.cursor()
        c.execute("UPDATE employees SET salary = CAST(salary * 1.15 AS INTEGER), morale = 80 WHERE user_id = ?", (self.user_id,))
        conn.commit(); conn.close()
        await i.response.send_message("<a:wt_toroexclaim:1480581004317036624> Strike settled with raises.", ephemeral=False)

class TerminalView(discord.ui.View):
    def __init__(self, bot, user_id):
        super().__init__(timeout=None)
        self.bot = bot
        conn = get_db_connection(); c = conn.cursor()
        c.execute("SELECT AVG(morale) FROM employees WHERE user_id = ?", (user_id,))
        avg = c.fetchone()[0]
        conn.close()
        if avg is not None and avg < 20:
            self.add_item(discord.ui.Button(label="RESOLVE STRIKE", style=discord.ButtonStyle.danger, custom_id="strike_btn", row=4))

    @discord.ui.button(label="Balance Sheet", style=discord.ButtonStyle.secondary, row=0)
    async def balance(self, i: discord.Interaction, btn):
        conn = get_db_connection(); c = conn.cursor()
        c.execute("SELECT capital, loan_balance, owner_salary, last_report, vp_title FROM businesses WHERE user_id = ?", (i.user.id,))
        biz = c.fetchone()
        c.execute("SELECT SUM(salary), COUNT(id) FROM employees WHERE user_id = ?", (i.user.id,))
        emps = c.fetchone()
        conn.close()
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
            "LATEST REPORT:\n"
            f"{biz[3]}\n"
            "```"
        )
        embed = discord.Embed(title="꒰ა ﹒chérie  ⸝⸝", color=0xffffff, description=receipt)
        await i.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="Operations", style=discord.ButtonStyle.secondary, row=0)
    async def ops(self, i: discord.Interaction, btn):
        embed = discord.Embed(title="꒰ა ﹒chérie  ⸝⸝", color=0xffffff, description="**Operational Control**")
        await i.response.send_message(embed=embed, view=OpsView(i.user.id), ephemeral=True)

    @discord.ui.button(label="HR", style=discord.ButtonStyle.secondary, row=0)
    async def hr(self, i: discord.Interaction, btn):
        conn = get_db_connection(); c = conn.cursor()
        c.execute("SELECT name, salary, morale, specialization FROM employees WHERE user_id = ?", (i.user.id,))
        emps = c.fetchall(); conn.close()
        embed = discord.Embed(title="꒰ა ﹒chérie  ⸝⸝", color=0xffffff)
        if not emps: embed.description = "No employees."
        else:
            desc = "<a:wt_torolove:1480580899430203484> **Human Resources**\n"
            for n,s,m,sp in emps[:15]:
                desc += f"<:s_white2:1382052523166142486> **{n}** ({sp}) - A$ {s:,} | {m}% morale\n"
            if len(emps) > 15: desc += f"*...and {len(emps)-15} more.*\n"
            embed.description = desc
        await i.response.send_message(embed=embed, view=HRView(i.user.id), ephemeral=True)

    @discord.ui.button(label="R&D Hub", style=discord.ButtonStyle.secondary, row=1)
    async def rnd(self, i: discord.Interaction, btn):
        conn = get_db_connection(); c = conn.cursor()
        c.execute("SELECT tech_level FROM businesses WHERE user_id = ?", (i.user.id,))
        tech = c.fetchone()[0]
        conn.close()
        embed = discord.Embed(title="🔬 R&D Tech Tree", color=0xffffff)
        desc = f"**Current Tech Level:** {tech}\n\n"
        # Show unlocked and upcoming milestones
        for milestone, label in TECH_MILESTONES.items():
            if tech >= milestone:
                desc += f"✅ **Tech {milestone}:** {label}\n"
            else:
                desc += f"🔒 **Tech {milestone}:** {label}\n"
        desc += "\n*Invest capital in R&D to unlock new tiers and bonuses!*"
        embed.description = desc
        view = ProductPerformanceView(i.user.id)
        await i.response.send_message(embed=embed, view=view, ephemeral=True)

    @discord.ui.button(label="Rename", style=discord.ButtonStyle.secondary, row=1)
    async def rename(self, i: discord.Interaction, btn):
        await i.response.send_modal(RenameCompanyModal())

    @discord.ui.button(label="IPO", style=discord.ButtonStyle.success, row=1)
    async def ipo(self, i: discord.Interaction, btn):
        conn = get_db_connection(); c = conn.cursor()
        c.execute("SELECT name, capital, is_public FROM businesses WHERE user_id = ?", (i.user.id,))
        biz = c.fetchone()
        if biz[2] == 1: return await i.response.send_message("<a:wt_torono:1480580892706603018> Already public.", ephemeral=True)
        if biz[1] < 2_000_000: return await i.response.send_message("<a:wt_torono:1480580892706603018> A$ 2M required.", ephemeral=True)
        c.execute("SELECT COUNT(id) FROM employees WHERE user_id = ?", (i.user.id,))
        emp_count = c.fetchone()[0]
        start_price = max(500, int((biz[1] * 0.001) + (emp_count * 10)))
        sym = biz[0][:4].upper()
        c.execute("UPDATE businesses SET is_public = 1 WHERE user_id = ?", (i.user.id,))
        conn.commit(); conn.close()
        conn_eco = get_eco_connection(); c_eco = conn_eco.cursor()
        c_eco.execute("INSERT OR IGNORE INTO stocks (symbol, name, price, volatility, trend) VALUES (?, ?, ?, 15, 'FLAT')", (sym, biz[0], start_price))
        conn_eco.commit(); conn_eco.close()
        await i.response.send_message(f"<a:wt_toroexclaim:1480581004317036624> **IPO SUCCESSFUL!** Trading as **{sym}** at A$ {start_price:,}.", ephemeral=False)

    @discord.ui.button(label="Marketing", style=discord.ButtonStyle.primary, row=2)
    async def market(self, i: discord.Interaction, btn):
        await i.response.send_modal(MarketingModal())

    @discord.ui.button(label="Pay Dividends", style=discord.ButtonStyle.primary, row=2)
    async def dividend(self, i: discord.Interaction, btn):
        await i.response.send_modal(DividendModal())

    @discord.ui.button(label="Invest in R&D", style=discord.ButtonStyle.primary, row=2)
    async def invest_rnd(self, i: discord.Interaction, btn):
        await i.response.send_modal(RndInvestModal())

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.data.get('custom_id') == "strike_btn":
            embed = discord.Embed(title="꒰ა ﹒chérie  ⸝⸝", color=0xffffff, description="**UNION DEMANDS**")
            await interaction.response.send_message(embed=embed, view=SettlementView(interaction.user.id), ephemeral=True)
            return False
        return True

# ============================================
# 🏙️ THE BUSINESS COG (main logic)
# ============================================
class Business(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.setup_db()
        self.daily_cycle.start()

    def setup_db(self):
        conn = get_db_connection()
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS businesses (
            user_id INTEGER PRIMARY KEY, name TEXT, capital INTEGER DEFAULT 0,
            owner_salary INTEGER DEFAULT 0, loan_balance INTEGER DEFAULT 0,
            installments_left INTEGER DEFAULT 0, days_open INTEGER DEFAULT 0,
            last_report TEXT DEFAULT 'No reports.', vp_id INTEGER, vp_title TEXT,
            demand_boost REAL DEFAULT 1.0, hq_level INTEGER DEFAULT 0,
            philosophy TEXT DEFAULT 'Mass Market', reputation INTEGER DEFAULT 100,
            is_public INTEGER DEFAULT 0, description TEXT DEFAULT '*A rising corporate empire.*',
            sector TEXT, tech_level INTEGER DEFAULT 0, marketing_budget INTEGER DEFAULT 0
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
        c.execute('''CREATE TABLE IF NOT EXISTS config (
            key TEXT PRIMARY KEY, value TEXT
        )''')
        for table, col, dtype in [
            ("businesses","sector","TEXT"), ("businesses","tech_level","INTEGER DEFAULT 0"),
            ("businesses","marketing_budget","INTEGER DEFAULT 0"),
            ("business_products","quality_tier","TEXT DEFAULT 'Standard'")
        ]:
            try: c.execute(f"ALTER TABLE {table} ADD COLUMN {col} {dtype}")
            except: pass
        conn.commit(); conn.close()

    # ---------- commands ----------
    @app_commands.command(name="appoint_vp")
    async def appoint_vp(self, i: discord.Interaction, user: discord.Member):
        if user.bot or user.id == i.user.id: return await i.response.send_message("<a:wt_torono:1480580892706603018> Invalid user.", ephemeral=True)
        conn = get_db_connection(); c = conn.cursor()
        if not c.execute("SELECT 1 FROM businesses WHERE user_id = ?", (i.user.id,)).fetchone():
            conn.close(); return await i.response.send_message("<a:wt_torono:1480580892706603018> No business.", ephemeral=True)
        conn.close()
        v = discord.ui.View(); v.add_item(VPTitleDropdown(user))
        await i.response.send_message(f"<a:wt_torospin:1480580977867624540> Select title for {user.name}:", view=v, ephemeral=True)

    @app_commands.command(name="rename_company", description="Rename your company")
    async def rename_cmd(self, i: discord.Interaction):
        conn = get_db_connection(); c = conn.cursor()
        if not c.execute("SELECT 1 FROM businesses WHERE user_id = ?", (i.user.id,)).fetchone():
            conn.close(); return await i.response.send_message("<a:wt_torono:1480580892706603018> No business found.", ephemeral=True)
        conn.close()
        await i.response.send_modal(RenameCompanyModal())

    @app_commands.command(name="set_banner", description="ADMIN: Set the newspaper embed banner image")
    @app_commands.default_permissions(administrator=True)
    async def set_banner(self, i: discord.Interaction, url: str):
        """Change the banner image used in the daily newspaper."""
        conn = get_db_connection(); c = conn.cursor()
        c.execute("INSERT OR REPLACE INTO config (key, value) VALUES ('newspaper_banner', ?)", (url,))
        conn.commit(); conn.close()
        await i.response.send_message(f"<a:wt_toroexclaim:1480581004317036624> Newspaper banner updated!")

    def get_cycle_hours(self) -> int:
        """Read configured cycle hours from config, default 5."""
        conn = get_db_connection(); c = conn.cursor()
        c.execute("SELECT value FROM config WHERE key = 'cycle_hours'")
        row = c.fetchone()
        conn.close()
        return int(row[0]) if row else 5

    @app_commands.command(name="set_cycle", description="ADMIN: Set how often the business cycle runs (in hours)")
    @app_commands.default_permissions(administrator=True)
    async def set_cycle(self, i: discord.Interaction, hours: int):
        if hours < 1 or hours > 168:
            return await i.response.send_message("<a:wt_torono:1480580892706603018> Must be between 1 and 168 hours.", ephemeral=True)
        conn = get_db_connection(); c = conn.cursor()
        c.execute("INSERT OR REPLACE INTO config (key, value) VALUES ('cycle_hours', ?)", (str(hours),))
        conn.commit(); conn.close()
        # Restart the loop with new timing
        self.daily_cycle.cancel()
        self.daily_cycle.change_interval(hours=hours)
        self.daily_cycle.start()
        await i.response.send_message(f"<a:wt_toroexclaim:1480581004317036624> Business cycle set to every **{hours} hours**.")

    @app_commands.command(name="business")
    async def business_hub(self, i: discord.Interaction):
        conn = get_db_connection(); c = conn.cursor()
        c.execute("SELECT name, capital, reputation, description, hq_level, sector, is_public, tech_level, marketing_budget FROM businesses WHERE user_id = ?", (i.user.id,))
        biz = c.fetchone()
        if not biz:
            conn.close(); v = discord.ui.View()
            v.add_item(discord.ui.Button(label="Fund Outright (500k)", style=discord.ButtonStyle.secondary, custom_id="f_out"))
            v.add_item(discord.ui.Button(label="Secure Loan", style=discord.ButtonStyle.secondary, custom_id="f_loan"))
            async def call(ix): await ix.response.send_modal(StartupModal(ix.data['custom_id']=="f_loan"))
            for child in v.children: child.callback = call
            return await i.response.send_message(embed=discord.Embed(title="꒰ა ﹒chérie  ⸝⸝", color=0xffffff, description="Incorporate for A$ 500k."), view=v, ephemeral=False)
        c.execute("SELECT COUNT(id), AVG(morale) FROM employees WHERE user_id = ?", (i.user.id,))
        emps = c.fetchone(); conn.close()
        await i.response.send_message("<a:wt_torospin:1480580977867624540> *𝐴𝑐𝑐𝑒𝑠𝑠𝑖𝑛𝑔 𝐶𝐸𝑂 𝑇𝑒𝑟𝑚𝑖𝑛𝑎𝑙...*", ephemeral=False)
        await asyncio.sleep(1.5)
        embed = discord.Embed(title=f"꒰ა ﹒{biz[0]}  ⸝⸝", color=0xffffff)
        embed.description = (
            f"*{biz[3]}*\n\n"
            f"<:s_white2:1382052523166142486> **Capital:** A$ {biz[1]:,}\n"
            f"<:s_white2:1382052523166142486> **Reputation:** {biz[2]}%\n"
            f"<:s_white2:1382052523166142486> **HQ:** {HQ_LEVELS[biz[4]]['name']}\n"
            f"<:s_white2:1382052523166142486> **Sector:** {biz[5] or 'None'}\n"
            f"<:s_white2:1382052523166142486> **Employees:** {emps[0] or 0} | Morale: {make_progress_bar(int(emps[1]) if emps[1] else 100)}\n"
            f"<:s_white2:1382052523166142486> **Tech Level:** {biz[7]} | Marketing: A$ {biz[8]:,}\n"
        )
        # Custom banner from config
        conn = get_db_connection(); c = conn.cursor()
        c.execute("SELECT value FROM config WHERE key = 'newspaper_banner'")
        row = c.fetchone()
        banner_url = row[0] if row else DEFAULT_BANNER
        conn.close()
        embed.set_image(url=banner_url)
        await i.edit_original_response(content=None, embed=embed, view=TerminalView(self.bot, i.user.id))

    @app_commands.command(name="invest_rnd", description="Invest capital into R&D to boost tech level")
    async def invest_rnd_cmd(self, i: discord.Interaction, amount: int):
        if amount <= 0: return await i.response.send_message("<a:wt_torono:1480580892706603018> Invalid amount.", ephemeral=True)
        conn = get_db_connection(); c = conn.cursor()
        c.execute("SELECT capital, tech_level FROM businesses WHERE user_id = ?", (i.user.id,))
        biz = c.fetchone()
        if not biz: conn.close(); return await i.response.send_message("No business.", ephemeral=True)
        if biz[0] < amount: conn.close(); return await i.response.send_message("<a:wt_torono:1480580892706603018> Insufficient capital.", ephemeral=True)
        old_tech = biz[1]
        pts = amount // 5000
        new_tech = old_tech + pts
        c.execute("UPDATE businesses SET capital = capital - ?, tech_level = tech_level + ? WHERE user_id = ?", (amount, pts, i.user.id))
        conn.commit(); conn.close()
        unlocked = []
        for milestone, desc in TECH_MILESTONES.items():
            if old_tech < milestone <= new_tech:
                unlocked.append(f"**Tech {milestone}:** {desc}")
        msg = f"<a:wt_toroexclaim:1480581004317036624> Invested A$ {amount:,} → +{pts} tech points (Total: {new_tech})."
        if unlocked:
            msg += "\n\n🎉 **Milestones Unlocked:**\n" + "\n".join(unlocked)
        await i.response.send_message(msg, ephemeral=True)

    @app_commands.command(name="marketing_push", description="Spend capital on a marketing blitz")
    async def marketing(self, i: discord.Interaction, amount: int):
        await i.response.send_modal(MarketingModal())

    # ---------- daily cycle (core simulation) ----------
    @tasks.loop(hours=5)  # default 5 hours
    async def daily_cycle(self):
        conn = get_db_connection(); c = conn.cursor()
        conn_eco = get_eco_connection(); c_eco = conn_eco.cursor()
        self.process_events(c)
        c.execute("SELECT * FROM businesses")
        businesses = c.fetchall()
        cols = [desc[0] for desc in c.description]
        performance = {}
        for row in businesses:
            biz = dict(zip(cols, row))
            uid = biz['user_id']
            rpt, net = self.simulate_company(c, c_eco, biz)
            c.execute("UPDATE businesses SET last_report = ?, demand_boost = MAX(0.8, demand_boost * 0.9), marketing_budget = MAX(0, marketing_budget - 5000) WHERE user_id = ?", (rpt, uid))
            if net is not None:
                performance[uid] = net
        sector_perf = {}
        for row in businesses:
            biz = dict(zip(cols, row))
            if biz['sector']:
                sector_perf.setdefault(biz['sector'], {})[biz['user_id']] = performance.get(biz['user_id'], 0)
        for sector, comps in sector_perf.items():
            total = sum(max(0, p) for p in comps.values()) or 1
            for uid, prof in comps.items():
                share = (max(0, prof) / total) * 100
                c.execute("UPDATE businesses SET demand_boost = demand_boost + ? WHERE user_id = ?", (share/200, uid))
        self.generate_events(c)
        conn.commit(); conn.close()
        conn_eco.commit(); conn_eco.close()
        await self.publish_newspaper()

    def apply_tech_passives(self, biz):
        """Apply tech-level passive bonuses."""
        tech = biz['tech_level']
        bonuses = {"cost_reduction": 0.0, "rep_boost": 0.0, "demand_boost": 0.0}
        if tech >= 10:
            bonuses["demand_boost"] += 0.05  # 5% demand boost
        if tech >= 20:
            bonuses["cost_reduction"] += 0.10  # 10% cost reduction
        if tech >= 25:
            bonuses["rep_boost"] += 10.0  # 10% reputation boost
        if tech >= 30:
            # Industry 4.0: double staff multipliers
            bonuses["cost_reduction"] += 0.10
            bonuses["demand_boost"] += 0.10
        return bonuses

    def simulate_company(self, c, c_eco, biz):
        uid = biz['user_id']
        c.execute("SELECT * FROM employees WHERE user_id = ?", (uid,))
        emps = c.fetchall()
        c.execute("SELECT * FROM business_products WHERE user_id = ? AND active = 1", (uid,))
        prods = c.fetchall()
        if not emps or not prods:
            return "No employees/products active.", None

        emp_count = len(emps)
        total_payroll = sum(e[3] for e in emps)
        avg_morale = sum(e[4] for e in emps)/emp_count
        if avg_morale < 20:
            return "STRIKE ACTIVE!", None

        # Tech passives
        passives = self.apply_tech_passives(biz)

        eng = 1.0 + 0.10*sum(1 for e in emps if e[5]=='Engineer') + biz['tech_level']*0.02
        if biz['tech_level'] >= 30:
            eng *= 2.0  # Industry 4.0
        aud = 1.0 - min(0.30, 0.05*sum(1 for e in emps if e[5]=='Auditor'))
        shark = 1.0 + 0.15*sum(1 for e in emps if e[5]=='Shark')

        rep_mod = biz['reputation']/100.0
        if biz['philosophy'] == 'Artisan':
            dem = random.uniform(0.9,1.2)*rep_mod*(biz['demand_boost'] + passives["demand_boost"])*shark
            out_m = 0.5*eng
            n_rep = min(100, biz['reputation']+2 + passives["rep_boost"])
        else:
            dem = random.uniform(1.0,1.5)*rep_mod*(biz['demand_boost'] + passives["demand_boost"])*shark
            out_m = 1.5*eng
            n_rep = max(0, biz['reputation']-3 + passives["rep_boost"])

        factory_capacity = int(sum(50*(e[4]/100) for e in emps)*out_m)
        remaining = factory_capacity
        tot_rev = tot_cost = 0
        for p in prods:
            p_id, name, cat, price, cost, active, rev, target, tier = p[0], p[2], p[3], p[4], p[5], p[6], p[7], p[8], p[9]
            tier_data = QUALITY_TIERS.get(tier, QUALITY_TIERS['Standard'])
            adj_price = int(price * tier_data['price_mult'])
            adj_cost = int(cost * tier_data['cost_mult'] * (1 - passives["cost_reduction"]))
            made = min(target, remaining)
            remaining -= made
            prod_dem = dem * tier_data['demand_elasticity']
            safe_cost = max(1, adj_cost)
            margin_ratio = adj_price / safe_cost
            if margin_ratio > 4: prod_dem *= 0.2
            elif margin_ratio > 2.5: prod_dem *= 0.6
            sold = min(made, int(made * prod_dem))
            rev = sold * adj_price
            tot_rev += rev
            tot_cost += made * (adj_cost * aud)
            c.execute("UPDATE business_products SET lifetime_revenue = lifetime_revenue + ? WHERE id = ?", (rev, p_id))

        overhead = int((10000 + emp_count*500) * aud)
        loan_pay = biz['loan_balance']//biz['installments_left'] if biz['installments_left']>0 else 0
        if loan_pay:
            c.execute("UPDATE businesses SET loan_balance = loan_balance - ?, installments_left = installments_left - 1 WHERE user_id = ?", (loan_pay, uid))
        exec_pay = biz['owner_salary'] * (2 if biz['vp_id'] else 1)
        total_exp = total_payroll + overhead + tot_cost + loan_pay + exec_pay
        net = int(tot_rev - total_exp)
        new_cap = biz['capital'] + net
        c.execute("UPDATE businesses SET capital = ?, reputation = ? WHERE user_id = ?", (new_cap, n_rep, uid))
        if biz['owner_salary'] > 0 and new_cap >= exec_pay:
            c_eco.execute("INSERT INTO wallets (user_id, balance, active_card) VALUES (?, ?, 'silver') ON CONFLICT DO UPDATE SET balance = balance + ?", (uid, biz['owner_salary'], biz['owner_salary']))
            if biz['vp_id']:
                c_eco.execute("INSERT INTO wallets (user_id, balance, active_card) VALUES (?, ?, 'silver') ON CONFLICT DO UPDATE SET balance = balance + ?", (biz['vp_id'], biz['owner_salary'], biz['owner_salary']))
        if biz['is_public']:
            sym = biz['name'][:4].upper()
            stk = c_eco.execute("SELECT price FROM stocks WHERE symbol = ?", (sym,)).fetchone()
            if stk:
                change = 1.05 if net > 0 else 0.95
                new_price = max(10, int(stk[0]*change))
                c_eco.execute("UPDATE stocks SET price = ?, trend = ? WHERE symbol = ?", (new_price, "UP" if net>0 else "DOWN", sym))
        c.execute("UPDATE employees SET morale = MAX(10, morale - 5) WHERE user_id = ?", (uid,))
        report = f"Revenue: A$ {tot_rev:,}\nExpenses: A$ {int(total_exp):,}\nNet: A$ {net:,}"
        return report, net

    def process_events(self, c):
        c.execute("SELECT * FROM market_events WHERE days_remaining > 0")
        for ev in c.fetchall():
            ev_id, text, sector, mod_json, days = ev
            modifiers = json.loads(mod_json)
            c.execute("UPDATE businesses SET demand_boost = demand_boost * ? WHERE sector = ?", (modifiers.get('demand_mult',1.0), sector))
            c.execute("UPDATE market_events SET days_remaining = days_remaining - 1 WHERE id = ?", (ev_id,))
        c.execute("DELETE FROM market_events WHERE days_remaining <= 0")

    def generate_events(self, c):
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
        c.execute("SELECT user_id FROM businesses")
        for (uid,) in c.fetchall():
            if random.random() < 0.25:
                evts = [
                    ("🔥 Your CTO filed a patent! +5 tech points", "UPDATE businesses SET tech_level = tech_level + 5 WHERE user_id = ?"),
                    ("💸 Employee embezzlement! Lost A$ 20k", "UPDATE businesses SET capital = MAX(0, capital - 20000) WHERE user_id = ?"),
                    ("🌟 Positive press! +10 reputation", "UPDATE businesses SET reputation = MIN(100, reputation + 10) WHERE user_id = ?"),
                ]
                msg, sql = random.choice(evts)
                c.execute(sql, (uid,))

    async def publish_newspaper(self):
        channel_id = 1400515374977650799  # set your #wall-street channel
        channel = self.bot.get_channel(channel_id)
        if not channel: return
        conn = get_db_connection(); c = conn.cursor()
        c.execute("SELECT name, capital, reputation FROM businesses ORDER BY capital DESC LIMIT 5")
        top = c.fetchall()
        embed = discord.Embed(title="📰 The Athena Financial Times", color=0xffffff)
        desc = "**Top Companies by Capital:**\n"
        for i,(n,cap,rep) in enumerate(top,1):
            desc += f"{i}. {n} - A$ {cap:,} (Rep: {rep}%)\n"
        embed.description = desc
        c.execute("SELECT event_text FROM market_events WHERE days_remaining > 0 LIMIT 3")
        for (ev,) in c.fetchall():
            embed.add_field(name="Market Event", value=ev, inline=False)
        # Custom banner
        c.execute("SELECT value FROM config WHERE key = 'newspaper_banner'")
        row = c.fetchone()
        banner_url = row[0] if row else DEFAULT_BANNER
        if banner_url:
            embed.set_image(url=banner_url)
        conn.close()
        try: await channel.send(embed=embed)
        except: pass

    @daily_cycle.before_loop
    async def before_cycle(self): await self.bot.wait_until_ready()

    @app_commands.command(name="bizleaderboard", description="Top companies by capital")
    async def leaderboard(self, i: discord.Interaction):
        conn = get_db_connection(); c = conn.cursor()
        c.execute("SELECT name, capital, reputation, sector FROM businesses ORDER BY capital DESC LIMIT 10")
        rows = c.fetchall(); conn.close()
        embed = discord.Embed(title="🏆 Business Moguls", color=0xffffff)
        desc = ""
        for n, cap, rep, sec in rows:
            desc += f"**{n}** ({sec or 'N/A'}) - A$ {cap:,} | {rep}% rep\n"
        embed.description = desc or "No companies yet."
        await i.response.send_message(embed=embed)

    @app_commands.command(name="pay_dividend", description="Pay a dividend to all shareholders")
    async def pay_dividend(self, i: discord.Interaction, amount: int):
        conn = get_db_connection(); c = conn.cursor()
        c.execute("SELECT name, capital, is_public FROM businesses WHERE user_id = ?", (i.user.id,))
        biz = c.fetchone()
        if not biz or not biz[2]: return await i.response.send_message("<a:wt_torono:1480580892706603018> Company not public.", ephemeral=True)
        if biz[1] < amount: return await i.response.send_message("<a:wt_torono:1480580892706603018> Insufficient capital.", ephemeral=True)
        c.execute("UPDATE businesses SET capital = capital - ? WHERE user_id = ?", (amount, i.user.id))
        conn.commit()
        conn_eco = get_eco_connection(); c_eco = conn_eco.cursor()
        c_eco.execute("SELECT user_id, shares FROM portfolio WHERE symbol = ?", (biz[0][:4].upper(),))
        shareholders = c_eco.fetchall()
        total_shares = sum(s[1] for s in shareholders) if shareholders else 0
        if total_shares == 0:
            conn_eco.close(); conn.close()
            return await i.response.send_message("No shareholders to pay.", ephemeral=True)
        for uid, sh in shareholders:
            payout = int(amount * (sh / total_shares))
            c_eco.execute("INSERT INTO wallets (user_id, balance, active_card) VALUES (?, ?, 'silver') ON CONFLICT DO UPDATE SET balance = balance + ?", (uid, payout, payout))
        conn_eco.commit(); conn_eco.close()
        conn.close()
        await i.response.send_message(f"💸 Paid A$ {amount:,} in dividends to {len(shareholders)} shareholders.", ephemeral=False)

async def setup(bot):
    await bot.add_cog(Business(bot))