import discord
from discord import app_commands
from discord.ext import commands
import datetime
import asyncio
import json
import os
from dotenv import load_dotenv
load_dotenv()
# ==========================================
#               BEÁLLÍTÁSOK
# ==========================================
TOKEN = os.getenv("DISCORD_TOKEN")
WHITELIST_IDS = []
PUNISH_ROLE_ID = 0   # <-- IDE ÍRD A BÜNTETŐ RANGOD ID-JÁT!
LOG_CHANNEL_ID = 1518687968917979206                # <-- Ide írhatsz egy csatorna ID-t, ha a tulaj DM-je mellett csatornára is akarsz logot

SETTINGS_FILE = "antinuke_settings.json"

DANGEROUS_PERMS = [
    "administrator", "manage_guild", "manage_roles", "manage_channels",
    "manage_webhooks", "kick_members", "ban_members", "mention_everyone",
    "manage_emojis_and_stickers", "manage_events", "moderate_members"
]

# ==========================================
#          PERZISZTENCIA (mentés/betöltés)
# ==========================================

def load_settings():
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "whitelist": WHITELIST_IDS,
        "punish_role_id": PUNISH_ROLE_ID,
        "log_channel_id": LOG_CHANNEL_ID,
        "trusted_bots": [],
        "sensitivity": {}
    }

def save_settings(bot):
    data = {
        "whitelist": list(bot.whitelist_ids),
        "punish_role_id": bot.punish_role_id,
        "log_channel_id": bot.log_channel_id,
        "trusted_bots": list(bot.trusted_bots),
        "sensitivity": bot.sensitivity
    }
    try:
        with open(SETTINGS_FILE, "w") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print(f"Beállítások mentése sikertelen: {e}")


class UltimateAntiNuke(commands.Bot):
    def __init__(self):
        intents = discord.Intents.all()
        super().__init__(command_prefix="!", intents=intents)

        cfg = load_settings()
        self.antinuke_status = True
        self.whitelist_ids = set(cfg.get("whitelist", WHITELIST_IDS))
        self.punish_role_id = cfg.get("punish_role_id", PUNISH_ROLE_ID)
        self.log_channel_id = cfg.get("log_channel_id", LOG_CHANNEL_ID)
        self.trusted_bots = set(cfg.get("trusted_bots", []))
        self.sensitivity = cfg.get("sensitivity", {})

        self.action_cooldowns = {}      # Mass-akciók követése
        self.quarantined_users = set()  # Manuálisan/automatán karanténba tett tagok
        self.lockdown_active = False
        self.role_backup = {}           # guild_id -> [role adatok] (gyors visszaállításhoz)

    async def setup_hook(self):
        await self.tree.sync()
        print("Minden fejlett védelmi parancs szinkronizálva!")


bot = UltimateAntiNuke()

# ==========================================
#          SEGÉDFÜGGVÉNYEK (CORE)
# ==========================================

async def get_latest_audit_user(guild, actions, target_id=None, limit=5):
    """Több audit-log akciótípus közül megkeresi a legutóbbi végrehajtót (opcionálisan egy adott célponthoz kötve)."""
    try:
        async for entry in guild.audit_logs(limit=limit):
            if entry.action in actions:
                if target_id is not None:
                    if getattr(entry.target, "id", None) != target_id:
                        continue
                return entry
    except Exception:
        return None
    return None


async def punish_user(guild, user, reason):
    """Megfosztja a felhasználót az összes rangjától, és csak a büntető rangot hagyja rajta."""
    if user is None:
        return False
    if user.id in bot.whitelist_ids or user.id == guild.owner_id or user.id == bot.user.id:
        return False

    try:
        bot.quarantined_users.add(user.id)
        punish_role = guild.get_role(bot.punish_role_id)
        if punish_role:
            await user.edit(roles=[punish_role], reason=f"Anti-Nuke Karantén: {reason}")
        else:
            await user.edit(roles=[], reason=f"Anti-Nuke: Nincs büntető rang, minden jog megvonva: {reason}")
        return True
    except Exception as e:
        print(f"Hiba a büntetés során ({getattr(user, 'name', user)}): {e}")
        return False


async def unpunish_user(guild, user, restore_roles=None):
    """Manuális karantén-feloldás."""
    try:
        bot.quarantined_users.discard(user.id)
        if restore_roles:
            await user.edit(roles=restore_roles, reason="Anti-Nuke: Karantén feloldva")
        else:
            await user.edit(roles=[], reason="Anti-Nuke: Karantén feloldva")
        return True
    except Exception as e:
        print(f"Hiba a feloldás során: {e}")
        return False


async def send_nuke_alert(guild, event_name, trigger_reason, punished_user=None):
    """Nova Guard stílusú riasztási Embed generálása + DM + log csatorna."""
    embed = discord.Embed(
        title="RAID VÉDELEM AKTIVÁLVA",
        description="```diff\n- GYANÚS ESEMÉNY DETEKTÁLVA\n```",
        color=discord.Color.from_rgb(47, 49, 54),
        timestamp=datetime.datetime.now(datetime.timezone.utc)
    )
    embed.add_field(name="► Szerver", value=f"`{guild.name}`", inline=True)
    embed.add_field(name="► Esemény", value=f"`{event_name}`", inline=True)
    embed.add_field(name="► Kiváltó ok", value=f"`{trigger_reason}`", inline=False)

    nemitett = f"{punished_user.mention} (Jogok megvonva + Karantén)" if punished_user else "0 fő"
    embed.add_field(name="► Büntetett tagok", value=nemitett, inline=True)
    embed.add_field(name="► Némítás", value="`Végleges (Kézi feloldásig)`", inline=True)
    embed.set_footer(text="Licenced by Nova Studio • ma")

    if guild.owner:
        try:
            await guild.owner.send(embed=embed)
        except Exception:
            pass

    if bot.log_channel_id:
        channel = guild.get_channel(bot.log_channel_id)
        if channel:
            try:
                await channel.send(embed=embed)
            except Exception:
                pass


