# duel_royale.py
# Requires: discord.py >= 2.0
import os
import asyncio
import random
import discord
from discord.ext import commands
from discord import app_commands
from typing import Optional

# ========= Guild targeting (instant slash sync) =========
def _guild_ids_from_env():
    raw = os.getenv("GUILD_IDS", "").strip()
    return [int(x) for x in raw.split(",") if x.strip().isdigit()]

# Fallback: hardcode your server ID here if you don’t want to use the env var.
GUILD_IDS = _guild_ids_from_env() or [1181834816631623761]  # <-- replace with YOUR server ID
GUILDS = [discord.Object(id=g) for g in GUILD_IDS]

# ========= Tunables =========
START_HP = 100
ROUND_DELAY = 1.0  # seconds between narration lines

# Exodia (special)
EXODIA_IMAGE_URL = "https://i.imgur.com/gXWD1ze.jpeg"
EXODIA_TRIGGER_CHANCE = 0.01  # 1% chance
EXODIA_DAMAGE = 1000

# Mix probabilities for normal rolls (EXODIA checked first; ULTRA_BUFF second)
HEAL_CHANCE = 0.15
BUFF_CHANCE = 0.10

# Ultra-rare global buff: 1% chance any turn; next successful action ×1000
ULTRA_BUFF = {
    "name": "divine intervention",
    "chance": 0.01,
    "multiplier": 1000.0
}

# Shared heal: heals self and also heals every opponent for 60% of the self-heal
SHARED_HEAL = {
    "name": "casts Healing Aura",
    "range": (25, 40),
    "chance": 0.65,
    "splash_ratio": 0.60,
    "weight": 0.20,
}

# ========= Move Pools =========
NORMAL_ATTACKS = [
    ("bar fight haymaker", (14, 24), 0.75),
    ("cheap tequila uppercut", (16, 26), 0.70),
    ("walk of shame kick", (12, 22), 0.80),
    ("toxic ex slap", (10, 20), 0.85),
    ("credit card decline strike", (15, 25), 0.75),
    ("hangover headbutt", (18, 28), 0.65),
    ("midlife crisis spin kick", (18, 32), 0.60),
    ("tax season chokehold", (20, 35), 0.55),
    ("paternity test slam", (18, 30), 0.65),
    ("gas station burrito gut punch", (12, 22), 0.80),

    ("WiFi disconnect strike", (14, 24), 0.75),
    ("Blue Screen of Death kick", (16, 28), 0.70),
    ("404 Not Found jab", (10, 20), 0.85),
    ("Pay-to-Win wallet smack", (18, 30), 0.65),
    ("Patch Notes Nerf hammer", (12, 24), 0.80),
    ("Loot Box sucker punch", (15, 27), 0.70),
    ("Lag Spike headbutt", (16, 26), 0.70),
    ("Controller Disconnect throw", (14, 24), 0.75),
    ("Rage Quit slam", (18, 32), 0.60),
    ("Keyboard Smash flurry", (12, 22), 0.80),

    ("Netflix and Kill elbow", (20, 34), 0.55),
    ("Office chair spin attack", (14, 24), 0.75),
    ("Group Chat left hook", (12, 22), 0.80),
    ("Passive-Aggressive Email blast", (10, 20), 0.85),
    ("Sunday Scaries stomp", (15, 27), 0.70),
    ("Silent Treatment choke", (16, 28), 0.65),
    ("Overdraft Fee jab", (12, 22), 0.80),
    ("Blackout Friday brawl", (18, 30), 0.65),
    ("Spam Call sucker punch", (10, 20), 0.90),
    ("PowerPoint presentation slam", (14, 26), 0.70),
]

HEALS = [
    ("drinks a Health Potion", (15, 25), 0.80),
    ("casts a Healing Spell", (18, 30), 0.70),
    ("uses a Medkit", (20, 35), 0.65),
    ("eats a Red Mushroom", (12, 22), 0.85),
    ("rests at a Bonfire", (25, 40), 0.50),
]

