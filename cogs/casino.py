import discord
from discord import app_commands
from discord.ext import commands
import sqlite3
import random
import asyncio

DB_PATH = "economy.db"

def get_balance(user_id: int) -> int:
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT balance FROM wallets WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else 0

async def update_balance(interaction: discord.Interaction, amount: int):
    """Updates balance and automatically handles Level Up Unlocks!"""
    user_id = interaction.user.id
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Ensure highest_balance column exists (Safety check for first run)
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

    # THE LEVEL UP LOGIC (Only triggers once per account via All-Time High check)
    if (highest_bal or 0) < 100000 and new_highest >= 100000:
        unlocked = "Gold Elite"
        new_card = "gold"
    elif (highest_bal or 0) < 600000 and new_highest >= 600000:
        unlocked = "Platinum Black"
        new_card = "plat_black"

    cursor.execute("UPDATE wallets SET balance = ?, highest_balance = ?, active_card = ? WHERE user_id = ?", (new_bal, new_highest, new_card, user_id))
    conn.commit()
    conn.close()

    if unlocked and interaction.channel:
        embed = discord.Embed(title="💳 VIP Tier Unlocked!", color=0xffd700)
        embed.description = f"Congratulations {interaction.user.mention}!\nYour earnings pushed your balance to **A$ {new_bal:,}**.\n\nYou have unlocked and automatically equipped the **{unlocked}** card!"
        if new_card == "plat_black":
            embed.description += "\n\n*(Tip: Use `/setcard` to switch to the exclusive Platinum Chérie theme!)*"
        await interaction.channel.send(embed=embed)

# ==========================================
# 🃏 BLACKJACK MATH (CRASH-PROOF VERSION)
# ==========================================
def calc_score(hand):
    score, aces = 0, 0
    for card in hand:
        # FIX: Explicitly strips suit emojis to prevent ValueError on 2-byte characters
        rank = card.replace('♠️', '').replace('♥️', '').replace('♦️', '').replace('♣️', '')
        rank = rank.replace('♠', '').replace('♥', '').replace('♦', '').replace('♣', '').strip()
        
        if rank in ['J', 'Q', 'K']: score += 10
        elif rank == 'A': aces, score = aces + 1, score + 11
        else: score += int(rank)
        
    while score > 21 and aces > 0:
        score -= 10
        aces -= 1
    return score

# ==========================================
# 🪙 GAME: INTERACTIVE COINFLIP
# ==========================================
class CoinflipView(discord.ui.View):
    def __init__(self, user_id: int, bet: int):
        super().__init__(timeout=45)
        self.user_id = user_id
        self.bet = bet

    async def flip(self, interaction: discord.Interaction, choice: str):
        if interaction.user.id != self.user_id: return
        for child in self.children: child.disabled = True
        
        embed = discord.Embed(title="🪙 Athena Coinflip", color=0x2b2d31, description=f"The coin is spinning in the air...\nYou bet **A$ {self.bet:,}** on **{choice.upper()}**.")
        await interaction.response.edit_message(embed=embed, view=self)
        await asyncio.sleep(1.5)
        
        outcome = random.choice(["heads", "tails"])
        outcome_emoji = "👤" if outcome == "heads" else "🦅"
        
        if choice == outcome:
            winnings = self.bet * 2
            await update_balance(interaction, winnings)
            msg, color = f"🎉 **You Won!** Payout: A$ {winnings:,}", 0x00ff00
        else:
            msg, color = "💀 **You Lost.** The house takes your wager.", 0xff0000
            
        embed.description = f"The coin landed on: **{outcome.upper()}** {outcome_emoji}\n\n{msg}\n🏦 **Balance:** A$ {get_balance(self.user_id):,}"
        embed.color = color
        await interaction.edit_original_response(embed=embed, view=self)
        self.stop()

    @discord.ui.button(label="HEADS", style=discord.ButtonStyle.primary, emoji="👤")
    async def btn_heads(self, interaction: discord.Interaction, button: discord.ui.Button): await self.flip(interaction, "heads")

    @discord.ui.button(label="TAILS", style=discord.ButtonStyle.secondary, emoji="🦅")
    async def btn_tails(self, interaction: discord.Interaction, button: discord.ui.Button): await self.flip(interaction, "tails")

