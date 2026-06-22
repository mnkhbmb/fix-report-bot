"""
bot.py — Засварын бүртгэлийн Discord Bot v3

Команд:
  /shipment  — Салбараас засварт явуулах багц бүртгэх  → SHP-XXXX
  /received  — Засварын газар хүлээж авсан тэмдэглэх
  /fix       — Тухайн REP засварлаж дуусгах           → Fixed tab руу шилжинэ
  /status    — SHP эсвэл REP статус шалгах
"""

import discord
from discord import app_commands, ui
import os
import re
import time
from dotenv import load_dotenv
from sheets import SheetsClient

# Локал дээр .env-ийг автоматаар олж уншина; Railway дээр жинхэнэ env var ашиглана.
load_dotenv()

DISCORD_TOKEN = os.environ["DISCORD_TOKEN"]
CHANNEL_NAME  = os.environ.get("REPAIR_CHANNEL_NAME", "repairs")

# Засварын командууд (/shipment /received /fix /return) ажиллах салбарын сувгууд.
# .env-д REPAIR_CHANNELS-ээр өөрчилнө. Хоосон бол ямар ч сувагт ажиллана.
_DEFAULT_REPAIR_CHANNELS = (
    "түмэн,2-спортын-төв-ордон,3-энхтайваны-төв-ордон,4-муис,4-ps,8-19,9-суис,10-цирк"
)
REPAIR_CHANNELS = {
    c.strip().lower()
    for c in os.environ.get("REPAIR_CHANNELS", _DEFAULT_REPAIR_CHANNELS).split(",")
    if c.strip()
}

# Зөвхөн эдгээр салбарын сувгуудад л "/haalt ашигла" гэж сануулна (allow-list).
# .env-д HAALT_CHANNELS-ээр өөрчилж болно (таслалаар). Хоосон бол доорх default.
_DEFAULT_HAALT_CHANNELS = "түмэн,4-муис,3-энхтайваны-төв-ордон,4-ps,9-суис,10-цирк"
HAALT_CHANNELS = {
    c.strip().lower()
    for c in os.environ.get("HAALT_CHANNELS", _DEFAULT_HAALT_CHANNELS).split(",")
    if c.strip()
}
REMIND_COOLDOWN = 60  # секунд — нэг channel-д хэт олон сануулахаас сэргийлнэ
_last_remind: dict[int, float] = {}


def _int_env(name: str):
    v = os.environ.get(name, "").strip()
    return int(v) if v.isdigit() else None


# Нэг серверийн дотор 2 category (суваг бүлэг) — ижил нэртэй суваг давхцахаас сэргийлнэ.
# Category ID тохируулсан бол түүгээр, үгүй бол сувгийн нэрээр шийднэ.
HAALT_CATEGORY_ID  = _int_env("HAALT_CATEGORY_ID")   # Тооцооны бүлэг
REPAIR_CATEGORY_ID = _int_env("REPAIR_CATEGORY_ID")  # Засварын бүлэг


def _is_haalt_here(channel) -> bool:
    """Энэ суваг тооцооны бүлэгт (category) хамаарах уу."""
    if HAALT_CATEGORY_ID is not None:
        return getattr(channel, "category_id", None) == HAALT_CATEGORY_ID
    chan = (getattr(channel, "name", "") or "").lower()
    return chan in HAALT_CHANNELS


def _is_repair_here(channel) -> bool:
    """Энэ суваг засварын бүлэгт (category) хамаарах уу."""
    if REPAIR_CATEGORY_ID is not None:
        return getattr(channel, "category_id", None) == REPAIR_CATEGORY_ID
    chan = (getattr(channel, "name", "") or "").lower()
    return chan in REPAIR_CHANNELS

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
    """Засварын командыг зөвхөн засварын бүлгийн салбарын сувгуудад зөвшөөрнө."""
    # Юу ч тохируулаагүй бол бүх сувагт зөвшөөрнө
    if REPAIR_CATEGORY_ID is None and not REPAIR_CHANNELS:
        return True
    return _is_repair_here(interaction.channel)