def check_mass_action(user_id, action_type, limit=2, seconds=10):
    """Rate-limit figyelő: megnézi, hogy a felhasználó többször végzett-e el egy akciót X másodperc alatt."""
    sens = bot.sensitivity.get(action_type, {})
    limit = sens.get("limit", limit)
    seconds = sens.get("seconds", seconds)

    now = datetime.datetime.now(datetime.timezone.utc)
    key = f"{user_id}_{action_type}"
    if key not in bot.action_cooldowns:
        bot.action_cooldowns[key] = []

    bot.action_cooldowns[key].append(now)
    recent = [t for t in bot.action_cooldowns[key] if (now - t).total_seconds() < seconds]
    bot.action_cooldowns[key] = recent
    return len(recent) >= limit


def is_dangerous_perms_grant(before_perms, after_perms):
    """Megnézi, hogy egy permission-változás veszélyes jogot ad-e hozzá, ami korábban nem volt ott."""
    return any(
        getattr(after_perms, perm, False) and not getattr(before_perms, perm, False)
        for perm in DANGEROUS_PERMS
    )


# ==========================================
#     AUTOMATA VÉDELMI FUNKCIÓK (1-42)
# ==========================================

# --- CSATORNA & SZÁL VÉDELEM (1-9) ---

@bot.event
async def on_guild_channel_delete(channel):  # 1. Csatorna törlés
    if not bot.antinuke_status:
        return
    guild = channel.guild
    entry = await get_latest_audit_user(guild, [discord.AuditLogAction.channel_delete])
    if entry and entry.user.id not in bot.whitelist_ids and entry.user.id != bot.user.id:
        if await punish_user(guild, entry.user, "Csatorna törlése"):
            try:
                await channel.clone(reason="Anti-Nuke visszaállítás")
            except Exception:
                pass
            await send_nuke_alert(guild, "Csatorna Törlés", "Tömeges csatorna_törlés esemény", entry.user)


@bot.event
async def on_guild_channel_create(channel):  # 2. Tömeges csatorna létrehozás (spam)
    if not bot.antinuke_status:
        return
    guild = channel.guild
    entry = await get_latest_audit_user(guild, [discord.AuditLogAction.channel_create])
    if entry and entry.user.id not in bot.whitelist_ids and entry.user.id != bot.user.id:
        if check_mass_action(entry.user.id, "channel_create", limit=3, seconds=10):
            if await punish_user(guild, entry.user, "Tömeges csatorna készítés (Spam)"):
                try:
                    await channel.delete(reason="Anti-Nuke takarítás")
                except Exception:
                    pass
                await send_nuke_alert(guild, "Csatorna Készítés Spam", "Tömeges csatorna_létrehozás esemény", entry.user)


@bot.event
async def on_guild_channel_update(before, after):  # 3. Csatorna alapadat szabotázs + 4. veszélyes overwrite
    if not bot.antinuke_status:
        return
    guild = before.guild

    # 3. Alapadat módosítás (név, topic, nsfw, slowmode, kategória)
    basic_changed = (
        before.name != after.name or
        getattr(before, "topic", None) != getattr(after, "topic", None) or
        getattr(before, "nsfw", None) != getattr(after, "nsfw", None) or
        getattr(before, "slowmode_delay", None) != getattr(after, "slowmode_delay", None) or
        before.category != after.category
    )

    # 4. Veszélyes engedély (@everyone vagy bármely rang admin/manage_* jogot kap a csatornán)
    dangerous_overwrite = False
    for target, perms in after.overwrites.items():
        old_perms = before.overwrites.get(target)
        allow, deny = perms.pair()
        if old_perms:
            old_allow, _ = old_perms.pair()
        else:
            old_allow = discord.Permissions.none()
        if any(getattr(allow, p, False) and not getattr(old_allow, p, False) for p in
               ["manage_channels", "manage_roles", "manage_webhooks", "administrator"]):
            dangerous_overwrite = True
            break

    if basic_changed or dangerous_overwrite:
        actions = [discord.AuditLogAction.channel_update, discord.AuditLogAction.overwrite_update,
                   discord.AuditLogAction.overwrite_create]
        entry = await get_latest_audit_user(guild, actions)
        if entry and entry.user.id not in bot.whitelist_ids and entry.user.id != bot.user.id:
            reason = "Veszélyes csatorna jogosultság módosítás" if dangerous_overwrite else "Csatorna engedélyek / adatok módosítása"
            if await punish_user(guild, entry.user, reason):
                try:
                    await after.edit(
                        name=before.name, topic=getattr(before, "topic", None),
                        nsfw=getattr(before, "nsfw", False),
                        slowmode_delay=getattr(before, "slowmode_delay", 0),
                        category=before.category,
                        overwrites=before.overwrites
                    )
                except Exception:
                    pass
                await send_nuke_alert(guild, "Csatorna Módosítás", reason, entry.user)


@bot.event
async def on_thread_create(thread):  # 5. Tömeges szál létrehozás (spam)
    if not bot.antinuke_status:
        return
    guild = thread.guild
    entry = await get_latest_audit_user(guild, [discord.AuditLogAction.thread_create])
    if entry and entry.user.id not in bot.whitelist_ids and entry.user.id != bot.user.id:
        if check_mass_action(entry.user.id, "thread_create", limit=5, seconds=10):
            if await punish_user(guild, entry.user, "Tömeges szál létrehozás (Spam)"):
                try:
                    await thread.delete()
                except Exception:
                    pass
                await send_nuke_alert(guild, "Szál Spam", "Tömeges szál_létrehozás esemény", entry.user)


