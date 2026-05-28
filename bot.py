"""
bot.py — Засварын бүртгэлийн Discord Bot v3

Команд:
  /shipment  — Салбараас засварт явуулах багц бүртгэх  → SHP-XXXX
  /received  — Засварын газар хүлээж авсан тэмдэглэх
  /fix       — Тухайн REP засварлаж дуусгах           → Fixed tab руу шилжинэ
  /status    — SHP эсвэл REP статус шалгах
"""

import discord
from discord import app_commands
import os
from dotenv import load_dotenv
from sheets import SheetsClient

load_dotenv(dotenv_path=r"D:\project\discord bot\fix-report-bot\.env")

DISCORD_TOKEN = os.environ["DISCORD_TOKEN"]
CHANNEL_NAME  = os.environ.get("REPAIR_CHANNEL_NAME", "repairs")

intents = discord.Intents.default()
intents.message_content = True


class RepairBot(discord.Client):
    def __init__(self):
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)
        self.sheets = SheetsClient()

    async def setup_hook(self):
        pass


client = RepairBot()


def check_channel(interaction: discord.Interaction) -> bool:
    return interaction.channel.name == CHANNEL_NAME


def _parse_items(raw: str) -> list[dict]:
    """'1 mouse, 2 keyboard, 10 чихэвч' → [{"qty":1,"item":"mouse"}, ...]"""
    import re
    results = []
    for part in raw.split(","):
        m = re.match(r"^\s*(\d+)\s+(.+?)\s*$", part.strip())
        if m:
            results.append({"qty": int(m.group(1)), "item": m.group(2)})
    return results


# ═══════════════════════════════════════════════════════════════════════════════
#  /shipment  — Салбараас багц явуулах
# ═══════════════════════════════════════════════════════════════════════════════
@client.tree.command(name="shipment", description="Засварт явуулах зүйлсийн багц бүртгэх")
@app_commands.describe(
    branch="Салбарын нэр",
    items="Жагсаалт: 1 mouse, 2 keyboard, 10 чихэвч",
    notes="Нэмэлт тайлбар (заавал биш)"
)
async def shipment_cmd(interaction: discord.Interaction, branch: str, items: str, notes: str = ""):
    if not check_channel(interaction):
        return await interaction.response.send_message(
            f"❌ **#{CHANNEL_NAME}** channel дотор ашиглана уу.", ephemeral=True)

    await interaction.response.defer()

    parsed = _parse_items(items)
    if not parsed:
        return await interaction.followup.send(
            "❌ Формат буруу. Жишээ: `1 mouse, 2 keyboard, 10 чихэвч`", ephemeral=True)

    shp_id, rep_rows = client.sheets.create_shipment(
        branch=branch, items=parsed,
        reported_by=str(interaction.user), notes=notes
    )

    embed = discord.Embed(title="📦 Засварын багц бүртгэгдлээ", color=0x2ECC71)
    embed.add_field(name="🆔 Илгээлтийн ID", value=f"`{shp_id}`", inline=True)
    embed.add_field(name="🏢 Салбар", value=branch, inline=True)
    embed.add_field(name="👤 Бүртгэсэн", value=str(interaction.user), inline=True)
    if notes:
        embed.add_field(name="📝 Тайлбар", value=notes, inline=False)

    rep_lines = "\n".join(f"`{r['rep_id']}` — {r['qty']}ш {r['item']}" for r in rep_rows)
    embed.add_field(name=f"🔧 Засварын зүйлс ({len(rep_rows)} төрөл)", value=rep_lines, inline=False)
    embed.set_footer(text=f"Засварын газарт мэдэгдэнэ үү → /received {shp_id}")
    await interaction.followup.send(embed=embed)


# ═══════════════════════════════════════════════════════════════════════════════
#  /received  — Засварын газар хүлээж авсан
# ═══════════════════════════════════════════════════════════════════════════════
@client.tree.command(name="received", description="Засварт ирсэн багцыг хүлээж авсан тэмдэглэх")
@app_commands.describe(shp_id="Илгээлтийн ID (жш: SHP-0001)")
async def received_cmd(interaction: discord.Interaction, shp_id: str):
    if not check_channel(interaction):
        return await interaction.response.send_message(
            f"❌ **#{CHANNEL_NAME}** channel дотор ашиглана уу.", ephemeral=True)

    await interaction.response.defer()

    result = client.sheets.mark_received(shp_id.upper(), received_by=str(interaction.user))
    if result is None:
        return await interaction.followup.send(f"❌ **{shp_id}** ID олдсонгүй.", ephemeral=True)

    embed = discord.Embed(title="📥 Багц хүлээж авлаа", color=0x3498DB)
    embed.add_field(name="🆔 Илгээлт", value=f"`{shp_id.upper()}`", inline=True)
    embed.add_field(name="🏢 Салбар", value=result["branch"], inline=True)
    embed.add_field(name="👤 Хүлээж авсан", value=str(interaction.user), inline=True)

    rep_lines = "\n".join(
        f"`{r['rep_id']}` — {r['qty']}ш {r['item']}" for r in result["reps"])
    embed.add_field(name=f"🔧 Засварт хүлээн авсан ({len(result['reps'])} төрөл)",
                    value=rep_lines, inline=False)
    embed.set_footer(text="Тус бүрийг засварлаад /fix [REP-ID] бичнэ үү")
    await interaction.followup.send(embed=embed)