# ==========================================
# 💣 GAME: GRID MINES
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
# 🃏 GAME: BLACKJACK
# ==========================================
class BlackjackView(discord.ui.View):
    def __init__(self, user_id: int, bet: int):
        super().__init__(timeout=60)
        self.user_id, self.bet = user_id, bet
        self.deck = [f"{r}{s}" for s in ['♠️', '♥️', '♦️', '♣️'] for r in ['2', '3', '4', '5', '6', '7', '8', '9', '10', 'J', 'Q', 'K', 'A']]
        random.shuffle(self.deck)
        self.player_hand, self.dealer_hand = [self.deck.pop(), self.deck.pop()], [self.deck.pop(), self.deck.pop()]

    def generate_embed(self, game_over=False, msg=""):
        embed = discord.Embed(title="🃏 Athena Blackjack", color=0x2b2d31)
        embed.add_field(name=f"Your Hand ({calc_score(self.player_hand)})", value=" ".join(self.player_hand), inline=False)
        if game_over:
            embed.add_field(name=f"Dealer's Hand ({calc_score(self.dealer_hand)})", value=" ".join(self.dealer_hand), inline=False)
            embed.description = f"**Wager:** A$ {self.bet:,}\n\n{msg}\n🏦 **Balance:** A$ {get_balance(self.user_id):,}"
            embed.color = 0x00ff00 if "Won" in msg else 0xffd700 if "Tied" in msg else 0xff0000
        else:
            embed.add_field(name="Dealer's Hand", value=f"{self.dealer_hand[0]} 🎴", inline=False)
            embed.description = f"**Wager:** A$ {self.bet:,}\n*Hit or Stand?*"
        return embed

    @discord.ui.button(label="Hit", style=discord.ButtonStyle.primary)
    async def hit_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id: return
        self.player_hand.append(self.deck.pop())
        if calc_score(self.player_hand) > 21:
            for c in self.children: c.disabled = True
            await interaction.response.edit_message(embed=self.generate_embed(True, "💀 **BUST!** Over 21."), view=self)
            self.stop()
        else: await interaction.response.edit_message(embed=self.generate_embed(), view=self)

    @discord.ui.button(label="Stand", style=discord.ButtonStyle.secondary)
    async def stand_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id: return
        for c in self.children: c.disabled = True
        while calc_score(self.dealer_hand) < 17: self.dealer_hand.append(self.deck.pop())
        p, d = calc_score(self.player_hand), calc_score(self.dealer_hand)
        if d > 21 or p > d:
            await update_balance(interaction, self.bet * 2)
            msg = f"🎉 **You Won!** Payout: A$ {self.bet * 2:,}"
        elif p == d:
            await update_balance(interaction, self.bet)
            msg = "🤝 **Push.** Bet refunded."
        else: msg = "💀 **Dealer Wins.**"
        await interaction.response.edit_message(embed=self.generate_embed(True, msg), view=self)
        self.stop()

# ==========================================
# 🎡 GAME: ROULETTE
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
# 🚀 GAME: CRYPTO BULL RUN
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
# 🎰 GAME: VIP SLOTS
# ==========================================
async def play_slots(interaction, bet):
    embed = discord.Embed(title="🎰 VIP Slots", color=0x2b2d31, description="┏━━━┳━━━┳━━━┓\n┃ ⬛ ┃ ⬛ ┃ ⬛ ┃\n┗━━━┻━━━┻━━━┛\n*Spinning...*")
    await interaction.response.send_message(embed=embed)
    msg = await interaction.original_response()
    await asyncio.sleep(1.5)
    r = [random.choice(["🍒", "🍋", "🍇", "💎", "7️⃣"]) for _ in range(3)]
    p = bet * 10 if r[0]==r[1]==r[2]=="7️⃣" else bet*5 if r[0]==r[1]==r[2]=="💎" else bet*3 if r[0]==r[1]==r[2] else int(bet*1.5) if (r[0]==r[1] or r[1]==r[2] or r[0]==r[2]) else 0
    if p > 0: await update_balance(interaction, p)
    res_str = f"┏━━━┳━━━┳━━━┓\n┃ {r[0]} ┃ {r[1]} ┃ {r[2]} ┃\n┗━━━┻━━━┻━━━┛"
    embed.description, embed.color = f"{res_str}\n\n{'🎉 **Win:** A$ '+str(p)+',' if p>0 else '💀 **Bust.**'}\n🏦 **Balance:** A$ {get_balance(interaction.user.id):,}", (0xffd700 if p>bet else 0xff0000)
    await msg.edit(embed=embed)

