import discord
from discord import app_commands
from discord.ext import commands
import sqlite3
import random
import asyncio

DB_PATH = "economy.db"

def get_db_connection():
    # Adding a 20-second timeout gives tasks time to wait for a lock to release
    conn = sqlite3.connect(DB_PATH, timeout=20, isolation_level=None)
    # This line is the magic fix for "database is locked"
    conn.execute('PRAGMA journal_mode=WAL;') 
    conn.execute('PRAGMA temp_store = MEMORY;')
    conn.execute('PRAGMA synchronous = NORMAL;')
    return conn


def get_balance(user_id: int) -> int:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT balance FROM wallets WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else 0

async def update_balance(interaction: discord.Interaction, amount: int):
    user_id = interaction.user.id
    conn = get_db_connection()
    cursor = conn.cursor()
    try: cursor.execute("ALTER TABLE wallets ADD COLUMN highest_balance INTEGER DEFAULT 0")
    except: pass
    cursor.execute("SELECT balance, active_card, highest_balance FROM wallets WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    if not row:
        cursor.execute("INSERT INTO wallets (user_id, balance, active_card, highest_balance) VALUES (?, 0, 'silver', 0)", (user_id,))
        old_bal, active_card, highest_bal = 0, 'silver', 0
    else:
        old_bal, active_card, highest_bal = row[0], row[1], row[2]

    new_bal = old_bal + amount
    new_highest = max(highest_bal if highest_bal else 0, new_bal)
    new_card = active_card
    unlocked = None

    if (highest_bal or 0) < 100000 and new_highest >= 100000:
        unlocked, new_card = "Gold Elite", "gold"
    elif (highest_bal or 0) < 600000 and new_highest >= 600000:
        unlocked, new_card = "Platinum Black", "plat_black"

    cursor.execute("UPDATE wallets SET balance = ?, highest_balance = ?, active_card = ? WHERE user_id = ?", (new_bal, new_highest, new_card, user_id))
    conn.commit()
    conn.close()

    if unlocked and interaction.channel:
        embed = discord.Embed(title="💳 VIP Tier Unlocked!", color=0xffd700)
        embed.description = f"Congratulations {interaction.user.mention}!\nYour earnings pushed your balance to **A$ {new_bal:,}**.\n\nYou have unlocked and automatically equipped the **{unlocked}** card!"
        await interaction.channel.send(embed=embed)


# ==========================================
# 🃏 1. HI-LO
# ==========================================
class HiLoView(discord.ui.View):
    def __init__(self, user_id: int, bet: int):
        super().__init__(timeout=45)
        self.user_id, self.bet = user_id, bet
        self.ranks = {'2':2, '3':3, '4':4, '5':5, '6':6, '7':7, '8':8, '9':9, '10':10, 'J':11, 'Q':12, 'K':13, 'A':14}
        self.deck = [f"{r}{s}" for s in ['♠️', '♥️', '♦️', '♣️'] for r in self.ranks.keys()]
        random.shuffle(self.deck)
        self.current_card = self.deck.pop()
        self.mult = 1.0
        self.step = 0

    def get_rank(self, card):
        clean = card.replace('♠️', '').replace('♥️', '').replace('♦️', '').replace('♣️', '').strip()
        return self.ranks[clean]

    async def guess(self, interaction: discord.Interaction, choice: str):
        if interaction.user.id != self.user_id: return
        next_card = self.deck.pop()
        curr_val, next_val = self.get_rank(self.current_card), self.get_rank(next_card)
        won = (choice == "high" and next_val > curr_val) or (choice == "low" and next_val < curr_val)
        
        if won:
            self.step += 1
            self.mult += (0.2 + (0.1 * self.step))
            self.current_card = next_card
            embed = discord.Embed(title="🃏 Hi-Lo", color=0x00ff00, description=f"**Card:** {self.current_card}\n\n✅ Correct! Next card was {'Higher' if choice=='high' else 'Lower'}.\n\n💰 **Current Value:** A$ {int(self.bet * self.mult):,} (`{self.mult:.2f}x`)")
            await interaction.response.edit_message(embed=embed, view=self)
        else:
            for c in self.children: c.disabled = True
            embed = discord.Embed(title="💥 BUST!", color=0xff0000, description=f"**Card:** {next_card}\n\n❌ Wrong! You lost your wager.\n🏦 **Balance:** A$ {get_balance(self.user_id):,}")
            await interaction.response.edit_message(embed=embed, view=self)
            self.stop()

    @discord.ui.button(label="Higher", style=discord.ButtonStyle.primary, emoji="🔼")
    async def btn_high(self, i, b): await self.guess(i, "high")
    @discord.ui.button(label="Lower", style=discord.ButtonStyle.danger, emoji="🔽")
    async def btn_low(self, i, b): await self.guess(i, "low")
    @discord.ui.button(label="Cash Out", style=discord.ButtonStyle.success, emoji="💵")
    async def btn_cash(self, interaction, button):
        if interaction.user.id != self.user_id: return
        for c in self.children: c.disabled = True
        winnings = int(self.bet * self.mult)
        await update_balance(interaction, winnings)
        embed = discord.Embed(title="💼 Cashed Out", color=0xffd700, description=f"You walked away with your profits!\n\n🏆 **Payout:** A$ {winnings:,} (`{self.mult:.2f}x`)\n🏦 **Balance:** A$ {get_balance(self.user_id):,}")
        await interaction.response.edit_message(embed=embed, view=self)
        self.stop()

# ==========================================
# 🥥 2. SHELL GAME
# ==========================================
class ShellGameView(discord.ui.View):
    def __init__(self, user_id: int, bet: int):
        super().__init__(timeout=30)
        self.user_id, self.bet = user_id, bet
        self.prize_cup = random.randint(0, 2)

    async def pick(self, interaction: discord.Interaction, cup_idx: int):
        if interaction.user.id != self.user_id: return
        for c in self.children: c.disabled = True
        won = (cup_idx == self.prize_cup)
        if won:
            winnings = int(self.bet * 2.5)
            await update_balance(interaction, winnings)
            embed = discord.Embed(title="🥥 You found it!", color=0x00ff00, description=f"The diamond was under Cup {cup_idx+1}!\n\n🏆 **Payout:** A$ {winnings:,}\n🏦 **Balance:** A$ {get_balance(self.user_id):,}")
        else:
            embed = discord.Embed(title="❌ Empty!", color=0xff0000, description=f"The diamond was under Cup {self.prize_cup+1}.\n\n💸 **Lost:** A$ {self.bet:,}\n🏦 **Balance:** A$ {get_balance(self.user_id):,}")
        await interaction.response.edit_message(embed=embed, view=self)
        self.stop()

    @discord.ui.button(label="Cup 1", style=discord.ButtonStyle.secondary, emoji="🥥")
    async def c1(self, i, b): await self.pick(i, 0)
    @discord.ui.button(label="Cup 2", style=discord.ButtonStyle.secondary, emoji="🥥")
    async def c2(self, i, b): await self.pick(i, 1)
    @discord.ui.button(label="Cup 3", style=discord.ButtonStyle.secondary, emoji="🥥")
    async def c3(self, i, b): await self.pick(i, 2)

# ==========================================
# 🐎 3. HORSE RACING
# ==========================================
class HorseRaceView(discord.ui.View):
    def __init__(self, user_id: int, bet: int):
        super().__init__(timeout=45)
        self.user_id, self.bet = user_id, bet

    async def race(self, interaction: discord.Interaction, choice: int):
        if interaction.user.id != self.user_id: return
        for c in self.children: c.disabled = True
        horses = ["🔴 Red", "🔵 Blue", "🟢 Green", "🟡 Yellow"]
        positions = [0, 0, 0, 0]
        embed = discord.Embed(title="🏁 And they're off!", color=0x2b2d31)
        await interaction.response.edit_message(embed=embed, view=self)
        
        for _ in range(4):
            await asyncio.sleep(1.2)
            for i in range(4): positions[i] += random.randint(1, 3)
            desc = ""
            for i in range(4): desc += f"{horses[i].split()[0]} {'—' * min(positions[i], 10)}🐎\n"
            embed.description = desc
            await interaction.edit_original_response(embed=embed, view=self)

        winner_idx = positions.index(max(positions))
        if choice == winner_idx:
            winnings = int(self.bet * 3.5)
            await update_balance(interaction, winnings)
            embed.title, embed.color = "🏆 Winner!", 0x00ff00
            embed.add_field(name="Result", value=f"{horses[winner_idx]} won!\n**Payout:** A$ {winnings:,}\n🏦 **Balance:** A$ {get_balance(self.user_id):,}")
        else:
            embed.title, embed.color = "💀 You Lost", 0xff0000
            embed.add_field(name="Result", value=f"{horses[winner_idx]} won the race.\n**Lost:** A$ {self.bet:,}\n🏦 **Balance:** A$ {get_balance(self.user_id):,}")
        await interaction.edit_original_response(embed=embed, view=self)
        self.stop()

    @discord.ui.button(label="Red", style=discord.ButtonStyle.danger, emoji="🔴")
    async def r1(self, i, b): await self.race(i, 0)
    @discord.ui.button(label="Blue", style=discord.ButtonStyle.primary, emoji="🔵")
    async def r2(self, i, b): await self.race(i, 1)
    @discord.ui.button(label="Green", style=discord.ButtonStyle.success, emoji="🟢")
    async def r3(self, i, b): await self.race(i, 2)
    @discord.ui.button(label="Yellow", style=discord.ButtonStyle.secondary, emoji="🟡")
    async def r4(self, i, b): await self.race(i, 3)

# ==========================================
# 🎲 4. CRAPS
# ==========================================
class DiceView(discord.ui.View):
    def __init__(self, user_id: int, bet: int):
        super().__init__(timeout=45)
        self.user_id, self.bet = user_id, bet

    async def roll(self, interaction: discord.Interaction, choice: str):
        if interaction.user.id != self.user_id: return
        for c in self.children: c.disabled = True
        embed = discord.Embed(title="🎲 Rolling the Dice...", color=0x2b2d31, description="🎲 🎲")
        await interaction.response.edit_message(embed=embed, view=self)
        await asyncio.sleep(1.5)
        
        d1, d2 = random.randint(1, 6), random.randint(1, 6)
        total = d1 + d2
        won, mult = False, 0
        if choice == "under" and total < 7: won, mult = True, 2
        elif choice == "over" and total > 7: won, mult = True, 2
        elif choice == "exact" and total == 7: won, mult = True, 5
        
        if won:
            winnings = self.bet * mult
            await update_balance(interaction, winnings)
            msg, clr = f"🎉 **You Won!** Payout: A$ {winnings:,}", 0x00ff00
        else: msg, clr = "💀 **You Lost.**", 0xff0000
            
        embed.description = f"🎲 **{d1}** + 🎲 **{d2}** = **{total}**\n\n{msg}\n🏦 **Balance:** A$ {get_balance(self.user_id):,}"
        embed.color = clr
        await interaction.edit_original_response(embed=embed, view=self)
        self.stop()

    @discord.ui.button(label="Under 7 (2x)", style=discord.ButtonStyle.primary)
    async def b_under(self, i, b): await self.roll(i, "under")
    @discord.ui.button(label="Exactly 7 (5x)", style=discord.ButtonStyle.success)
    async def b_exact(self, i, b): await self.roll(i, "exact")
    @discord.ui.button(label="Over 7 (2x)", style=discord.ButtonStyle.danger)
    async def b_over(self, i, b): await self.roll(i, "over")

# ==========================================
# 🏛️ 5. BACCARAT
# ==========================================
class BaccaratView(discord.ui.View):
    def __init__(self, user_id: int, bet: int):
        super().__init__(timeout=45)
        self.user_id, self.bet = user_id, bet

    async def play(self, interaction: discord.Interaction, choice: str):
        if interaction.user.id != self.user_id: return
        for c in self.children: c.disabled = True
        p_score, b_score = random.randint(0, 9), random.randint(0, 9)
        winner = "player" if p_score > b_score else "banker" if b_score > p_score else "tie"
        
        if choice == winner:
            mult = 8 if winner == "tie" else 2
            winnings = self.bet * mult
            await update_balance(interaction, winnings)
            msg, clr = f"🎉 **You Won!** Payout: A$ {winnings:,}", 0x00ff00
        else: msg, clr = "💀 **You Lost.**", 0xff0000
            
        embed = discord.Embed(title="🏛️ Baccarat Result", color=clr)
        embed.add_field(name="Player Score", value=f"**{p_score}**")
        embed.add_field(name="Banker Score", value=f"**{b_score}**")
        embed.description = f"{msg}\n🏦 **Balance:** A$ {get_balance(self.user_id):,}"
        await interaction.response.edit_message(embed=embed, view=self)
        self.stop()

    @discord.ui.button(label="Player (2x)", style=discord.ButtonStyle.primary)
    async def p(self, i, b): await self.play(i, "player")
    @discord.ui.button(label="Banker (2x)", style=discord.ButtonStyle.danger)
    async def bk(self, i, b): await self.play(i, "banker")
    @discord.ui.button(label="Tie (8x)", style=discord.ButtonStyle.success)
    async def t(self, i, b): await self.play(i, "tie")


# ==========================================
# 🪙 6. COINFLIP
# ==========================================
class CoinflipView(discord.ui.View):
    def __init__(self, uid, b): super().__init__(timeout=45); self.uid, self.b = uid, b
    async def flip(self, i, c):
        if i.user.id != self.uid: return
        for ch in self.children: ch.disabled = True
        await i.response.edit_message(embed=discord.Embed(title="🪙 Spinning...", color=0x2b2d31), view=self)
        await asyncio.sleep(1.5)
        out = random.choice(["heads", "tails"])
        if c == out: await update_balance(i, self.b * 2); msg, clr = f"🎉 **Won!** A$ {self.b*2:,}", 0x00ff00
        else: msg, clr = "💀 **Lost.**", 0xff0000
        await i.edit_original_response(embed=discord.Embed(title=f"Landed: {out.upper()}", description=f"{msg}\n🏦 Bal: A$ {get_balance(self.uid):,}", color=clr), view=self)
    @discord.ui.button(label="HEADS", style=discord.ButtonStyle.primary)
    async def bh(self, i, b): await self.flip(i, "heads")
    @discord.ui.button(label="TAILS", style=discord.ButtonStyle.secondary)
    async def bt(self, i, b): await self.flip(i, "tails")

# ==========================================
# ♠️ 7. BLACKJACK
# ==========================================
def calc_score(hand):
    s, a = 0, 0
    for c in hand:
        r = c.replace('♠️','').replace('♥️','').replace('♦️','').replace('♣️','').replace('♠','').replace('♥','').replace('♦','').replace('♣','').strip()
        if r in ['J','Q','K']: s += 10
        elif r == 'A': a, s = a+1, s+11
        else: s += int(r)
    while s > 21 and a > 0: s, a = s-10, a-1
    return s

class BlackjackView(discord.ui.View):
    def __init__(self, uid, b):
        super().__init__(timeout=60); self.uid, self.b = uid, b
        self.deck = [f"{r}{s}" for s in ['♠️', '♥️', '♦️', '♣️'] for r in ['2','3','4','5','6','7','8','9','10','J','Q','K','A']]
        random.shuffle(self.deck)
        self.p_hand, self.d_hand = [self.deck.pop(), self.deck.pop()], [self.deck.pop(), self.deck.pop()]

    def get_e(self, go=False, m=""):
        e = discord.Embed(title="🃏 Blackjack", color=0x00ff00 if "Won" in m else 0xff0000 if "Bust" in m or "Loss" in m else 0x2b2d31)
        e.add_field(name=f"You ({calc_score(self.p_hand)})", value=" ".join(self.p_hand))
        if go: e.add_field(name=f"Dealer ({calc_score(self.d_hand)})", value=" ".join(self.d_hand)); e.description = f"{m}\n🏦 Bal: A$ {get_balance(self.uid):,}"
        else: e.add_field(name="Dealer", value=f"{self.d_hand[0]} 🎴"); e.description = f"**Wager:** A$ {self.b:,}\nHit or Stand?"
        return e

    @discord.ui.button(label="Hit", style=discord.ButtonStyle.primary)
    async def h(self, i, b):
        if i.user.id != self.uid: return
        self.p_hand.append(self.deck.pop())
        if calc_score(self.p_hand) > 21:
            for c in self.children: c.disabled = True
            await i.response.edit_message(embed=self.get_e(True, "💀 **BUST!**"), view=self); self.stop()
        else: await i.response.edit_message(embed=self.get_e(), view=self)

    @discord.ui.button(label="Stand", style=discord.ButtonStyle.secondary)
    async def s(self, i, b):
        if i.user.id != self.uid: return
        for c in self.children: c.disabled = True
        while calc_score(self.d_hand) < 17: self.d_hand.append(self.deck.pop())
        ps, ds = calc_score(self.p_hand), calc_score(self.d_hand)
        if ds > 21 or ps > ds: await update_balance(i, self.b * 2); m = f"🎉 **Won!** A$ {self.b*2:,}"
        elif ps == ds: await update_balance(i, self.b); m = "🤝 **Push.**"
        else: m = "💀 **Dealer Wins.**"
        await i.response.edit_message(embed=self.get_e(True, m), view=self); self.stop()

# ==========================================
# 💣 8. GRID MINES
# ==========================================
class MineButton(discord.ui.Button):
    def __init__(self, index, is_mine, row):
        super().__init__(style=discord.ButtonStyle.secondary, label="❓", row=row)
        self.index, self.is_mine = index, is_mine

    async def callback(self, interaction: discord.Interaction):
        view: MinesView = self.view
        if interaction.user.id != view.user_id: return await interaction.response.send_message("❌ Not your game!", ephemeral=True)
        self.disabled = True
        if self.is_mine:
            self.emoji, self.label, self.style = "💣", "", discord.ButtonStyle.danger
            await view.game_over(interaction, won=False)
        else:
            self.emoji, self.label, self.style = "💎", "", discord.ButtonStyle.success
            view.safe_clicks += 1
            await view.update_game(interaction)

class MinesView(discord.ui.View):
    def __init__(self, user_id: int, bet: int):
        super().__init__(timeout=60)
        self.user_id, self.bet, self.safe_clicks = user_id, bet, 0
        self.mults = [1.0, 1.15, 1.35, 1.6, 1.9, 2.3, 2.8, 3.5, 4.5, 5.8, 7.5, 10.0, 15.0, 25.0, 50.0, 100.0, 250.0, 500.0]
        contents = ['💣']*3 + ['💎']*17
        random.shuffle(contents)
        for i in range(20): self.add_item(MineButton(i, contents[i] == '💣', i // 5))
        self.cashout_btn = discord.ui.Button(style=discord.ButtonStyle.primary, label="Cash Out (A$ 0)", emoji="💵", row=4)
        self.cashout_btn.callback = self.cashout
        self.add_item(self.cashout_btn)

    async def update_game(self, interaction: discord.Interaction):
        current_mult = self.mults[self.safe_clicks]
        self.cashout_btn.label, self.cashout_btn.style = f"Cash Out (A$ {int(self.bet * current_mult):,})", discord.ButtonStyle.success
        embed = discord.Embed(title="💣 Athena Mines", color=0x2b2d31, description=f"**Wager:** A$ {self.bet:,}\n**Multiplier:** `{current_mult}x`\n*Find diamonds to multiply your profit!*")
        await interaction.response.edit_message(embed=embed, view=self)

    async def game_over(self, interaction: discord.Interaction, won: bool):
        for item in self.children:
            item.disabled = True
            if isinstance(item, MineButton):
                if item.is_mine: item.emoji, item.style = "💣", discord.ButtonStyle.secondary
                else: item.emoji, item.style = "💎", discord.ButtonStyle.secondary
        if won:
            winnings = int(self.bet * self.mults[self.safe_clicks])
            await update_balance(interaction, winnings)
            embed = discord.Embed(title="💵 Cashed Out!", color=0x00ff00, description=f"🏆 **Payout:** A$ {winnings:,}\n🏦 **Balance:** A$ {get_balance(self.user_id):,}")
        else:
            embed = discord.Embed(title="💥 BOOM!", color=0xff0000, description=f"💀 **Lost:** A$ {self.bet:,}\n🏦 **Balance:** A$ {get_balance(self.user_id):,}")
        await interaction.response.edit_message(embed=embed, view=self)
        self.stop()

    async def cashout(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id: return
        if self.safe_clicks == 0: return await interaction.response.send_message("❌ Find 1 diamond first!", ephemeral=True)
        await self.game_over(interaction, won=True)

# ==========================================
# 🚀 9. CRYPTO BULL RUN
# ==========================================
class CryptoTraderView(discord.ui.View):
    def __init__(self, user_id: int, bet: int):
        super().__init__(timeout=45)
        self.user_id, self.bet, self.step, self.mults = user_id, bet, 0, [1.2, 1.5, 2.0, 3.0, 5.0, 10.0, 25.0]

    @discord.ui.button(label="HOLD (Next Week)", style=discord.ButtonStyle.primary, emoji="📈")
    async def h(self, interaction, button):
        if interaction.user.id != self.user_id: return
        if random.random() < (0.20 + (self.step * 0.08)):
            for c in self.children: c.disabled = True
            embed = discord.Embed(title="📉 CRASH!", color=0xff0000, description=f"The bubble burst. Portfolio is zero.\n🏦 **Balance:** A$ {get_balance(self.user_id):,}")
            embed.set_image(url="https://media.tenor.com/PZcI8Uiyx2UAAAAC/crash-stock-market.gif")
            await interaction.response.edit_message(embed=embed, view=self)
            self.stop()
        else:
            self.current_mult = self.mults[self.step]
            self.step += 1
            next_m = self.mults[self.step] if self.step < len(self.mults) else "MAX"
            embed = discord.Embed(title="🚀 Crypto Surge", color=0x00ff00, description=f"📊 **Value:** A$ {int(self.bet*self.current_mult):,} (`{self.current_mult}x`)\n⚠️ Hold for `{next_m}x`?")
            if next_m == "MAX": button.disabled = True
            await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="CASH OUT", style=discord.ButtonStyle.success, emoji="💵")
    async def c(self, interaction, button):
        if interaction.user.id != self.user_id: return
        w = int(self.bet * self.mults[self.step-1 if self.step > 0 else 0])
        await update_balance(interaction, w)
        for c in self.children: c.disabled = True
        embed = discord.Embed(title="💼 Trade Closed", color=0xffd700, description=f"🏆 **Payout:** A$ {w:,}\n🏦 **Balance:** A$ {get_balance(self.user_id):,}")
        await interaction.response.edit_message(embed=embed, view=self)
        self.stop()

# ==========================================
# 🎡 10. ROULETTE
# ==========================================
class RouletteView(discord.ui.View):
    def __init__(self, user_id: int, bet: int):
        super().__init__(timeout=45)
        self.user_id, self.bet = user_id, bet

    async def spin(self, interaction: discord.Interaction, choice: str):
        if interaction.user.id != self.user_id: return
        for c in self.children: c.disabled = True
        embed = discord.Embed(title="🎡 Athena Roulette", color=0x2b2d31, description="The wheel is spinning...")
        await interaction.response.edit_message(embed=embed, view=self)
        await asyncio.sleep(2)
        res = random.randint(0, 36)
        color = "green" if res == 0 else "red" if res % 2 != 0 else "black"
        emoji, mult = ("🟢", 14) if color == "green" else (("🔴", 2) if color == "red" else ("⚫", 2))
        if choice == color:
            await update_balance(interaction, self.bet * mult)
            msg, clr = f"🎉 **Won!** Payout: A$ {self.bet*mult:,}", 0x00ff00
        else: msg, clr = "💀 **Lost.**", 0xff0000
        embed.description, embed.color = f"Landed on: {emoji} **{res} {color.upper()}**\n\n{msg}\n🏦 **Balance:** A$ {get_balance(self.user_id):,}", clr
        await interaction.edit_original_response(embed=embed, view=self)
        self.stop()

    @discord.ui.button(label="RED (2x)", style=discord.ButtonStyle.danger, emoji="🔴")
    async def r(self, i, b): await self.spin(i, "red")
    @discord.ui.button(label="BLACK (2x)", style=discord.ButtonStyle.primary, emoji="⚫")
    async def bl(self, i, b): await self.spin(i, "black")
    @discord.ui.button(label="GREEN (14x)", style=discord.ButtonStyle.success, emoji="🟢")
    async def g(self, i, b): await self.spin(i, "green")

# ==========================================
# 🎰 11. VIP SLOTS
# ==========================================
async def play_slots(interaction, bet):
    embed = discord.Embed(title="🎰 VIP Slots", color=0x2b2d31, description="┏━━━┳━━━┳━━━┓\n┃ ⬛ ┃ ⬛ ┃ ⬛ ┃\n┗━━━┻━━━┻━━━┛\n*Spinning...*")
    
    # FIX: Edit the deferred response directly instead of creating a new followup
    await interaction.edit_original_response(embed=embed)
    await asyncio.sleep(1.5)
    
    r = [random.choice(["🍒", "🍋", "🍇", "💎", "7️⃣"]) for _ in range(3)]
    p = bet * 10 if r[0]==r[1]==r[2]=="7️⃣" else bet*5 if r[0]==r[1]==r[2]=="💎" else bet*3 if r[0]==r[1]==r[2] else int(bet*1.5) if (r[0]==r[1] or r[1]==r[2] or r[0]==r[2]) else 0
    
    if p > 0: await update_balance(interaction, p)
    res_str = f"┏━━━┳━━━┳━━━┓\n┃ {r[0]} ┃ {r[1]} ┃ {r[2]} ┃\n┗━━━┻━━━┻━━━┛"
    embed.description, embed.color = f"{res_str}\n\n{'🎉 **Win:** A$ '+str(p)+',' if p>0 else '💀 **Bust.**'}\n🏦 **Balance:** A$ {get_balance(interaction.user.id):,}", (0xffd700 if p>bet else 0xff0000)
    
    # Edit the exact same message to show the final result
    await interaction.edit_original_response(embed=embed)

# ==========================================
# UI: MODAL & CENTRAL LOBBY
# ==========================================
class BetModal(discord.ui.Modal):
    def __init__(self, game_name):
        super().__init__(title=f'{game_name} Wager')
        self.game_name = game_name
    bet_amount = discord.ui.TextInput(label='Wager Amount (A$)', placeholder='e.g. 500', required=True, max_length=8)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer() # THE FIX: Adds a 15-minute timeout window
        
        try: bet = int(self.bet_amount.value.replace(',', ''))
        except: return await interaction.followup.send("❌ Numbers only.", ephemeral=True)
        if bet <= 0: return await interaction.followup.send("❌ Bet 1+.", ephemeral=True)
        if bet > get_balance(interaction.user.id): return await interaction.followup.send("❌ Insufficient Funds.", ephemeral=True)

        await update_balance(interaction, -bet) # DEDUCT BET ONCE

        # ALL 11 GAMES ROUTED using followup.send
        if self.game_name == "Grid Mines":
            await interaction.followup.send(embed=discord.Embed(title="💣 Athena Mines", description=f"**Wager:** A$ {bet:,}\nDon't hit the 3 bombs!"), view=MinesView(interaction.user.id, bet))
        elif self.game_name == "Blackjack (21)":
            v = BlackjackView(interaction.user.id, bet)
            if calc_score(v.p_hand) == 21:
                await update_balance(interaction, int(bet*2.5))
                for c in v.children: c.disabled = True
                await interaction.followup.send(embed=v.get_e(True, "🎉 **NATURAL BLACKJACK!**"), view=v)
            else: await interaction.followup.send(embed=v.get_e(), view=v)
        elif self.game_name == "Crypto Bull Run":
            await interaction.followup.send(embed=discord.Embed(title="🚀 Market Dip Bought!", description=f"**Wager:** A$ {bet:,}\nClick **HOLD** to pump the multiplier!"), view=CryptoTraderView(interaction.user.id, bet))
        elif self.game_name == "Roulette":
            await interaction.followup.send(embed=discord.Embed(title="🎡 Table Open", description=f"**Bet:** A$ {bet:,}\nPick a color!"), view=RouletteView(interaction.user.id, bet))
        elif self.game_name == "VIP Slots":
            await play_slots(interaction, bet)
        elif self.game_name == "Coinflip":
            embed = discord.Embed(title="🪙 Coinflip", color=0x2b2d31, description=f"Wagered **A$ {bet:,}**.\nChoose **Heads** or **Tails** below.")
            await interaction.followup.send(embed=embed, view=CoinflipView(interaction.user.id, bet))
        elif self.game_name == "Hi-Lo":
            v = HiLoView(interaction.user.id, bet)
            await interaction.followup.send(embed=discord.Embed(title="🃏 Hi-Lo", description=f"**Card:** {v.current_card}\nWill the next card be Higher or Lower?"), view=v)
        elif self.game_name == "Shell Game":
            await interaction.followup.send(embed=discord.Embed(title="🥥 Shell Game", description=f"Bet: A$ {bet:,}. Find the diamond under the cups!"), view=ShellGameView(interaction.user.id, bet))
        elif self.game_name == "Horse Racing":
            await interaction.followup.send(embed=discord.Embed(title="🐎 Horse Racing", description=f"Bet: A$ {bet:,}. Pick your winning horse!"), view=HorseRaceView(interaction.user.id, bet))
        elif self.game_name == "Craps (Dice)":
            await interaction.followup.send(embed=discord.Embed(title="🎲 Craps", description=f"Bet: A$ {bet:,}. What will the two dice roll?"), view=DiceView(interaction.user.id, bet))
        elif self.game_name == "Baccarat":
            await interaction.followup.send(embed=discord.Embed(title="🏛️ Baccarat", description=f"Bet: A$ {bet:,}. Player or Banker?"), view=BaccaratView(interaction.user.id, bet))

class CasinoDropdown(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label='Grid Mines', description='Interactive grid. Avoid bombs!', emoji='💣'),
            discord.SelectOption(label='Blackjack (21)', description='Classic 21 against Dealer', emoji='🃏'),
            discord.SelectOption(label='Crypto Bull Run', description='Hold for multipliers or crash', emoji='🚀'),
            discord.SelectOption(label='Roulette', description='Red, Black, or Green', emoji='🎡'),
            discord.SelectOption(label='VIP Slots', description='3-reel 10x jackpot slot', emoji='🎰'),
            discord.SelectOption(label='Coinflip', description='True heads or tails call', emoji='🪙'),
            discord.SelectOption(label='Hi-Lo', description='Guess next card for multipliers', emoji='🔼'),
            discord.SelectOption(label='Horse Racing', description='Animated 4-horse race (3.5x)', emoji='🐎'),
            discord.SelectOption(label='Baccarat', description='High roller Player vs Banker', emoji='🏛️'),
            discord.SelectOption(label='Craps (Dice)', description='Roll 2 dice. Hit exactly 7 for 5x', emoji='🎲'),
            discord.SelectOption(label='Shell Game', description='Find diamond under 3 cups', emoji='🥥'),
        ]
        super().__init__(placeholder='Select a VIP table...', options=options)
    async def callback(self, i): await i.response.send_modal(BetModal(self.values[0]))

class CasinoLobbyView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(CasinoDropdown())

class Casino(commands.Cog):
    def __init__(self, bot): self.bot = bot
    @app_commands.command(name="casino", description="Enter the Grand Casino to wager your Athena Coins")
    async def casino_lobby(self, interaction: discord.Interaction):
        embed = discord.Embed(title="🥂 The Grand Casino", color=0xffffff)
        embed.description = (
            "Welcome to the high-roller tables, where fortunes are made and lost.\n"
            "Select a game from the dropdown below to place your wager.\n\n"
            "__**THE VIP TABLES**__\n"
            "All 11 games are currently online and fully operational."
        )
        embed.set_thumbnail(url="https://media.tenor.com/fL4h-jO-aB8AAAAi/chips-poker.gif")
        embed.set_image(url="https://media.tenor.com/7H_I2t5fM6sAAAAC/casino-las-vegas.gif")
        embed.set_footer(text="Gamble responsibly. The House always has the edge.")
        
        await interaction.followup.send(embed=embed, view=CasinoLobbyView())

async def setup(bot): await bot.add_cog(Casino(bot))