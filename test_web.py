"""Вэб API-г санах ойн хуурамч sheet-ээр шалгана (Google, Discord хүрэхгүй)."""
import asyncio, io, json
from aiohttp import FormData
from aiohttp.test_utils import TestClient, TestServer
from PIL import Image
import web
import sheets as sh


class MemSheets(sh.SheetsClient):
    """Жинхэнэ SheetsClient логик, зөвхөн хадгалалт нь санах ойд."""
    def __init__(self):
        self.data = {sh.TAB_LOG: [sh.LOG_HEADERS], sh.TAB_TASK: [sh.TASK_HEADERS], sh.TAB_ACT: [sh.ACT_HEADERS], sh.TAB_NOTE: [sh.NOTE_HEADERS]}
    def _get_rows(self, tab, sheet_id=None): return [list(r) for r in self.data[tab]]
    def _append_row(self, tab, row, sheet_id=None): self.data[tab].append(list(row))
    def _update_row(self, tab, n, values, sheet_id=None): self.data[tab][n - 1] = list(values)
    def _update_cell(self, tab, n, col, value, sheet_id=None):
        r = self.data[tab][n - 1]; i = ord(col) - 65
        r += [""] * (i + 1 - len(r)); r[i] = value
    def add_act(self, act_id, date, f, items, link):
        for it in items:
            self._append_row(sh.TAB_ACT, [act_id, date, f["src"], f["dst"], f["giver"], f["receiver"],
                                          it["item"], str(it["qty"]), it["serial"], f["notes"], link])
    @property
    def log(self): return self.get_log("0000", "9999")


