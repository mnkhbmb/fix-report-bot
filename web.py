"""
web.py — Тайлан / Ажлууд / Акт вэб (утсанд зориулсан).
Ботын дотор (bot.py → start_web) эсвэл бие даан (`python web.py`) ажиллана.
Discord нь заавал биш: ACT_CHANNEL_ID тохируулсан үед актыг сувагт бас илгээнэ.
"""
import asyncio
import base64
import hashlib
import hmac
import io
import secrets
import time
import os
import re
import uuid
from collections import defaultdict
from datetime import datetime
from html import escape

import aiohttp
from aiohttp import web
from fpdf import FPDF
from PIL import Image, ImageOps

from sheets import SHEET_ID, TAGS, USERS, ADMIN, can_see, db

HERE = os.path.dirname(os.path.abspath(__file__))
# ponytail: эхний олдсон кирилл фонт — Railway-д fonts/DejaVuSans.ttf repo-д байх ёстой
FONT = next((p for p in [
    os.path.join(HERE, "fonts", "DejaVuSans.ttf"),
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    r"C:\Windows\Fonts\arial.ttf",
] if os.path.exists(p)), None)
PIN = os.environ.get("ACT_PIN", "")
# GOOGLE_CLIENT_ID тавьсан бол Google-ээр нэвтэрнэ (зөвхөн USERS доторх имэйл), эс бөгөөс хуучин PIN горим (= ADMIN)
CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
# ponytail: SESSION_SECRET тавиагүй бол санамсаргүй — restart бүрт бүгд дахин нэвтэрнэ
SECRET = (os.environ.get("SESSION_SECRET") or secrets.token_hex(32)).encode()
SESSION_DAYS = 30
# Ажлын зураг: Railway Volume холбосон бол тэнд (redeploy-д устахгүй), эс бөгөөс repo хавтсанд (redeploy-д устна!)
PHOTO_DIR = os.path.join(os.environ.get("RAILWAY_VOLUME_MOUNT_PATH") or HERE, "photos")
PHOTO_RE = re.compile(r"^[0-9a-f]{32}\.jpg$")
# R2_BUCKET тавьсан бол зураг Cloudflare R2-д (private bucket, манай сервер дамжуулна), үгүй бол локал хавтаст
R2_BUCKET = os.environ.get("R2_BUCKET", "")
_r2 = None


