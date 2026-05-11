import discord
from discord import app_commands
from discord.ext import commands, tasks
import sqlite3
import time
import random
import asyncio

DB_PATH = "business.db"
ECO_DB = "economy.db"

# ==========================================
# 📊 UTILITIES & CONNECTIONS
# ==========================================
def get_db_connection():
    conn = sqlite3.connect(DB_PATH, isolation_level=None)
    conn.execute('PRAGMA temp_store = MEMORY;')
    conn.execute('PRAGMA synchronous = NORMAL;')
    return conn

def get_eco_connection():
    conn = sqlite3.connect(ECO_DB, isolation_level=None)
    conn.execute('PRAGMA temp_store = MEMORY;')
    conn.execute('PRAGMA synchronous = NORMAL;')
    return conn

HQ_LEVELS = {
    0: {"name": "Startup Garage", "max_emp": 5, "cost": 0},
    1: {"name": "Leased Office Space", "max_emp": 50, "cost": 150000},
    2: {"name": "Tech Campus", "max_emp": 500, "cost": 800000},
    3: {"name": "Corporate Skyscraper", "max_emp": 2500, "cost": 3000000}
}

NAMES = ["Liam", "Emma", "Noah", "Olivia", "Oliver", "Ava", "Elijah", "Sophia", "Mateo", "Isabella", "Lucas", "Mia", "Arthur", "Kades", "Phoenix", "Declan", "Ezra", "Aiden", "Sarah", "James"]

def make_progress_bar(current: int, total: int = 100) -> str:
    fill_left = "<:fillleft:1502707988761153567>"
    fill_mid = "<:fillmid:1502707936823087246>"
    fill_right = "<:fillright:1502707911560794192>"
    empty_left = "<:emptyleft:1502707971363311767>"
    empty_mid = "<:emptymid:1502707866744651948>"
    empty_right = "<:emptyright:1502707890664771717>"
    
    segments = 10
    percent = current / total if total > 0 else 0
    visual_current = min(max(int(percent * segments), 0), segments)
    
    bar = ""
    for i in range(segments):
        is_filled = i < visual_current
        if i == 0: bar += fill_left if is_filled else empty_left
        elif i == segments - 1: bar += fill_right if is_filled else empty_right
        else: bar += fill_mid if is_filled else empty_mid
    return f"{bar}  **({current}%)**"

def make_ascii_chart(value, max_value, length=15):
    if max_value <= 0: return "░" * length
    filled = int((value / max_value) * length)
    empty = length - filled
    return "█" * filled + "░" * empty

# ==========================================
# 🏛️ MODALS & DROPDOWNS
# ==========================================
class DescriptionModal(discord.ui.Modal, title='Set Company Bio'):
    desc = discord.ui.TextInput(label='Company Description', style=discord.TextStyle.paragraph, max_length=150, placeholder='A rising corporate empire...')

    async def on_submit(self, interaction: discord.Interaction):
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("UPDATE businesses SET description = ? WHERE user_id = ?", (self.desc.value, interaction.user.id))
        conn.commit(); conn.close()
        await interaction.response.send_message("<a:wt_toroexclaim:1480581004317036624> Company bio updated successfully.", ephemeral=True)

class SetSalaryModal(discord.ui.Modal, title='Executive Payroll'):
    salary = discord.ui.TextInput(label='Daily Personal Salary (A$)', placeholder='e.g., 5000', max_length=7)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            amt = int(self.salary.value)
            if amt < 0: raise ValueError
            conn = get_db_connection(); c = conn.cursor()
            c.execute("UPDATE businesses SET owner_salary = ? WHERE user_id = ?", (amt, interaction.user.id))
            conn.commit(); conn.close()
            await interaction.response.send_message(f"<a:wt_toroexclaim:1480581004317036624> Salary set to **A$ {amt:,}**.", ephemeral=True)
        except ValueError:
            await interaction.response.send_message("<a:wt_torono:1480580892706603018> Invalid amount.", ephemeral=True)

