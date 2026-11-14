"""
web.py — Тайлан / Ажлууд / Акт вэб (утсанд зориулсан).
Ботын дотор (bot.py → start_web) эсвэл бие даан (`python web.py`) ажиллана.
Discord нь заавал биш: ACT_CHANNEL_ID тохируулсан үед актыг сувагт бас илгээнэ.
"""
import asyncio
import io
import os
from collections import defaultdict
from datetime import datetime
from html import escape

from aiohttp import web
from fpdf import FPDF
from PIL import Image, ImageOps

HERE = os.path.dirname(os.path.abspath(__file__))
# ponytail: эхний олдсон кирилл фонт — Railway-д fonts/DejaVuSans.ttf repo-д байх ёстой
FONT = next((p for p in [
    os.path.join(HERE, "fonts", "DejaVuSans.ttf"),
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    r"C:\Windows\Fonts\arial.ttf",
] if os.path.exists(p)), None)
PIN = os.environ.get("ACT_PIN", "")
ACT_CHANNEL_ID = int(os.environ.get("ACT_CHANNEL_ID", "0") or 0)
BRANCHES = ["түмэн", "2-спортын-төв-ордон", "3-энхтайваны-төв-ордон", "4-муис",
            "4-ps", "8-19", "9-суис", "10-цирк", "Дархан"]

with open(os.path.join(HERE, "app.html"), encoding="utf-8") as fh:
    APP_HTML = fh.read().replace(
        "{{BRANCHES}}", "".join(f'<option value="{escape(b)}">' for b in BRANCHES))


# ── Цэвэр функцууд (тестлэгдэнэ) ─────────────────────────────────────────────

def parse_items(names, qtys, serials) -> list[dict]:
    out = []
    for n, q, s in zip(names, qtys, serials):
        n = n.strip()
        if not n:
            continue
        try:
            q = max(1, int(q))
        except ValueError:
            q = 1
        out.append({"item": n, "qty": q, "serial": s.strip()})
    return out


def shrink(data: bytes) -> bytes:
    """Утасны том зургийг 1280px JPEG болгоно."""
    img = ImageOps.exif_transpose(Image.open(io.BytesIO(data))).convert("RGB")
    img.thumbnail((1280, 1280))
    out = io.BytesIO()
    img.save(out, "JPEG", quality=70)
    return out.getvalue()


def _new_pdf() -> FPDF:
    pdf = FPDF()
    pdf.add_font("dv", "", FONT)
    pdf.add_font("dv", "B", FONT)   # ponytail: тусдаа bold фонт алга, хүснэгтийн толгойд ижлийг
    pdf.set_font("dv", size=11)
    pdf.add_page()
    return pdf


