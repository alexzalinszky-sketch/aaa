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
    if not user_id or user_id == bot.user.id: return
    
    # Folyamatos logolás
    log_channel = bot.get_channel(LOG_CHANNEL_ID)
    member = guild.get_member(user_id)
    if log_channel and member:
        await log_channel.send(embed=create_live_log_embed(member, reason))

    # Védelmi logika
    now = datetime.datetime.now()
    tracker[action_type][user_id].append(now)
    tracker[action_type][user_id] = [t for t in tracker[action_type][user_id] if (now - t).seconds < 60]
    
    if len(tracker[action_type][user_id]) > 3:
        if member:
            try: await member.timeout(datetime.timedelta(minutes=30), reason=f"Anti-Nuke: {reason}")
            except: pass
        if log_channel: 
            await log_channel.send(embed=create_raid_embed(guild, reason, count))
        return True
    return False
async def check_action(guild, user_id, action_type, reason, count=0):
    if not user_id or user_id == bot.user.id: return
    
    # --- FOLYAMATOS LOGOLÁS (Minden eseménynél fut) ---
    log_channel = bot.get_channel(LOG_CHANNEL_ID)
    member = guild.get_member(user_id)
    if log_channel and member:
        await log_channel.send(embed=create_live_log_embed(member, reason))

    # --- VÉDELMI LOGIKA (Csak ha sok a gyanús esemény) ---
    now = datetime.datetime.now()
    tracker[action_type][user_id].append(now)
    tracker[action_type][user_id] = [t for t in tracker[action_type][user_id] if (now - t).seconds < 60]
    
    if len(tracker[action_type][user_id]) > 3:
        if member:
            try: await member.timeout(datetime.timedelta(minutes=30), reason=f"Anti-Nuke: {reason}")
            except: pass
        # Ha eléri a limitet, küldi a RAID embedet is
        if log_channel: 
            await log_channel.send(embed=create_raid_embed(guild, reason, count))
        return True
    return False

# --- ESEMÉNYKEZELŐK (JAVÍTVA) ---
@bot.event
async def on_guild_channel_create(c):
    entry = await get_audit_entry(c.guild, discord.AuditLogAction.channel_create)
    if entry: await check_action(c.guild, entry.user.id, "ch_c", "Csatorna létrehozás")

@bot.event
async def on_guild_channel_delete(c):
    entry = await get_audit_entry(c.guild, discord.AuditLogAction.channel_delete)
    if entry: await check_action(c.guild, entry.user.id, "ch_d", "Csatorna törlés")

@bot.event
async def on_guild_channel_update(b, a):
    entry = await get_audit_entry(a.guild, discord.AuditLogAction.channel_update)
    if entry: await check_action(a.guild, entry.user.id, "ch_u", "Csatorna módosítás")

@bot.event
async def on_guild_role_create(r):
    entry = await get_audit_entry(r.guild, discord.AuditLogAction.role_create)
    if entry: await check_action(r.guild, entry.user.id, "rl_c", "Rang létrehozás")

@bot.event
async def on_guild_role_delete(r):
    entry = await get_audit_entry(r.guild, discord.AuditLogAction.role_delete)
    if entry: await check_action(r.guild, entry.user.id, "rl_d", "Rang törlés")

@bot.event
async def on_member_ban(g, u):
    entry = await get_audit_entry(g, discord.AuditLogAction.ban)
    if entry: await check_action(g, entry.user.id, "ban", "Tag kitiltás")

@bot.event
async def on_webhooks_update(c):
    async for entry in c.guild.audit_logs(limit=1):
        if entry.action in [discord.AuditLogAction.webhook_create, discord.AuditLogAction.webhook_delete]:
            await check_action(c.guild, entry.user.id, "web", "Webhook módosítás")
            break

@bot.event
async def on_scheduled_event_create(e):
    entry = await get_audit_entry(e.guild, discord.AuditLogAction.scheduled_event_create)
    if entry: await check_action(e.guild, entry.user.id, "evt", "Esemény létrehozás")

@bot.command()
@commands.has_permissions(administrator=True)
async def unlock(ctx):
    await ctx.send("✅ Astra Security: Szerver feloldva.")
    
@bot.command()
async def teszt(ctx):
    """Parancs a logolás és a rendszer tesztelésére."""
    # Teszt embed küldése a log csatornába
    log_channel = bot.get_channel(LOG_CHANNEL_ID)
    if log_channel:
        embed = discord.Embed(
            title="🧪 Rendszer Teszt",
            description="A logoló rendszer sikeresen csatlakozott.",
            color=0x00AAFF
        )
        embed.set_footer(text=f"Tesztelve: {ctx.author.name}")
        await log_channel.send(embed=embed)
        await ctx.send("✅ Teszt üzenet elküldve a log csatornába!")
    else:
        await ctx.send("❌ Hiba: A log csatorna ID nem található vagy érvénytelen.")

bot.run(TOKEN)