BUFFS = [
    ("focus stance", (1.25, 1.50), 0.85),
    ("adrenaline surge", (1.40, 1.60), 0.75),
    ("battle rhythm", (1.20, 1.40), 0.90),
    ("berserker’s edge", (1.50, 1.75), 0.65),
    ("blessing of vitality", (1.30, 1.60), 0.70),
]

# ========= Helpers =========
def roll_from_pool(pool):
    name, (lo, hi), chance = random.choice(pool)
    success = (random.random() <= chance)
    amount = random.uniform(lo, hi) if success else 0.0
    return name, success, amount

def pick_action():
    if random.random() < EXODIA_TRIGGER_CHANCE:
        return {'kind': 'exodia', 'name': "**summon all cards of EXODIA**",
                'success': True, 'amount': EXODIA_DAMAGE, 'shared': False}
    if random.random() < ULTRA_BUFF["chance"]:
        return {'kind': 'ultra_buff', 'name': ULTRA_BUFF["name"],
                'success': True, 'amount': ULTRA_BUFF["multiplier"], 'shared': False}

    r = random.random()
    if r < BUFF_CHANCE:
        name, success, mult = roll_from_pool(BUFFS)
        return {'kind': 'buff', 'name': name, 'success': success, 'amount': mult, 'shared': False}
    elif r < BUFF_CHANCE + HEAL_CHANCE:
        if random.random() < SHARED_HEAL["weight"]:
            lo, hi = SHARED_HEAL["range"]
            success = (random.random() <= SHARED_HEAL["chance"])
            heal = random.randint(lo, hi) if success else 0
            return {'kind': 'heal', 'name': SHARED_HEAL["name"], 'success': success,
                    'amount': int(heal), 'shared': True}
        else:
            name, success, heal = roll_from_pool(HEALS)
            return {'kind': 'heal', 'name': name, 'success': success,
                    'amount': int(round(heal)), 'shared': False}
    else:
        name, success, dmg = roll_from_pool(NORMAL_ATTACKS)
        return {'kind': 'attack', 'name': name, 'success': success,
                'amount': int(round(dmg)), 'shared': False}

def apply_multiplier_if_any(mult_state, attacker_id, base_amount):
    mult = mult_state.get(attacker_id)
    if not mult or base_amount <= 0:
        return int(base_amount), None
    final = int(round(base_amount * mult))
    mult_state.pop(attacker_id, None)
    return final, mult

def get_tc_emoji(guild: Optional[discord.Guild]) -> str:
    """
    Try to find a custom emoji named 'TC' in this guild.
    If found, returns something like '<:TC:1234567890>', else returns ':TC:' fallback.
    """
    if guild:
        emoji = discord.utils.get(guild.emojis, name="TC")
        if emoji:
            return str(emoji)
    return ":TC:"