def r2():
    global _r2
    if _r2 is None:
        import boto3
        _r2 = boto3.client("s3", region_name="auto",
                           endpoint_url=f"https://{os.environ['R2_ACCOUNT_ID']}.r2.cloudflarestorage.com",
                           aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
                           aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"])
    return _r2


def put_photo(name, data):
    if R2_BUCKET:
        return r2().put_object(Bucket=R2_BUCKET, Key=name, Body=data, ContentType="image/jpeg")
    os.makedirs(PHOTO_DIR, exist_ok=True)
    with open(os.path.join(PHOTO_DIR, name), "wb") as fh:
        fh.write(data)


def get_photo(name):
    if R2_BUCKET:
        try:
            return r2().get_object(Bucket=R2_BUCKET, Key=name)["Body"].read()
        except r2().exceptions.NoSuchKey:
            return None
    path = os.path.join(PHOTO_DIR, name)
    return open(path, "rb").read() if os.path.exists(path) else None
ACT_CHANNEL_ID = int(os.environ.get("ACT_CHANNEL_ID", "0") or 0)
BRANCHES = ["түмэн", "2-спортын-төв-ордон", "3-энхтайваны-төв-ордон", "4-муис",
            "4-ps", "8-19", "9-суис", "10-цирк", "Дархан"]

with open(os.path.join(HERE, "app.html"), encoding="utf-8") as fh:
    APP_HTML = fh.read().replace(
        "{{BRANCHES}}", "".join(f'<option value="{escape(b)}">' for b in BRANCHES)).replace(
        "{{TAGS}}", "".join(f'<option value="{escape(t)}">{escape(t)}</option>' for t in TAGS)).replace(
        "{{SHEET_URL}}", f"https://docs.google.com/spreadsheets/d/{SHEET_ID}").replace(
        "{{GOOGLE_CLIENT_ID}}", escape(CLIENT_ID))
WD = ["Даваа", "Мягмар", "Лхагва", "Пүрэв", "Баасан", "Бямба", "Ням"]


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


def day_label(d: str) -> str:
    """'2026-11-14' → '2026-11-14 · Бямба · 46-р 7 хоног' (ISO долоо хоног)."""
    try:
        dt = datetime.strptime(d, "%Y-%m-%d")
    except ValueError:
        return d
    return f"{d} · {WD[dt.weekday()]} · {dt.isocalendar()[1]}-р 7 хоног"


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


def sign_session(email: str, days: int = SESSION_DAYS) -> str:
    """Cookie = base64(имэйл|дуусах хугацаа).hmac — сервер дээр session хадгалахгүй."""
    body = base64.urlsafe_b64encode(f"{email}|{int(time.time()) + days * 86400}".encode()).decode()
    return body + "." + hmac.new(SECRET, body.encode(), hashlib.sha256).hexdigest()


def read_session(value: str) -> str:
    """Хүчинтэй cookie бол имэйл, үгүй бол ''. USERS-ээс хасагдсан хүн шууд гарна."""
    body, _, sig = value.rpartition(".")
    if not hmac.compare_digest(sig, hmac.new(SECRET, body.encode(), hashlib.sha256).hexdigest()):
        return ""
    email, _, exp = base64.urlsafe_b64decode(body).decode().partition("|")
    return email if exp.isdigit() and int(exp) > time.time() and email in USERS else ""


async def verify_google(token: str) -> str:
    """Google ID token → баталгаажсан имэйл ('' бол буруу)."""
    # ponytail: tokeninfo endpoint (нэвтрэх үед л 1 удаа) — ачаалал ихсэвэл google-auth-ын локал JWT шалгалт руу
    async with aiohttp.ClientSession() as http:
        async with http.get("https://oauth2.googleapis.com/tokeninfo", params={"id_token": token}) as r:
            info = await r.json() if r.status == 200 else {}
    if not CLIENT_ID or info.get("aud") != CLIENT_ID or info.get("email_verified") not in ("true", True):
        return ""
    return (info.get("email") or "").lower()


def build_report_pdf(title: str, entries: list[dict]) -> bytes:
    """Сарын тайлан — Word-ийн хэлбэртэй: огноо, доор нь мөрүүд."""
    pdf = _new_pdf()
    pdf.set_font_size(16)
    pdf.cell(0, 12, f"{title} — Ажлын тайлан", align="C", new_x="LMARGIN", new_y="NEXT")
    by_day = defaultdict(list)
    for e in entries:
        text = "✓ " + e["text"][9:] if e["text"].startswith("Дууссан: ") else e["text"]
        by = f"{e['by']}: " if e.get("by") else ""   # багийн тайланд хэн хийсэн
        by_day[e["date"]].append((f"[{e['tag']}] " if e.get("tag") else "") + by + text)
    for day in sorted(by_day):
        pdf.ln(3)
        pdf.set_font_size(12)
        pdf.cell(0, 8, day_label(day), new_x="LMARGIN", new_y="NEXT")
        pdf.set_font_size(11)
        for text in by_day[day]:
            pdf.multi_cell(0, 6, f"• {text}", new_x="LMARGIN", new_y="NEXT")
    return bytes(pdf.output())


# ── HTTP ─────────────────────────────────────────────────────────────────────

@web.middleware
async def auth(request, handler):
    # ponytail: /photos/ нэвтрэлтгүй (<img>) — нэр нь 128-бит санамсаргүй тул таагдахгүй
    if request.path in ("/", "/auth/google", "/auth/logout") or request.path.startswith("/photos/"):
        return await handler(request)
    if CLIENT_ID:
        request["me"] = read_session(request.cookies.get("s", ""))
        if not request["me"]:
            return web.json_response({"error": "Нэвтэрнэ үү", "login": True}, status=401)
    else:
        if PIN and request.headers.get("X-PIN", "") != PIN:
            return web.json_response({"error": "PIN буруу"}, status=401)
        request["me"] = ADMIN
    return await handler(request)


async def login(request):
    email = await verify_google((await request.json()).get("credential", ""))
    if email not in USERS:
        return web.json_response({"error": f"{email or 'Энэ данс'} — эрх алга. Админд хандана уу."}, status=403)
    r = web.json_response({"ok": True})
    r.set_cookie("s", sign_session(email), max_age=SESSION_DAYS * 86400, httponly=True,
                 secure=request.secure or request.headers.get("X-Forwarded-Proto") == "https", samesite="Lax")
    return r


async def logout(request):
    r = web.json_response({"ok": True})
    r.del_cookie("s")
    return r


async def me_get(request):
    me = request["me"]
    return web.json_response({"email": me, "name": USERS.get(me, me), "admin": me == ADMIN,
                              "users": USERS, "login": bool(CLIENT_ID)})


def _pdf(body: bytes, name: str, **headers) -> web.Response:
    return web.Response(body=body, content_type="application/pdf",
                        headers={"Content-Disposition": f'attachment; filename="{name}"', **headers})


async def index(request):
    return web.Response(text=APP_HTML, content_type="text/html")


def _range(q) -> tuple[str, str]:
    """?from=&to= (YYYY-MM-DD) эсвэл ?month=YYYY-MM (хоосон бол энэ сар)."""
    if q.get("from"):
        a, b = q["from"], q.get("to") or q["from"]
        fmt = "%Y-%m-%d"
    else:
        m = q.get("month") or datetime.now().strftime("%Y-%m")
        a, b, fmt = m, m, "%Y-%m"
    try:
        datetime.strptime(a, fmt), datetime.strptime(b, fmt)
    except ValueError:
        raise web.HTTPBadRequest(text="Огноо буруу")
    # ponytail: мөр харьцуулалт тул сарын төгсгөл "-31" бүх сард болно
    return (a, b) if fmt == "%Y-%m-%d" else (a + "-01", b + "-31")


async def _entries(request):
    """scope=me → миний бичсэн бүх бичлэг; scope=team → багийн бичлэгүүд (хэн ч бичсэн)."""
    a, b = _range(request.query)
    rows = await db(request.app["sheets"].get_log, a, b, request.query.get("tag", ""))
    team = request.query.get("scope") == "team"
    return a, b, [e for e in rows if (e["team"] == "1" if team else e["who"] == request["me"])]


async def log_get(request):
    _, _, entries = await _entries(request)
    return web.json_response([{**e, "label": day_label(e["date"])} for e in entries])


async def log_post(request):
    d = await request.json()
    text, date, tag = ((d.get(k) or "").strip() for k in ("text", "date", "tag"))
    if not text:
        return web.json_response({"error": "Хоосон байна"}, status=400)
    try:
        date = datetime.strptime(date, "%Y-%m-%d").strftime("%Y-%m-%d") if date else ""
    except ValueError:
        return web.json_response({"error": "Огноо буруу"}, status=400)
    # ponytail: олон мөр бичвэл мөр бүр тусдаа бичлэг
    for line in filter(None, (l.strip() for l in text.splitlines())):
        await db(request.app["sheets"].add_log, line, date, tag, request["me"], "1" if d.get("team") else "")
    return web.json_response({"ok": True})


async def report_pdf(request):
    a, b, entries = await _entries(request)
    if request.query.get("scope") == "team":
        entries = [{**e, "by": USERS.get(e["who"], e["who"])} for e in entries]
    title = a if a == b else f"{a} — {b}"
    return _pdf(await asyncio.to_thread(build_report_pdf, title, entries), f"Тайлан-{a}_{b}.pdf")


async def tasks_get(request):
    return web.json_response([t for t in await db(request.app["sheets"].get_tasks) if can_see(t, request["me"])])


async def _check(request, *ids):
    """Хэрэглэгч эдгээр ажлыг харж чадахгүй бол 404."""
    # ponytail: бичих бүрт нэмэлт 1 уншилт — удаан санагдвал sheets-ийн методууд руу me дамжуулна
    for tid in filter(None, ids):
        try:
            await db(request.app["sheets"].task_for, tid, request["me"])
        except ValueError as e:
            raise web.HTTPNotFound(text=str(e))


async def notes_get(request):
    await _check(request, request.query.get("id", ""))
    return web.json_response(await db(request.app["sheets"].get_task_notes, request.query.get("id", "")))


async def notes_post(request):
    d = await request.json()
    text = (d.get("text") or "").strip()
    if not text:
        return web.json_response({"error": "Хоосон байна"}, status=400)
    await _check(request, d.get("id", ""))
    try:
        await db(request.app["sheets"].add_task_note, d.get("id", ""), text, request["me"])
    except ValueError as e:
        return web.json_response({"error": str(e)}, status=404)
    return web.json_response({"ok": True})


async def tasks_post(request):
    d = await request.json()
    text, parent, tag, due = ((d.get(k) or "").strip() for k in ("text", "parent", "tag", "due"))
    if not text:
        return web.json_response({"error": "Хоосон байна"}, status=400)
    await _check(request, parent)
    try:
        tid = await db(request.app["sheets"].add_task, text, parent, tag, "1" if d.get("urgent") else "", due,
                       request["me"], "1" if d.get("team") else "")
    except ValueError as e:
        return web.json_response({"error": str(e)}, status=400)
    return web.json_response({"id": tid})


async def tasks_done(request):
    d = await request.json()
    await _check(request, d.get("id", ""))
    text = await db(request.app["sheets"].finish_task,
                    d.get("id", ""), (d.get("note") or "").strip(), request["me"])
    if text is None:
        return web.json_response({"error": "Ажил олдсонгүй"}, status=404)
    return web.json_response({"ok": True})


async def log_tag(request):
    """{row, text, tag} → tag солих; {row, text, parent} → өөр бичлэгийн доор нэгтгэх/салгах."""
    d = await request.json()
    s = request.app["sheets"]
    fn, val = (s.set_log_parent, d["parent"]) if "parent" in d else (s.set_log_tag, (d.get("tag") or "").strip())
    try:
        await db(fn, int(d.get("row", 0)), d.get("text", ""), val or "", request["me"])
    except ValueError as e:
        return web.json_response({"error": str(e)}, status=400)
    return web.json_response({"ok": True})


async def task_photo(request):
    data = await request.post()
    raw = [p.file.read() for p in data.getall("photos", []) if getattr(p, "filename", "")]
    if not raw:
        return web.json_response({"error": "Зураг алга"}, status=400)
    try:
        imgs = await asyncio.to_thread(lambda: [shrink(r) for r in raw])
    except Exception:
        return web.json_response({"error": "Зураг уншиж чадсангүй"}, status=400)
    await _check(request, data.get("id", ""))
    names = [f"{uuid.uuid4().hex}.jpg" for _ in imgs]
    for n, img in zip(names, imgs):
        await asyncio.to_thread(put_photo, n, img)
    try:
        await db(request.app["sheets"].add_task_photos, data.get("id", ""), names)
    except ValueError as e:
        return web.json_response({"error": str(e)}, status=404)
    return web.json_response({"photos": names})


async def photo_get(request):
    name = request.match_info["name"]
    data = PHOTO_RE.match(name) and await asyncio.to_thread(get_photo, name)
    if not data:
        raise web.HTTPNotFound()
    return web.Response(body=data, content_type="image/jpeg",
                        headers={"Cache-Control": "public, max-age=31536000, immutable"})


async def tasks_move(request):
    """{id, parent} → зөөх; {id, tag|urgent|due|team} → тэр талбарыг солих."""
    d = await request.json()
    s = request.app["sheets"]
    field = next((k for k in ("tag", "urgent", "due", "team") if k in d), None)
    await _check(request, d.get("id", ""), None if field else d.get("parent"))
    try:
        if field:
            await db(s.set_task, d.get("id", ""), field, str(d[field] or "").strip())
        else:
            await db(s.move_task, d.get("id", ""), (d.get("parent") or "").strip())
    except ValueError as e:
        return web.json_response({"error": str(e)}, status=400)
    return web.json_response({"ok": True})


async def chat_post(request):
    import assistant
    if not assistant.enabled():
        return web.json_response({"error": "Railway дээр ANTHROPIC_API_KEY тохируулаагүй байна"}, status=503)
    history = (await request.json()).get("messages") or []
    history = [m for m in history if m.get("role") in ("user", "assistant") and isinstance(m.get("content"), str)]
    if not history or history[-1]["role"] != "user":
        return web.json_response({"error": "Хоосон байна"}, status=400)
    try:
        text, actions = await assistant.chat(request.app["sheets"], history, request["me"])
    except Exception as e:
        return web.json_response({"error": f"Туслах алдаа: {e}"}, status=502)
    return web.json_response({"text": text, "actions": actions})


async def acts_get(request):
    return web.json_response(
        await db(request.app["sheets"].get_acts, request.query.get("q", "")))


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
    act_id = await db(sheets.next_act_id)
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

    await db(sheets.add_act, act_id, date, f, items, link)
    await db(sheets.add_log, f"Акт {act_id}: {f['src']} → {f['dst']} — {summary}", "", "", request["me"])
    return _pdf(pdf, f"{act_id}.pdf", **{"X-Act-Id": act_id})


def make_app(sheets, bot=None) -> web.Application:
    app = web.Application(middlewares=[auth], client_max_size=80 * 1024 * 1024)
    app["sheets"], app["bot"] = sheets, bot
    app.router.add_get("/", index)
    app.router.add_post("/auth/google", login)
    app.router.add_post("/auth/logout", logout)
    app.router.add_get("/api/me", me_get)
    app.router.add_get("/api/log", log_get)
    app.router.add_post("/api/log", log_post)
    app.router.add_get("/api/report.pdf", report_pdf)
    app.router.add_get("/api/tasks", tasks_get)
    app.router.add_post("/api/tasks", tasks_post)
    app.router.add_post("/api/tasks/done", tasks_done)
    app.router.add_post("/api/tasks/move", tasks_move)
    app.router.add_get("/api/tasks/notes", notes_get)
    app.router.add_post("/api/tasks/notes", notes_post)
    app.router.add_post("/api/chat", chat_post)
    app.router.add_post("/api/log/tag", log_tag)
    app.router.add_post("/api/tasks/photo", task_photo)
    app.router.add_get("/photos/{name}", photo_get)
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