# ═══════════════════════════════════════════════════════════════════════════════
#  /fix  — REP засварлаж дуусгах → Fixed tab руу шилжинэ
# ═══════════════════════════════════════════════════════════════════════════════
@client.tree.command(name="fix", description="Тухайн засварыг дуусгах (Fixed tab руу шилжинэ)")
@app_commands.describe(
    rep_id="Засварын ID (жш: REP-0003)",
    notes="Засварын тайлбар (заавал биш)"
)
async def fix_cmd(interaction: discord.Interaction, rep_id: str, notes: str = ""):
    if not check_channel(interaction):
        return await interaction.response.send_message(
            f"❌ **#{CHANNEL_NAME}** channel дотор ашиглана уу.", ephemeral=True)

    await interaction.response.defer()

    result = client.sheets.mark_fixed(
        rep_id=rep_id.upper(), fixed_by=str(interaction.user), notes=notes)

    if result is None:
        return await interaction.followup.send(
            f"❌ **{rep_id}** ID олдсонгүй эсвэл аль хэдийн дууссан байна.", ephemeral=True)

    embed = discord.Embed(title="✅ Засвар дууслаа → Fixed tab-д бүртгэгдлээ", color=0x9B59B6)
    embed.add_field(name="🆔 REP ID", value=f"`{rep_id.upper()}`", inline=True)
    embed.add_field(name="📦 Зүйл", value=f"{result['qty']}ш {result['item']}", inline=True)
    embed.add_field(name="🏢 Салбар", value=result["branch"], inline=True)
    embed.add_field(name="📦 Илгээлт", value=f"`{result['shp_id']}`", inline=True)
    if notes:
        embed.add_field(name="📋 Засварын тайлбар", value=notes, inline=False)

    # SHP бүрэн дууссан эсэх
    shp_status = result.get("shp_status")
    if shp_status == "done":
        embed.add_field(
            name="🎉 Илгээлт бүрэн дууслаа!",
            value=f"`{result['shp_id']}` доторх бүх засвар дуусч **Дууссан** болов.",
            inline=False
        )
    elif shp_status == "partial":
        remaining = result.get("remaining", 0)
        embed.add_field(
            name="⏳ Илгээлтийн явц",
            value=f"`{result['shp_id']}` — {remaining} засвар үлдсэн байна",
            inline=False
        )

    await interaction.followup.send(embed=embed)


