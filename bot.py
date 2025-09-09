# bot.py — Discord ↔ Google Sheets bot + loads duel_royale cog (commands.Bot version)

import os
import json
import asyncio
from datetime import datetime

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

import gspread
from google.oauth2.service_account import Credentials

# ----------------- ENV -----------------
load_dotenv()

DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
SPREADSHEET_ID = os.getenv("GOOGLE_SPREADSHEET_ID")              # the /d/<THIS>/edit ID
WORKSHEET_NAME = os.getenv("GOOGLE_WORKSHEET_NAME", "Sheet1")     # tab name
SA_JSON_INLINE = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON_INLINE")   # preferred on Railway
SA_JSON_PATH = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON_PATH")       # optional alternative

def _guild_ids_from_env() -> list[int]:
    raw = (os.getenv("GUILD_IDS") or "").strip()
    return [int(x) for x in raw.split(",") if x.strip().isdigit()]

DEFAULT_GUILD_IDS = [1181834816631623761]  # <-- replace with YOUR server ID if not using env
GUILD_IDS: list[int] = _guild_ids_from_env() or DEFAULT_GUILD_IDS
GUILDS = [discord.Object(id=g) for g in GUILD_IDS]

# ----------------- Google Sheets -----------------
def make_gspread_client() -> gspread.Client:
    if SA_JSON_INLINE:
        info = json.loads(SA_JSON_INLINE)
        creds = Credentials.from_service_account_info(
            info,
            scopes=["https://www.googleapis.com/auth/spreadsheets"],
        )
    elif SA_JSON_PATH and os.path.exists(SA_JSON_PATH):
        creds = Credentials.from_service_account_file(
            SA_JSON_PATH,
            scopes=["https://www.googleapis.com/auth/spreadsheets"],
        )
    else:
        raise RuntimeError(
            "Provide Google creds via GOOGLE_SERVICE_ACCOUNT_JSON_INLINE "
            "or GOOGLE_SERVICE_ACCOUNT_JSON_PATH."
        )
    return gspread.authorize(creds)

gc = make_gspread_client()
sh = gc.open_by_key(SPREADSHEET_ID)
ws = sh.worksheet(WORKSHEET_NAME)

# ----------------- Discord setup (commands.Bot) -----------------
intents = discord.Intents.default()
intents.guilds = True
# If you can't enable the privileged intent in Dev Portal, set this to False:
intents.members = True  # requires toggling “Server Members Intent” in Developer Portal → Bot tab

bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)
tree = bot.tree  # convenience alias

write_lock = asyncio.Lock()

# ----------------- Helpers -----------------
def safe_append_row(values: list[str]) -> None:
    ws.append_row(values, value_input_option="USER_ENTERED")

def safe_set_cell(a1: str, value: str) -> None:
    ws.update_acell(a1, value)

def parse_row_str(s: str) -> list[str]:
    return [c.strip() for c in (s.split("\t") if "\t" in s else s.split(","))]

# ----------------- Ready → sync to guild(s) -----------------
@bot.event
async def on_ready():
    try:
        print("Registered commands in code:", [c.name for c in tree.get_commands()])
        total = 0
        for g in GUILDS:
            synced = await tree.sync(guild=g)
            print(f"Synced {len(synced)} commands to guild {g.id}")
            total += len(synced)
        print(f"Logged in as {bot.user} (ID: {bot.user.id})")
    except Exception as e:
        print("Command sync failed:", e)

# ----------------- Core commands -----------------
@tree.command(name="status", description="Check bot ↔ Sheets connectivity.")
@app_commands.guilds(*GUILDS)
async def status_cmd(interaction: discord.Interaction):
    try:
        _ = ws.title
        await interaction.response.send_message("✅ Online and connected to Sheets.", ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(f"❌ {e}", ephemeral=True)

@tree.command(name="ping", description="Test command")
@app_commands.guilds(*GUILDS)
async def ping_cmd(interaction: discord.Interaction):
    await interaction.response.send_message("Pong!", ephemeral=True)

@tree.command(name="append", description="Append a full row to the sheet.")
@app_commands.guilds(*GUILDS)
@app_commands.describe(row="Comma or tab separated values")
async def append_cmd(interaction: discord.Interaction, row: str):
    await interaction.response.defer(ephemeral=True)
    values = parse_row_str(row)
    async with write_lock:
        try:
            await asyncio.to_thread(safe_append_row, values)
            await interaction.followup.send(f"✅ Appended {len(values)} value(s).", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ {e}", ephemeral=True)

@tree.command(name="setcell", description="Write a value to a specific cell (A1).")
@app_commands.guilds(*GUILDS)
@app_commands.describe(cell='Cell like "A1"', value="Text or number")
async def setcell_cmd(interaction: discord.Interaction, cell: str, value: str):
    await interaction.response.defer(ephemeral=True)
    async with write_lock:
        try:
            await asyncio.to_thread(safe_set_cell, cell, value)
            await interaction.followup.send(f"✅ Set {cell} = {value}", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ {e}", ephemeral=True)

# ----------------- Admin logging commands -----------------
@tree.command(name="loguser", description="(Admins) Log a category for a server member")
@app_commands.default_permissions(administrator=True)
@app_commands.guilds(*GUILDS)
@app_commands.describe(member="Pick the server member to log",
                       category="Category to log (e.g., Audition, Landscaping)")
async def loguser(interaction: discord.Interaction, member: discord.Member, category: str):
    await interaction.response.defer(ephemeral=True)
    date_str = datetime.now().strftime("%m/%d/%Y")
    values = [date_str, member.display_name, category]
    async with write_lock:
        try:
            await asyncio.to_thread(safe_append_row, values)
            await interaction.followup.send(
                f"✅ Logged **{member.display_name}** → **{category}**", ephemeral=True
            )
        except Exception as e:
            await interaction.followup.send(f"❌ {e}", ephemeral=True)

@tree.command(name="loguser_text", description="(Admins) Log a category for a name you type")
@app_commands.default_permissions(administrator=True)
@app_commands.guilds(*GUILDS)
@app_commands.describe(username="Name to record (free text)", category="Category to log")
async def loguser_text(interaction: discord.Interaction, username: str, category: str):
    await interaction.response.defer(ephemeral=True)
    date_str = datetime.now().strftime("%m/%d/%Y")
    values = [date_str, username, category]
    async with write_lock:
        try:
            await asyncio.to_thread(safe_append_row, values)
            await interaction.followup.send(
                f"✅ Logged **{username}** → **{category}**", ephemeral=True
            )
        except Exception as e:
            await interaction.followup.send(f"❌ {e}", ephemeral=True)

# ----------------- Run (async; load the duel_royale extension) -----------------
async def _main():
    # Load your duel/royale cog before starting the bot
    try:
        await bot.load_extension("duel_royale")  # file: duel_royale.py in same folder
        print("Loaded duel_royale cog ✅")
    except Exception as e:
        print(f"Failed to load duel_royale cog: {e}")

    await bot.start(DISCORD_BOT_TOKEN)

if __name__ == "__main__":
    if not DISCORD_BOT_TOKEN:
        raise RuntimeError("Missing DISCORD_BOT_TOKEN.")
    asyncio.run(_main())
