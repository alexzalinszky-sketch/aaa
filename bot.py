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

def create_raid_embed(guild, reason, muted_count=0):
    embed = discord.Embed(title="RAID VÉDELEM AKTIVÁLVA", color=0x800080)
    embed.description = "```diff\n- GYANÚS ESEMÉNY DETEKTÁLVA\n```"
    embed.add_field(name="▶ Szerver", value=f"`{guild.name}`", inline=True)
    embed.add_field(name="▶ Kiváltó ok", value=f"`{reason}`", inline=True)
    embed.add_field(name="▶ Némított tagok", value=f"`{muted_count} fő`", inline=True)
    embed.add_field(name="▶ Némítás időtartama", value="`30 perc`", inline=False)
    embed.add_field(name="▶ Lejárat", value="`5 perc múlva automatikusan kikapcsol.`", inline=False)
    embed.set_footer(text=f"Licenced by Astra Studio • ma {datetime.datetime.now().strftime('%H:%M')}-kor")
    return embed

async def check_action(guild, user_id, action_type, reason, count=0):
    if not user_id or user_id == bot.user.id: return
    now = datetime.datetime.now()
    tracker[action_type][user_id].append(now)
    tracker[action_type][user_id] = [t for t in tracker[action_type][user_id] if (now - t).seconds < 60]
    
    if len(tracker[action_type][user_id]) > 3:
        member = guild.get_member(user_id)
        if member:
            try: await member.timeout(datetime.timedelta(minutes=30), reason=f"Anti-Nuke: {reason}")
            except: pass
        try:
            everyone = guild.default_role
            for channel in guild.channels:
                if isinstance(channel, (discord.TextChannel, discord.VoiceChannel)):
                    await channel.set_permissions(everyone, send_messages=False, speak=False)
        except: pass
        log_channel = bot.get_channel(LOG_CHANNEL_ID)
        if log_channel: await log_channel.send(embed=create_raid_embed(guild, reason, count))
        return True
    return False

# --- I. CSATORNA ÉS SZÁL MŰVELETEK ---
@bot.event
async def on_guild_channel_create(c): await check_action(c.guild, (await c.guild.audit_logs(limit=1, action=discord.AuditLogAction.channel_create).flatten())[0].user.id, "ch_c", "Csatorna létrehozás")
@bot.event
async def on_guild_channel_delete(c): await check_action(c.guild, (await c.guild.audit_logs(limit=1, action=discord.AuditLogAction.channel_delete).flatten())[0].user.id, "ch_d", "Csatorna törlés")
@bot.event
async def on_guild_channel_update(b, a): await check_action(a.guild, (await a.guild.audit_logs(limit=1, action=discord.AuditLogAction.channel_update).flatten())[0].user.id, "ch_u", "Csatorna módosítás")
@bot.event
async def on_thread_create(t): await check_action(t.guild, (await t.guild.audit_logs(limit=1, action=discord.AuditLogAction.thread_create).flatten())[0].user.id, "th_c", "Szál létrehozás")
@bot.event
async def on_thread_delete(t): await check_action(t.guild, (await t.guild.audit_logs(limit=1, action=discord.AuditLogAction.thread_delete).flatten())[0].user.id, "th_d", "Szál törlés")

# --- II. SZERVER ÉS RANG MŰVELETEK ---
@bot.event
async def on_guild_update(b, a): await check_action(a, (await a.audit_logs(limit=1, action=discord.AuditLogAction.guild_update).flatten())[0].user.id, "gu_u", "Szerver módosítás")
@bot.event
async def on_guild_role_create(r): await check_action(r.guild, (await r.guild.audit_logs(limit=1, action=discord.AuditLogAction.role_create).flatten())[0].user.id, "rl_c", "Rang létrehozás")
@bot.event
async def on_guild_role_delete(r): await check_action(r.guild, (await r.guild.audit_logs(limit=1, action=discord.AuditLogAction.role_delete).flatten())[0].user.id, "rl_d", "Rang törlés")
@bot.event
async def on_guild_role_update(b, a): await check_action(a.guild, (await a.guild.audit_logs(limit=1, action=discord.AuditLogAction.role_update).flatten())[0].user.id, "rl_u", "Rang módosítás")

# --- III. FELHASZNÁLÓI ÉS BOT MŰVELETEK ---
@bot.event
async def on_member_kick(m): await check_action(m.guild, (await m.guild.audit_logs(limit=1, action=discord.AuditLogAction.kick).flatten())[0].user.id, "kick", "Tag kirúgás")
@bot.event
async def on_member_ban(g, u): await check_action(g, (await g.audit_logs(limit=1, action=discord.AuditLogAction.ban).flatten())[0].user.id, "ban", "Tag kitiltás")
@bot.event
async def on_member_join(m): 
    if m.bot: await check_action(m.guild, (await m.guild.audit_logs(limit=1, action=discord.AuditLogAction.bot_add).flatten())[0].user.id, "bot", "Bot behívás", 1)

# --- WEBHOOK ÉS ESEMÉNY MŰVELETEK ---
@bot.event
async def on_webhooks_update(c): 
    # Mivel ez egy általános esemény, külön szűrjük a logokat a pontos műveletre
    async for entry in c.guild.audit_logs(limit=1):
        if entry.action in [discord.AuditLogAction.webhook_create, discord.AuditLogAction.webhook_delete, discord.AuditLogAction.webhook_update]:
            await check_action(c.guild, entry.user.id, "web", f"Webhook {entry.action.name} esemény")

@bot.event
async def on_scheduled_event_create(e): await check_action(e.guild, (await e.guild.audit_logs(limit=1, action=discord.AuditLogAction.scheduled_event_create).flatten())[0].user.id, "evt", "Esemény létrehozás")

@bot.command()
@commands.has_permissions(administrator=True)
async def unlock(ctx):
    everyone = ctx.guild.default_role
    for channel in ctx.guild.channels:
        await channel.set_permissions(everyone, send_messages=None, speak=None)
    await ctx.send("✅ Astra Security: Szerver feloldva.")

bot.run(TOKEN)
