# cogs/business_part1.py (Save this as business.py, Part 2 will complete it)
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
# 📊 UTILITIES & CONSTANTS
# ==========================================
HQ_LEVELS = {
    0: {"name": "The Startup Garage", "max_emp": 5, "cost": 0},
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
    percent = current / total
    visual_current = min(max(int(percent * segments), 0), segments)
    
    bar = ""
    for i in range(segments):
        is_filled = i < visual_current
        if i == 0: bar += fill_left if is_filled else empty_left
        elif i == segments - 1: bar += fill_right if is_filled else empty_right
        else: bar += fill_mid if is_filled else empty_mid
    return f"{bar}  **({current}%)**"

# ==========================================
# 🏛️ DROPDOWNS & MODALS
# ==========================================
class VPTitleDropdown(discord.ui.Select):
    def __init__(self, vp_user: discord.Member):
        self.vp_user = vp_user
        options = [
            discord.SelectOption(label="Chief Operating Officer (COO)", value="COO"),
            discord.SelectOption(label="Chief Financial Officer (CFO)", value="CFO"),
            discord.SelectOption(label="Chief Marketing Officer (CMO)", value="CMO"),
            discord.SelectOption(label="Vice President (VP)", value="VP")
        ]
        super().__init__(placeholder="Select executive title...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("UPDATE businesses SET vp_id = ?, vp_title = ? WHERE user_id = ?", (self.vp_user.id, self.values[0], interaction.user.id))
        conn.commit()
        conn.close()
        await interaction.response.send_message(f"<a:wt_toroexclaim:1480581004317036624> **{self.vp_user.name}** is now the **{self.values[0]}**.", ephemeral=False)

class ProductModal(discord.ui.Modal, title='R&D: Launch New Product'):
    p_name = discord.ui.TextInput(label='Product Name', min_length=3, max_length=30)
    p_price = discord.ui.TextInput(label='Unit Price (A$)', min_length=1, max_length=7)
    p_cost = discord.ui.TextInput(label='Production Cost Per Unit (A$)', min_length=1, max_length=7)
    
    def __init__(self, category: str):
        super().__init__()
        self.category = category

    async def on_submit(self, interaction: discord.Interaction):
        try:
            price = int(self.p_price.value)
            cost = int(self.p_cost.value)
            if price <= 0 or cost < 0 or cost >= price: raise ValueError
            
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            c.execute("INSERT INTO business_products (user_id, name, category, unit_price, cost_to_make, active) VALUES (?, ?, ?, ?, ?, 1)", 
                      (interaction.user.id, self.p_name.value, self.category, price, cost))
            conn.commit()
            conn.close()
            await interaction.response.send_message(f"<a:wt_toroexclaim:1480581004317036624> Launched **{self.p_name.value}** (Margin: A$ {price - cost:,}/unit).", ephemeral=True)
        except ValueError:
            await interaction.response.send_message("<a:wt_torono:1480580892706603018> Invalid pricing. Cost must be less than Unit Price.", ephemeral=True)

class PhilosophyDropdown(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="Artisan / Premium", description="High rep, lower output volume.", value="Artisan"),
            discord.SelectOption(label="Mass Market", description="High output, bleeds brand reputation.", value="Mass Market")
        ]
        super().__init__(placeholder="Select Production Philosophy...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("UPDATE businesses SET philosophy = ? WHERE user_id = ?", (self.values[0], interaction.user.id))
        conn.commit()
        conn.close()
        await interaction.response.send_message(f"<a:wt_toroexclaim:1480581004317036624> Philosophy shifted to **{self.values[0]}**.", ephemeral=True)

class HireSpecialistDropdown(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="Lead Engineer", description="Boosts base production output. (A$ 15k)", value="Engineer"),
            discord.SelectOption(label="Quality Auditor", description="Reduces overhead & defect costs. (A$ 15k)", value="Auditor"),
            discord.SelectOption(label="Sales Shark", description="Permanently boosts market demand. (A$ 15k)", value="Shark")
        ]
        super().__init__(placeholder="Hire Specialized Staff...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        spec = self.values[0]
        cost = 15000
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT capital, hq_level FROM businesses WHERE user_id = ?", (interaction.user.id,))
        biz = c.fetchone()
        
        c.execute("SELECT COUNT(id) FROM employees WHERE user_id = ?", (interaction.user.id,))
        emp_count = c.fetchone()[0]

        if biz[0] < cost:
            conn.close()
            return await interaction.response.send_message("<a:wt_torono:1480580892706603018> Insufficient capital.", ephemeral=True)
        if emp_count >= HQ_LEVELS[biz[1]]["max_emp"]:
            conn.close()
            return await interaction.response.send_message("<a:wt_torono:1480580892706603018> HQ at maximum capacity. Upgrade required.", ephemeral=True)
            
        c.execute("UPDATE businesses SET capital = capital - ? WHERE user_id = ?", (cost, interaction.user.id))
        c.execute("INSERT INTO employees (user_id, name, salary, morale, specialization) VALUES (?, ?, 4000, 100, ?)", (interaction.user.id, random.choice(NAMES), spec))
        conn.commit()
        conn.close()
        await interaction.response.send_message(f"<a:wt_toroexclaim:1480581004317036624> Hired a new **{spec}**.", ephemeral=True)

class StartupModal(discord.ui.Modal, title='Incorporate Business'):
    b_name = discord.ui.TextInput(label='Company Name', min_length=3, max_length=30)

    def __init__(self, use_loan: bool):
        super().__init__()
        self.use_loan = use_loan

    async def on_submit(self, interaction: discord.Interaction):
        conn_eco = sqlite3.connect(ECO_DB)
        c_eco = conn_eco.cursor()
        c_eco.execute("SELECT balance FROM wallets WHERE user_id = ?", (interaction.user.id,))
        bal = c_eco.fetchone()
        
        if not self.use_loan:
            if not bal or bal[0] < 500000:
                conn_eco.close()
                return await interaction.response.send_message("<a:wt_torono:1480580892706603018> Insufficient personal funds (A$ 500k required).", ephemeral=True)
            c_eco.execute("UPDATE wallets SET balance = balance - 500000 WHERE user_id = ?", (interaction.user.id,))
            capital, loan, installments = 500000, 0, 0
        else:
            capital, loan, installments = 500000, 550000, 10

        conn_eco.commit()
        conn_eco.close()

        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("INSERT INTO businesses (user_id, name, capital, loan_balance, installments_left, reputation) VALUES (?, ?, ?, ?, ?, 100)", 
                  (interaction.user.id, self.b_name.value, capital, loan, installments))
        conn.commit()
        conn.close()
        await interaction.response.send_message(f"<a:wt_toroexclaim:1480581004317036624> **{self.b_name.value}** incorporated! Run `/business`.", ephemeral=False)

# cogs/business_part2.py (Append this to the bottom of your business.py file)

class ProductCategoryDropdown(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="Technology & Electronics", value="Tech"),
            discord.SelectOption(label="Food & Beverage", value="Food"),
            discord.SelectOption(label="Retail & Clothing", value="Retail"),
            discord.SelectOption(label="Luxury Goods", value="Luxury"),
            discord.SelectOption(label="Industrial Services", value="Industrial")
        ]
        super().__init__(placeholder="Select a market sector...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(ProductModal(self.values[0]))

class ProductView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=60)
        self.add_item(ProductCategoryDropdown())

class HRView(discord.ui.View):
    def __init__(self, user_id):
        super().__init__(timeout=60)
        self.add_item(FireEmployeeDropdown(user_id))
        self.add_item(HireSpecialistDropdown())

    @discord.ui.button(label="Hire Standard Staff (A$ 2k)", style=discord.ButtonStyle.success, row=2)
    async def hire_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT capital, hq_level FROM businesses WHERE user_id = ?", (interaction.user.id,))
        biz = c.fetchone()
        
        c.execute("SELECT COUNT(id) FROM employees WHERE user_id = ?", (interaction.user.id,))
        emp_count = c.fetchone()[0]

        if biz[0] < 2000:
            conn.close()
            return await interaction.response.send_message("<a:wt_torono:1480580892706603018> Insufficient capital.", ephemeral=True)
            
        if emp_count >= HQ_LEVELS[biz[1]]["max_emp"]:
            conn.close()
            return await interaction.response.send_message("<a:wt_torono:1480580892706603018> HQ at maximum capacity. Upgrade required.", ephemeral=True)
            
        c.execute("UPDATE businesses SET capital = capital - 2000 WHERE user_id = ?", (interaction.user.id,))
        c.execute("INSERT INTO employees (user_id, name, salary, morale, specialization) VALUES (?, ?, 1500, 80, 'None')", (interaction.user.id, random.choice(NAMES)))
        conn.commit()
        conn.close()
        await interaction.response.send_message("<a:wt_toroexclaim:1480581004317036624> Standard employee hired.", ephemeral=True)

class TerminalView(discord.ui.View):
    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot

    @discord.ui.button(label="Balance Sheet", style=discord.ButtonStyle.secondary)
    async def balance_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT capital, loan_balance, installments_left, owner_salary, last_report, vp_id, vp_title, hq_level, reputation, philosophy FROM businesses WHERE user_id = ?", (interaction.user.id,))
        biz = c.fetchone()
        
        c.execute("SELECT SUM(salary), COUNT(id) FROM employees WHERE user_id = ?", (interaction.user.id,))
        emps = c.fetchone()
        conn.close()

        emp_count, total_payroll = emps[1] or 0, emps[0] or 0
        overhead = 10000 + (emp_count * 500)
        
        embed = discord.Embed(title="꒰ა ﹒chérie  ⸝⸝", color=0xffffff)
        
        desc = (
            f"**<a:wt_torolove:1480580899430203484> Financial Balance Sheet**\n"
            f"<:s_white2:1382052523166142486> **Liquid Capital:** A$ {biz[0]:,}\n"
            f"<:s_white2:1382052523166142486> **CEO Salary:** A$ {biz[3]:,}\n"
            f"<:s_white2:1382052523166142486> **Employee Payroll:** A$ {total_payroll:,} / day\n"
            f"<:s_white2:1382052523166142486> **Fixed Overhead:** A$ {overhead:,} / day\n"
            f"<:s_white2:1382052523166142486> **HQ Level:** {HQ_LEVELS[biz[7]]['name']}\n"
            f"<:s_white2:1382052523166142486> **Brand Rep:** {biz[8]}% | **Strategy:** {biz[9]}\n"
        )
        if biz[5]: desc += f"<:s_white2:1382052523166142486> **Executive VP:** <@{biz[5]}> ({biz[6]})\n"
        if biz[1] > 0: desc += f"<:s_white2:1382052523166142486> **Loan Balance:** A$ {biz[1]:,} ({biz[2]} left)\n"
            
        desc += f"\n**<a:wt_torolove:1480580899430203484> Latest Daily Report:**\n*{biz[4]}*"
        embed.description = desc
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="R&D / HQ Operations", style=discord.ButtonStyle.secondary)
    async def ops_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(title="꒰ა ﹒chérie  ⸝⸝", color=0xffffff, description="<a:wt_torolove:1480580899430203484> **Operational Control**\nSelect an action to adjust company structure or product line.")
        view = discord.ui.View()
        view.add_item(discord.ui.Button(label="Launch New Product", style=discord.ButtonStyle.primary, custom_id="prod_btn"))
        view.add_item(discord.ui.Button(label="Upgrade HQ Capacity", style=discord.ButtonStyle.success, custom_id="hq_btn"))
        view.add_item(PhilosophyDropdown())
        
        async def inner_callback(i: discord.Interaction):
            if i.data['custom_id'] == "prod_btn":
                await i.response.send_message(view=ProductView(), ephemeral=True)
            elif i.data['custom_id'] == "hq_btn":
                conn = sqlite3.connect(DB_PATH); c = conn.cursor()
                c.execute("SELECT capital, hq_level FROM businesses WHERE user_id = ?", (i.user.id,))
                biz = c.fetchone()
                
                next_level = biz[1] + 1
                if next_level not in HQ_LEVELS:
                    conn.close()
                    return await i.response.send_message("<a:wt_torono:1480580892706603018> Your HQ is already at maximum level.", ephemeral=True)
                    
                cost = HQ_LEVELS[next_level]["cost"]
                if biz[0] < cost:
                    conn.close()
                    return await i.response.send_message(f"<a:wt_torono:1480580892706603018> Upgrade costs A$ {cost:,}. You have A$ {biz[0]:,}.", ephemeral=True)
                    
                c.execute("UPDATE businesses SET capital = capital - ?, hq_level = ? WHERE user_id = ?", (cost, next_level, i.user.id))
                conn.commit(); conn.close()
                await i.response.send_message(f"<a:wt_toroexclaim:1480581004317036624> HQ Upgraded to **{HQ_LEVELS[next_level]['name']}**!", ephemeral=True)

        for child in view.children: 
            if isinstance(child, discord.ui.Button): child.callback = inner_callback
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @discord.ui.button(label="HR Department", style=discord.ButtonStyle.secondary)
    async def hr_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT name, salary, morale, specialization FROM employees WHERE user_id = ?", (interaction.user.id,))
        emps = c.fetchall()
        conn.close()

        embed = discord.Embed(title="꒰ა ﹒chérie  ⸝⸝", color=0xffffff)
        if not emps:
            embed.description = "You currently have no employees. Click below to hire someone."
        else:
            desc = "<a:wt_torolove:1480580899430203484> **Human Resources**\n"
            for name, salary, morale, spec in emps[:15]: 
                spec_text = f" ({spec})" if spec != 'None' else ""
                desc += f"<:s_white2:1382052523166142486> **{name}{spec_text}** | A$ {salary:,} | Morale: {morale}%\n"
            if len(emps) > 15: desc += f"*...and {len(emps)-15} more.*\n"
            embed.description = desc
            
        await interaction.response.send_message(embed=embed, view=HRView(interaction.user.id), ephemeral=True)

    @discord.ui.button(label="Take Public (IPO)", style=discord.ButtonStyle.success)
    async def ipo_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT name, capital, is_public FROM businesses WHERE user_id = ?", (interaction.user.id,))
        biz = c.fetchone()
        
        if biz[2] == 1:
            conn.close()
            return await interaction.response.send_message("<a:wt_torono:1480580892706603018> Your company is already publicly traded.", ephemeral=True)
            
        if biz[1] < 2000000:
            conn.close()
            return await interaction.response.send_message("<a:wt_torono:1480580892706603018> IPO requires A$ 2,000,000 in Liquid Capital.", ephemeral=True)

        # Automatic Stock Pricing Formula
        c.execute("SELECT COUNT(id) FROM employees WHERE user_id = ?", (interaction.user.id,))
        emp_count = c.fetchone()[0]
        
        # Base price calculated by Capital + Employee strength, kept affordable for server members
        starting_price = max(500, int((biz[1] * 0.001) + (emp_count * 10)))
        stock_symbol = biz[0][:4].upper()
        
        c.execute("UPDATE businesses SET is_public = 1 WHERE user_id = ?", (interaction.user.id,))
        conn.commit(); conn.close()
        
        # Inject into economy.db stocks table
        conn_eco = sqlite3.connect(ECO_DB)
        c_eco = conn_eco.cursor()
        c_eco.execute("INSERT OR IGNORE INTO stocks (symbol, name, price, volatility, trend) VALUES (?, ?, ?, 15, '➖ FLAT')", (stock_symbol, biz[0], starting_price))
        conn_eco.commit(); conn_eco.close()

        await interaction.response.send_message(f"<a:wt_toroexclaim:1480581004317036624> **IPO SUCCESSFUL!**\n**{biz[0]}** is now trading on the Athena Exchange under the symbol **{stock_symbol}** at **A$ {starting_price:,}** per share.", ephemeral=False)