@bot.event
async def on_thread_delete(thread):  # 6. Tömeges szál/fórum törlés
    if not bot.antinuke_status:
        return
    guild = thread.guild
    entry = await get_latest_audit_user(guild, [discord.AuditLogAction.thread_delete])
    if entry and entry.user.id not in bot.whitelist_ids and entry.user.id != bot.user.id:
        if check_mass_action(entry.user.id, "thread_delete", limit=3, seconds=10):
            await punish_user(guild, entry.user, "Tömeges fórum/szál törlés")
            await send_nuke_alert(guild, "Szál Törlés", "Tömeges szál_törlés esemény", entry.user)


@bot.event
async def on_thread_update(before, after):  # 7. Szál archiválás/zárolás trükközés
    if not bot.antinuke_status:
        return
    guild = before.guild
    if before.name != after.name or before.archived != after.archived or before.locked != after.locked:
        entry = await get_latest_audit_user(guild, [discord.AuditLogAction.thread_update])
        if entry and entry.user.id not in bot.whitelist_ids and entry.user.id != bot.user.id:
            if check_mass_action(entry.user.id, "thread_update", limit=4, seconds=10):
                await punish_user(guild, entry.user, "Tömeges szál szabotázs (archiválás/zárolás)")
                await send_nuke_alert(guild, "Szál Szabotázs", "Szálak tömeges manipulálása", entry.user)


@bot.event
async def on_raw_bulk_message_delete(payload):  # 8. Tömeges üzenettörlés (purge raid)
    if not bot.antinuke_status:
        return
    guild = bot.get_guild(payload.guild_id) if payload.guild_id else None
    if not guild:
        return
    entry = await get_latest_audit_user(guild, [discord.AuditLogAction.message_bulk_delete])
    if entry and entry.user.id not in bot.whitelist_ids and entry.user.id != bot.user.id:
        if len(payload.message_ids) >= 20:
            await punish_user(guild, entry.user, "Tömeges üzenettörlés (Purge Raid)")
            await send_nuke_alert(guild, "Üzenet Purge", f"{len(payload.message_ids)} üzenet törölve egyszerre", entry.user)


@bot.event
async def on_message_delete(message):  # 9. Gyors egyenkénti üzenettörlés-sorozat (mod abuse)
    if not bot.antinuke_status or message.guild is None:
        return
    guild = message.guild
    entry = await get_latest_audit_user(guild, [discord.AuditLogAction.message_delete], target_id=message.author.id)
    if entry and entry.user.id not in bot.whitelist_ids and entry.user.id != bot.user.id and entry.user.id != message.author.id:
        if check_mass_action(entry.user.id, "message_delete", limit=15, seconds=10):
            await punish_user(guild, entry.user, "Üzenettörlési sorozat (gyanús moderálás)")
            await send_nuke_alert(guild, "Üzenettörlési Sorozat", "Gyors, sorozatos üzenettörlés más tagjaitól", entry.user)


# --- RANG & JOGOSULTSÁG VÉDELEM (10-18) ---

@bot.event
async def on_guild_role_delete(role):  # 10. Rang törlése
    if not bot.antinuke_status:
        return
    guild = role.guild
    entry = await get_latest_audit_user(guild, [discord.AuditLogAction.role_delete])
    if entry and entry.user.id not in bot.whitelist_ids and entry.user.id != bot.user.id:
        if await punish_user(guild, entry.user, "Rang törlése"):
            try:
                await guild.create_role(
                    name=role.name, permissions=role.permissions,
                    color=role.color, hoist=role.hoist, mentionable=role.mentionable
                )
            except Exception:
                pass
            await send_nuke_alert(guild, "Rang Törlés", "Tömeges rang_törlés esemény", entry.user)


@bot.event
async def on_guild_role_create(role):  # 11. Tömeges rang létrehozás (spam)
    if not bot.antinuke_status:
        return
    guild = role.guild
    entry = await get_latest_audit_user(guild, [discord.AuditLogAction.role_create])
    if entry and entry.user.id not in bot.whitelist_ids and entry.user.id != bot.user.id:
        if check_mass_action(entry.user.id, "role_create", limit=2, seconds=10):
            if await punish_user(guild, entry.user, "Tömeges rang létrehozás (Spam)"):
                try:
                    await role.delete(reason="Anti-Nuke takarítás")
                except Exception:
                    pass
                await send_nuke_alert(guild, "Rang Készítés Spam", "Tömeges rang_létrehozás esemény", entry.user)


@bot.event
async def on_guild_role_update(before, after):  # 12. Veszélyes jog osztás + 13. név/szín szabotázs + 14. @everyone tampering + 15. hierarchia csempészés
    if not bot.antinuke_status:
        return
    guild = before.guild

    violation_perms = is_dangerous_perms_grant(before.permissions, after.permissions)
    violation_name = before.name != after.name
    violation_everyone = before.is_default() and (before.permissions != after.permissions)
    violation_position = after.position - before.position > 3  # gyanúsan nagy hierarchia-ugrás

    if violation_perms or violation_name or violation_everyone or violation_position:
        entry = await get_latest_audit_user(guild, [discord.AuditLogAction.role_update])
        if entry and entry.user.id not in bot.whitelist_ids and entry.user.id != bot.user.id:
            reason = "@everyone jogok szabotázsa" if violation_everyone else (
                "Veszélyes rangjog kiosztás" if violation_perms else (
                    "Rang hierarchia csempészés" if violation_position else "Rangnév/szín módosítás"))
            if await punish_user(guild, entry.user, reason):
                try:
                    await after.edit(permissions=before.permissions, name=before.name, color=before.color)
                except Exception:
                    pass
                await send_nuke_alert(guild, "Rang Szabotázs", reason, entry.user)


