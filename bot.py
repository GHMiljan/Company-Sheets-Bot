import os, json, asyncio
from datetime import datetime
import discord
from discord import app_commands
from dotenv import load_dotenv
import gspread
from google.oauth2.service_account import Credentials
from tenacity import retry, stop_after_attempt, wait_exponential

load_dotenv()
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
SPREADSHEET_ID = os.getenv("GOOGLE_SPREADSHEET_ID")
WORKSHEET_NAME = os.getenv("GOOGLE_WORKSHEET_NAME", "Sheet1")

SERVICE_JSON_PATH = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON_PATH")
SERVICE_JSON_INLINE = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON_INLINE")

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
if SERVICE_JSON_PATH:
    creds = Credentials.from_service_account_file(SERVICE_JSON_PATH, scopes=SCOPES)
elif SERVICE_JSON_INLINE:
    creds = Credentials.from_service_account_info(json.loads(SERVICE_JSON_INLINE), scopes=SCOPES)
else:
    raise RuntimeError("Provide Google creds via GOOGLE_SERVICE_ACCOUNT_JSON_PATH or GOOGLE_SERVICE_ACCOUNT_JSON_INLINE.")

gc = gspread.authorize(creds)
sh = gc.open_by_key(SPREADSHEET_ID)
ws = sh.worksheet(WORKSHEET_NAME)

write_lock = asyncio.Lock()

@retry(wait=wait_exponential(min=1, max=10), stop=stop_after_attempt(5))
def safe_append_row(values):
    ws.append_row(values, value_input_option="USER_ENTERED")

@retry(wait=wait_exponential(min=1, max=10), stop=stop_after_attempt(5))
def safe_update_acell(a1, value):
    ws.update_acell(a1, value)

intents = discord.Intents.default()
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

# Put your server ID here for instant slash commands (replace 123...):
GUILD_IDS = [1181834816631623761]   # <-- your real server ID (integer, no quotes)
GUILDS = [discord.Object(id=g) for g in GUILD_IDS]

@client.event
async def on_ready():
    try:
        print("Registered commands in code:",
              [c.name for c in tree.get_commands()])  # debug

        if GUILD_IDS:
            total = 0
            for g in GUILDS:
                synced = await tree.sync(guild=g)
                print(f"Synced {len(synced)} commands to guild {g.id}")
                total += len(synced)
        else:
            synced = await tree.sync()
            print(f"Synced {len(synced)} global commands")

        print(f"Logged in as {client.user} (ID: {client.user.id})")
    except Exception as e:
        print("Command sync failed:", e)
@tree.command(name="ping", description="Test command")
async def ping_cmd(interaction: discord.Interaction):
    await interaction.response.send_message("Pong!", ephemeral=True)
@tree.command(name="status", description="Check bot ↔ Sheets connectivity.")
@tree.command(name="ping", description="Test command")
@app_commands.guilds(*GUILDS)   # pin to your server for instant sync
async def ping_cmd(interaction: discord.Interaction):
    await interaction.response.send_message("Pong!", ephemeral=True)

