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

    # Ensure user exists and the highest_balance column is ready
    cursor.execute("INSERT OR IGNORE INTO wallets (user_id, balance, active_card, highest_balance) VALUES (?, 0, 'silver', 0)", (user_id,))
    try: cursor.execute("ALTER TABLE wallets ADD COLUMN highest_balance INTEGER DEFAULT 0")
    except: pass

    cursor.execute("SELECT balance, active_card, highest_balance FROM wallets WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    old_bal = row[0]
    active_card = row[1] if row[1] else 'silver'
    highest_bal = row[2] if len(row) > 2 and row[2] is not None else old_bal

    new_bal = old_bal + amount
    new_highest = max(highest_bal, new_bal)
    new_card = active_card
    unlocked = None

    # THE LEVEL UP LOGIC (Only triggers on All-Time Highs)
    if highest_bal < 100000 and new_highest >= 100000:
        unlocked = "Gold Elite"
        new_card = "gold"
    elif highest_bal < 600000 and new_highest >= 600000:
        unlocked = "Platinum Black"
        new_card = "plat_black"

    cursor.execute("UPDATE wallets SET balance = ?, highest_balance = ?, active_card = ? WHERE user_id = ?", (new_bal, new_highest, new_card, user_id))
    conn.commit()
    conn.close()

    # If they unlocked a tier, drop the hype message in the chat
    if unlocked and interaction.channel:
        embed = discord.Embed(title="💳 VIP Tier Unlocked!", color=0xffd700)
        embed.description = f"Congratulations {interaction.user.mention}!\nYour casino winnings pushed your balance to **A$ {new_bal:,}**.\n\nYou have unlocked and automatically equipped the **{unlocked}** card!"
        if new_card == "plat_black":
            embed.description += "\n\n*(Tip: You can use `/setcard` to switch to the exclusive Platinum Chérie theme!)*"
        await interaction.channel.send(embed=embed)


# ==========================================
# 💣 GAME: MINES
# ==========================================
class MineButton(discord.ui.Button):
    def __init__(self, index, is_mine, row):
        super().__init__(style=discord.ButtonStyle.secondary, label="❓", row=row)
        self.index = index
        self.is_mine = is_mine

    async def callback(self, interaction: discord.Interaction):
        view: MinesView = self.view
        if interaction.user.id != view.user_id: return await interaction.response.send_message("❌ This is not your game!", ephemeral=True)
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
        self.user_id = user_id
        self.bet = bet
        self.safe_clicks = 0
        self.mults = [1.0, 1.15, 1.35, 1.6, 1.9, 2.3, 2.8, 3.5, 4.5, 5.8, 7.5, 10.0, 15.0, 25.0, 50.0, 100.0, 250.0, 500.0]
        
        contents = ['💣']*3 + ['💎']*17
        random.shuffle(contents)
        for i in range(20): self.add_item(MineButton(i, contents[i] == '💣', i // 5))
            
        self.cashout_btn = discord.ui.Button(style=discord.ButtonStyle.primary, label="Cash Out (A$ 0)", emoji="💵", row=4)
        self.cashout_btn.callback = self.cashout
        self.add_item(self.cashout_btn)

    async def update_game(self, interaction: discord.Interaction):
        current_mult = self.mults[self.safe_clicks]
        current_win = int(self.bet * current_mult)
        self.cashout_btn.label, self.cashout_btn.style = f"Cash Out (A$ {current_win:,})", discord.ButtonStyle.success
        
        embed = discord.Embed(title="💣 Athena Mines", color=0x2b2d31, description=f"**Wager:** A$ {self.bet:,}\n**Multiplier:** `{current_mult}x`\n**Current Profit:** A$ {current_win:,}\n\n*Find diamonds to increase the multiplier, or cash out!*")
        await interaction.response.edit_message(embed=embed, view=self)

    async def game_over(self, interaction: discord.Interaction, won: bool):
        for item in self.children:
            item.disabled = True
            if isinstance(item, MineButton):
                if item.is_mine and item.emoji != "💣": item.emoji, item.label, item.style = "💣", "", discord.ButtonStyle.secondary
                elif not item.is_mine and item.emoji != "💎": item.emoji, item.label, item.style = "💎", "", discord.ButtonStyle.secondary

        if won:
            winnings = int(self.bet * self.mults[self.safe_clicks])
            await update_balance(interaction, winnings)
            embed = discord.Embed(title="💵 Cashed Out!", color=0x00ff00, description=f"You safely navigated the minefield!\n\n🏆 **Payout:** A$ {winnings:,}\n🏦 **Balance:** A$ {get_balance(self.user_id):,}")
        else:
            embed = discord.Embed(title="💥 BOOM!", color=0xff0000, description=f"You hit a mine and lost everything.\n\n💸 **Lost:** A$ {self.bet:,}\n🏦 **Balance:** A$ {get_balance(self.user_id):,}")

        await interaction.response.edit_message(embed=embed, view=self)
        self.stop()

    async def cashout(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id: return await interaction.response.send_message("❌ This is not your game!", ephemeral=True)
        if self.safe_clicks == 0: return await interaction.response.send_message("❌ You must find at least 1 diamond to cash out!", ephemeral=True)
        await self.game_over(interaction, won=True)

# ==========================================
# 🃏 GAME: BLACKJACK
# ==========================================
def calc_score(hand):
    score, aces = 0, 0
    for card in hand:
        rank = card[:-1]
        if rank in ['J', 'Q', 'K']: score += 10
        elif rank == 'A': aces, score = aces + 1, score + 11
        else: score += int(rank)
    while score > 21 and aces > 0: score, aces = score - 10, aces - 1
    return score

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
            embed.description = f"**Wager:** A$ {self.bet:,}\n*Hit to draw a card, or Stand to keep your current hand.*"
        return embed

    @discord.ui.button(label="Hit", style=discord.ButtonStyle.primary)
    async def hit_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id: return
        self.player_hand.append(self.deck.pop())
        if calc_score(self.player_hand) > 21:
            for child in self.children: child.disabled = True
            await interaction.response.edit_message(embed=self.generate_embed(True, "💀 **BUST!** You went over 21."), view=self)
            self.stop()
        else: await interaction.response.edit_message(embed=self.generate_embed(), view=self)

    @discord.ui.button(label="Stand", style=discord.ButtonStyle.secondary)
    async def stand_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id: return
        for child in self.children: child.disabled = True
        while calc_score(self.dealer_hand) < 17: self.dealer_hand.append(self.deck.pop())
        
        p_score, d_score = calc_score(self.player_hand), calc_score(self.dealer_hand)
        if d_score > 21 or p_score > d_score:
            await update_balance(interaction, self.bet * 2)
            msg = f"🎉 **You Won!** Payout: A$ {self.bet * 2:,}"
        elif p_score == d_score:
            await update_balance(interaction, self.bet)
            msg = "🤝 **Push (Tied).** Your wager was refunded."
        else: msg = "💀 **Dealer Wins.** You lost your wager."
            
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
        for child in self.children: child.disabled = True
        
        embed = discord.Embed(title="🎡 Athena Roulette", color=0x2b2d31, description=f"The wheel is spinning...\nYou bet **A$ {self.bet:,}** on **{choice.upper()}**.")
        await interaction.response.edit_message(embed=embed, view=self)
        await asyncio.sleep(2)
        
        result_num = random.randint(0, 36)
        if result_num == 0: color, emoji, mult = "green", "🟢", 14
        elif result_num % 2 == 0: color, emoji, mult = "black", "⚫", 2
        else: color, emoji, mult = "red", "🔴", 2
            
        if choice == color:
            winnings = self.bet * mult
            await update_balance(interaction, winnings)
            msg, embed.color = f"🎉 **You Won!** Payout: A$ {winnings:,}", 0x00ff00
        else:
            msg, embed.color = "💀 **You Lost.** The house takes your wager.", 0xff0000
            
        embed.description = f"The ball landed on: {emoji} **{result_num} {color.capitalize()}**\n\n{msg}\n🏦 **Balance:** A$ {get_balance(self.user_id):,}"
        await interaction.edit_original_response(embed=embed, view=self)
        self.stop()

    @discord.ui.button(label="RED (2x)", style=discord.ButtonStyle.danger, emoji="🔴")
    async def btn_red(self, interaction: discord.Interaction, button: discord.ui.Button): await self.spin(interaction, "red")
    @discord.ui.button(label="BLACK (2x)", style=discord.ButtonStyle.primary, emoji="⚫")
    async def btn_black(self, interaction: discord.Interaction, button: discord.ui.Button): await self.spin(interaction, "black")
    @discord.ui.button(label="GREEN (14x)", style=discord.ButtonStyle.success, emoji="🟢")
    async def btn_green(self, interaction: discord.Interaction, button: discord.ui.Button): await self.spin(interaction, "green")

# ==========================================
# 📈 GAME: CRYPTO TRADER
# ==========================================
class CryptoTraderView(discord.ui.View):
    def __init__(self, user_id: int, bet: int):
        super().__init__(timeout=45) 
        self.user_id, self.bet = user_id, bet
        self.multipliers, self.step, self.current_mult = [1.2, 1.5, 2.0, 3.0, 5.0, 10.0, 25.0], 0, 1.0

    @discord.ui.button(label="HOLD (Next Week)", style=discord.ButtonStyle.primary, emoji="📈")
    async def hold_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id: return

        if random.random() < (0.20 + (self.step * 0.08)):
            for child in self.children: child.disabled = True
            embed = discord.Embed(title="📉 MARKET COLLAPSE!", color=0xff0000, description=f"**The bubble burst.** Your portfolio plummeted to zero.\n\n💸 **Lost:** A$ {self.bet:,}\n🏦 **Balance:** A$ {get_balance(self.user_id):,}")
            embed.set_image(url="https://media.tenor.com/PZcI8Uiyx2UAAAAC/crash-stock-market.gif") 
            await interaction.response.edit_message(embed=embed, view=self)
            self.stop()
        else:
            self.current_mult = self.multipliers[self.step]
            self.step += 1
            next_mult = self.multipliers[self.step] if self.step < len(self.multipliers) else "MAX"
            embed = discord.Embed(title="🚀 Crypto Bull Run", color=0x00ff00, description=f"The market is surging! You survived another week.\n\n💰 **Initial Investment:** A$ {self.bet:,}\n📊 **Current Value:** A$ {int(self.bet * self.current_mult):,}  (`{self.current_mult}x`)\n\n⚠️ *Do you secure your profits, or hold for **{next_mult}x**?*")
            if next_mult == "MAX": self.hold_btn.disabled = True 
            await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="CASH OUT", style=discord.ButtonStyle.success, emoji="💵")
    async def cash_out_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id: return
        winnings = int(self.bet * self.current_mult)
        await update_balance(interaction, winnings) 
        for child in self.children: child.disabled = True
        
        embed = discord.Embed(title="💼 Trade Closed", color=0xffd700, description=f"You safely secured your profits before the crash!\n\n🏆 **Payout:** A$ {winnings:,} (`{self.current_mult}x`)\n🏦 **Balance:** A$ {get_balance(self.user_id):,}")
        await interaction.response.edit_message(embed=embed, view=self)
        self.stop()

# ==========================================
# 🎰 GAME: VISUAL SLOTS & 🪙 COINFLIP
# ==========================================
async def play_slots(interaction: discord.Interaction, bet: int):
    embed = discord.Embed(title="🎰 Athena VIP Slots", color=0x2b2d31, description=f"**Wager:** A$ {bet:,}\n\n┏━━━┳━━━┳━━━┓\n┃ ⬛ ┃ ⬛ ┃ ⬛ ┃\n┗━━━┻━━━┻━━━┛\n\n*Spinning the reels...*")
    await interaction.response.send_message(embed=embed)
    message = await interaction.original_response()
    await asyncio.sleep(1.5)

    result = [random.choice(["🍒", "🍋", "🍇", "💎", "7️⃣"]) for _ in range(3)]
    result_str = f"┏━━━┳━━━┳━━━┓\n┃ {result[0]} ┃ {result[1]} ┃ {result[2]} ┃\n┗━━━┻━━━┻━━━┛"
    
    payout = 0
    if result[0] == result[1] == result[2]:
        payout = bet * 10 if result[0] == "7️⃣" else bet * 5 if result[0] == "💎" else bet * 3
        msg, color = f"🎉 **JACKPOT!** You won **A$ {payout:,}**!", 0xffd700
    elif result[0] == result[1] or result[1] == result[2] or result[0] == result[2]:
        payout = int(bet * 1.5)
        msg, color = f"✨ **Mini Win!** You won **A$ {payout:,}**.", 0x00ff00
    else:
        msg, color = "💀 **Bust.** You lost your wager.", 0xff0000

    if payout > 0: await update_balance(interaction, payout)
    embed.color, embed.description = color, f"**Wager:** A$ {bet:,}\n\n{result_str}\n\n{msg}\n🏦 **Balance:** A$ {get_balance(interaction.user.id):,}"
    await message.edit(embed=embed)

async def play_coinflip(interaction: discord.Interaction, bet: int):
    won = random.choice([True, False])
    embed = discord.Embed(title="🪙 Double or Nothing", color=0x2b2d31, description=f"{interaction.user.mention} flips a coin...\n**Wager:** A$ {bet:,}")
    await interaction.response.send_message(embed=embed)
    message = await interaction.original_response()
    await asyncio.sleep(1.5)
    
    if won:
        await update_balance(interaction, bet * 2)
        embed.description, embed.color = f"🪙 The coin landed on **HEADS**!\n\n🎉 **You Won:** A$ {bet * 2:,}\n🏦 **Balance:** A$ {get_balance(interaction.user.id):,}", 0x00ff00
    else:
        embed.description, embed.color = f"🪙 The coin landed on **TAILS**!\n\n💀 **You Lost:** A$ {bet:,}\n🏦 **Balance:** A$ {get_balance(interaction.user.id):,}", 0xff0000
    await message.edit(embed=embed)


# ==========================================
# UI: MODAL & LOBBY
# ==========================================
class BetModal(discord.ui.Modal):
    def __init__(self, game_name: str):
        super().__init__(title=f'{game_name} Wager')
        self.game_name = game_name

    bet_amount = discord.ui.TextInput(label='Wager Amount (A$)', placeholder='e.g. 500', style=discord.TextStyle.short, required=True, max_length=8)

    async def on_submit(self, interaction: discord.Interaction):
        try: bet = int(self.bet_amount.value.replace(',', ''))
        except ValueError: return await interaction.response.send_message("❌ Invalid amount. Numbers only.", ephemeral=True)
        if bet <= 0: return await interaction.response.send_message("❌ Minimum wager is A$ 1.", ephemeral=True)

        if bet > get_balance(interaction.user.id):
            return await interaction.response.send_message(f"❌ **Declined:** Insufficient Funds.", ephemeral=True)

        # ONE-TIME BET DEDUCTION FOR ALL GAMES
        await update_balance(interaction, -bet)

        if self.game_name == "VIP Slots": await play_slots(interaction, bet)
        elif self.game_name == "Coinflip": await play_coinflip(interaction, bet)
        elif self.game_name == "Crypto Bull Run":
            embed = discord.Embed(title="🚀 Crypto Bull Run", color=0x2b2d31, description=f"You bought the dip!\n\n💰 **Investment:** A$ {bet:,}\n📊 **Current Value:** A$ {bet:,} (`1.0x`)\n\n⚠️ *The market is volatile. Hold to increase your multiplier, or Cash Out before it crashes!*")
            await interaction.response.send_message(embed=embed, view=CryptoTraderView(interaction.user.id, bet))
        elif self.game_name == "Blackjack (21)":
            view = BlackjackView(interaction.user.id, bet)
            if calc_score(view.player_hand) == 21:
                winnings = int(bet * 2.5)
                await update_balance(interaction, winnings)
                for child in view.children: child.disabled = True
                await interaction.response.send_message(embed=view.generate_embed(True, f"🎉 **BLACKJACK!** Instant Win!\nPayout: A$ {winnings:,}"), view=view)
            else:
                await interaction.response.send_message(embed=view.generate_embed(), view=view)
        elif self.game_name == "Grid Mines":
            await interaction.response.send_message(embed=discord.Embed(title="💣 Athena Mines", color=0x2b2d31, description=f"**Wager:** A$ {bet:,}\n**Multiplier:** `1.0x`\n**Current Profit:** A$ 0\n\n*Click the grid below. Find diamonds 💎 to multiply your wager, but avoid the 3 hidden bombs!*"), view=MinesView(interaction.user.id, bet))
        elif self.game_name == "Roulette":
            await interaction.response.send_message(embed=discord.Embed(title="🎡 Place Your Bets", color=0x2b2d31, description=f"You brought **A$ {bet:,}** to the table.\n\nWhere do you want to place your chips?"), view=RouletteView(interaction.user.id, bet))

class CasinoDropdown(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label='Grid Mines', description='Interactive: Click tiles to multiply wager, avoid bombs!', emoji='💣'),
            discord.SelectOption(label='Blackjack (21)', description='Interactive: Play cards against the House', emoji='🃏'),
            discord.SelectOption(label='Crypto Bull Run', description='Interactive: Hold for massive multipliers or crash!', emoji='🚀'),
            discord.SelectOption(label='Roulette', description='Place chips on Red, Black, or Green', emoji='🎡'),
            discord.SelectOption(label='VIP Slots', description='Classic 3-reel slot machine', emoji='🎰'),
            discord.SelectOption(label='Coinflip', description='50/50 Double or Nothing', emoji='🪙'),
        ]
        super().__init__(placeholder='Select a game table...', min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(BetModal(game_name=self.values[0]))

class CasinoLobbyView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(CasinoDropdown())

class Casino(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="casino", description="Enter the Grand Casino to wager your Athena Coins")
    async def casino_lobby(self, interaction: discord.Interaction):
        embed = discord.Embed(title="🥂 The Grand Casino", color=0x2b2d31)
        embed.description = (
            "Welcome to the high-roller tables, where fortunes are made and lost.\n"
            "Select a game from the dropdown below to place your wager.\n\n"
            "__**AVAILABLE VIP TABLES**__\n\n"
            "<:s_white2:1382052523166142486> **Grid Mines (Stake Style)**\n"
            "└ *Click tiles to multiply your wager. Find diamonds, avoid the 3 hidden bombs!*\n\n"
            "<:s_white2:1382052523166142486> **Blackjack (21)**\n"
            "└ *The classic card game. Hit or Stand to beat the Dealer without busting.*\n\n"
            "<:s_white2:1382052523166142486> **Crypto Bull Run**\n"
            "└ *Hold your portfolio for massive multipliers, but cash out before the market crashes.*\n\n"
            "<:s_white2:1382052523166142486> **Roulette**\n"
            "└ *Place your chips on the spinning wheel. 🔴 (2x), ⚫ (2x), or 🟢 (14x).*\n\n"
            "<:s_white2:1382052523166142486> **VIP Slots**\n"
            "└ *Spin the 3-reel slot machine. Match three 7️⃣s to hit the ultimate 10x Jackpot.*\n\n"
            "<:s_white2:1382052523166142486> **Coinflip**\n"
            "└ *Pure 50/50 odds. Double your money or lose it all.*"
        )
        embed.set_thumbnail(url="https://media.tenor.com/fL4h-jO-aB8AAAAi/chips-poker.gif")
        embed.set_image(url="https://media.tenor.com/7H_I2t5fM6sAAAAC/casino-las-vegas.gif")
        embed.set_footer(text="Gamble responsibly. The House always has the edge.")
        
        await interaction.response.send_message(embed=embed, view=CasinoLobbyView())

async def setup(bot):
    await bot.add_cog(Casino(bot))