@bot.event
async def on_member_update(before, after):  # 16. Veszélyes rang osztás tagnak + 17. tömeges nickname deface + 18. mass timeout abuse
    if not bot.antinuke_status:
        return
    guild = before.guild

    # 16. Meglévő tag veszélyes ranggal lát el (privilege escalation)
    new_roles = [r for r in after.roles if r not in before.roles]
    dangerous_role_added = any(is_dangerous_perms_grant(discord.Permissions.none(), r.permissions) for r in new_roles)
    if dangerous_role_added:
        entry = await get_latest_audit_user(guild, [discord.AuditLogAction.member_role_update], target_id=after.id)
        if entry and entry.user.id not in bot.whitelist_ids and entry.user.id != bot.user.id:
            if await punish_user(guild, entry.user, "Veszélyes rang osztása másik tagnak"):
                try:
                    await after.edit(roles=before.roles, reason="Anti-Nuke visszaállítás")
                except Exception:
                    pass
                await send_nuke_alert(guild, "Jogosultság-átruházás", "Privilege escalation kísérlet", entry.user)

    # 17. Tömeges nickname deface
    if before.nick != after.nick:
        entry = await get_latest_audit_user(guild, [discord.AuditLogAction.member_update], target_id=after.id)
        if entry and entry.user.id not in bot.whitelist_ids and entry.user.id != bot.user.id and entry.user.id != after.id:
            if check_mass_action(entry.user.id, "nick_change", limit=5, seconds=10):
                await punish_user(guild, entry.user, "Tömeges nickname deface")
                await send_nuke_alert(guild, "Nickname Deface", "Tagok nevének tömeges átírása", entry.user)

    # 18. Tömeges némítás/timeout abuse
    if before.timed_out_until != after.timed_out_until and after.timed_out_until:
        entry = await get_latest_audit_user(guild, [discord.AuditLogAction.member_update], target_id=after.id)
        if entry and entry.user.id not in bot.whitelist_ids and entry.user.id != bot.user.id:
            if check_mass_action(entry.user.id, "timeout", limit=4, seconds=15):
                await punish_user(guild, entry.user, "Tömeges timeout / némítás visszaélés")
                await send_nuke_alert(guild, "Timeout Visszaélés", "Tagok tömeges elnémítása", entry.user)


@bot.event
async def on_app_command_permissions_update(permissions):  # 19. Integrációs parancsjogok kockázatos módosítása
    if not bot.antinuke_status:
        return
    guild = permissions.guild
    entry = await get_latest_audit_user(guild, [discord.AuditLogAction.app_command_permission_update])
    if entry and entry.user.id not in bot.whitelist_ids and entry.user.id != bot.user.id:
        await punish_user(guild, entry.user, "Parancs-integráció jogainak kockázatos módosítása")
        await send_nuke_alert(guild, "Integráció Szabotázs", "Slash command jogosultságok manipulálása", entry.user)


@bot.event
async def on_automod_rule_update(rule):  # 20. Auto-Mod szabály gyengítése
    if not bot.antinuke_status:
        return
    guild = rule.guild
    entry = await get_latest_audit_user(guild, [discord.AuditLogAction.automod_rule_update])
    if entry and entry.user.id not in bot.whitelist_ids and entry.user.id != bot.user.id:
        await punish_user(guild, entry.user, "Auto-Mod szabály gyengítése/szabotálása")
        await send_nuke_alert(guild, "AutoMod Szabotázs", "Védelmi szabály illetéktelen módosítása", entry.user)


# --- TAG, MODERÁCIÓ ÉS MEGHÍVÓ VÉDELEM (21-32) ---

@bot.event
async def on_member_remove(member):  # 21. Tömeges kick (Mass Kick)
    if not bot.antinuke_status:
        return
    guild = member.guild
    entry = await get_latest_audit_user(guild, [discord.AuditLogAction.kick], target_id=member.id)
    if entry and entry.user.id not in bot.whitelist_ids and entry.user.id != bot.user.id:
        if check_mass_action(entry.user.id, "kick", limit=2, seconds=10):
            await punish_user(guild, entry.user, "Tömeges tag-eltávolítás (Mass Kick)")
            await send_nuke_alert(guild, "Mass Kick", "Tömeges tag_eltávolítás esemény", entry.user)


@bot.event
async def on_member_ban(guild, user_banned):  # 22. Tömeges ban + auto-unban
    if not bot.antinuke_status:
        return
    entry = await get_latest_audit_user(guild, [discord.AuditLogAction.ban], target_id=user_banned.id)
    if entry and entry.user.id not in bot.whitelist_ids and entry.user.id != bot.user.id:
        if check_mass_action(entry.user.id, "ban", limit=2, seconds=10):
            if await punish_user(guild, entry.user, "Tömeges kitiltás (Mass Ban)"):
                try:
                    await guild.unban(user_banned, reason="Anti-Nuke automatikus visszahívás")
                except Exception:
                    pass
                await send_nuke_alert(guild, "Mass Ban", "Tömeges kitiltás esemény", entry.user)


@bot.event
async def on_member_unban(guild, user_unbanned):  # 23. Illetéktelen unban (kitiltottak visszahozása)
    if not bot.antinuke_status:
        return
    entry = await get_latest_audit_user(guild, [discord.AuditLogAction.unban], target_id=user_unbanned.id)
    if entry and entry.user.id not in bot.whitelist_ids and entry.user.id != bot.user.id:
        if check_mass_action(entry.user.id, "unban", limit=2, seconds=10):
            await punish_user(guild, entry.user, "Tömeges/illetéktelen unban visszaélés")
            await send_nuke_alert(guild, "Unban Visszaélés", "Kitiltott felhasználók tömeges visszahozása", entry.user)


async def watch_member_prune(guild, before_count):  # 24. Tömeges prune (segédfunkció, parancsból hívható)
    entry = await get_latest_audit_user(guild, [discord.AuditLogAction.kick])
    if entry and entry.user.id not in bot.whitelist_ids:
        await punish_user(guild, entry.user, "Tömeges prune (inaktív tagok lemészárlása)")
        await send_nuke_alert(guild, "Mass Prune", "Tömeges automatikus tagtisztítás", entry.user)


