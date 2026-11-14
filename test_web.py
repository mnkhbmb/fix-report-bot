"""Вэб API-г санах ойн хуурамч sheet-ээр шалгана (Google, Discord хүрэхгүй)."""
import asyncio, io
from aiohttp import FormData
from aiohttp.test_utils import TestClient, TestServer
from PIL import Image
import web


class FakeSheets:
    def __init__(self):
        self.log, self.tasks, self.acts = [], [], []
    def add_log(self, text, date=""): self.log.append({"date": date or "2026-11-14", "time": "10:00", "text": text})
    def get_log(self, month): return [e for e in self.log if e["date"].startswith(month)]
    def add_task(self, text):
        tid = f"T-{len(self.tasks)+1:04d}"
        self.tasks.append({"id": tid, "text": text, "status": "Хийх", "created": "", "done": "", "note": ""})
        return tid
    def get_tasks(self): return self.tasks
    def finish_task(self, tid, note):
        t = next((t for t in self.tasks if t["id"] == tid), None)
        if not t: return None
        t.update(status="Хийсэн", note=note); self.add_log(f"Дууссан: {t['text']} — {note}")
        return t["text"]
    def next_act_id(self): return f"ACT-{len(self.acts)+1:04d}"
    def add_act(self, act_id, date, f, items, link):
        self.acts += [{"Акт ID": act_id, "Хаашаа": f["dst"], "Зүйл": i["item"], "Серийн дугаар": i["serial"]} for i in items]
    def get_acts(self, q=""): return [a for a in self.acts if q.lower() in " ".join(a.values()).lower()]


async def main():
    assert web.parse_items(["PC", "", "Монитор"], ["12", "1", "x"], ["SN1", "", " M7 "]) == [
        {"item": "PC", "qty": 12, "serial": "SN1"}, {"item": "Монитор", "qty": 1, "serial": "M7"}]

    web.PIN = "1234"
    s = FakeSheets()
    async with TestClient(TestServer(web.make_app(s))) as c:
        assert (await c.get("/")).status == 200                      # хуудас PIN-гүй нээгдэнэ
        assert (await c.get("/api/tasks")).status == 401             # API PIN-тэй
        H = {"X-PIN": "1234"}

        assert (await c.post("/api/log", json={"text": "Lof 4 тог баригч солисон"}, headers=H)).status == 200
        assert (await c.post("/api/log", json={"text": "a\n\nb", "date": "2026-11-13"}, headers=H)).status == 200
        assert [e["text"] for e in s.log if e["date"] == "2026-11-13"] == ["a", "b"]
        assert (await c.post("/api/log", json={"text": "x", "date": "13/11"}, headers=H)).status == 400
        tid = (await (await c.post("/api/tasks", json={"text": "Дархан руу PC бэлдэх"}, headers=H)).json())["id"]
        assert (await c.post("/api/tasks/done", json={"id": tid, "note": "12 ширхэг бэлэн"}, headers=H)).status == 200
        assert s.tasks[0]["status"] == "Хийсэн" and "12 ширхэг бэлэн" in s.log[-1]["text"]

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

        found = await (await c.get("/api/acts?q=дархан", headers=H)).json()
        assert found and found[0]["Акт ID"] == "ACT-0001"

        r = await c.get("/api/report.pdf?month=2026-11", headers=H)
        rep = await r.read(); assert rep.startswith(b"%PDF")
        open("test_report.pdf", "wb").write(rep)
    print("ok — test_act.pdf, test_report.pdf")

if __name__ == "__main__":
    asyncio.run(main())