# ═══════════════════════════════════════════════════════════════════════════════
#  /status  — SHP эсвэл REP статус шалгах
# ═══════════════════════════════════════════════════════════════════════════════
@client.tree.command(name="status", description="Илгээлт (SHP) эсвэл засвар (REP) статус шалгах")
@app_commands.describe(id="SHP-XXXX эсвэл REP-XXXX")
async def status_cmd(interaction: discord.Interaction, id: str):
    await interaction.response.defer(ephemeral=True)
    id_upper = id.strip().upper()

    if id_upper.startswith("SHP-"):
        result = client.sheets.get_shipment_status(id_upper)
        if result is None:
            return await interaction.followup.send(f"❌ **{id_upper}** олдсонгүй.", ephemeral=True)

        emoji_map = {"Илгээсэн": "📤", "Хүлээж авсан": "📥", "Дууссан": "✅"}
        emoji = emoji_map.get(result["status"], "❓")
        color = 0x2ECC71 if result["status"] == "Дууссан" else 0xF39C12

        embed = discord.Embed(title=f"{emoji} Илгээлтийн статус — {id_upper}", color=color)
        embed.add_field(name="🏢 Салбар", value=result["branch"], inline=True)
        embed.add_field(name="📊 Статус", value=result["status"], inline=True)
        embed.add_field(name="📅 Огноо", value=result["created_date"], inline=True)

        done   = [r for r in result["reps"] if r["location"] == "fixed"]
        active = [r for r in result["reps"] if r["location"] == "repair"]

        if active:
            lines = "\n".join(f"`{r['rep_id']}` — {r['qty']}ш {r['item']} [{r['status']}]" for r in active)
            embed.add_field(name="⏳ Засварлаж байна", value=lines, inline=False)
        if done:
            lines = "\n".join(f"`{r['rep_id']}` — {r['qty']}ш {r['item']} ✅" for r in done)
            embed.add_field(name="✅ Дууссан", value=lines, inline=False)

    elif id_upper.startswith("REP-"):
        result = client.sheets.get_repair_status(id_upper)
        if result is None:
            return await interaction.followup.send(f"❌ **{id_upper}** олдсонгүй.", ephemeral=True)

        location_label = "Fixed tab (дууссан)" if result["location"] == "fixed" else "Repairs tab (засварлаж байна)"
        embed = discord.Embed(
            title=f"{'✅' if result['location']=='fixed' else '⏳'} Засварын статус — {id_upper}",
            color=0x2ECC71 if result["location"] == "fixed" else 0xF39C12
        )
        embed.add_field(name="📦 Зүйл", value=f"{result['qty']}ш {result['item']}", inline=True)
        embed.add_field(name="🏢 Салбар", value=result["branch"], inline=True)
        embed.add_field(name="📊 Байршил", value=location_label, inline=True)
        embed.add_field(name="📦 Илгээлт", value=f"`{result['shp_id']}`", inline=True)
        embed.add_field(name="📊 Статус", value=result["status"], inline=True)
        if result.get("notes"):
            embed.add_field(name="📋 Тэмдэглэл", value=result["notes"], inline=False)
    else:
        return await interaction.followup.send(
            "❌ SHP-XXXX эсвэл REP-XXXX форматаар оруулна уу.", ephemeral=True)

    await interaction.followup.send(embed=embed, ephemeral=True)


# ═══════════════════════════════════════════════════════════════════════════════
#  /help  — Командуудын жагсаалт
# ═══════════════════════════════════════════════════════════════════════════════
@client.tree.command(name="help", description="Засварын бүртгэлийн бүх командын жагсаалт")
async def help_cmd(interaction: discord.Interaction):
    embed = discord.Embed(
        title="📋 Засварын бүртгэлийн командууд",
        description=f"Доорх командуудыг **#{CHANNEL_NAME}** channel дотор ашиглана уу.",
        color=0x5865F2
    )

    embed.add_field(
        name="📦 `/shipment`  —  Засварт явуулах багц бүртгэх",
        value=(
            "`branch` — Салбарын нэр\n"
            "`items` — Жагсаалт: `1 mouse, 2 keyboard, 10 чихэвч`\n"
            "`notes` — Нэмэлт тайлбар _(заавал биш)_\n"
            "→ **SHP-XXXX** болон тус бүрт **REP-XXXX** үүснэ"
        ),
        inline=False
    )

    embed.add_field(
        name="📥 `/received`  —  Засварын газар хүлээж авсан тэмдэглэх",
        value=(
            "`shp_id` — Илгээлтийн ID, жш: `SHP-0001`\n"
            "→ SHP болон холбоотой бүх REP **Хүлээж авсан** болно"
        ),
        inline=False
    )

    embed.add_field(
        name="✅ `/fix`  —  Засвар дуусгах",
        value=(
            "`rep_id` — Засварын ID, жш: `REP-0003`\n"
            "`notes` — Засварын тайлбар _(заавал биш)_\n"
            "→ REP **Fixed** tab руу шилжинэ; бүх REP дуусвал SHP **Дууссан** болно"
        ),
        inline=False
    )

    embed.add_field(
        name="🔍 `/status`  —  Статус шалгах",
        value=(
            "`id` — `SHP-XXXX` эсвэл `REP-XXXX`\n"
            "→ Илгээлт эсвэл засварын дэлгэрэнгүй мэдээлэл харуулна"
        ),
        inline=False
    )

    embed.add_field(
        name="📌 Workflow",
        value=(
            "**Салбар:** `/shipment` → SHP + REP үүснэ\n"
            "**Засварын газар:** `/received` → `/fix` (тус бүрт)"
        ),
        inline=False
    )

    await interaction.response.send_message(embed=embed, ephemeral=True)


# ── Events ────────────────────────────────────────────────────────────────────
@client.event
async def on_ready():
    print(f"✅  Bot нэвтэрлээ: {client.user}")
    print(f"💬  Channel: #{CHANNEL_NAME}")
    for guild in client.guilds:
        await client.tree.sync(guild=guild)
        print(f"✅  Slash командууд sync → {guild.name}")


client.run(DISCORD_TOKEN)