def build_act_pdf(act_id: str, date: str, f: dict, items: list[dict], photos: list[bytes]) -> bytes:
    pdf = _new_pdf()
    pdf.set_font_size(16)
    pdf.cell(0, 12, f"ХҮЛЭЭЛЦЭХ АКТ № {act_id}", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font_size(11)
    for label, val in [("Огноо", date), ("Хаанаас", f["src"]), ("Хаашаа", f["dst"]),
                       ("Өгсөн", f["giver"]), ("Хүлээн авсан", f["receiver"])]:
        pdf.cell(0, 7, f"{label}: {val}", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)
    with pdf.table(col_widths=(8, 60, 12, 60)) as t:
        t.row(["№", "Зүйл", "Тоо", "Серийн дугаар"])
        for i, it in enumerate(items, 1):
            t.row([str(i), it["item"], str(it["qty"]), it["serial"]])
    if f["notes"]:
        pdf.ln(4)
        pdf.multi_cell(0, 7, f"Тэмдэглэл: {f['notes']}")
    for p in photos:   # ponytail: хуудсанд 1 зураг
        pdf.add_page()
        pdf.image(io.BytesIO(p), x=10, y=10, w=190, h=277, keep_aspect_ratio=True)
    return bytes(pdf.output())


def build_report_pdf(month: str, entries: list[dict]) -> bytes:
    """Сарын тайлан — Word-ийн хэлбэртэй: огноо, доор нь мөрүүд."""
    pdf = _new_pdf()
    pdf.set_font_size(16)
    pdf.cell(0, 12, f"{month} — Ажлын тайлан", align="C", new_x="LMARGIN", new_y="NEXT")
    by_day = defaultdict(list)
    for e in entries:
        by_day[e["date"]].append(e["text"])
    for day in sorted(by_day):
        pdf.ln(3)
        pdf.set_font_size(12)
        pdf.cell(0, 8, day, new_x="LMARGIN", new_y="NEXT")
        pdf.set_font_size(11)
        for text in by_day[day]:
            pdf.multi_cell(0, 6, f"• {text}", new_x="LMARGIN", new_y="NEXT")
    return bytes(pdf.output())


# ── HTTP ─────────────────────────────────────────────────────────────────────

@web.middleware
async def auth(request, handler):
    if request.path != "/" and PIN and request.headers.get("X-PIN", "") != PIN:
        return web.json_response({"error": "PIN буруу"}, status=401)
    return await handler(request)


def _pdf(body: bytes, name: str, **headers) -> web.Response:
    return web.Response(body=body, content_type="application/pdf",
                        headers={"Content-Disposition": f'attachment; filename="{name}"', **headers})


async def index(request):
    return web.Response(text=APP_HTML, content_type="text/html")


async def log_get(request):
    month = request.query.get("month") or datetime.now().strftime("%Y-%m")
    return web.json_response(await asyncio.to_thread(request.app["sheets"].get_log, month))


async def log_post(request):
    text = ((await request.json()).get("text") or "").strip()
    if not text:
        return web.json_response({"error": "Хоосон байна"}, status=400)
    await asyncio.to_thread(request.app["sheets"].add_log, text)
    return web.json_response({"ok": True})


async def report_pdf(request):
    month = request.query.get("month") or datetime.now().strftime("%Y-%m")
    entries = await asyncio.to_thread(request.app["sheets"].get_log, month)
    return _pdf(await asyncio.to_thread(build_report_pdf, month, entries), f"Тайлан-{month}.pdf")


async def tasks_get(request):
    return web.json_response(await asyncio.to_thread(request.app["sheets"].get_tasks))


async def tasks_post(request):
    text = ((await request.json()).get("text") or "").strip()
    if not text:
        return web.json_response({"error": "Хоосон байна"}, status=400)
    tid = await asyncio.to_thread(request.app["sheets"].add_task, text)
    return web.json_response({"id": tid})


async def tasks_done(request):
    d = await request.json()
    text = await asyncio.to_thread(request.app["sheets"].finish_task,
                                   d.get("id", ""), (d.get("note") or "").strip())
    if text is None:
        return web.json_response({"error": "Ажил олдсонгүй"}, status=404)
    return web.json_response({"ok": True})


async def acts_get(request):
    return web.json_response(
        await asyncio.to_thread(request.app["sheets"].get_acts, request.query.get("q", "")))


async def act_post(request):
    sheets, bot = request.app["sheets"], request.app["bot"]
    data = await request.post()
    f = {k: (data.get(k) or "").strip() for k in ("src", "dst", "giver", "receiver", "notes")}
    items = parse_items(data.getall("item", []), data.getall("qty", []), data.getall("serial", []))
    if not (f["src"] and f["dst"] and items):
        return web.json_response({"error": "Хаанаас, хаашаа, дор хаяж нэг зүйл бөглөнө үү"}, status=400)

    raw = [p.file.read() for p in data.getall("photos", []) if getattr(p, "filename", "")]
    photos = await asyncio.to_thread(lambda: [shrink(r) for r in raw])
    date = datetime.now().strftime("%Y-%m-%d %H:%M")
    act_id = await asyncio.to_thread(sheets.next_act_id)
    pdf = await asyncio.to_thread(build_act_pdf, act_id, date, f, items, photos)
    summary = ", ".join(f"{it['qty']}ш {it['item']}" for it in items)

    link = ""
    channel = bot.get_channel(ACT_CHANNEL_ID) if bot and ACT_CHANNEL_ID else None
    if channel:
        import discord
        msg = await channel.send(
            content=f"📄 **{act_id}** · {f['src']} → {f['dst']} · {summary}",
            file=discord.File(io.BytesIO(pdf), f"{act_id}.pdf"))
        link = msg.jump_url

    await asyncio.to_thread(sheets.add_act, act_id, date, f, items, link)
    await asyncio.to_thread(sheets.add_log, f"Акт {act_id}: {f['src']} → {f['dst']} — {summary}")
    return _pdf(pdf, f"{act_id}.pdf", **{"X-Act-Id": act_id})


def make_app(sheets, bot=None) -> web.Application:
    app = web.Application(middlewares=[auth], client_max_size=80 * 1024 * 1024)
    app["sheets"], app["bot"] = sheets, bot
    app.router.add_get("/", index)
    app.router.add_get("/api/log", log_get)
    app.router.add_post("/api/log", log_post)
    app.router.add_get("/api/report.pdf", report_pdf)
    app.router.add_get("/api/tasks", tasks_get)
    app.router.add_post("/api/tasks", tasks_post)
    app.router.add_post("/api/tasks/done", tasks_done)
    app.router.add_get("/api/acts", acts_get)
    app.router.add_post("/api/act", act_post)
    return app


async def start_web(sheets, bot=None):
    runner = web.AppRunner(make_app(sheets, bot))
    await runner.setup()
    port = int(os.environ.get("PORT", "8080"))
    await web.TCPSite(runner, "0.0.0.0", port).start()
    print(f"🌐  Вэб: http://localhost:{port}")


if __name__ == "__main__":   # Discord-гүй, бие даан ажиллуулах
    from dotenv import load_dotenv
    load_dotenv()
    from sheets import SheetsClient

    async def _main():
        await start_web(SheetsClient())
        await asyncio.Event().wait()
    asyncio.run(_main())
