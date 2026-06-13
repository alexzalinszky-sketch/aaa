import discord
from discord.ext import commands
import datetime
import os
from collections import defaultdict

TOKEN = os.getenv("DISCORD_TOKEN")
LOG_CHANNEL_ID = int(os.getenv("LOG_CHANNEL_ID", 0))

intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents)

tracker = defaultdict(lambda: defaultdict(list))

# --- SEGÉDFÜGGVÉNYEK ---
async def get_audit_entry(guild, action):
    async for entry in guild.audit_logs(limit=1, action=action):
        return entry
    return None

def create_raid_embed(guild, reason, muted_count=0):
    embed = discord.Embed(title="RAID VÉDELEM AKTIVÁLVA", color=0x800080)
    embed.description = "```diff\n- GYANÚS ESEMÉNY DETEKTÁLVA\n```"
    embed.add_field(name="▶ Szerver", value=f"`{guild.name}`", inline=True)
    embed.add_field(name="▶ Kiváltó ok", value=f"`{reason}`", inline=True)
    embed.add_field(name="▶ Némított tagok", value=f"`{muted_count} fő`", inline=True)
    embed.set_footer(text=f"Astra Security • {datetime.datetime.now().strftime('%H:%M')}")
    return embed

# EZ A FÜGGVÉNY HIÁNYZOTT A KÓDODBÓL!
def create_live_log_embed(user, action_name):
    embed = discord.Embed(title="🔔 ESEMÉNY DETEKTÁLVA", color=0x00FF00)
    embed.add_field(name="▶ Elkövető", value=f"{user.name} (`{user.id}`)", inline=True)
    embed.add_field(name="▶ Művelet", value=f"`{action_name}`", inline=True)
    embed.set_footer(text=f"Astra Security • {datetime.datetime.now().strftime('%H:%M:%S')}")
    return embed

async def check_action(guild, user_id, action_type, reason, count=0):
    if not user_id or user_id == bot.user.id:
        return

    log_channel = bot.get_channel(LOG_CHANNEL_ID)
    member = guild.get_member(user_id)

    # Esemény log
    if log_channel and member:
        await log_channel.send(
            embed=create_live_log_embed(member, reason)
        )

    # TESZT MÓD
    if log_channel:
        await log_channel.send(
            embed=create_raid_embed(guild, f"TESZT • {reason}", 0)
        )

    return True

bot.run(TOKEN)