class InvestModal(discord.ui.Modal, title='Inject Personal Capital'):
    amount = discord.ui.TextInput(label='Amount to Invest (A$)', placeholder='e.g., 100000')

    async def on_submit(self, interaction: discord.Interaction):
        try:
            amt = int(self.amount.value)
            if amt <= 0: raise ValueError
            
            conn_eco = get_eco_connection()
            c_eco = conn_eco.cursor()
            c_eco.execute("SELECT balance FROM wallets WHERE user_id = ?", (interaction.user.id,))
            bal = c_eco.fetchone()
            
            if not bal or bal[0] < amt:
                conn_eco.close()
                return await interaction.response.send_message("<a:wt_torono:1480580892706603018> Insufficient personal funds.", ephemeral=True)
            
            c_eco.execute("UPDATE wallets SET balance = balance - ? WHERE user_id = ?", (amt, interaction.user.id))
            conn_eco.commit(); conn_eco.close()

            conn = get_db_connection(); c = conn.cursor()
            c.execute("UPDATE businesses SET capital = capital + ? WHERE user_id = ?", (amt, interaction.user.id))
            conn.commit(); conn.close()

            await interaction.response.send_message(f"<a:wt_toroexclaim:1480581004317036624> Successfully injected **A$ {amt:,}** into your company!", ephemeral=True)
        except ValueError:
            await interaction.response.send_message("<a:wt_torono:1480580892706603018> Invalid amount.", ephemeral=True)

class ProductModal(discord.ui.Modal, title='R&D: Launch Product'):
    p_name = discord.ui.TextInput(label='Product Name', min_length=3, max_length=30)
    p_price = discord.ui.TextInput(label='Unit Price (A$)', min_length=1, max_length=7)
    p_cost = discord.ui.TextInput(label='Cost Per Unit (A$)', min_length=1, max_length=7)
    p_qty = discord.ui.TextInput(label='Daily Target Quantity', placeholder='e.g., 500', min_length=1, max_length=7)
    
    def __init__(self, category: str):
        super().__init__(); self.category = category

    async def on_submit(self, interaction: discord.Interaction):
        try:
            price, cost, qty = int(self.p_price.value), int(self.p_cost.value), int(self.p_qty.value)
            if price <= 0 or cost < 0 or cost >= price or qty <= 0: raise ValueError
            conn = get_db_connection(); c = conn.cursor()
            c.execute("INSERT INTO business_products (user_id, name, category, unit_price, cost_to_make, production_target, active) VALUES (?, ?, ?, ?, ?, ?, 1)", 
                      (interaction.user.id, self.p_name.value, self.category, price, cost, qty))
            conn.commit(); conn.close()
            await interaction.response.send_message(f"<a:wt_toroexclaim:1480581004317036624> **{self.p_name.value}** launched (Target: {qty}/day)!", ephemeral=True)
        except:
            await interaction.response.send_message("<a:wt_torono:1480580892706603018> Invalid pricing data.", ephemeral=True)

class PhilosophyDropdown(discord.ui.Select):
    def __init__(self):
        opts = [
            discord.SelectOption(label="Artisan / Premium", description="High rep, lower output volume.", value="Artisan"),
            discord.SelectOption(label="Mass Market", description="High output, bleeds reputation.", value="Mass Market")
        ]
        super().__init__(placeholder="Select Production Philosophy...", options=opts)

    async def callback(self, i: discord.Interaction):
        conn = get_db_connection(); c = conn.cursor()
        c.execute("UPDATE businesses SET philosophy = ? WHERE user_id = ?", (self.values[0], i.user.id))
        conn.commit(); conn.close()
        await i.response.send_message(f"<a:wt_toroexclaim:1480581004317036624> Strategy set to **{self.values[0]}**.", ephemeral=True)

class HireSpecialistDropdown(discord.ui.Select):
    def __init__(self):
        opts = [
            discord.SelectOption(label="Lead Engineer (A$ 15k)", description="Boosts production output.", value="Engineer"),
            discord.SelectOption(label="Quality Auditor (A$ 15k)", description="Reduces overhead costs.", value="Auditor"),
            discord.SelectOption(label="Sales Shark (A$ 15k)", description="Boosts market demand.", value="Shark")
        ]
        super().__init__(placeholder="Hire Elite Specialist...", options=opts)

    async def callback(self, i: discord.Interaction):
        conn = get_db_connection(); c = conn.cursor()
        c.execute("SELECT capital, hq_level FROM businesses WHERE user_id = ?", (i.user.id,))
        biz = c.fetchone()
        c.execute("SELECT COUNT(id) FROM employees WHERE user_id = ?", (i.user.id,))
        emps = c.fetchone()[0]
        
        if biz[0] < 15000: return await i.response.send_message("<a:wt_torono:1480580892706603018> Insufficient funds.", ephemeral=True)
        if emps >= HQ_LEVELS[biz[1]]["max_emp"]: return await i.response.send_message("<a:wt_torono:1480580892706603018> HQ full.", ephemeral=True)
            
        c.execute("UPDATE businesses SET capital = capital - 15000 WHERE user_id = ?", (i.user.id,))
        c.execute("INSERT INTO employees (user_id, name, salary, morale, specialization) VALUES (?, ?, 4000, 100, ?)", (i.user.id, random.choice(NAMES), self.values[0]))
        conn.commit(); conn.close()
        await i.response.send_message(f"<a:wt_toroexclaim:1480581004317036624> **{self.values[0]}** hired.", ephemeral=True)

