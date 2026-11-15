"""
assistant.py — 🎤 Туслах: монголоор хэлсэн/бичсэнийг ажил, тайлан, акт болгоно (Claude API).
Sheet-д бичихээс өмнө хэрэглэгчээс баталгаажуулалт авна (system prompt-оор).
"""
import asyncio
import json
import os
from datetime import datetime

from sheets import TAGS, db

MODEL = "claude-opus-5-5"
WD = ["Даваа", "Мягмар", "Лхагва", "Пүрэв", "Баасан", "Бямба", "Ням"]

SYSTEM = f"""Чи The Lof интернэт кафены IT ажилтны ажлын туслах. Хэрэглэгч монголоор (заримдаа латинаар, \
заримдаа дуу хоолойгоор бичигдсэн алдаатай текстээр) ярина. Чи үргэлж товч, кирилл монголоор хариулна.

Хийж чадах зүйл: хийх ажил нэмэх (main эсвэл өөр main-ийн sub), ажил дуусгах, ажлыг өөр main-ийн доор зөөх, \
өдрийн тайланд бичлэг нэмэх, тайлан харах/PDF гаргах, хүлээлцэх акт бэлдэх, өмнөх актаас хайх.

Дүрэм:
- Sheet-д бичих үйлдлийн өмнө (add_task, finish_task, move_task, add_log, set_log_tag) юу бичихээ товч жагсаагаад \
"Зөв үү?" гэж асуу. Хэрэглэгч зөвшөөрсний ДАРАА л tool дууд. Унших tool-уудыг шууд дуудаж болно.
- Дутуу мэдээллийг эргэж асуу: акт бол хаанаас, хаашаа, юу, хэдэн ширхэг, серийн дугаар (байвал), \
хэн өгч хэн авсан; ажил дуусгах бол аль ажил, юу хийж дуусгасан.
- Ажлын ID-г таамаглахгүй — эхлээд list_tasks дуудаж ол.
- Нэг хэлсэн зүйлд олон ажил байвал тус бүрээр нь салга. Нэг ажлын жижиг алхмууд бол sub болгохыг санал болго.
- Дуу хоолойгоор бичигдсэн тул нэр, тоо, серийн дугаарыг давтаж баталгаажуул.
- Огноо: "өчигдөр", "энэ 7 хоног" гэхийг өнөөдрөөс тооцоол. 7 хоног = Даваа–Ням.
- Салбарууд: түмэн, 2-спортын-төв-ордон, 3-энхтайваны-төв-ордон, 4-муис, 4-ps, 8-19, 9-суис, 10-цирк, Дархан.
- Tag: {", ".join(TAGS)} (текстэд байвал автомат, өөр tag хэрэглэгч хэлбэл тавь)."""

_str = {"type": "string"}
TOOLS = [
    {"name": "list_tasks", "description": "Хийх (дуусаагүй) ажлууд ба тэдгээрийн main/sub бүтэц.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "add_task", "description": "Ажил нэмнэ. parent = main ажлын ID (sub бол), эс бөгөөс хоосон. "
     "tag = салбар/төсөл (жш Lof, Viot); хоосон бол автомат. urgent = яаралтай эсэх, due = дуусах огноо YYYY-MM-DD.",
     "input_schema": {"type": "object", "properties": {"text": _str, "parent": _str, "tag": _str,
                                                      "urgent": {"type": "boolean"}, "due": _str}, "required": ["text"]}},
    {"name": "finish_task", "description": "Ажлыг дуусгана, тайланд автоматаар бичигдэнэ.",
     "input_schema": {"type": "object", "properties": {"id": _str, "note": _str}, "required": ["id"]}},
    {"name": "move_task", "description": "Ажлыг өөр main-ийн sub болгоно (parent хоосон = main болгоно).",
     "input_schema": {"type": "object", "properties": {"id": _str, "parent": _str}, "required": ["id", "parent"]}},
    {"name": "add_log", "description": "Тайланд хийсэн ажлын бичлэг нэмнэ. date=YYYY-MM-DD (хоосон = өнөөдөр).",
     "input_schema": {"type": "object", "properties": {"text": _str, "date": _str, "tag": _str}, "required": ["text"]}},
    {"name": "get_log", "description": "Огнооны хүрээн дэх тайлангийн бичлэгүүд (YYYY-MM-DD, хоёулаа орно).",
     "input_schema": {"type": "object", "properties": {"start": _str, "end": _str, "tag": _str}, "required": ["start", "end"]}},
    {"name": "set_log_tag", "description": "Тайлангийн бичлэгийн tag-ийг солино. row, text-ийг get_log-оос ав. "
     "tag='' → автомат, '-' → tag-гүй.",
     "input_schema": {"type": "object", "properties": {"row": {"type": "integer"}, "text": _str, "tag": _str},
                      "required": ["row", "text", "tag"]}},
    {"name": "report_pdf", "description": "Хэрэглэгчийн утсанд тайлангийн PDF татуулна.",
     "input_schema": {"type": "object", "properties": {"start": _str, "end": _str, "tag": _str}, "required": ["start", "end"]}},
    {"name": "search_acts", "description": "Өмнөх актуудаас хайна (салбар, зүйл, серийн дугаар...).",
     "input_schema": {"type": "object", "properties": {"q": _str}, "required": ["q"]}},
    {"name": "prepare_act", "description": "Актын маягтыг бөглөж хэрэглэгчид харуулна. Хэрэглэгч зураг нэмээд өөрөө илгээнэ.",
     "input_schema": {"type": "object", "properties": {
         "src": _str, "dst": _str, "giver": _str, "receiver": _str, "notes": _str,
         "items": {"type": "array", "items": {"type": "object", "properties": {
             "item": _str, "qty": {"type": "integer"}, "serial": _str}, "required": ["item"]}}},
         "required": ["src", "dst", "items"]}},
]