# ==========================================
# UI: MODAL & LOBBY
# ==========================================
class BetModal(discord.ui.Modal):
    def __init__(self, game_name):
        super().__init__(title=f'{game_name} Wager')
        self.game_name = game_name
    bet_amount = discord.ui.TextInput(label='Wager Amount (A$)', placeholder='e.g. 500', required=True, max_length=8)

    async def on_submit(self, interaction: discord.Interaction):
        try: bet = int(self.bet_amount.value.replace(',', ''))
        except: return await interaction.response.send_message("❌ Numbers only.", ephemeral=True)
        if bet <= 0: return await interaction.response.send_message("❌ Bet 1+.", ephemeral=True)
        if bet > get_balance(interaction.user.id): return await interaction.response.send_message("❌ No money.", ephemeral=True)

        await update_balance(interaction, -bet) # DEDUCT BET ONCE

        if self.game_name == "VIP Slots": await play_slots(interaction, bet)
        elif self.game_name == "Coinflip":
            embed = discord.Embed(title="🪙 Coinflip", color=0x2b2d31, description=f"Wagered **A$ {bet:,}**.\nChoose **Heads** or **Tails** below.")
            await interaction.response.send_message(embed=embed, view=CoinflipView(interaction.user.id, bet))
        elif self.game_name == "Crypto Bull Run":
            await interaction.response.send_message(embed=discord.Embed(title="🚀 Market Dip Bought!", description=f"**Wager:** A$ {bet:,}\nClick **HOLD** to pump the multiplier!"), view=CryptoTraderView(interaction.user.id, bet))
        elif self.game_name == "Blackjack (21)":
            v = BlackjackView(interaction.user.id, bet)
            if calc_score(v.player_hand) == 21:
                await update_balance(interaction, int(bet*2.5))
                for c in v.children: c.disabled = True
                await interaction.response.send_message(embed=v.generate_embed(True, "🎉 **BLACKJACK!**"), view=v)
            else: await interaction.response.send_message(embed=v.generate_embed(), view=v)
        elif self.game_name == "Grid Mines":
            await interaction.response.send_message(embed=discord.Embed(title="💣 Athena Mines", description=f"**Wager:** A$ {bet:,}\nDon't hit the 3 bombs!"), view=MinesView(interaction.user.id, bet))
        elif self.game_name == "Roulette":
            await interaction.response.send_message(embed=discord.Embed(title="🎡 Table Open", description=f"**Bet:** A$ {bet:,}\nPick a color!"), view=RouletteView(interaction.user.id, bet))

class CasinoDropdown(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label='Grid Mines', emoji='💣'),
            discord.SelectOption(label='Blackjack (21)', emoji='🃏'),
            discord.SelectOption(label='Crypto Bull Run', emoji='🚀'),
            discord.SelectOption(label='Roulette', emoji='🎡'),
            discord.SelectOption(label='VIP Slots', emoji='🎰'),
            discord.SelectOption(label='Coinflip', emoji='🪙'),
        ]
        super().__init__(placeholder='Select a game table...', options=options)
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
            "__**AVAILABLE VIP TABLES**__\n\n"
            "<:s_white2:1382052523166142486> **Grid Mines (Stake Style)**\n"
            "└ *Click tiles to multiply your wager. Find diamonds, avoid the 3 hidden bombs! Push your luck up to 500x.*\n\n"
            "<:s_white2:1382052523166142486> **Blackjack (21)**\n"
            "└ *The classic card game. Hit or Stand to beat the Dealer without busting. Pays 2.5x on a natural Blackjack!*\n\n"
            "<:s_white2:1382052523166142486> **Crypto Bull Run**\n"
            "└ *Interactive trading. Hold your portfolio for massive multipliers, but cash out before the market crashes.*\n\n"
            "<:s_white2:1382052523166142486> **Roulette**\n"
            "└ *Place your chips on the spinning wheel. 🔴 Red (2x), ⚫ Black (2x), or 🟢 Green (14x).*\n\n"
            "<:s_white2:1382052523166142486> **VIP Slots**\n"
            "└ *Spin the 3-reel slot machine. Match three 7️⃣s to hit the ultimate 10x Jackpot.*\n\n"
            "<:s_white2:1382052523166142486> **Coinflip**\n"
            "└ *Pure 50/50 odds. Double your money or lose it all.*"
        )
        embed.set_thumbnail(url="https://media.tenor.com/fL4h-jO-aB8AAAAi/chips-poker.gif")
        embed.set_image(url="https://media.tenor.com/7H_I2t5fM6sAAAAC/casino-las-vegas.gif")
        embed.set_footer(text="Gamble responsibly. The House always has the edge.")
        
        await interaction.response.send_message(embed=embed, view=CasinoLobbyView())
        
async def setup(bot): await bot.add_cog(Casino(bot))