@bot.event
async def on_voice_state_update(before, after):  # 25. Tömeges hangcsatorna kirúgás + 26. tömeges áthelyezés
    if not bot.antinuke_status:
        return
    member = after if hasattr(after, "channel") else before
    guild = member.guild if hasattr(member, "guild") else None
    if guild is None:
        return

    if before.channel and not after.channel:  # kirúgva a csatornából
        entry = await get_latest_audit_user(guild, [discord.AuditLogAction.member_disconnect])
        if entry and entry.user.id not in bot.whitelist_ids and entry.user.id != bot.user.id:
            if check_mass_action(entry.user.id, "voice_disconnect", limit=4, seconds=10):
                await punish_user(guild, entry.user, "Tömeges hangcsatorna-kirúgás")
                await send_nuke_alert(guild, "Voice Kick Raid", "Tagok tömeges kidobása hangcsatornákból", entry.user)

    elif before.channel != after.channel and before.channel and after.channel:  # áthelyezve
        entry = await get_latest_audit_user(guild, [discord.AuditLogAction.member_move])
        if entry and entry.user.id not in bot.whitelist_ids and entry.user.id != bot.user.id:
            if check_mass_action(entry.user.id, "voice_move", limit=4, seconds=10):
                await punish_user(guild, entry.user, "Tömeges hangcsatorna áthelyezés")
                await send_nuke_alert(guild, "Voice Move Raid", "Tagok tömeges áthelyezése hangcsatornák között", entry.user)


@bot.event
async def on_invite_delete(invite):  # 27. Tömeges meghívó törlés
    if not bot.antinuke_status:
        return
    guild = invite.guild
    entry = await get_latest_audit_user(guild, [discord.AuditLogAction.invite_delete])
    if entry and entry.user.id not in bot.whitelist_ids and entry.user.id != bot.user.id:
        if check_mass_action(entry.user.id, "invite_delete", limit=3, seconds=10):
            await punish_user(guild, entry.user, "Meghívók tömeges megsemmisítése")
            await send_nuke_alert(guild, "Meghívó Szabotázs", "Szerver elszigetelési kísérlet meghívók törlésével", entry.user)


@bot.event
async def on_invite_create(invite):  # 28. Gyanús, korlátlan meghívó tömeges generálása (raid-becsalogatás)
    if not bot.antinuke_status:
        return
    guild = invite.guild
    entry = await get_latest_audit_user(guild, [discord.AuditLogAction.invite_create])
    if entry and entry.user.id not in bot.whitelist_ids and entry.user.id != bot.user.id:
        if invite.max_age == 0 and (invite.max_uses == 0 or invite.max_uses is None):
            if check_mass_action(entry.user.id, "invite_create_unlimited", limit=2, seconds=10):
                if await punish_user(guild, entry.user, "Tömeges, korlátlan meghívó generálás (raid előkészület)"):
                    try:
                        await invite.delete()
                    except Exception:
                        pass
                    await send_nuke_alert(guild, "Meghívó Spam", "Korlátlan meghívók tömeges generálása", entry.user)


@bot.event
async def on_guild_update(before, after):  # 29. Szerver alapadat szabotázs + 30. verification level csökkentés + 31. community/widget szabotázs
    if not bot.antinuke_status:
        return
    guild = before

    verification_lowered = after.verification_level.value < before.verification_level.value
    basic_changed = (
        before.name != after.name or before.icon != after.icon or
        getattr(before, "vanity_url_code", None) != getattr(after, "vanity_url_code", None)
    )
    community_changed = (
        getattr(before, "rules_channel", None) != getattr(after, "rules_channel", None) or
        getattr(before, "public_updates_channel", None) != getattr(after, "public_updates_channel", None)
    )
    widget_changed = getattr(before, "widget_enabled", None) != getattr(after, "widget_enabled", None)

    if verification_lowered or basic_changed or community_changed or widget_changed:
        entry = await get_latest_audit_user(guild, [discord.AuditLogAction.guild_update])
        if entry and entry.user.id not in bot.whitelist_ids and entry.user.id != bot.user.id:
            reason = ("Biztonsági szint (verification level) csökkentése" if verification_lowered else
                      "Community beállítások szabotázsa" if community_changed else
                      "Widget engedélyezés módosítása" if widget_changed else
                      "Szerver alapbeállítások átírása")
            if await punish_user(guild, entry.user, reason):
                try:
                    await after.edit(
                        name=before.name, icon=before.icon,
                        verification_level=before.verification_level
                    )
                except Exception:
                    pass
                await send_nuke_alert(guild, "Szerver Módosítás", reason, entry.user)


@bot.event
async def on_member_join(member):  # 32. Illetéktelen bot meghívása
    if not bot.antinuke_status:
        return
    guild = member.guild

    if member.bot and member.id not in bot.trusted_bots:
        entry = await get_latest_audit_user(guild, [discord.AuditLogAction.bot_add], target_id=member.id)
        if entry:
            inviter = entry.user
            if inviter.id not in bot.whitelist_ids and inviter.id != guild.owner_id:
                try:
                    await member.kick(reason="Illetéktelen kártékony bot.")
                except Exception:
                    pass
                await punish_user(guild, inviter, "Kártékony külső bot meghívása")
                await send_nuke_alert(guild, "Malicious Bot Bejutás", "Illetéktelen bot integráció észlelve", inviter)


# --- INTEGRÁCIÓK, WEBHOOK, AUTOMOD, EMOJI, ESEMÉNY VÉDELEM (33-42) ---