def _parse_items(raw: str) -> list[dict]:
    """'1 mouse, 2 keyboard, 10 чихэвч' → [{"qty":1,"item":"mouse"}, ...]"""
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
    items="Жагсаалт: 1 mouse, 2 keyboard, 10 чихэвч",
    notes="Нэмэлт тайлбар (заавал биш)"
)
async def shipment_cmd(interaction: discord.Interaction, items: str, notes: str = ""):
    if not check_channel(interaction):
        return await interaction.response.send_message(
            "❌ Энэ командыг **салбарын суваг** дотор ашиглана уу.", ephemeral=True)

    await interaction.response.defer()

    # Салбарыг сувгийн нэрнээс автоматаар авна
    branch = interaction.channel.name
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
            "❌ Энэ командыг **салбарын суваг** дотор ашиглана уу.", ephemeral=True)

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
            "❌ Энэ командыг **салбарын суваг** дотор ашиглана уу.", ephemeral=True)

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
#  /return  — Зассан зүйлийг салбарт буцаах
# ═══════════════════════════════════════════════════════════════════════════════
@client.tree.command(name="return", description="Зассан зүйлийг салбарт буцаасныг тэмдэглэх")
@app_commands.describe(rep_id="REP ID (жш: REP-0003)")
async def return_cmd(interaction: discord.Interaction, rep_id: str):
    if not check_channel(interaction):
        return await interaction.response.send_message(
            "❌ Энэ командыг **салбарын суваг** дотор ашиглана уу.", ephemeral=True)

    await interaction.response.defer()
    result = client.sheets.mark_returned(rep_id.upper(), returned_by=str(interaction.user))

    if result is None:
        return await interaction.followup.send(
            f"❌ **{rep_id}** Fixed tab-аас олдсонгүй. Эхлээд `/fix` хийсэн эсэхийг шалгана уу.",
            ephemeral=True)

    if result.get("already_returned"):
        return await interaction.followup.send(
            f"⚠️ **{rep_id.upper()}** аль хэдийн буцаасан байна.\n"
            f"Буцаасан: **{result['ret_by']}** · {result['ret_date']}",
            ephemeral=True)

    embed = discord.Embed(
        title="📤 Салбарт буцаалаа",
        description=f"`{rep_id.upper()}` зассан зүйл салбарт буцаагдлаа.",
        color=0x1ABC9C
    )
    embed.add_field(name="📦 Зүйл", value=f"{result['qty']}ш {result['item']}", inline=True)
    embed.add_field(name="🏢 Салбар", value=result["branch"], inline=True)
    embed.add_field(name="📦 Илгээлт", value=f"`{result['shp_id']}`", inline=True)
    embed.add_field(name="🔧 Зассан", value=f"{result['fix_by']} · {result['fix_date']}", inline=False)
    embed.add_field(name="📤 Буцаасан", value=f"{result['ret_by']} · {result['ret_date']}", inline=False)
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

        loc = result["location"]
        loc_label = {
            "repair":   "Repairs tab (засварлаж байна)",
            "fixed":    "Fixed tab (дууссан)",
            "returned": "Fixed tab (салбарт буцаасан)"
        }.get(loc, loc)
        loc_emoji = {"repair": "⏳", "fixed": "✅", "returned": "📤"}.get(loc, "❓")
        loc_color = {"repair": 0xF39C12, "fixed": 0x2ECC71, "returned": 0x1ABC9C}.get(loc, 0x95A5A6)

        embed = discord.Embed(
            title=f"{loc_emoji} Засварын статус — {id_upper}",
            color=loc_color
        )
        embed.add_field(name="📦 Зүйл", value=f"{result['qty']}ш {result['item']}", inline=True)
        embed.add_field(name="🏢 Салбар", value=result["branch"], inline=True)
        embed.add_field(name="📊 Байршил", value=loc_label, inline=True)
        embed.add_field(name="📦 Илгээлт", value=f"`{result['shp_id']}`", inline=True)
        embed.add_field(name="📊 Статус", value=result["status"], inline=True)
        if result.get("notes"):
            embed.add_field(name="📋 Тэмдэглэл", value=result["notes"], inline=False)
        if loc == "returned":
            embed.add_field(name="📤 Буцаасан",
                            value=f"{result['ret_by']} · {result['ret_date']}", inline=False)
    else:
        return await interaction.followup.send(
            "❌ SHP-XXXX эсвэл REP-XXXX форматаар оруулна уу.", ephemeral=True)

    await interaction.followup.send(embed=embed, ephemeral=True)