class FireEmployeeDropdown(discord.ui.Select):
    def __init__(self, user_id):
        self.user_id = user_id
        conn = get_db_connection(); c = conn.cursor()
        c.execute("SELECT id, name, salary FROM employees WHERE user_id = ?", (user_id,))
        emps = c.fetchall(); conn.close()

        opts = [discord.SelectOption(label=f"Fire {name}", description=f"A$ {salary:,}", value=str(eid)) for eid, name, salary in emps[:25]]
        if not opts: opts.append(discord.SelectOption(label="No employees", value="none"))
        super().__init__(placeholder="Terminate staff...", options=opts)

    async def callback(self, i: discord.Interaction):
        if self.values[0] == "none": return
        conn = get_db_connection(); c = conn.cursor()
        c.execute("DELETE FROM employees WHERE id = ?", (int(self.values[0]),))
        conn.commit(); conn.close()
        await i.response.send_message("<a:wt_toroexclaim:1480581004317036624> Employee fired.", ephemeral=True)

class StartupModal(discord.ui.Modal, title='Incorporate Business'):
    b_name = discord.ui.TextInput(label='Company Name', min_length=3, max_length=30)

    def __init__(self, use_loan: bool):
        super().__init__(); self.use_loan = use_loan

    async def on_submit(self, i: discord.Interaction):
        conn_eco = get_eco_connection(); c_eco = conn_eco.cursor()
        c_eco.execute("SELECT balance FROM wallets WHERE user_id = ?", (i.user.id,))
        bal = c_eco.fetchone()
        
        if not self.use_loan:
            if not bal or bal[0] < 500000:
                conn_eco.close()
                return await i.response.send_message("<a:wt_torono:1480580892706603018> Insufficient funds (A$ 500k req).", ephemeral=True)
            c_eco.execute("UPDATE wallets SET balance = balance - 500000 WHERE user_id = ?", (i.user.id,))
            capital, loan, inst = 500000, 0, 0
        else: capital, loan, inst = 500000, 550000, 10

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

# ==========================================
# 💻 UI VIEWS & SUB-MENUS
# ==========================================
class ProductPerformanceView(discord.ui.View):
    def __init__(self, user_id):
        super().__init__(timeout=180)
        self.user_id = user_id

    @discord.ui.button(label="Refresh Data", style=discord.ButtonStyle.secondary)
    async def refresh_btn(self, i: discord.Interaction, button: discord.ui.Button):
        await i.response.edit_message(embed=self.get_embed(), view=self)

    def get_embed(self):
        conn = get_db_connection(); c = conn.cursor()
        c.execute("SELECT name, unit_price, cost_to_make, lifetime_revenue FROM business_products WHERE user_id = ?", (self.user_id,))
        prods = c.fetchall(); conn.close()

        embed = discord.Embed(title="꒰ა ﹒chérie  ⸝⸝", color=0xffffff)
        if not prods:
            embed.description = "<a:wt_toroconfused:1480580932367945918> 𝑁𝑜 𝑝𝑟𝑜𝑑𝑢𝑐𝑡 𝑙𝑖𝑛𝑒𝑠 𝑎𝑐𝑡𝑖𝑣𝑒."
            return embed

        max_rev = max([p[3] for p in prods]) if prods else 0
        desc = "**<a:wt_torolove:1480580899430203484> R&D Performance Analytics**\n\n"
        
        for name, price, cost, rev in prods:
            margin = price - cost
            chart = make_ascii_chart(rev, max_rev)
            desc += (
                f"**<:s_white2:1382052523166142486> {name}** | Margin: A$ {margin:,}\n"
                f"`{chart}` A$ {rev:,}\n\n"
            )
        embed.description = desc
        return embed