@bot.event
async def on_webhooks_update(channel):  # 33. Webhook spam + 34. webhook átirányítás (phishing) + 35. webhook törlés
    if not bot.antinuke_status:
        return
    guild = channel.guild
    entry = await get_latest_audit_user(
        guild,
        [discord.AuditLogAction.webhook_create, discord.AuditLogAction.webhook_update, discord.AuditLogAction.webhook_delete]
    )
    if entry and entry.user.id not in bot.whitelist_ids and entry.user.id != bot.user.id:
        if entry.action == discord.AuditLogAction.webhook_create:
            if check_mass_action(entry.user.id, "webhook_create", limit=2, seconds=10):
                await punish_user(guild, entry.user, "Webhook spam észlelve")
                await send_nuke_alert(guild, "Webhook Raid", "Tömeges webhook_készítés esemény", entry.user)
        elif entry.action == discord.AuditLogAction.webhook_update:
            await punish_user(guild, entry.user, "Webhook átirányítás (phishing kísérlet)")
            await send_nuke_alert(guild, "Webhook Phishing", "Webhook URL/csatorna átirányítás", entry.user)
        elif entry.action == discord.AuditLogAction.webhook_delete:
            if check_mass_action(entry.user.id, "webhook_delete", limit=2, seconds=10):
                await punish_user(guild, entry.user, "Webhookok tömeges törlése")
                await send_nuke_alert(guild, "Webhook Törlés", "Legitim webhookok tömeges eltávolítása", entry.user)


@bot.event
async def on_guild_integrations_update(guild):  # 36. Integráció (OAuth/app) eltávolítása vagy módosítása
    if not bot.antinuke_status:
        return
    entry = await get_latest_audit_user(
        guild, [discord.AuditLogAction.integration_delete, discord.AuditLogAction.integration_update]
    )
    if entry and entry.user.id not in bot.whitelist_ids and entry.user.id != bot.user.id:
        await punish_user(guild, entry.user, "Integráció kockázatos módosítása/eltávolítása")
        await send_nuke_alert(guild, "Integráció Szabotázs", "OAuth/app integráció manipulálása", entry.user)


@bot.event
async def on_automod_rule_create(rule):  # 37. Auto-Mod szabály manipuláció (kártékony szabály bevezetése)
    if not bot.antinuke_status:
        return
    guild = rule.guild
    entry = await get_latest_audit_user(guild, [discord.AuditLogAction.automod_rule_create])
    if entry and entry.user.id not in bot.whitelist_ids and entry.user.id != bot.user.id:
        if await punish_user(guild, entry.user, "Auto-Mod szabály manipuláció"):
            try:
                await rule.delete()
            except Exception:
                pass
            await send_nuke_alert(guild, "AutoMod Szabotázs", "Illetéktelen AutoMod szabály generálás", entry.user)


@bot.event
async def on_guild_emojis_update(guild, before, after):  # 38. Tömeges emoji törlés + 39. tömeges emoji spam
    if not bot.antinuke_status:
        return
    if len(after) < len(before):
        entry = await get_latest_audit_user(guild, [discord.AuditLogAction.emoji_delete])
        if entry and entry.user.id not in bot.whitelist_ids and entry.user.id != bot.user.id:
            if check_mass_action(entry.user.id, "emoji_delete", limit=4, seconds=10):
                await punish_user(guild, entry.user, "Tömeges Emoji törlés")
                await send_nuke_alert(guild, "Emoji Szabotázs", "Szerver hangulatjelek tömeges törlése", entry.user)
    elif len(after) > len(before):
        entry = await get_latest_audit_user(guild, [discord.AuditLogAction.emoji_create])
        if entry and entry.user.id not in bot.whitelist_ids and entry.user.id != bot.user.id:
            if check_mass_action(entry.user.id, "emoji_create", limit=6, seconds=10):
                await punish_user(guild, entry.user, "Tömeges Emoji spam (slot feltöltés)")
                await send_nuke_alert(guild, "Emoji Spam", "Emoji helyek tömeges feltöltése", entry.user)


@bot.event
async def on_guild_stickers_update(guild, before, after):  # 40. Tömeges matrica törlés + spam
    if not bot.antinuke_status:
        return
    if len(after) < len(before):
        entry = await get_latest_audit_user(guild, [discord.AuditLogAction.sticker_delete])
        if entry and entry.user.id not in bot.whitelist_ids and entry.user.id != bot.user.id:
            if check_mass_action(entry.user.id, "sticker_delete", limit=4, seconds=10):
                await punish_user(guild, entry.user, "Tömeges matrica törlés")
                await send_nuke_alert(guild, "Matrica Szabotázs", "Szerver matricáinak tömeges törlése", entry.user)
    elif len(after) > len(before):
        entry = await get_latest_audit_user(guild, [discord.AuditLogAction.sticker_create])
        if entry and entry.user.id not in bot.whitelist_ids and entry.user.id != bot.user.id:
            if check_mass_action(entry.user.id, "sticker_create", limit=6, seconds=10):
                await punish_user(guild, entry.user, "Tömeges matrica spam")
                await send_nuke_alert(guild, "Matrica Spam", "Matrica helyek tömeges feltöltése", entry.user)


@bot.event
async def on_guild_scheduled_event_delete(event):  # 41. Tömeges esemény törlés
    if not bot.antinuke_status:
        return
    guild = event.guild
    entry = await get_latest_audit_user(guild, [discord.AuditLogAction.scheduled_event_delete])
    if entry and entry.user.id not in bot.whitelist_ids and entry.user.id != bot.user.id:
        if check_mass_action(entry.user.id, "event_delete", limit=3, seconds=10):
            await punish_user(guild, entry.user, "Események szétbarmolása")
            await send_nuke_alert(guild, "Esemény Törlés", "Ütemezett szerveresemények tömeges törlése", entry.user)


@bot.event
async def on_stage_instance_delete(stage_instance):  # 42. Stage szabotázs (élő közösségi esemény megszakítása)
    if not bot.antinuke_status:
        return
    guild = stage_instance.guild
    entry = await get_latest_audit_user(guild, [discord.AuditLogAction.stage_instance_delete])
    if entry and entry.user.id not in bot.whitelist_ids and entry.user.id != bot.user.id:
        if check_mass_action(entry.user.id, "stage_delete", limit=3, seconds=10):
            await punish_user(guild, entry.user, "Stage események tömeges megszakítása")
            await send_nuke_alert(guild, "Stage Szabotázs", "Élő közösségi színpad tömeges törlése", entry.user)


