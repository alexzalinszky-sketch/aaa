import discord
from discord.ext import commands
import datetime
import os
import asyncio
from collections import defaultdict

TOKEN = os.getenv("DISCORD_TOKEN")
LOG_CHANNEL_ID = int(os.getenv("LOG_CHANNEL_ID", 0))

intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents)

tracker = defaultdict(lambda: defaultdict(list))

# Teszt loop állapota
test_loop_running = False


# --- SEGÉDFÜGGVÉNYEK ---

async def get_audit_entry(guild, action):
    async for entry in guild.audit_logs(limit=1, action=action):
        return entry
    return None


def create_raid_embed(guild, reason, muted_count=0):
    embed = discord.Embed(
        title="RAID VÉDELEM AKTIVÁLVA",
        color=0x800080
    )

    embed.description = "```diff\n- GYANÚS ESEMÉNY DETEKTÁLVA\n```"

    embed.add_field(
        name="▶ Szerver",
        value=f"`{guild.name}`",
        inline=True
    )

    embed.add_field(
        name="▶ Kiváltó ok",
        value=f"`{reason}`",
        inline=True
    )

    embed.add_field(
        name="▶ Némított tagok",
        value=f"`{muted_count} fő`",
        inline=True
    )

    embed.set_footer(
        text=f"Astra Security • {datetime.datetime.now().strftime('%H:%M')}"
    )

    return embed


def create_live_log_embed(user, action_name):
    embed = discord.Embed(
        title="🔔 ESEMÉNY DETEKTÁLVA",
        color=0x00FF00
    )

    embed.add_field(
        name="▶ Elkövető",
        value=f"{user.name} (`{user.id}`)",
        inline=True
    )

    embed.add_field(
        name="▶ Művelet",
        value=f"`{action_name}`",
        inline=True
    )

    embed.set_footer(
        text=f"Astra Security • {datetime.datetime.now().strftime('%H:%M:%S')}"
    )

    return embed


async def check_action(guild, user_id, action_type, reason, count=0):
    log_channel = bot.get_channel(LOG_CHANNEL_ID)

    if not log_channel:
        return False

    member = guild.get_member(user_id) if user_id else None

    # Normál log
    if member:
        await log_channel.send(
            embed=create_live_log_embed(member, reason)
        )

    # Raid embed
    await log_channel.send(
        embed=create_raid_embed(
            guild,
            f"🚨 TESZT NUKE DETEKTÁLVA • {reason}",
            0
        )
    )

    return True


# --------------------
# ESEMÉNYEK
# --------------------

@bot.event
async def on_ready():
    print(f"✅ Bejelentkezve: {bot.user}")


# --------------------
# PARANCSOK
# --------------------

@bot.command()
@commands.has_permissions(administrator=True)
async def test(ctx):
    global test_loop_running

    if test_loop_running:
        await ctx.send("⚠️ A teszt már fut.")
        return

    test_loop_running = True
    await ctx.send("▶️ Folyamatos teszt elindítva.")

    while test_loop_running:
        try:
            await check_action(
                ctx.guild,
                ctx.author.id,
                "test",
                "Manuális teszt"
            )

            await asyncio.sleep(4)

        except Exception as e:
            print(f"Hiba: {e}")
            await asyncio.sleep(5)


@bot.command()
@commands.has_permissions(administrator=True)
async def stop(ctx):
    global test_loop_running

    test_loop_running = False
    await ctx.send("⏹️ Teszt leállítva.")


@test.error
async def test_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ Ehhez admin jogosultság kell.")


@stop.error
async def stop_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ Ehhez admin jogosultság kell.")


bot.run(TOKEN)