# ========= Views (Confirm) =========
class BetAcceptView(discord.ui.View):
    def __init__(self, challenger_id: int, opponent_id: int, timeout: float = 90):
        super().__init__(timeout=timeout)
        self.challenger_id = challenger_id
        self.opponent_id = opponent_id
        self.challenger_ok = False
        self.opponent_ok = False

    async def _maybe_done(self, interaction: discord.Interaction):
        if self.challenger_ok and self.opponent_ok:
            self.stop()
            await interaction.response.edit_message(view=None)
        else:
            await interaction.response.defer()

    @discord.ui.button(label="Challenger: Confirm", style=discord.ButtonStyle.primary)
    async def challenger(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.challenger_id:
            return await interaction.response.send_message("You’re not the challenger.", ephemeral=True)
        if not self.challenger_ok:
            self.challenger_ok = True
            button.label = "Challenger: ✅"
            button.disabled = True
            await interaction.message.edit(view=self)
        await self._maybe_done(interaction)

    @discord.ui.button(label="Opponent: Confirm", style=discord.ButtonStyle.success)
    async def opponent(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.opponent_id:
            return await interaction.response.send_message("You’re not the opponent.", ephemeral=True)
        if not self.opponent_ok:
            self.opponent_ok = True
            button.label = "Opponent: ✅"
            button.disabled = True
            await interaction.message.edit(view=self)
        await self._maybe_done(interaction)

# ========= Cog =========
class DuelRoyale(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def narrate(self, followup: discord.Webhook, lines: list[str]):
        for line in lines:
            await followup.send(line, allowed_mentions=discord.AllowedMentions.none())
            await asyncio.sleep(ROUND_DELAY)

    # ---- shared duel engine (used by /duel and /duelbet) ----
    async def _run_duel(self, interaction: discord.Interaction, author: discord.Member, opponent: discord.Member):
        await interaction.followup.send(f"⚔️ **Duel begins!** {author.display_name} vs {opponent.display_name}")
        names = {author.id: author.display_name, opponent.id: opponent.display_name}
        hp = {author.id: START_HP, opponent.id: START_HP}
        next_multiplier = {}
        await self.narrate(interaction.followup, [f"Both fighters start at {START_HP} HP."])

        attacker, defender = author.id, opponent.id
        round_no = 1
        while hp[attacker] > 0 and hp[defender] > 0:
            act = pick_action()
            header = f"__Round {round_no}__ — **{names[attacker]}** uses {act['name']}!"

            if act['kind'] == 'exodia':
                embed = discord.Embed(
                    title="💀 EXODIA OBLITERATE!!! 💀",
                    description=f"{names[attacker]} unleashes the forbidden one!",
                    color=discord.Color.dark_red()
                )
                embed.set_image(url=EXODIA_IMAGE_URL)
                await interaction.followup.send(embed=embed)
                hp[defender] = max(0, hp[defender] - EXODIA_DAMAGE)
                body = f"It deals **{EXODIA_DAMAGE}** damage!"
            elif act['kind'] == 'ultra_buff':
                next_multiplier[attacker] = float(act['amount'])
                body = f"{names[attacker]} is blessed with **{act['name']}**! Next move ×{act['amount']:.0f}!"
            elif act['kind'] == 'buff':
                if act['success']:
                    next_multiplier[attacker] = float(act['amount'])
                    body = f"{names[attacker]}'s next move is empowered ×**{act['amount']:.2f}**!"
                else:
                    body = f"{names[attacker]}'s attempt to power up **fails**."
            elif act['kind'] == 'heal':
                if act['success']:
                    heal_amount, consumed = apply_multiplier_if_any(next_multiplier, attacker, act['amount'])
                    hp[attacker] = min(START_HP, hp[attacker] + heal_amount)
                    suff = f" (buff ×{consumed:.2f})" if consumed else ""
                    extra = ""
                    if act.get('shared'):
                        splash = int(round(heal_amount * SHARED_HEAL["splash_ratio"]))
                        hp[defender] = min(START_HP, hp[defender] + splash)
                        extra = f" | {names[defender]} also heals **{splash} HP**."
                    body = f"Restores **{heal_amount} HP**{suff}.{extra}"
                else:
                    body = "…but the recovery **fails**!"
            else:
                if act['success']:
                    dmg, consumed = apply_multiplier_if_any(next_multiplier, attacker, act['amount'])
                    hp[defender] = max(0, hp[defender] - dmg)
                    suff = f" (buff ×{consumed:.2f})" if consumed else ""
                    body = f"Hit for **{dmg}** damage{suff}."
                else:
                    body = "…but it **misses**!"

            bars = f"HP — {names[author.id]}: **{hp[author.id]}** | {names[opponent.id]}: **{hp[opponent.id]}**"
            await self.narrate(interaction.followup, [header, body, bars])

            attacker, defender = defender, attacker
            round_no += 1

        winner_id = attacker if hp[attacker] > 0 else defender
        return author if winner_id == author.id else opponent

    # -------- /duel (public) --------
    @app_commands.command(name="duel", description="Start a 1v1 duel.")
    @app_commands.guilds(*GUILDS)
    @app_commands.describe(opponent="Who do you want to duel?")
    async def duel(self, interaction: discord.Interaction, opponent: discord.Member):
        author = interaction.user
        if opponent.bot or opponent.id == author.id:
            return await interaction.response.send_message("Pick a real opponent (not yourself or a bot).", ephemeral=True)
        await interaction.response.defer(thinking=False)
        winner = await self._run_duel(interaction, author, opponent)
        await interaction.followup.send(f"🏆 **{winner.display_name}** wins the duel!")

    # -------- /duelbet (public; loser prompted to /pay with :TC:) --------
    @app_commands.command(name="duelbet", description="Challenge a duel with a bet (loser pays winner after).")
    @app_commands.guilds(*GUILDS)
    @app_commands.describe(opponent="Who do you want to duel?", amount="Bet amount")
    async def duelbet(self, interaction: discord.Interaction, opponent: discord.Member, amount: int):
        author = interaction.user
        if amount <= 0:
            return await interaction.response.send_message("Bet amount must be positive.", ephemeral=True)
        if opponent.bot or opponent.id == author.id:
            return await interaction.response.send_message("Pick a real opponent (not yourself or a bot).", ephemeral=True)

        # Both players confirm
        view = BetAcceptView(challenger_id=author.id, opponent_id=opponent.id, timeout=90)
        content = (
            f"💰 **Bet Duel Requested**: {author.mention} vs {opponent.mention}\n"
            f"Proposed bet: **{amount}**\n\n"
            f"Both players must confirm within 90 seconds."
        )
        await interaction.response.send_message(content, view=view)
        msg = await interaction.original_response()
        await view.wait()
        if not (view.challenger_ok and view.opponent_ok):
            try:
                await msg.edit(content="❌ Bet duel cancelled (no confirmation).", view=None)
            except:
                pass
            return

        # Run the duel
        await interaction.followup.send("All set—running the duel!")
        winner = await self._run_duel(interaction, author, opponent)
        loser = opponent if winner.id == author.id else author

        # Build currency icon (custom <:TC:ID> if available, else literal :TC:)
        tc = get_tc_emoji(interaction.guild)

        # Prompt loser to pay winner using their economy bot
        pay_cmd = f"/pay {winner.mention} {amount}"
        embed = discord.Embed(
            title="Bet Result",
            description=(
                f"🏆 **Winner:** {winner.mention}\n"
                f"💰 {loser.mention}, please settle the bet of **{amount} {tc}**\n"
                f"```{pay_cmd}```\n"
                f"_Copy & send the `/pay` command with your economy bot._"
            ),
            color=discord.Color.gold()
        )
        await interaction.followup.send(embed=embed)

    # -------- /royale (public) --------
    @app_commands.command(name="royale", description="Start a multi-player battle royale.")
    @app_commands.guilds(*GUILDS)
    @app_commands.describe(
        player1="Optional player", player2="Optional player", player3="Optional player",
        player4="Optional player", player5="Optional player", player6="Optional player",
        player7="Optional player",
    )
    async def royale(
        self,
        interaction: discord.Interaction,
        player1: discord.Member | None = None,
        player2: discord.Member | None = None,
        player3: discord.Member | None = None,
        player4: discord.Member | None = None,
        player5: discord.Member | None = None,
        player6: discord.Member | None = None,
        player7: discord.Member | None = None,
    ):
        author = interaction.user
        candidates = [author, player1, player2, player3, player4, player5, player6, player7]
        roster: list[discord.Member] = []
        seen = set()

        for m in candidates:
            if m and not m.bot and m.id not in seen:
                seen.add(m.id)
                roster.append(m)

        if len(roster) < 2:
            return await interaction.response.send_message(
                "You need at least 2 human players. Add folks with the options (author auto-included).",
                ephemeral=True
            )

        await interaction.response.defer(thinking=False)
        followup = interaction.followup

        names = {m.id: m.display_name for m in roster}
        hp = {m.id: START_HP for m in roster}
        alive = [m.id for m in roster]
        next_multiplier = {}

        await self.narrate(followup, [
            f"👑 **Battle Royale begins!** ({len(roster)} players)",
            ", ".join(f"**{m.display_name}**" for m in roster),
            f"All start at {START_HP} HP. Last one standing wins!"
        ])

        round_no = 1
        while len(alive) > 1:
            await followup.send(f"— **Round {round_no}** —")
            random.shuffle(alive)

            for attacker in list(alive):
                if attacker not in alive:
                    continue

                targets = [pid for pid in alive if pid != attacker]
                if not targets:
                    break
                defender = random.choice(targets)

                act = pick_action()

                if act['kind'] == 'exodia':
                    embed = discord.Embed(
                        title="💀 EXODIA OBLITERATE!!! 💀",
                        description=f"**{names[attacker]}** unleashes the forbidden one on **{names[defender]}**!",
                        color=discord.Color.dark_red()
                    )
                    embed.set_image(url=EXODIA_IMAGE_URL)
                    await followup.send(embed=embed)
                    hp[defender] = max(0, hp[defender] - EXODIA_DAMAGE)
                    l1 = f"{names[attacker]} uses {act['name']}!"
                    l2 = f"It deals **{EXODIA_DAMAGE}** damage!"
                    l3 = f"{names[defender]} HP: **{hp[defender]}**"

                elif act['kind'] == 'ultra_buff':
                    next_multiplier[attacker] = float(act['amount'])
                    l1 = f"{names[attacker]} is blessed with **{act['name']}**!"
                    l2 = f"Next move ×{act['amount']:.0f}."
                    l3 = f"{names[attacker]} HP: **{hp[attacker]}**"

                elif act['kind'] == 'buff':
                    if act['success']:
                        next_multiplier[attacker] = float(act['amount'])
                        l1 = f"{names[attacker]} enters {act['name']}!"
                        l2 = f"Their next move is empowered ×**{act['amount']:.2f}**."
                    else:
                        l1 = f"{names[attacker]} attempts {act['name']}…"
                        l2 = "but it **fails**."
                    l3 = f"{names[attacker]} HP: **{hp[attacker]}**"

                elif act['kind'] == 'heal':
                    if act['success']:
                        heal, consumed = apply_multiplier_if_any(next_multiplier, attacker, act['amount'])
                        hp[attacker] = min(START_HP, hp[attacker] + heal)
                        if act.get('shared'):
                            splash = int(round(heal * SHARED_HEAL["splash_ratio"]))
                            for pid in alive:
                                if pid != attacker:
                                    hp[pid] = min(START_HP, hp[pid] + splash)
                            l1 = f"{names[attacker]} {act['name']}!"
                            l2 = f"Restores **{heal} HP** to self"
                            if consumed:
                                l2 += f" (buff ×{consumed:.2f})"
                            l2 += f" and **{splash} HP** to everyone else!"
                        else:
                            l1 = f"{names[attacker]} {act['name']}!"
                            l2 = f"Restores **{heal} HP**" + (f" (buff ×{consumed:.2f})" if consumed else "") + "."
                        l3 = f"{names[attacker]} HP: **{hp[attacker]}**"
                    else:
                        l1 = f"{names[attacker]} tries to {act['name']}…"
                        l2 = "but it **fails**."
                        l3 = f"{names[attacker]} HP: **{hp[attacker]}**"

                else:
                    if act['success']:
                        dmg, consumed = apply_multiplier_if_any(next_multiplier, attacker, act['amount'])
                        hp[defender] = max(0, hp[defender] - dmg)
                        l1 = f"{names[attacker]} uses {act['name']} on {names[defender]}!"
                        l2 = f"It hits for **{dmg}**!" + (f" (buff ×{consumed:.2f})" if consumed else "")
                    else:
                        l1 = f"{names[attacker]} uses {act['name']} on {names[defender]}!"
                        l2 = "It **misses**!"
                    l3 = f"{names[defender]} HP: **{hp[defender]}**"

                await self.narrate(followup, [l1, l2, l3])

                if hp[defender] <= 0 and defender in alive:
                    alive.remove(defender)
                    await followup.send(f"💀 **{names[defender]}** has been eliminated! ({len(alive)} remaining)")
                await asyncio.sleep(ROUND_DELAY)

            round_no += 1

        winner_id = alive[0]
        await followup.send(f"🏆 **{names[winner_id]}** wins the Royale!")

async def setup(bot: commands.Bot):
    await bot.add_cog(DuelRoyale(bot))