# ==========================================
#    KEZELŐ SLASH COMMANDOK (43-58)
# ==========================================

def is_authorized(interaction: discord.Interaction) -> bool:
    return interaction.user.id in bot.whitelist_ids or interaction.user.id == interaction.guild.owner_id


@bot.tree.command(name="antinuke", description="Az automata szervervédelem ki- és bekapcsolása.")  # 43
@app_commands.describe(beallitas="Válaszd ki a védelmi státuszt")
@app_commands.choices(beallitas=[
    app_commands.Choice(name="Bekapcsolás", value="be"),
    app_commands.Choice(name="Kikapcsolás", value="ki")
])
async def antinuke(interaction: discord.Interaction, beallitas: app_commands.Choice[str]):
    if not is_authorized(interaction):
        await interaction.response.send_message("❌ **Nincs jogosultságod** az Anti-Nuke rendszer kezeléséhez!", ephemeral=True)
        return

    if beallitas.value == "be":
        bot.antinuke_status = True
        embed = discord.Embed(
            title="🛡️ Anti-Nuke Rendszer",
            description="🟢 **A 58+ pontos fejlett automata háttérvédelem AKTIVÁLVA.**\nA bot teljesen önállóan üzemel, és azonnal karanténba helyezi a rombolókat.",
            color=discord.Color.green()
        )
    else:
        bot.antinuke_status = False
        embed = discord.Embed(
            title="⚠️ Anti-Nuke Rendszer",
            description="🔴 **A védelem KIKAPCSOLVA.**\nA bot kikapcsolt állapotban van, a szerver biztonsági szintje lecsökkent.",
            color=discord.Color.red()
        )
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="antinuke-status", description="Megnézi az Anti-Nuke rendszer jelenlegi állapotát és beállításait.")  # 44
async def antinuke_status(interaction: discord.Interaction):
    embed = discord.Embed(title="📊 Anti-Nuke Állapot", color=discord.Color.blurple())
    embed.add_field(name="Védelem", value="🟢 Bekapcsolva" if bot.antinuke_status else "🔴 Kikapcsolva", inline=True)
    embed.add_field(name="Lockdown", value="🔒 Aktív" if bot.lockdown_active else "🔓 Nincs", inline=True)
    embed.add_field(name="Whitelist tagok", value=str(len(bot.whitelist_ids)), inline=True)
    embed.add_field(name="Karanténban", value=str(len(bot.quarantined_users)), inline=True)
    role = interaction.guild.get_role(bot.punish_role_id)
    embed.add_field(name="Büntető rang", value=role.mention if role else "Nincs beállítva", inline=True)
    log_ch = interaction.guild.get_channel(bot.log_channel_id) if bot.log_channel_id else None
    embed.add_field(name="Log csatorna", value=log_ch.mention if log_ch else "Nincs beállítva", inline=True)
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="whitelist-add", description="Hozzáad egy felhasználót a védett (whitelist) listához.")  # 45
async def whitelist_add(interaction: discord.Interaction, tag: discord.Member):
    if not is_authorized(interaction):
        await interaction.response.send_message("❌ Nincs jogosultságod!", ephemeral=True)
        return
    bot.whitelist_ids.add(tag.id)
    save_settings(bot)
    await interaction.response.send_message(f"✅ {tag.mention} hozzáadva a whitelisthez.", ephemeral=True)


@bot.tree.command(name="whitelist-remove", description="Eltávolít egy felhasználót a whitelistből.")  # 46
async def whitelist_remove(interaction: discord.Interaction, tag: discord.Member):
    if not is_authorized(interaction):
        await interaction.response.send_message("❌ Nincs jogosultságod!", ephemeral=True)
        return
    bot.whitelist_ids.discard(tag.id)
    save_settings(bot)
    await interaction.response.send_message(f"✅ {tag.mention} eltávolítva a whitelistből.", ephemeral=True)


@bot.tree.command(name="whitelist-list", description="Kilistázza a whitelisten lévő tagokat.")  # 47
async def whitelist_list(interaction: discord.Interaction):
    members = [f"<@{uid}>" for uid in bot.whitelist_ids]
    await interaction.response.send_message(
        "**Whitelist tagok:**\n" + ("\n".join(members) if members else "Nincs feltöltve."), ephemeral=True
    )


@bot.tree.command(name="set-punish-role", description="Beállítja a karanténhoz használt büntető rangot.")  # 48
async def set_punish_role(interaction: discord.Interaction, rang: discord.Role):
    if not is_authorized(interaction):
        await interaction.response.send_message("❌ Nincs jogosultságod!", ephemeral=True)
        return
    bot.punish_role_id = rang.id
    save_settings(bot)
    await interaction.response.send_message(f"✅ Büntető rang beállítva: {rang.mention}", ephemeral=True)


@bot.tree.command(name="set-log-channel", description="Beállítja, melyik csatornára küldje a riasztásokat a bot.")  # 49
async def set_log_channel(interaction: discord.Interaction, csatorna: discord.TextChannel):
    if not is_authorized(interaction):
        await interaction.response.send_message("❌ Nincs jogosultságod!", ephemeral=True)
        return
    bot.log_channel_id = csatorna.id
    save_settings(bot)
    await interaction.response.send_message(f"✅ Log csatorna beállítva: {csatorna.mention}", ephemeral=True)


@bot.tree.command(name="quarantine", description="Manuálisan karanténba helyez egy felhasználót.")  # 50
async def quarantine(interaction: discord.Interaction, tag: discord.Member, ok: str = "Manuális karantén"):
    if not is_authorized(interaction):
        await interaction.response.send_message("❌ Nincs jogosultságod!", ephemeral=True)
        return
    success = await punish_user(interaction.guild, tag, ok)
    msg = f"✅ {tag.mention} karanténba helyezve." if success else f"⚠️ Nem sikerült karanténba tenni {tag.mention}-t (lehet whitelisten van)."
    await interaction.response.send_message(msg, ephemeral=True)