# ==========================================
# 🏙️ THE BUSINESS COG
# ==========================================
class Business(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.setup_db()
        self.daily_cycle.start()

    def setup_db(self):
        conn = sqlite3.connect(DB_PATH); cursor = conn.cursor()
        cursor.execute('''CREATE TABLE IF NOT EXISTS businesses (
            user_id INTEGER PRIMARY KEY, name TEXT, capital INTEGER DEFAULT 0, 
            owner_salary INTEGER DEFAULT 0, loan_balance INTEGER DEFAULT 0, 
            installments_left INTEGER DEFAULT 0, days_open INTEGER DEFAULT 0, 
            last_report TEXT DEFAULT 'No reports.', vp_id INTEGER, vp_title TEXT, 
            demand_boost REAL DEFAULT 1.0, hq_level INTEGER DEFAULT 0, 
            philosophy TEXT DEFAULT 'Mass Market', reputation INTEGER DEFAULT 100, is_public INTEGER DEFAULT 0
        )''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS employees (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, name TEXT, 
            salary INTEGER, morale INTEGER, specialization TEXT DEFAULT 'None'
        )''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS business_products (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, name TEXT, 
            category TEXT, unit_price INTEGER, cost_to_make INTEGER, active INTEGER DEFAULT 1
        )''')
        conn.commit(); conn.close()

    @app_commands.command(name="appoint_vp", description="CEO: Appoint a Vice President for your company")
    async def appoint_vp(self, interaction: discord.Interaction, user: discord.Member):
        if user.bot or user.id == interaction.user.id:
            return await interaction.response.send_message("<a:wt_torono:1480580892706603018> Invalid user.", ephemeral=True)
            
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT name FROM businesses WHERE user_id = ?", (interaction.user.id,))
        biz = c.fetchone()
        conn.close()
        
        if not biz:
            return await interaction.response.send_message("<a:wt_torono:1480580892706603018> You do not own a business.", ephemeral=True)
            
        view = discord.ui.View()
        view.add_item(VPTitleDropdown(user))
        await interaction.response.send_message(f"<a:wt_torospin:1480580977867624540> Select an executive title for **{user.name}**:", view=view, ephemeral=True)

    @app_commands.command(name="business", description="Access the CEO Terminal")
    async def business_hub(self, interaction: discord.Interaction):
        conn = sqlite3.connect(DB_PATH); cursor = conn.cursor()
        cursor.execute("SELECT name, capital, reputation FROM businesses WHERE user_id = ?", (interaction.user.id,))
        biz = cursor.fetchone()
        
        if not biz:
            conn.close()
            view = discord.ui.View()
            view.add_item(discord.ui.Button(label="Fund Outright (A$ 500k)", style=discord.ButtonStyle.success, custom_id="f_out"))
            view.add_item(discord.ui.Button(label="Secure Reserve Loan", style=discord.ButtonStyle.primary, custom_id="f_loan"))
            
            async def btn_call(i: discord.Interaction):
                await i.response.send_modal(StartupModal(use_loan=(i.data['custom_id'] == "f_loan")))
                
            for child in view.children: child.callback = btn_call
            
            embed = discord.Embed(title="꒰ა ﹒chérie  ⸝⸝", color=0xffffff)
            embed.description = "<a:wt_torolove:1480580899430203484> **Business Incorporation**\n\nIt costs A$ 500,000 to incorporate. Secure a loan if needed."
            return await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

        cursor.execute("SELECT COUNT(id), AVG(morale) FROM employees WHERE user_id = ?", (interaction.user.id,))
        emps = cursor.fetchone(); conn.close()
        
        await interaction.response.send_message("<a:wt_torospin:1480580977867624540> *𝐴𝑐𝑐𝑒𝑠𝑠𝑖𝑛𝑔 𝐶𝐸𝑂 𝑇𝑒𝑟𝑚𝑖𝑛𝑎𝑙...*", ephemeral=True)
        await asyncio.sleep(1.5)

        embed = discord.Embed(title=f"꒰ა ﹒{biz[0]}  ⸝⸝", color=0xffffff)
        embed.description = (
            f"<:s_white2:1382052523166142486> **Capital:** A$ {biz[1]:,}\n"
            f"<:s_white2:1382052523166142486> **Reputation:** {biz[2]}%\n"
            f"<:s_white2:1382052523166142486> **Employees:** {emps[0] or 0}\n\n"
            f"**<a:wt_torolove:1480580899430203484> Company Morale**\n"
            f"{make_progress_bar(int(emps[1]) if emps[1] else 100)}\n"
        )
        embed.set_image(url="https://cdn.discordapp.com/attachments/1441473281420169367/1501576429761200290/0ac4c99804a08a107d2cf6f09d79655f.jpg?ex=6a008806&is=69ff3686&hm=4205b070b2abc9c883782db32c3e709027a4b6381ba1c83da86b0ad8c9834784&")
        await interaction.edit_original_response(content=None, embed=embed, view=TerminalView(self.bot))

    # ==========================================
    # ⚙️ THE DAILY ECONOMIC ENGINE
    # ==========================================
    @tasks.loop(hours=24)
    async def daily_cycle(self):
        conn = sqlite3.connect(DB_PATH); c = conn.cursor()
        conn_eco = sqlite3.connect(ECO_DB); c_eco = conn_eco.cursor()

        c.execute("SELECT user_id, capital, owner_salary, loan_balance, installments_left, vp_id, philosophy, reputation, demand_boost, is_public, name FROM businesses")
        businesses = c.fetchall()

        for uid, capital, owner_sal, loan, inst, vp_id, philosophy, rep, demand_boost, is_public, b_name in businesses:
            c.execute("SELECT salary, morale, specialization FROM employees WHERE user_id = ?", (uid,))
            emps = c.fetchall()
            
            c.execute("SELECT id, name, unit_price, cost_to_make FROM business_products WHERE user_id = ? AND active = 1", (uid,))
            products = c.fetchall()
            
            if not products or not emps:
                c.execute("UPDATE businesses SET last_report = 'No products or employees to run operations.' WHERE user_id = ?", (uid,))
                continue
                
            emp_count, total_payroll = len(emps), sum([e[0] for e in emps])
            
            # Strike Logic
            avg_morale = sum([e[1] for e in emps]) / emp_count if emp_count > 0 else 100
            if avg_morale < 20:
                c.execute("UPDATE businesses SET last_report = 'CRITICAL: Employees are on STRIKE! Zero output generated.' WHERE user_id = ?", (uid,))
                continue

            # Specialization Multipliers
            eng_boost = 1.0 + (0.10 * sum(1 for e in emps if e[2] == 'Engineer'))
            aud_savings = 1.0 - min(0.30, (0.05 * sum(1 for e in emps if e[2] == 'Auditor')))
            shark_boost = 1.0 + (0.15 * sum(1 for e in emps if e[2] == 'Shark'))

            # Philosophy & Reputation Math
            rep_modifier = rep / 100.0
            if philosophy == "Artisan":
                base_demand = random.uniform(0.9, 1.2) * rep_modifier * demand_boost * shark_boost
                output_mult = 0.5 * eng_boost
                new_rep = min(100, rep + 2)
            else:
                base_demand = random.uniform(1.0, 1.5) * rep_modifier * demand_boost * shark_boost
                output_mult = 1.5 * eng_boost
                new_rep = max(0, rep - 3)

            total_revenue = 0
            total_production_cost = 0
            
            # Produce and Sell all products evenly
            for p_id, p_name, price, cost in products:
                units_made = int(sum([50 * (e[1] / 100) for e in emps]) * output_mult / len(products))
                units_sold = int(units_made * base_demand)
                if units_sold > units_made: units_sold = units_made
                
                total_revenue += units_sold * price
                total_production_cost += units_made * (cost * aud_savings)

            overhead = int((10000 + (emp_count * 500)) * aud_savings)
            
            installment_payment = loan // inst if inst > 0 else 0
            if inst > 0: c.execute("UPDATE businesses SET loan_balance = loan_balance - ?, installments_left = installments_left - 1 WHERE user_id = ?", (installment_payment, uid))
            
            total_exec_pay = owner_sal * 2 if vp_id else owner_sal
            total_expenses = total_payroll + overhead + total_production_cost + installment_payment + total_exec_pay
            net_profit = int(total_revenue - total_expenses)
            
            new_capital = capital + net_profit
            c.execute("UPDATE businesses SET capital = ?, reputation = ?, demand_boost = 1.0 WHERE user_id = ?", (new_capital, new_rep, uid))
            
            # Pay Executives
            if owner_sal > 0 and capital >= total_exec_pay:
                c_eco.execute("INSERT INTO wallets (user_id, balance, active_card) VALUES (?, ?, 'silver') ON CONFLICT(user_id) DO UPDATE SET balance = balance + ?", (uid, owner_sal, owner_sal))
                if vp_id: c_eco.execute("INSERT INTO wallets (user_id, balance, active_card) VALUES (?, ?, 'silver') ON CONFLICT(user_id) DO UPDATE SET balance = balance + ?", (vp_id, owner_sal, owner_sal))
                
            # Public Company Updates
            if is_public:
                stock_symbol = b_name[:4].upper()
                c_eco.execute("SELECT price FROM stocks WHERE symbol = ?", (stock_symbol,))
                stock_data = c_eco.fetchone()
                if stock_data:
                    trend_adj = 1.05 if net_profit > 0 else 0.95
                    new_stock_price = max(10, int(stock_data[0] * trend_adj))
                    trend_icon = "📈 UP" if new_stock_price > stock_data[0] else "📉 DOWN"
                    c_eco.execute("UPDATE stocks SET price = ?, trend = ? WHERE symbol = ?", (new_stock_price, trend_icon, stock_symbol))
                
            report = f"Generated A$ {total_revenue:,}. Expenses: A$ {int(total_expenses):,} (Prod: {int(total_production_cost):,}, Overhead: {overhead:,}, Payroll: {total_payroll:,}). Net: A$ {net_profit:,}."
            c.execute("UPDATE businesses SET last_report = ? WHERE user_id = ?", (report, uid))
            c.execute("UPDATE employees SET morale = MAX(10, morale - 5) WHERE user_id = ?", (uid,))

        conn.commit(); conn.close()
        conn_eco.commit(); conn_eco.close()

    @daily_cycle.before_loop
    async def before_cycle(self): await self.bot.wait_until_ready()

async def setup(bot): await bot.add_cog(Business(bot))