async def main():
    assert web.parse_items(["PC", "", "Монитор"], ["12", "1", "x"], ["SN1", "", " M7 "]) == [
        {"item": "PC", "qty": 12, "serial": "SN1"}, {"item": "Монитор", "qty": 1, "serial": "M7"}]

    web.PIN = "1234"
    s = MemSheets()
    assert web.day_label("2026-11-14") == "2026-11-14 · Бямба · 46-р 7 хоног"
    async with TestClient(TestServer(web.make_app(s))) as c:
        assert (await c.get("/")).status == 200                      # хуудас PIN-гүй нээгдэнэ
        assert (await c.get("/api/tasks")).status == 401             # API PIN-тэй
        H = {"X-PIN": "1234"}

        assert (await c.post("/api/log", json={"text": "Lof 4 тог баригч солисон"}, headers=H)).status == 200
        assert (await c.post("/api/log", json={"text": "a\n\nb", "date": "2026-11-13"}, headers=H)).status == 200
        assert [e["text"] for e in s.log if e["date"] == "2026-11-13"] == ["a", "b"]
        assert (await c.post("/api/log", json={"text": "x", "date": "13/11"}, headers=H)).status == 400
        # tag: автомат (Lof), гараар (Crystal), шүүлт, 7 хоногийн хүрээ
        assert (await c.post("/api/log", json={"text": "Domofon", "date": "2026-11-10", "tag": "Crystal"}, headers=H)).status == 200
        wk = await (await c.get("/api/log?from=2026-11-09&to=2026-11-15", headers=H)).json()
        assert {e["text"]: e["tag"] for e in wk}["Lof 4 тог баригч солисон"] == "Lof"
        assert [e["text"] for e in wk if e["tag"] == "Crystal"] == ["Domofon"]
        only = await (await c.get("/api/log?from=2026-11-09&to=2026-11-15&tag=lof", headers=H)).json()
        assert [e["text"] for e in only] == ["Lof 4 тог баригч солисон"]
        assert (await c.get("/api/log?from=2026-11-14&to=2026-11-14", headers=H)).status == 200
        assert (await c.get("/api/log?from=bad", headers=H)).status == 400

        # main / sub ажил
        tid = (await (await c.post("/api/tasks", json={"text": "Дархан руу PC бэлдэх"}, headers=H)).json())["id"]
        sub = (await (await c.post("/api/tasks", json={"text": "SSD шалгах", "parent": tid}, headers=H)).json())["id"]
        assert (await c.post("/api/tasks", json={"text": "x", "parent": sub}, headers=H)).status == 400   # sub-ийн sub болохгүй
        assert (await c.post("/api/tasks", json={"text": "x", "parent": "T-9999"}, headers=H)).status == 400
        # main-ийг өөр main-ийн sub болгох / буцаах
        mv = lambda i, p: c.post("/api/tasks/move", json={"id": i, "parent": p}, headers=H)
        other = (await (await c.post("/api/tasks", json={"text": "Kiosk авах"}, headers=H)).json())["id"]
        assert (await mv(other, tid)).status == 200
        assert {t["id"]: t for t in s.get_tasks()}[other]["parent"] == tid
        assert (await mv(tid, other)).status == 400      # sub-ийн доор орохгүй (ганц түвшин)
        assert (await mv(other, other)).status == 400
        assert (await mv(other, "")).status == 200
        assert {t["id"]: t for t in s.get_tasks()}[other]["parent"] == ""
        # 2 main нэгтгэх: sub-тай tid-г other руу → tid болон түүний sub хоёулаа other-ийн доор
        assert (await mv(tid, other)).status == 200
        p = {t["id"]: t["parent"] for t in s.get_tasks()}
        assert p[tid] == other and p[sub] == other
        assert (await mv(tid, "")).status == 200 and (await mv(sub, tid)).status == 200   # буцааж тавина
        assert (await mv(other, "")).status == 200
        assert (await c.post("/api/tasks/done", json={"id": sub, "note": "7 ширхэг"}, headers=H)).status == 200
        assert s.log[-1]["text"] == "Дууссан: Дархан руу PC бэлдэх › SSD шалгах — 7 ширхэг"
        assert (await c.post("/api/tasks/done", json={"id": tid, "note": "12 ширхэг бэлэн"}, headers=H)).status == 200
        t = {t["id"]: t for t in s.get_tasks()}
        assert t[tid]["status"] == "Хийсэн" and t[sub]["parent"] == tid and "12 ширхэг бэлэн" in s.log[-1]["text"]

        # ажлын tag: гараар → sub өвлөнө → дуусахад тайланд тэр tag-аар орно; солих / автомат / tag-гүй
        vm = (await (await c.post("/api/tasks", json={"text": "Уулзалт", "tag": "Viot"}, headers=H)).json())["id"]
        vs = (await (await c.post("/api/tasks", json={"text": "Слайд", "parent": vm}, headers=H)).json())["id"]
        tg = lambda: {t["id"]: t["tag"] for t in s.get_tasks()}
        assert tg()[vm] == tg()[vs] == "Viot" and tg()[tid] == ""
        assert (await c.post("/api/tasks/done", json={"id": vs}, headers=H)).status == 200
        assert s.log[-1]["tag"] == "Viot"
        tt = lambda i, x: c.post("/api/tasks/move", json={"id": i, "tag": x}, headers=H)
        assert (await tt(vm, "Lof")).status == 200 and tg()[vs] == "Lof"
        assert (await tt(vs, "-")).status == 200 and tg()[vs] == ""
        assert (await tt("T-9999", "Lof")).status == 400
        # 📝 ажлын тэмдэглэл
        nt = lambda i, x: c.post("/api/tasks/notes", json={"id": i, "text": x}, headers=H)
        assert (await nt(vm, "Утсаар ярьсан, маргааш уулзана")).status == 200
        assert (await nt(vm, " ")).status == 400 and (await nt("T-9999", "x")).status == 404
        ns = await (await c.get(f"/api/tasks/notes?id={vm}", headers=H)).json()
        assert [n["text"] for n in ns] == ["Утсаар ярьсан, маргааш уулзана"] and ns[0]["time"]
        # яаралтай + дуусах хугацаа
        uj = (await (await c.post("/api/tasks", json={"text": "Сервер унасан", "urgent": True, "due": "2026-11-16"}, headers=H)).json())["id"]
        t = {x["id"]: x for x in s.get_tasks()}[uj]
        assert (t["urgent"], t["due"]) == ("1", "2026-11-16")
        assert (await c.post("/api/tasks", json={"text": "x", "due": "16/11"}, headers=H)).status == 400
        st = lambda **kw: c.post("/api/tasks/move", json={"id": uj, **kw}, headers=H)
        assert (await st(urgent="")).status == 200 and (await st(due="")).status == 200
        assert (await st(due="bad")).status == 400
        t = {x["id"]: x for x in s.get_tasks()}[uj]
        assert (t["urgent"], t["due"]) == ("", "")

        img = io.BytesIO(); Image.new("RGB", (3000, 2000), "red").save(img, "JPEG")
        fd = FormData()
        for k, v in [("src", "10-цирк"), ("dst", "Дархан"), ("giver", "Мөнхбямба"), ("receiver", "Бат"),
                     ("notes", "1 case эвдэрсэн"), ("item", "PC"), ("qty", "12"), ("serial", "SN1, SN2")]:
            fd.add_field(k, v)
        fd.add_field("photos", img.getvalue(), filename="a.jpg", content_type="image/jpeg")
        r = await c.post("/api/act", data=fd, headers=H)
        assert r.status == 200 and r.headers["X-Act-Id"] == "ACT-0001", await r.text()
        pdf = await r.read(); assert pdf.startswith(b"%PDF")
        open("test_act.pdf", "wb").write(pdf)
        assert "Дархан" in s.log[-1]["text"]                          # акт тайланд орсон

        # ажил дээр зураг: хадгална, PIN-гүй нээгдэнэ, буруу нэр 404
        import tempfile
        web.PHOTO_DIR = tempfile.mkdtemp()
        fd = FormData(); fd.add_field("id", tid)
        for _ in range(2):
            fd.add_field("photos", img.getvalue(), filename="a.jpg", content_type="image/jpeg")
        r = await c.post("/api/tasks/photo", data=fd, headers=H)
        names = (await r.json())["photos"]
        assert r.status == 200 and len(names) == 2
        assert {t["id"]: t for t in s.get_tasks()}[tid]["photos"] == ",".join(names)
        assert (await c.get("/photos/" + names[0])).status == 200
        assert (await c.get("/photos/..%2Fsheets.py")).status == 404
        assert (await c.get("/photos/" + "0" * 32 + ".jpg")).status == 404
        fd = FormData(); fd.add_field("id", "T-9999"); fd.add_field("photos", img.getvalue(), filename="a.jpg")
        assert (await c.post("/api/tasks/photo", data=fd, headers=H)).status == 404

        found = await (await c.get("/api/acts?q=дархан", headers=H)).json()
        assert found and found[0]["Акт ID"] == "ACT-0001"

        r = await c.get("/api/report.pdf?month=2026-11", headers=H)
        rep = await r.read(); assert rep.startswith(b"%PDF")
        open("test_report.pdf", "wb").write(rep)
    # 🎤 туслахын tool-ууд (Claude дуудахгүй — зөвхөн гүйцэтгэл)
    import assistant
    acts = []
    tid = assistant.run_tool(s, "add_task", {"text": "Гаражийн камер"}, acts).split(": ")[1]
    assert any(t["id"] == tid for t in json.loads(assistant.run_tool(s, "list_tasks", {}, acts)))
    assert assistant.run_tool(s, "finish_task", {"id": "T-9999"}, acts) == "Ажил олдсонгүй"
    assistant.run_tool(s, "add_log", {"text": "Viot уулзалт", "date": "2026-11-12"}, acts)
    assert json.loads(assistant.run_tool(s, "get_log", {"start": "2026-11-12", "end": "2026-11-12"}, acts))[0]["tag"] == "Viot"
    # бичлэгийг өөр tag руу шилжүүлэх
    e = s.get_log("2026-11-12", "2026-11-12")[0]
    assistant.run_tool(s, "set_log_tag", {"row": e["row"], "text": e["text"], "tag": "Crystal"}, acts)
    assert s.get_log("2026-11-12", "2026-11-12", "crystal")[0]["text"] == "Viot уулзалт"
    s.set_log_tag(e["row"], e["text"], "-"); assert s.get_log("2026-11-12", "2026-11-12")[0]["tag"] == ""
    s.set_log_tag(e["row"], e["text"], ""); assert s.get_log("2026-11-12", "2026-11-12")[0]["tag"] == "Viot"
    try:
        s.set_log_tag(e["row"], "өөр текст", "Lof"); assert False   # мөр шилжсэн бол бичихгүй
    except ValueError:
        pass
    # тайлангийн 2 бичлэг нэгтгэх / салгах
    s.add_log("Viot дизайн", "2026-11-12")
    kid = [x for x in s.get_log("2026-11-12", "2026-11-12") if x["text"] == "Viot дизайн"][0]
    s.set_log_parent(kid["row"], kid["text"], e["text"])
    assert [x["parent"] for x in s.get_log("2026-11-12", "2026-11-12")] == ["", "Viot уулзалт"]
    s.set_log_parent(kid["row"], kid["text"], "")
    assert s.get_log("2026-11-12", "2026-11-12")[1]["parent"] == ""
    assistant.run_tool(s, "prepare_act", {"src": "10-цирк", "dst": "Дархан", "items": [{"item": "PC", "qty": 12}]}, acts)
    assert acts[0]["type"] == "prepare_act" and acts[0]["items"][0]["qty"] == 12
    try:
        assistant.run_tool(s, "add_log", {"text": "x", "date": "13/11"}, acts); assert False
    except ValueError:
        pass
    print("ok — test_act.pdf, test_report.pdf")

if __name__ == "__main__":
    asyncio.run(main())