@bot.tree.command(name="unquarantine", description="Feloldja egy felhasználó karanténját.")  # 51
async def unquarantine(interaction: discord.Interaction, tag: discord.Member):
    if not is_authorized(interaction):
        await interaction.response.send_message("❌ Nincs jogosultságod!", ephemeral=True)
        return
    success = await unpunish_user(interaction.guild, tag)
    msg = f"✅ {tag.mention} karanténja feloldva." if success else "⚠️ Hiba történt a feloldás során."
    await interaction.response.send_message(msg, ephemeral=True)


@bot.tree.command(name="lockdown", description="Lezárja az összes szöveges csatornát az @everyone elől (vészhelyzet).")  # 52
async def lockdown(interaction: discord.Interaction):
    if not is_authorized(interaction):
        await interaction.response.send_message("❌ Nincs jogosultságod!", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    everyone = interaction.guild.default_role
    for ch in interaction.guild.text_channels:
        try:
            await ch.set_permissions(everyone, send_messages=False, reason="Anti-Nuke Lockdown")
        except Exception:
            pass
    bot.lockdown_active = True
    await interaction.followup.send("🔒 **Lockdown aktiválva.** Minden csatorna lezárva.", ephemeral=True)


@bot.tree.command(name="unlock", description="Feloldja a lockdownt, visszaadja az írási jogot mindenkinek.")  # 53
async def unlock(interaction: discord.Interaction):
    if not is_authorized(interaction):
        await interaction.response.send_message("❌ Nincs jogosultságod!", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    everyone = interaction.guild.default_role
    for ch in interaction.guild.text_channels:
        try:
            await ch.set_permissions(everyone, send_messages=None, reason="Anti-Nuke Lockdown feloldása")
        except Exception:
            pass
    bot.lockdown_active = False
    await interaction.followup.send("🔓 **Lockdown feloldva.**", ephemeral=True)


@bot.tree.command(name="panic", description="Kirúgja az összes nem megbízható, whitelisten nem lévő botot a szerverről.")  # 54
async def panic(interaction: discord.Interaction):
    if not is_authorized(interaction):
        await interaction.response.send_message("❌ Nincs jogosultságod!", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    kicked = 0
    for member in interaction.guild.members:
        if member.bot and member.id not in bot.whitelist_ids and member.id not in bot.trusted_bots and member.id != bot.user.id:
            try:
                await member.kick(reason="Anti-Nuke Panic Mode")
                kicked += 1
            except Exception:
                pass
    await interaction.followup.send(f"🚨 **Panic mód lefutott.** {kicked} nem megbízható bot eltávolítva.", ephemeral=True)


@bot.tree.command(name="trusted-bot-add", description="Megbízható botok listájához ad hozzá egyet (nem lesz kirúgva panic módban).")  # 55
async def trusted_bot_add(interaction: discord.Interaction, bot_tag: discord.Member):
    if not is_authorized(interaction):
        await interaction.response.send_message("❌ Nincs jogosultságod!", ephemeral=True)
        return
    bot.trusted_bots.add(bot_tag.id)
    save_settings(bot)
    await interaction.response.send_message(f"✅ {bot_tag.mention} megbízható botként megjelölve.", ephemeral=True)


@bot.tree.command(name="sensitivity", description="Beállítja egy védelmi funkció érzékenységét (hány akció hány másodperc alatt).")  # 56
async def sensitivity(interaction: discord.Interaction, funkcio: str, limit: int, masodperc: int):
    if not is_authorized(interaction):
        await interaction.response.send_message("❌ Nincs jogosultságod!", ephemeral=True)
        return
    bot.sensitivity[funkcio] = {"limit": limit, "seconds": masodperc}
    save_settings(bot)
    await interaction.response.send_message(
        f"✅ `{funkcio}` érzékenység beállítva: {limit} akció / {masodperc} mp.", ephemeral=True
    )


@bot.tree.command(name="role-backup", description="Elmenti a szerver jelenlegi rangstruktúráját gyors visszaállításhoz.")  # 57
async def role_backup_cmd(interaction: discord.Interaction):
    if not is_authorized(interaction):
        await interaction.response.send_message("❌ Nincs jogosultságod!", ephemeral=True)
        return
    backup = [
        {"name": r.name, "permissions": r.permissions.value, "color": r.color.value,
         "hoist": r.hoist, "mentionable": r.mentionable, "position": r.position}
        for r in interaction.guild.roles if not r.is_default()
    ]
    bot.role_backup[interaction.guild.id] = backup
    await interaction.response.send_message(f"✅ {len(backup)} rang elmentve biztonsági mentésbe.", ephemeral=True)


@bot.tree.command(name="role-restore", description="Visszaállítja a legutóbb elmentett rangstruktúrát (hiányzó rangokat újra létrehozza).")  # 58
async def role_restore_cmd(interaction: discord.Interaction):
    if not is_authorized(interaction):
        await interaction.response.send_message("❌ Nincs jogosultságod!", ephemeral=True)
        return
    backup = bot.role_backup.get(interaction.guild.id)
    if not backup:
        await interaction.response.send_message("⚠️ Nincs elmentett biztonsági mentés ehhez a szerverhez.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    existing_names = {r.name for r in interaction.guild.roles}
    restored = 0
    for r in backup:
        if r["name"] not in existing_names:
            try:
                await interaction.guild.create_role(
                    name=r["name"], permissions=discord.Permissions(r["permissions"]),
                    color=discord.Color(r["color"]), hoist=r["hoist"], mentionable=r["mentionable"]
                )
                restored += 1
            except Exception:
                pass
    await interaction.followup.send(f"✅ {restored} hiányzó rang visszaállítva a mentésből.", ephemeral=True)


# Elindítás
bot.run(TOKEN)