class HRView(discord.ui.View):
    def __init__(self, user_id):
        super().__init__(timeout=180)
        self.add_item(FireEmployeeDropdown(user_id))
        self.add_item(HireSpecialistDropdown())

    @discord.ui.button(label="Hire Staff (A$ 2k)", style=discord.ButtonStyle.secondary, row=2)
    async def hire_btn(self, i: discord.Interaction, button: discord.ui.Button):
        conn = get_db_connection(); c = conn.cursor()
        c.execute("SELECT capital, hq_level FROM businesses WHERE user_id = ?", (i.user.id,))
        biz = c.fetchone()
        c.execute("SELECT COUNT(id) FROM employees WHERE user_id = ?", (i.user.id,))
        emps = c.fetchone()[0]

        if biz[0] < 2000: return await i.response.send_message("<a:wt_torono:1480580892706603018> Not enough capital.", ephemeral=True)
        if emps >= HQ_LEVELS[biz[1]]["max_emp"]: return await i.response.send_message("<a:wt_torono:1480580892706603018> HQ full.", ephemeral=True)
            
        c.execute("UPDATE businesses SET capital = capital - 2000 WHERE user_id = ?", (i.user.id,))
        c.execute("INSERT INTO employees (user_id, name, salary, morale, specialization) VALUES (?, ?, 1500, 80, 'None')", (i.user.id, random.choice(NAMES)))
        conn.commit(); conn.close()
        await i.response.send_message("<a:wt_toroexclaim:1480581004317036624> Staff hired.", ephemeral=True)

    @discord.ui.button(label="Host Event (A$ 5k)", style=discord.ButtonStyle.secondary, row=2)
    async def morale_btn(self, i: discord.Interaction, button: discord.ui.Button):
        conn = get_db_connection(); c = conn.cursor()
        c.execute("SELECT capital FROM businesses WHERE user_id = ?", (i.user.id,))
        cap = c.fetchone()[0]
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

    @discord.ui.button(label="Launch Product", style=discord.ButtonStyle.secondary, row=1)
    async def prod_btn(self, i: discord.Interaction, button: discord.ui.Button):
        opts = [discord.SelectOption(label=c, value=c) for c in ["Tech", "Food", "Luxury", "Retail", "Industrial"]]
        sel = discord.ui.Select(placeholder="Market Sector...", options=opts)
        async def call(it): await it.response.send_modal(ProductModal(sel.values[0]))
        sel.callback = call
        v = discord.ui.View(); v.add_item(sel)
        await i.response.send_message(view=v, ephemeral=True)

    @discord.ui.button(label="Upgrade HQ", style=discord.ButtonStyle.secondary, row=1)
    async def hq_btn(self, i: discord.Interaction, button: discord.ui.Button):
        conn = get_db_connection(); c = conn.cursor()
        c.execute("SELECT capital, hq_level FROM businesses WHERE user_id = ?", (i.user.id,))
        biz = c.fetchone()
        next_lvl = biz[1] + 1
        if next_lvl not in HQ_LEVELS: return await i.response.send_message("<a:wt_torono:1480580892706603018> Max level reached.", ephemeral=True)
        cost = HQ_LEVELS[next_lvl]["cost"]
        if biz[0] < cost: return await i.response.send_message(f"<a:wt_torono:1480580892706603018> Costs A$ {cost:,}.", ephemeral=True)
        c.execute("UPDATE businesses SET capital = capital - ?, hq_level = ? WHERE user_id = ?", (cost, next_lvl, i.user.id))
        conn.commit(); conn.close()
        await i.response.send_message(f"<a:wt_toroexclaim:1480581004317036624> HQ Upgraded!", ephemeral=True)

    @discord.ui.button(label="Set Company Bio", style=discord.ButtonStyle.secondary, row=1)
    async def bio_btn(self, i: discord.Interaction, button: discord.ui.Button):
        await i.response.send_modal(DescriptionModal())

    @discord.ui.button(label="Set Exec Salary", style=discord.ButtonStyle.secondary, row=2)
    async def sal_btn(self, i: discord.Interaction, button: discord.ui.Button):
        await i.response.send_modal(SetSalaryModal())

    @discord.ui.button(label="Inject Capital", style=discord.ButtonStyle.secondary, row=2)
    async def inject_btn(self, i: discord.Interaction, button: discord.ui.Button):
        await i.response.send_modal(InvestModal())