def run_tool(sheets, name: str, a: dict, actions: list) -> str:
    """Tool-ийг гүйцэтгэнэ. Утсан дээр хийх зүйлийг (PDF, акт маягт) actions-д нэмнэ."""
    if name == "list_tasks":
        return json.dumps([t for t in sheets.get_tasks() if t["status"] != "Хийсэн"], ensure_ascii=False)
    if name == "add_task":
        return "Нэмэгдлээ: " + sheets.add_task(a["text"], a.get("parent", ""), a.get("tag", ""),
                                               "1" if a.get("urgent") else "", a.get("due", ""))
    if name == "finish_task":
        return "Дууслаа" if sheets.finish_task(a["id"], a.get("note", "")) is not None else "Ажил олдсонгүй"
    if name == "move_task":
        sheets.move_task(a["id"], a.get("parent", ""))
        return "Зөөгдлөө"
    if name == "add_log":
        datetime.strptime(a["date"], "%Y-%m-%d") if a.get("date") else None   # буруу огноо → алдаа
        sheets.add_log(a["text"], a.get("date", ""), a.get("tag", ""))
        return "Бичигдлээ"
    if name == "set_log_tag":
        sheets.set_log_tag(int(a["row"]), a["text"], a["tag"])
        return "Tag солигдлоо"
    if name == "get_log":
        return json.dumps(sheets.get_log(a["start"], a["end"], a.get("tag", "")), ensure_ascii=False)
    if name == "search_acts":
        return json.dumps(sheets.get_acts(a["q"])[:30], ensure_ascii=False)
    if name in ("report_pdf", "prepare_act"):
        actions.append({"type": name, **a})
        return "Хэрэглэгчийн дэлгэц дээр гарлаа"
    raise ValueError(f"Үл мэдэх tool: {name}")


async def chat(sheets, history: list[dict]) -> tuple[str, list]:
    """history = [{role, content: str}, ...] (утсан дээр хадгалагдана). → (хариу, actions)"""
    import anthropic
    client = anthropic.AsyncAnthropic()
    now = datetime.now()
    system = SYSTEM + f"\n\nӨнөөдөр: {now:%Y-%m-%d}, {WD[now.weekday()]}."
    messages = [{"role": m["role"], "content": m["content"]} for m in history[-30:]]   # ponytail: сүүлийн 30
    actions = []
    for _ in range(8):   # ponytail: нэг ээлжинд tool-ын 8 тойрог хангалттай
        r = await client.beta.messages.create(
            model=MODEL, max_tokens=16000, system=system, tools=TOOLS, messages=messages,
            output_config={"effort": "low"},          # чат — хурдан хариу
            betas=["server-side-fallback-2026-07-01"],
            extra_body={"fallbacks": "default"},      # татгалзвал өөр загвараар дахин
        )
        if r.stop_reason == "refusal":
            return "Уучлаарай, энэ хүсэлтийг гүйцэтгэж чадсангүй.", actions
        if r.stop_reason != "tool_use":
            break
        messages.append({"role": "assistant", "content": r.content})
        results = []
        for b in r.content:
            if b.type != "tool_use":
                continue
            try:
                out, err = await db(run_tool, sheets, b.name, b.input, actions), False
            except Exception as e:   # алдааг Claude-д буцааж, өөрөө засуулна
                out, err = f"Алдаа: {e}", True
            results.append({"type": "tool_result", "tool_use_id": b.id, "content": out, "is_error": err})
        messages.append({"role": "user", "content": results})
    text = "\n".join(b.text for b in r.content if b.type == "text").strip()
    return text or "Болсон.", actions


def enabled() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY"))
