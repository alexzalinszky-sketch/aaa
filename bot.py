import discord
from discord.ext import commands
import datetime
import asyncio
import os
from collections import defaultdict

# --- CONFIG ---
# A TOKEN-t a Render "Environment" fülön állítsd be DISCORD_TOKEN néven
TOKEN = os.getenv("DISCORD_TOKEN")
LOG_CHANNEL_ID = int(os.getenv("LOG_CHANNEL_ID", 0))

# --- INTENTS & BOT ---
intents = discord.Intents.default()
intents.members = True
intents.guilds = True
intents.message_content = True
intents.moderation = True

bot = commands.Bot(command_prefix="!", intents=intents)

# --- MEMÓRIA (Számlálók) ---
actions = defaultdict(lambda: defaultdict(list))

# --- EMBED GENERÁLÓ ---
def create_raid_embed(guild, reason, muted_count=0):
    embed = discord.Embed(title="RAID VÉDELEM AKTIVÁLVA", color=0x800080) # Lila szín
    embed.description = "```diff\n- GYANÚS ESEMÉNY DETEKTÁLVA\n```"
    embed.add_field(name="▶ Szerver", value=f"`{guild.name}`", inline=True)
    embed.add_field(name="▶ Kiváltó ok", value=f"`{reason}`", inline=True)
    embed.add_field(name="▶ Némított tagok", value=f"`{muted_count} fő`", inline=True)
    embed.add_field(name="▶ Némítás időtartama", value="`30 perc`", inline=False)
    embed.add_field(name="▶ Lejárat", value="`5 perc múlva automatikusan kikapcsol.`", inline=False)
    embed.set_footer(text=f"Licenced by Astra Studio • ma {datetime.datetime.now().strftime('%H:%M')}-kor")
    return embed

# --- VÉDELMI LOGIKA ---
async def punish(guild, member, reason):
    try:
        await member.ban(reason=reason)
    except: pass
    
    log_channel = bot.get_channel(LOG_CHANNEL_ID)
    if log_channel:
        await log_channel.send(embed=create_raid_embed(guild, reason))

@bot.event
async def on_ready():
    # FIX: DND állapot és Streaming státusz
    activity = discord.Streaming(name="Astra Studio - Security", url="https://www.twitch.tv/twitch")
    await bot.change_presence(status=discord.Status.dnd, activity=activity)
    print(f"✅ Astra Studio aktív (DND mód) - {bot.user}")

@bot.event
async def on_member_ban(guild, user):
    async for entry in guild.audit_logs(limit=1, action=discord.AuditLogAction.ban):
        if entry.target.id == user.id and not entry.user.bot:
            actions["ban"][entry.user.id].append(datetime.datetime.now())
            if len(actions["ban"][entry.user.id]) >= 3:
                await punish(guild, entry.user, "Tömeges ban (0/3)")

@bot.event
async def on_guild_channel_create(channel):
    async for entry in channel.guild.audit_logs(limit=1, action=discord.AuditLogAction.channel_create):
        if not entry.user.bot:
            actions["chan"][entry.user.id].append(datetime.datetime.now())
            if len(actions["chan"][entry.user.id]) >= 3:
                await channel.delete()
                await punish(channel.guild, entry.user, "Tömeges csatorna létrehozás")

@bot.event
async def on_member_join(member):
    if member.bot:
        async for entry in member.guild.audit_logs(limit=1, action=discord.AuditLogAction.bot_add):
            await member.kick()
            await punish(member.guild, entry.user, "Bot behívása")

@bot.event
async def on_message(message):
    if "@everyone" in message.content or "@here" in message.content:
        if not message.author.guild_permissions.administrator:
            await message.delete()
    await bot.process_commands(message)

if __name__ == "__main__":
    bot.run(TOKEN)