# ═══════════════════════════════════════════════════════════════════════════════
#  /aguulakh, /stock_add, /swap  — Салбарын агуулах
# ═══════════════════════════════════════════════════════════════════════════════
@client.tree.command(name="aguulakh", description="Энэ салбарын агуулах дахь зүйлсийн жагсаалт")
async def aguulakh_cmd(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    branch = interaction.channel.name
    items = client.sheets.get_aguulakh(branch)

    embed = discord.Embed(
        title=f"📦 Агуулах — {branch}",
        color=0x3498DB
    )
    if not items:
        embed.description = "_Хоосон. `/stock_add` командаар зүйл нэмнэ үү._"
    else:
        lines = "\n".join(
            f"• **{it['item']}** — `{it['qty']}ш`"
            + (f"  _({it['notes']})_" if it["notes"] else "")
            for it in items
        )
        embed.description = lines
        embed.set_footer(text=f"Нийт {len(items)} төрөл")
    await interaction.followup.send(embed=embed, ephemeral=True)


@client.tree.command(name="stock_add", description="Агуулахад зүйл нэмэх (эсвэл хасах)")
@app_commands.describe(
    item="Зүйлийн нэр (жш: mouse, keyboard, чихэвч)",
    qty="Тоо (хасах бол сөрөг тоо)",
    notes="Тэмдэглэл (заавал биш)"
)
async def stock_add_cmd(interaction: discord.Interaction, item: str, qty: int, notes: str = ""):
    await interaction.response.defer()
    branch = interaction.channel.name
    result = client.sheets.adjust_stock(branch, item, qty, notes)

    action = "нэмэгдэв" if qty >= 0 else "хасагдав"
    embed = discord.Embed(
        title=f"📦 Агуулах шинэчлэгдэв — {branch}",
        description=(
            f"**{item}** {abs(qty)}ш {action}.\n"
            f"Өмнө: `{result['old_qty']}ш` → Одоо: `{result['new_qty']}ш`"
            + ("\n_✨ Шинэ зүйл үүсгэв_" if result["created"] else "")
        ),
        color=0x2ECC71 if qty >= 0 else 0xE67E22
    )
    if notes:
        embed.add_field(name="📋 Тэмдэглэл", value=notes, inline=False)
    embed.set_footer(text=f"Бүртгэсэн: {interaction.user}")
    await interaction.followup.send(embed=embed)


@client.tree.command(name="swap", description="Эвдэрсэн зүйлийг агуулахаас солих")
@app_commands.describe(
    item="Зүйлийн нэр",
    qty="Хэдэн ширхэг солих",
    reason="Шалтгаан (жш: эвдэрсэн, ажиллахгүй)"
)
async def swap_cmd(interaction: discord.Interaction, item: str, qty: int, reason: str = "эвдэрсэн"):
    await interaction.response.defer()
    if qty <= 0:
        return await interaction.followup.send("❌ Тоо эерэг байх ёстой.", ephemeral=True)

    branch = interaction.channel.name
    result = client.sheets.record_swap(branch, item, qty, reason, str(interaction.user))

    embed = discord.Embed(
        title="🔄 Зүйл солилоо",
        description=f"**{branch}** салбарын **{item}** ({qty}ш) солигдов.",
        color=0xE74C3C
    )
    embed.add_field(name="📋 Шалтгаан", value=reason, inline=True)
    embed.add_field(name="📦 Агуулахад үлдэгдэл", value=f"`{result['remaining']}ш`", inline=True)
    embed.set_footer(text=f"Бүртгэсэн: {interaction.user} · {result['date']}")
    await interaction.followup.send(embed=embed)


# ═══════════════════════════════════════════════════════════════════════════════
#  /haalt  — Ээлжийн хаалт / тооцоо (Modal form)
# ═══════════════════════════════════════════════════════════════════════════════
# Ээлж бүрийн цагийн интервал
SHIFT_TIMES = {
    "Өдөр": "09:00-19:00",
    "Орой": "19:00-09:00",
    "Бүтэн гараа": "",   # цаг бичихгүй
}
SHIFT_EMOJI = {
    "Өдөр": "🌅",
    "Орой": "🌙",
    "Бүтэн гараа": "🌗",
}


def _parse_int(raw: str) -> int:
    """'1,500,000' эсвэл '-80 000' → 1500000 / -80000 (зөвхөн тоо + хасах тэмдэг)."""
    if not raw:
        return 0
    raw = raw.strip()
    neg = raw.startswith("-")
    cleaned = re.sub(r"[^\d]", "", raw)
    if not cleaned:
        return 0
    return -int(cleaned) if neg else int(cleaned)


class HaaltModal(ui.Modal, title="🧮 Ээлжийн хаалт"):
    def __init__(self, branch: str, shift: str, worker: str):
        super().__init__()
        self.branch = branch
        self.shift  = shift
        self.worker = worker
        self.time_range = SHIFT_TIMES.get(shift, "")

    cash = ui.TextInput(
        label="Бэлэн (₮)",
        placeholder="жш: 80000",
        required=True, max_length=15
    )
    card = ui.TextInput(
        label="Карт (₮)",
        placeholder="жш: 562450",
        required=True, max_length=15
    )
    dans = ui.TextInput(
        label="Данс (₮)",
        placeholder="жш: 0",
        required=False, max_length=15, default="0"
    )
    zardal = ui.TextInput(
        label="Зардал (₮)",
        placeholder="жш: 40000",
        required=False, max_length=15, default="0"
    )
    notes = ui.TextInput(
        label="Зардлын задаргаа (заавал биш)",
        placeholder="жш: баллонтой ус - 8800",
        required=False, style=discord.TextStyle.paragraph, max_length=500
    )

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer()

        cash_n   = _parse_int(self.cash.value)
        card_n   = _parse_int(self.card.value)
        dans_n   = _parse_int(self.dans.value)
        zardal_n = _parse_int(self.zardal.value)

        result = client.sheets.add_haalt(
            branch=self.branch, shift=self.shift, time_range=self.time_range,
            worker=self.worker.strip(),
            cash=cash_n, card=card_n, dans=dans_n, zardal=zardal_n,
            notes=(self.notes.value or "").strip(),
            reported_by=str(interaction.user)
        )

        shift_emoji = SHIFT_EMOJI.get(self.shift, "🕘")
        shift_label = f"{self.shift} /{self.time_range}/" if self.time_range else self.shift
        embed = discord.Embed(
            title=f"{shift_emoji} {result['date']} — {shift_label}",
            description=f"**{self.branch}** · {result['worker']}",
            color=0x2ECC71
        )

        lines = [
            f"**Бэлэн** — `{cash_n:,}₮`",
            f"**Карт**  — `{card_n:,}₮`",
        ]
        if dans_n:
            lines.append(f"**Данс**  — `{dans_n:,}₮`")
        if zardal_n:
            lines.append(f"**Зардал** — `{zardal_n:,}₮`")
        lines.append("━━━━━━━━━━━━━━━━━")
        lines.append(f"**🧮 Нийт** — `{result['net_total']:,}₮`")
        embed.add_field(name="💰 Дүн", value="\n".join(lines), inline=False)

        if result["notes"]:
            embed.add_field(name="📝 Зардлын задаргаа", value=result["notes"], inline=False)
        embed.set_footer(text=f"Бүртгэсэн: {interaction.user}")

        await interaction.followup.send(embed=embed)


@client.tree.command(name="haalt", description="Ээлжийн хаалт / тооцоо бүртгэх (form гарч ирнэ)")
@app_commands.describe(eelj="Ээлж сонгоно уу", ajiltan="Ажилтны нэр")
@app_commands.choices(eelj=[
    app_commands.Choice(name="🌅 Өдөр (09:00-19:00)", value="Өдөр"),
    app_commands.Choice(name="🌙 Орой (19:00-09:00)", value="Орой"),
    app_commands.Choice(name="🌗 Бүтэн гараа", value="Бүтэн гараа"),
])
async def haalt_cmd(interaction: discord.Interaction,
                    eelj: app_commands.Choice[str], ajiltan: str):
    # Зөвхөн тооцооны бүлгийн (category) сувгуудад зөвшөөрнө
    if HAALT_CATEGORY_ID is not None and not _is_haalt_here(interaction.channel):
        return await interaction.response.send_message(
            "❌ `/haalt` командыг зөвхөн **тооцооны бүлгийн суваг**т ашиглана.", ephemeral=True)

    # Channel нэрийг салбар болгоно
    branch = interaction.channel.name
    modal = HaaltModal(branch=branch, shift=eelj.value, worker=ajiltan)
    await interaction.response.send_modal(modal)


# ═══════════════════════════════════════════════════════════════════════════════
#  /help  — Командуудын жагсаалт
# ═══════════════════════════════════════════════════════════════════════════════
@client.tree.command(name="help", description="Засварын бүртгэлийн бүх командын жагсаалт")
async def help_cmd(interaction: discord.Interaction):
    embed = discord.Embed(
        title="📋 Засварын бүртгэлийн командууд",
        description="Доорх командуудыг тухайн **салбарын суваг** дотор ашиглана уу.",
        color=0x5865F2
    )

    embed.add_field(
        name="📦 `/shipment`  —  Засварт явуулах багц бүртгэх",
        value=(
            "`items` — Жагсаалт: `1 mouse, 2 keyboard, 10 чихэвч`\n"
            "`notes` — Нэмэлт тайлбар _(заавал биш)_\n"
            "→ Салбар нь **сувгийн нэрнээс** автоматаар тодорхойлогдоно\n"
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
        name="📤 `/return`  —  Зассан зүйлийг салбарт буцаах",
        value=(
            "`rep_id` — Зассан REP ID\n"
            "→ Fixed tab-д **Буцаасан** хүн/огноо бичигдэнэ"
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
        name="🧮 `/haalt`  —  Ээлжийн хаалт / тооцоо бүртгэх",
        value=(
            "`eelj` — 🌅 Өдөр (09:00-19:00) эсвэл 🌙 Орой (19:00-09:00)\n"
            "`ajiltan` — Ажилтны нэр\n"
            "→ Form гарч ирнэ: Бэлэн, Карт, Данс, Зардал, Зардлын задаргаа\n"
            "→ **Нийт** = Бэлэн + Карт + Данс + Зардал автоматаар бодогдоно\n"
            "→ Салбар бүрт тусдаа sheet tab үүснэ"
        ),
        inline=False
    )

    embed.add_field(
        name="📦 Агуулах командууд",
        value=(
            "`/aguulakh` — Энэ салбарын агуулах харах\n"
            "`/stock_add item:mouse qty:10` — Нэмэх (сөрөг тоо хасна)\n"
            "`/swap item:mouse qty:1 reason:эвдэрсэн` — Солих + лог"
        ),
        inline=False
    )

    embed.add_field(
        name="📌 Workflow",
        value=(
            "**Засвар:** `/shipment` → `/received` → `/fix` → `/return`\n"
            "**Тооцоо:** ээлж бүрийн төгсгөлд `/haalt`\n"
            "**Агуулах:** `/swap` — эвдэрсэн зүйл солих + автомат хасна"
        ),
        inline=False
    )

    await interaction.response.send_message(embed=embed, ephemeral=True)


# ── Events ────────────────────────────────────────────────────────────────────
@client.event
async def on_message(message: discord.Message):
    """Салбарын суваг дотор энгийн текст бичихэд зөв командыг ашиглахыг сануулна."""
    if message.author.bot or message.guild is None:
        return

    # Аль бүлгийн суваг вэ — тэр контекстэд тохирох командыг сануулна
    if _is_haalt_here(message.channel):
        reminder = (
            "📌 Энэ суваг **ээлжийн хаалт**-д зориулагдсан.\n"
            "Тооцоогоо бүртгэхдээ **`/haalt`** командыг ашиглаарай 🙏"
        )
    elif _is_repair_here(message.channel):
        reminder = (
            "📌 Энэ суваг **засварын бүртгэл**-д зориулагдсан.\n"
            "Засварт явуулахдаа **`/shipment`** командыг ашиглаарай 🙏"
        )
    else:
        return

    now = time.time()
    if now - _last_remind.get(message.channel.id, 0) < REMIND_COOLDOWN:
        return
    _last_remind[message.channel.id] = now

    try:
        await message.reply(reminder, delete_after=20, mention_author=False)
    except discord.HTTPException:
        pass


async def _sync_guild(guild: discord.Guild):
    """Global командуудыг тухайн серверт хуулж шууд sync хийнэ (1 цаг хүлээхгүй)."""
    client.tree.copy_global_to(guild=guild)
    await client.tree.sync(guild=guild)


@client.event
async def on_guild_join(guild: discord.Guild):
    """Бот шинэ серверт нэгдэхэд тэр даруй slash командуудыг sync хийнэ."""
    await _sync_guild(guild)
    print(f"✅  Шинэ серверт sync → {guild.name}")


@client.event
async def on_ready():
    print(f"✅  Bot нэвтэрлээ: {client.user}")
    for guild in client.guilds:
        await _sync_guild(guild)
        print(f"✅  Slash командууд sync → {guild.name}")


client.run(DISCORD_TOKEN)