class SettlementView(discord.ui.View):
    def __init__(self, user_id):
        super().__init__(timeout=60)
        self.user_id = user_id

    @discord.ui.button(label="Pay One-Time Settlement (A$ 100k)", style=discord.ButtonStyle.danger)
    async def pay_btn(self, i: discord.Interaction, button: discord.ui.Button):
        conn = get_db_connection(); c = conn.cursor()
        c.execute("SELECT capital FROM businesses WHERE user_id = ?", (self.user_id,))
        if c.fetchone()[0] < 100000: return await i.response.send_message("<a:wt_torono:1480580892706603018> Insufficient funds.", ephemeral=True)
        c.execute("UPDATE businesses SET capital = capital - 100000 WHERE user_id = ?", (self.user_id,))
        c.execute("UPDATE employees SET morale = 50 WHERE user_id = ?", (self.user_id,))
        conn.commit(); conn.close()
        await i.response.send_message("<a:wt_toroexclaim:1480581004317036624> Strike settled.", ephemeral=False)

    @discord.ui.button(label="Grant 15% Permanent Raise", style=discord.ButtonStyle.danger)
    async def raise_btn(self, i: discord.Interaction, button: discord.ui.Button):
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
        row = c.fetchone()
        avg_morale = row[0] if row[0] is not None else 100
        conn.close()

        if avg_morale < 20:
            self.add_item(discord.ui.Button(label="RESOLVE STRIKE", style=discord.ButtonStyle.danger, custom_id="strike_btn", row=2))

    @discord.ui.button(label="Balance Sheet", style=discord.ButtonStyle.secondary, row=0)
    async def balance_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        conn = get_db_connection(); c = conn.cursor()
        c.execute("SELECT capital, loan_balance, owner_salary, last_report, vp_title FROM businesses WHERE user_id = ?", (interaction.user.id,))
        biz = c.fetchone()
        c.execute("SELECT SUM(salary), COUNT(id) FROM employees WHERE user_id = ?", (interaction.user.id,))
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
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="HQ Operations", style=discord.ButtonStyle.secondary, row=0)
    async def ops_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(title="꒰ა ﹒chérie  ⸝⸝", color=0xffffff, description="<a:wt_torolove:1480580899430203484> **Operational Control**")
        await interaction.response.send_message(embed=embed, view=OpsView(interaction.user.id), ephemeral=True)

    @discord.ui.button(label="HR Department", style=discord.ButtonStyle.secondary, row=0)
    async def hr_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        conn = get_db_connection(); c = conn.cursor()
        c.execute("SELECT name, salary, morale, specialization FROM employees WHERE user_id = ?", (interaction.user.id,))
        emps = c.fetchall(); conn.close()

        embed = discord.Embed(title="꒰ა ﹒chérie  ⸝⸝", color=0xffffff)
        if not emps: embed.description = "No employees."
        else:
            desc = "<a:wt_torolove:1480580899430203484> **Human Resources**\n"
            for name, salary, morale, spec in emps[:15]: 
                st = f" ({spec})" if spec != 'None' else ""
                desc += f"<:s_white2:1382052523166142486> **{name}{st}** | A$ {salary:,} | Morale: {morale}%\n\n"
            if len(emps) > 15: desc += f"*...and {len(emps)-15} more.*\n"
            embed.description = desc
            
        await interaction.response.send_message(embed=embed, view=HRView(interaction.user.id), ephemeral=True)

    @discord.ui.button(label="R&D Hub", style=discord.ButtonStyle.secondary, row=1)
    async def rnd_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = ProductPerformanceView(interaction.user.id)
        await interaction.response.send_message(embed=view.get_embed(), view=view, ephemeral=True)

    @discord.ui.button(label="Take Public (IPO)", style=discord.ButtonStyle.success, row=1)
    async def ipo_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        conn = get_db_connection(); c = conn.cursor()
        c.execute("SELECT name, capital, is_public FROM businesses WHERE user_id = ?", (interaction.user.id,))
        biz = c.fetchone()
        
        if biz[2] == 1: return await interaction.response.send_message("<a:wt_torono:1480580892706603018> Already public.", ephemeral=True)
        if biz[1] < 2000000: return await interaction.response.send_message("<a:wt_torono:1480580892706603018> A$ 2M required.", ephemeral=True)

        c.execute("SELECT COUNT(id) FROM employees WHERE user_id = ?", (interaction.user.id,))
        emp_count = c.fetchone()[0]
        
        start_price = max(500, int((biz[1] * 0.001) + (emp_count * 10)))
        sym = biz[0][:4].upper()
        
        c.execute("UPDATE businesses SET is_public = 1 WHERE user_id = ?", (interaction.user.id,))
        conn.commit(); conn.close()
        
        conn_eco = get_eco_connection(); c_eco = conn_eco.cursor()
        c_eco.execute("INSERT OR IGNORE INTO stocks (symbol, name, price, volatility, trend) VALUES (?, ?, ?, 15, 'FLAT')", (sym, biz[0], start_price))
        conn_eco.commit(); conn_eco.close()
        await interaction.response.send_message(f"<a:wt_toroexclaim:1480581004317036624> **IPO SUCCESSFUL!** Trading as **{sym}** at A$ {start_price:,}.", ephemeral=False)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.data.get('custom_id') == "strike_btn":
            embed = discord.Embed(title="꒰ა ﹒chérie  ⸝⸝", color=0xffffff, description="**UNION DEMANDS:** Resolve the strike below.")
            await interaction.response.send_message(embed=embed, view=SettlementView(interaction.user.id), ephemeral=True)
            return False
        return True