async def status_cmd(interaction: discord.Interaction):
    try:
        _ = ws.title
        await interaction.response.send_message("✅ Online and connected to Sheets.", ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(f"⚠️ {e}", ephemeral=True)
# --- Admin-only: log a server member by mention/picker ---
@tree.command(name="loguser", description="(Admins) Log a category for a server member")
@app_commands.default_permissions(administrator=True)   # only admins can use
@app_commands.describe(member="Pick the server member to log",
                       category="Category to log (e.g., Audition, Landscaping)")
async def loguser(interaction: discord.Interaction, member: discord.Member, category: str):
    await interaction.response.defer(ephemeral=True)

    # Date as MM/DD/YYYY
    date_str = datetime.now().strftime("%m/%d/%Y")
    target_name = member.display_name  # or member.name if you prefer the username

    # Row: Date | User | Category
    values = [date_str, target_name, category]

    async with write_lock:
        try:
            await asyncio.to_thread(safe_append_row, values)
            await interaction.followup.send(f"✅ Logged **{target_name}** → **{category}**", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ Error: {e}", ephemeral=True)


# --- Admin-only: log any text name (for users not in the server / external) ---
@tree.command(name="loguser_text", description="(Admins) Log a category for a name you type")
@app_commands.default_permissions(administrator=True)
@app_commands.describe(username="Name to record (free text)", category="Category to log")
async def loguser_text(interaction: discord.Interaction, username: str, category: str):
    await interaction.response.defer(ephemeral=True)

    date_str = datetime.now().strftime("%m/%d/%Y")
    values = [date_str, username, category]

    async with write_lock:
        try:
            await asyncio.to_thread(safe_append_row, values)
            await interaction.followup.send(f"✅ Logged **{username}** → **{category}**", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ Error: {e}", ephemeral=True)

@tree.command(name="append", description="Append a full row to the sheet.")
@app_commands.describe(row='Comma or tab separated values')
async def append_cmd(interaction: discord.Interaction, row: str):
    await interaction.response.defer(ephemeral=True)
    values = [c.strip() for c in (row.split("\t") if "\t" in row else row.split(","))]
    async with write_lock:
        try:
            await asyncio.to_thread(safe_append_row, values)
            await interaction.followup.send(f"✅ Appended {len(values)} value(s).", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ {e}", ephemeral=True)

@tree.command(name="setcell", description="Write a value to a specific cell (A1).")
@app_commands.describe(cell='e.g., A1', value='Text or number')
async def setcell_cmd(interaction: discord.Interaction, cell: str, value: str):
    await interaction.response.defer(ephemeral=True)
    async with write_lock:
        try:
            await asyncio.to_thread(safe_update_acell, cell, value)
            await interaction.followup.send(f"✅ Set {cell} = {value}", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ {e}", ephemeral=True)

@tree.command(name="log", description="Append a timestamped key/value row.")
@app_commands.describe(key='Label', value='Value')
async def log_cmd(interaction: discord.Interaction, key: str, value: str):
    await interaction.response.defer(ephemeral=True)
    ts = datetime.utcnow().isoformat(timespec="seconds") + "Z"
    user = f"{interaction.user.name}#{interaction.user.discriminator}"
    values = [ts, user, key, value]
    async with write_lock:
        try:
            await asyncio.to_thread(safe_append_row, values)
            await interaction.followup.send(f"✅ Logged {key} → {value}", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ {e}", ephemeral=True)
# ----------------- Guild config -----------------
GUILD_IDS = [1181834816631623761]   # <-- your real server ID (int, no quotes)
GUILDS = [discord.Object(id=g) for g in GUILD_IDS]

# ----------------- Status (must be async) -----------------
@tree.command(name="status", description="Check bot ↔ Sheets connectivity.")
@app_commands.guilds(*GUILDS)
async def status_cmd(interaction: discord.Interaction):
    try:
        _ = ws.title
        await interaction.response.send_message("✅ Online and connected to Sheets.", ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(f"❌ {e}", ephemeral=True)

# ----------------- Ping test -----------------
@tree.command(name="ping", description="Test command")
@app_commands.guilds(*GUILDS)
async def ping_cmd(interaction: discord.Interaction):
    await interaction.response.send_message("Pong!", ephemeral=True)

# ----------------- Admin commands -----------------
@tree.command(name="loguser", description="(Admins) Log a category for a server member")
@app_commands.default_permissions(administrator=True)
@app_commands.guilds(*GUILDS)
@app_commands.describe(member="Pick the server member to log",
                       category="Category to log (e.g., Audition, Landscaping)")
async def loguser(interaction: discord.Interaction, member: discord.Member, category: str):
    await interaction.response.defer(ephemeral=True)
    date_str = datetime.now().strftime("%m/%d/%Y")
    target_name = member.display_name
    values = [date_str, target_name, category]
    async with write_lock:
        try:
            await asyncio.to_thread(safe_append_row, values)
            await interaction.followup.send(f"✅ Logged **{target_name}** → **{category}**", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ Error: {e}", ephemeral=True)

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
            await interaction.followup.send(f"✅ Logged **{username}** → **{category}**", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ Error: {e}", ephemeral=True)

# ----------------- Force guild sync on ready -----------------
@client.event
async def on_ready():
    try:
        print("Registered commands in code:", [c.name for c in tree.get_commands()])
        total = 0
        for g in GUILDS:
            synced = await tree.sync(guild=g)
            print(f"Synced {len(synced)} commands to guild {g.id}")
            total += len(synced)
        print(f"Logged in as {client.user} (ID: {client.user.id})")
    except Exception as e:
        print("Command sync failed:", e)
            
if __name__ == "__main__":
    if not DISCORD_BOT_TOKEN:
        raise RuntimeError("Missing DISCORD_BOT_TOKEN.")
    client.run(DISCORD_BOT_TOKEN)

