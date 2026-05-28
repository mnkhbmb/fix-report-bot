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
#  /return  — Зассан зүйлийг салбарт буцаах
# ═══════════════════════════════════════════════════════════════════════════════
@client.tree.command(name="return", description="Зассан зүйлийг салбарт буцаасныг тэмдэглэх")
@app_commands.describe(rep_id="REP ID (жш: REP-0003)")
async def return_cmd(interaction: discord.Interaction, rep_id: str):
    if not check_channel(interaction):
        return await interaction.response.send_message(
            f"❌ **#{CHANNEL_NAME}** channel дотор ашиглана уу.", ephemeral=True)

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
#  /toootsoo  — Өдрийн тооцоо (Modal form)
# ═══════════════════════════════════════════════════════════════════════════════
def _parse_amount_lines(raw: str) -> list[dict]:
    """
    Multi-line text-аас [{"desc": "...", "amount": N}] жагсаалт хийнэ.
    Жишээ:  'Нацагаа цаг 3500\\nGameranger error 9250'
            'Нацагаа цаг - 3500, Gameranger 9250'
    """
    if not raw or not raw.strip():
        return []
    results = []
    # Мөр болон comma хоёуланг нь separator болгож хуваана
    parts = re.split(r"[\n,]+", raw)
    for part in parts:
        part = part.strip().replace("-", " ")
        if not part:
            continue
        m = re.match(r"^(.+?)\s+(\d[\d\s,]*)$", part)
        if m:
            desc = m.group(1).strip()
            amount = int(re.sub(r"[\s,]", "", m.group(2)))
            results.append({"desc": desc, "amount": amount})
    return results


def _parse_int(raw: str) -> int:
    """'1,500,000' эсвэл '1500000' → 1500000"""
    if not raw:
        return 0
    cleaned = re.sub(r"[^\d]", "", raw)
    return int(cleaned) if cleaned else 0


class ToootsooModal(ui.Modal, title="📊 Өдрийн тооцоо"):
    def __init__(self, branch: str, shift: str):
        super().__init__()
        self.branch = branch
        self.shift  = shift

    worker = ui.TextInput(
        label="Ажилтны нэр",
        placeholder="жш: Дөлгөөн",
        required=True, max_length=50
    )
    cash = ui.TextInput(
        label="Бэлэн (₮)",
        placeholder="жш: 109500",
        required=True, max_length=15
    )
    card = ui.TextInput(
        label="Карт (₮)",
        placeholder="жш: 1158750",
        required=True, max_length=15
    )
    expenses = ui.TextInput(
        label="Зардал (мөр бүрт: тайлбар дүн)",
        placeholder="Нацагаа цаг 3500\nGameranger error 9250",
        required=False, style=discord.TextStyle.paragraph, max_length=500
    )
    incomes = ui.TextInput(
        label="Нэмэлт орлого (заавал биш)",
        placeholder="Зээл буцаалт 5000",
        required=False, style=discord.TextStyle.paragraph, max_length=500
    )

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer()

        cash_n = _parse_int(self.cash.value)
        card_n = _parse_int(self.card.value)
        exp_list = _parse_amount_lines(self.expenses.value)
        inc_list = _parse_amount_lines(self.incomes.value)

        result = client.sheets.add_toootsoo(
            branch=self.branch, shift=self.shift,
            worker=self.worker.value.strip(),
            cash=cash_n, card=card_n,
            expenses=exp_list, incomes=inc_list,
            reported_by=str(interaction.user)
        )

        shift_emoji = "🌅" if "өглөө" in self.shift.lower() else "🌙"
        embed = discord.Embed(
            title=f"{shift_emoji} {result['date']} — {self.shift}",
            description=f"**{self.branch}** · {result['worker']}",
            color=0x2ECC71
        )

        if exp_list:
            lines = "\n".join(f"• {e['desc']} — `{e['amount']:,}₮`" for e in exp_list)
            embed.add_field(name="📉 Зардал", value=lines, inline=False)
        if inc_list:
            lines = "\n".join(f"• {i['desc']} — `{i['amount']:,}₮`" for i in inc_list)
            embed.add_field(name="📈 Нэмэлт орлого", value=lines, inline=False)

        summary = (
            f"**Бэлэн** — `{cash_n:,}₮`\n"
            f"**Карт**  — `{card_n:,}₮`\n"
            f"**Зардал** — `{result['total_exp']:,}₮`\n"
            f"━━━━━━━━━━━━━━━━━\n"
            f"**🧮 Нийт** — `{result['net_total']:,}₮`"
        )
        embed.add_field(name="💰 Дүн", value=summary, inline=False)
        embed.set_footer(text=f"Бүртгэсэн: {interaction.user}")

        await interaction.followup.send(embed=embed)


@client.tree.command(name="toootsoo", description="Өдрийн тооцоо бүртгэх (form гарч ирнэ)")
@app_commands.describe(shift="Ээлж сонгоно уу")
@app_commands.choices(shift=[
    app_commands.Choice(name="🌅 Өглөө",  value="Өглөө"),
    app_commands.Choice(name="🌙 Орой",  value="Орой"),
])
async def toootsoo_cmd(interaction: discord.Interaction, shift: app_commands.Choice[str]):
    # Channel нэрийг салбар болгоно (#4-муис → "4-муис")
    branch = interaction.channel.name
    modal = ToootsooModal(branch=branch, shift=shift.value)
    await interaction.response.send_modal(modal)


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
        name="📊 `/toootsoo`  —  Өдрийн тооцоо бүртгэх",
        value=(
            "`shift` — 🌅 Өглөө эсвэл 🌙 Орой\n"
            "→ Form гарч ирнэ: Ажилтан, Бэлэн, Карт, Зардал, Орлого\n"
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
            "**Тооцоо:** өглөө/орой `/toootsoo`\n"
            "**Агуулах:** `/swap` — эвдэрсэн зүйл солих + автомат хасна"
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