# ==========================================
# 🏙️ THE BUSINESS COG
# ==========================================
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
            philosophy TEXT DEFAULT 'Mass Market', reputation INTEGER DEFAULT 100, is_public INTEGER DEFAULT 0,
            description TEXT DEFAULT '*A rising corporate empire.*'
        )''')
        c.execute('''CREATE TABLE IF NOT EXISTS employees (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, name TEXT, 
            salary INTEGER, morale INTEGER, specialization TEXT DEFAULT 'None'
        )''')
        c.execute('''CREATE TABLE IF NOT EXISTS business_products (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, name TEXT, 
            category TEXT, unit_price INTEGER, cost_to_make INTEGER, active INTEGER DEFAULT 1,
            lifetime_revenue INTEGER DEFAULT 0, production_target INTEGER DEFAULT 100
        )''')

        new_cols = [
            ("businesses", "vp_id", "INTEGER"), ("businesses", "vp_title", "TEXT"), ("businesses", "demand_boost", "REAL DEFAULT 1.0"),
            ("businesses", "hq_level", "INTEGER DEFAULT 0"), ("businesses", "philosophy", "TEXT DEFAULT 'Mass Market'"), 
            ("businesses", "reputation", "INTEGER DEFAULT 100"), ("businesses", "is_public", "INTEGER DEFAULT 0"), 
            ("businesses", "description", "TEXT DEFAULT '*A rising corporate empire.*'"),
            ("employees", "specialization", "TEXT DEFAULT 'None'"), ("business_products", "lifetime_revenue", "INTEGER DEFAULT 0"),
            ("business_products", "production_target", "INTEGER DEFAULT 100")
        ]
        
        for table, col, dtype in new_cols:
            try: c.execute(f"ALTER TABLE {table} ADD COLUMN {col} {dtype}")
            except sqlite3.OperationalError: pass
                
        conn.commit(); conn.close()

    @app_commands.command(name="appoint_vp", description="CEO: Appoint a VP")
    async def appoint_vp(self, i: discord.Interaction, user: discord.Member):
        if user.bot or user.id == i.user.id: return await i.response.send_message("<a:wt_torono:1480580892706603018> Invalid user.", ephemeral=True)
        conn = get_db_connection(); c = conn.cursor()
        biz = c.execute("SELECT name FROM businesses WHERE user_id = ?", (i.user.id,)).fetchone(); conn.close()
        if not biz: return await i.response.send_message("<a:wt_torono:1480580892706603018> No business found.", ephemeral=True)
        
        v = discord.ui.View(); v.add_item(VPTitleDropdown(user))
        await i.response.send_message(f"<a:wt_torospin:1480580977867624540> Select title for {user.name}:", view=v, ephemeral=True)

    @app_commands.command(name="business", description="Access CEO Terminal")
    async def business_hub(self, i: discord.Interaction):
        conn = get_db_connection(); c = conn.cursor()
        c.execute("SELECT name, capital, reputation, description, hq_level FROM businesses WHERE user_id = ?", (i.user.id,))
        biz = c.fetchone()
        
        if not biz:
            conn.close(); v = discord.ui.View()
            v.add_item(discord.ui.Button(label="Fund Outright (500k)", style=discord.ButtonStyle.secondary, custom_id="f_out"))
            v.add_item(discord.ui.Button(label="Secure Loan", style=discord.ButtonStyle.secondary, custom_id="f_loan"))
            async def call(ix: discord.Interaction): await ix.response.send_modal(StartupModal(use_loan=(ix.data['custom_id'] == "f_loan")))
            for child in v.children: child.callback = call
            return await i.response.send_message(embed=discord.Embed(title="꒰ა ﹒chérie  ⸝⸝", color=0xffffff, description="Incorporate for A$ 500k."), view=v, ephemeral=True)

        c.execute("SELECT COUNT(id), AVG(morale) FROM employees WHERE user_id = ?", (i.user.id,))
        emps = c.fetchone(); conn.close()
        
        await i.response.send_message("<a:wt_torospin:1480580977867624540> *𝐴𝑐𝑐𝑒𝑠𝑠𝑖𝑛𝑔 𝐶𝐸𝑂 𝑇𝑒𝑟𝑚𝑖𝑛𝑎𝑙...*", ephemeral=True)
        await asyncio.sleep(1.5)

        embed = discord.Embed(title=f"꒰ა ﹒{biz[0]}  ⸝⸝", color=0xffffff)
        embed.description = (
            f"*{biz[3]}*\n\n"
            f"<:s_white2:1382052523166142486> **Capital:** A$ {biz[1]:,}\n"
            f"<:s_white2:1382052523166142486> **Reputation:** {biz[2]}%\n"
            f"<:s_white2:1382052523166142486> **HQ:** {HQ_LEVELS[biz[4]]['name']}\n"
            f"<:s_white2:1382052523166142486> **Employees:** {emps[0] or 0}\n\n"
            f"**<a:wt_torolove:1480580899430203484> Company Morale**\n"
            f"{make_progress_bar(int(emps[1]) if emps[1] else 100)}\n"
        )
        embed.set_image(url="https://cdn.discordapp.com/attachments/1441473281420169367/1501576429761200290/0ac4c99804a08a107d2cf6f09d79655f.jpg?ex=6a008806&is=69ff3686&hm=4205b070b2abc9c883782db32c3e709027a4b6381ba1c83da86b0ad8c9834784")
        await i.edit_original_response(content=None, embed=embed, view=TerminalView(self.bot, i.user.id))

    @tasks.loop(hours=24)
    async def daily_cycle(self):
        conn = get_db_connection(); c = conn.cursor()
        conn_eco = get_eco_connection(); c_eco = conn_eco.cursor()

        c.execute("SELECT user_id, capital, owner_salary, loan_balance, installments_left, vp_id, philosophy, reputation, demand_boost, is_public, name FROM businesses")
        businesses = c.fetchall()
        
        # Volatility: Roll a Global Market State
        global_market = random.choice([0.8, 1.0, 1.2, 1.5]) 

        for uid, cap, owner_sal, loan, inst, vp_id, phil, rep, d_boost, pub, b_name in businesses:
            c.execute("SELECT salary, morale, specialization FROM employees WHERE user_id = ?", (uid,))
            emps = c.fetchall()
            c.execute("SELECT id, name, unit_price, cost_to_make, production_target FROM business_products WHERE user_id = ? AND active = 1", (uid,))
            prods = c.fetchall()
            
            if not prods or not emps:
                c.execute("UPDATE businesses SET last_report = 'No products or employees active.' WHERE user_id = ?", (uid,))
                continue
                
            emp_count, total_payroll = len(emps), sum([e[0] for e in emps])
            avg_morale = sum([e[1] for e in emps]) / emp_count if emp_count > 0 else 100
            
            if avg_morale < 20:
                c.execute("UPDATE businesses SET last_report = 'CRITICAL: STRIKE ACTIVE! Production Halted.' WHERE user_id = ?", (uid,))
                continue

            eng = 1.0 + (0.10 * sum(1 for e in emps if e[2] == 'Engineer'))
            aud = 1.0 - min(0.30, (0.05 * sum(1 for e in emps if e[2] == 'Auditor')))
            shark = 1.0 + (0.15 * sum(1 for e in emps if e[2] == 'Shark'))

            rep_mod = rep / 100.0
            if phil == "Artisan":
                dem = random.uniform(0.9, 1.2) * rep_mod * d_boost * shark * global_market
                out_m = 0.5 * eng
                n_rep = min(100, rep + 2)
            else:
                dem = random.uniform(1.0, 1.5) * rep_mod * d_boost * shark * global_market
                out_m = 1.5 * eng
                n_rep = max(0, rep - 3)

            tot_rev, tot_cost = 0, 0
            
            # Factory total daily capacity based on employees
            factory_capacity = int(sum([50 * (e[1]/100) for e in emps]) * out_m)
            remaining_capacity = factory_capacity
            overpriced_flag = False

            for p_id, p_name, price, cost, target_qty in prods:
                made = min(target_qty, remaining_capacity)
                remaining_capacity -= made
                
                # Pricing check mechanic: Huge markup severely damages demand
                prod_dem = dem
                safe_cost = max(1, cost)
                margin_ratio = price / safe_cost
                
                if margin_ratio > 4.0:
                    prod_dem *= 0.2
                    overpriced_flag = True
                elif margin_ratio > 2.5:
                    prod_dem *= 0.6
                
                sold = int(made * prod_dem)
                if sold > made: sold = made
                
                rev = sold * price
                tot_rev += rev
                tot_cost += made * (cost * aud)
                c.execute("UPDATE business_products SET lifetime_revenue = lifetime_revenue + ? WHERE id = ?", (rev, p_id))

            over = int((10000 + (emp_count * 500)) * aud)
            inst_pay = loan // inst if inst > 0 else 0
            if inst > 0: c.execute("UPDATE businesses SET loan_balance = loan_balance - ?, installments_left = installments_left - 1 WHERE user_id = ?", (inst_pay, uid))
            
            t_exec = owner_sal * 2 if vp_id else owner_sal
            t_exp = total_payroll + over + tot_cost + inst_pay + t_exec
            net = int(tot_rev - t_exp)
            
            n_cap = cap + net
            c.execute("UPDATE businesses SET capital = ?, reputation = ?, demand_boost = 1.0 WHERE user_id = ?", (n_cap, n_rep, uid))
            
            if owner_sal > 0 and n_cap >= t_exec:
                c_eco.execute("INSERT INTO wallets (user_id, balance, active_card) VALUES (?, ?, 'silver') ON CONFLICT DO UPDATE SET balance = balance + ?", (uid, owner_sal, owner_sal))
                if vp_id: c_eco.execute("INSERT INTO wallets (user_id, balance, active_card) VALUES (?, ?, 'silver') ON CONFLICT DO UPDATE SET balance = balance + ?", (vp_id, owner_sal, owner_sal))
                
            if pub:
                sym = b_name[:4].upper()
                stk = c_eco.execute("SELECT price FROM stocks WHERE symbol = ?", (sym,)).fetchone()
                if stk:
                    adj = 1.05 if net > 0 else 0.95
                    n_prc = max(10, int(stk[0] * adj))
                    c_eco.execute("UPDATE stocks SET price = ?, trend = ? WHERE symbol = ?", (n_prc, "UP" if n_prc > stk[0] else "DOWN", sym))
                
            report_extra = "\nMarket reaction poor due to severe overpricing!" if overpriced_flag else ""
            rpt = f"Market Multiplier: {global_market}x\nRevenue: A$ {tot_rev:,}\nExpenses: A$ {int(t_exp):,}\nNet: A$ {net:,}{report_extra}"
            c.execute("UPDATE businesses SET last_report = ? WHERE user_id = ?", (rpt, uid))
            c.execute("UPDATE employees SET morale = MAX(10, morale - 5) WHERE user_id = ?", (uid,))

        conn.commit(); conn.close()
        conn_eco.commit(); conn_eco.close()

    @daily_cycle.before_loop
    async def before_cycle(self): await self.bot.wait_until_ready()

async def setup(bot): await bot.add_cog(Business(bot))