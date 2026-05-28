# Discord Bot — Бүтэн Системийн Баримт бичиг

## Ерөнхий тойм

Энэ систем нь **2 тусдаа bot**-аас бүрдэнэ:

---

## 🤖 Bot 1 — AI Тусламжийн Bot (`helper-bot`)

### Зорилго
Ажилтан, шинэ ажилчдын асуултад **Claude AI** ашиглан автоматаар хариулдаг bot.

### Технологи
- Python + discord.py
- Anthropic Claude Haiku API
- RAG (knowledge base дотроос хайж хариулдаг)

### Файлын бүтэц
```
helper-bot/
├── bot.py              # Bot-ын үндсэн файл — #helper-boy channel сонсдог
├── ai_client.py        # Claude API-тай холбогддог
├── knowledge_base.py   # .txt .md .pdf файл уншиж хайдаг
├── requirements.txt
├── .env
└── knowledge/
    └── example_faq.md  # Мэдлэгийн сан — өөрийн файлаа энд хийнэ
```

### Команд / Ажиллах байдал
| Үйлдэл | Тайлбар |
|--------|---------|
| `#helper-boy` channel-д мессеж бичих | Bot автоматаар хариулна |

### .env тохиргоо
```env
DISCORD_TOKEN=...
ANTHROPIC_API_KEY=...
HELP_CHANNEL_NAME=helper-boy
```

### Ажиллуулах
```bash
python -m pip install -r requirements.txt
python bot.py
```

---

## 🔧 Bot 2 — Засварын Бүртгэлийн Bot (`fix-report-bot`)

### Зорилго
Салбараас засварт явуулсан тоног төхөөрөмжийг бүртгэж, Google Sheet-д хадгалдаг. Засварын газар хүлээж авч, тус бүрийг засварлаж дуусгахад автоматаар шинэчлэгддэг.

### Технологи
- Python + discord.py (slash commands)
- Google Sheets API
- Service Account authentication

### Файлын бүтэц
```
fix-report-bot/
├── bot.py              # Slash командууд
├── sheets.py           # Google Sheets клиент (3 tab)
├── requirements.txt
├── .env
└── credentials.json    # Google Service Account key
```

### .env тохиргоо
```env
DISCORD_TOKEN=...
GOOGLE_SHEET_ID=...
GOOGLE_CREDS_FILE=credentials.json
REPAIR_CHANNEL_NAME=helper-boy
```

---

## 📊 Google Sheet бүтэц (3 tab)

### [Repairs] tab — Засварлаж байгаа зүйлс
| REP ID | SHP ID | Салбар | Зүйл | Тоо | Бүртгэсэн | Огноо | Статус |
|--------|--------|--------|------|-----|-----------|-------|--------|
| REP-0001 | SHP-0001 | Дархан | mouse | 1 | user#1234 | 2026-05-20 | Хүлээж авсан |

**Статус:** `Хүлээгдэж байна` → `Хүлээж авсан` → (Fixed tab руу шилжинэ)

### [Fixed] tab — Дууссан засварууд
| REP ID | SHP ID | Салбар | Зүйл | Тоо | Бүртгэсэн | Бүртгэсэн огноо | Засварласан хүн | Засварласан огноо | Тайлбар |
|--------|--------|--------|------|-----|-----------|-----------------|-----------------|-------------------|---------|
| REP-0001 | SHP-0001 | Дархан | mouse | 1 | ... | ... | user#5678 | 2026-05-21 | Солив |

### [Shipments] tab — Илгээлтийн бүртгэл
| SHP ID | Салбар | Бүртгэсэн | Огноо | Статус | Хүлээж авсан хүн | Хүлээж авсан огноо | Тайлбар |
|--------|--------|-----------|-------|--------|-------------------|--------------------|---------|
| SHP-0001 | Дархан | user#1234 | 2026-05-20 | Дууссан | user#5678 | 2026-05-21 | |

**Статус:** `Илгээсэн` → `Хүлээж авсан` → `Дууссан`

---

## 💬 Slash Командууд

### `/shipment` — Салбараас засварт явуулах
```
/shipment branch:Дархан items:1 mouse, 2 keyboard, 10 чихэвч notes:яаралтай
```
**Үр дүн:**
- `SHP-0001` үүснэ → Shipments tab-д орно (`Илгээсэн`)
- Зүйл бүрт REP ID үүснэ → Repairs tab-д орно
  - `REP-0001` — 1ш mouse
  - `REP-0002` — 2ш keyboard
  - `REP-0003` — 10ш чихэвч

---

### `/received` — Засварын газар хүлээж авсан
```
/received SHP-0001
```
**Үр дүн:**
- `SHP-0001` → `Хүлээж авсан` болно
- Холбоотой бүх REP → `Хүлээж авсан` болно

---

### `/fix` — Тухайн зүйлийн засвар дууссан
```
/fix REP-0001 notes:Шинэ mouse солив
```
**Үр дүн:**
- `REP-0001` Repairs tab-аас **устаж** Fixed tab-д **нэмэгдэнэ**
- Хэрэв SHP-ийн бүх REP дуусвал → SHP автоматаар `Дууссан` болно 🎉

---

### `/status` — Статус шалгах
```
/status SHP-0001    ← бүх REP-ийн явцтай харуулна
/status REP-0001    ← тухайн зүйлийн дэлгэрэнгүй
```

---

## 🔄 Бүтэн Workflow жишээ

```
САЛБАР                          ЗАСВАРЫН ГАЗАР
──────────────────────────────────────────────────────

1. /shipment branch:Дархан
   items:1 mouse, 2 keyboard

   → SHP-0001 үүснэ (Илгээсэн)
   → REP-0001 mouse    ┐ Repairs tab
   → REP-0002 keyboard ┘

2.                              /received SHP-0001
                                → SHP-0001: Хүлээж авсан
                                → REP-0001: Хүлээж авсан
                                → REP-0002: Хүлээж авсан

3.                              /fix REP-0001 notes:Солив
                                → REP-0001: Repairs-аас хасагдаж
                                            Fixed-д нэмэгдэнэ ✅
                                → SHP: 1 засвар үлдсэн

4.                              /fix REP-0002
                                → REP-0002: Fixed-д нэмэгдэнэ ✅
                                → SHP-0001: Дууссан 🎉
```

---

## ⚙️ Google Sheet тохируулах

### Service Account үүсгэх
1. [console.cloud.google.com](https://console.cloud.google.com) → шинэ project
2. **APIs & Services → Enable APIs** → `Google Sheets API` идэвхжүүлнэ
3. **IAM & Admin → Service Accounts → Create**
4. **Keys → Add Key → JSON** → `credentials.json` болгон хадгална
5. Google Sheet → **Share** → `client_email`-д **Editor** эрх өгнө

### Sheet ID олох
```
https://docs.google.com/spreadsheets/d/ [SHEET_ID_ЭНД] /edit
```

---

## 🚀 Суулгаж ажиллуулах

```bash
# 1. Package суулгах
python -m pip install -r requirements.txt

# 2. .env файл бөглөх
# (DISCORD_TOKEN, GOOGLE_SHEET_ID, ANTHROPIC_API_KEY, etc.)

# 3. credentials.json файлыг folder-т хийх

# 4. Ажиллуулах
python bot.py
```

### Амжилттай нэвтэрсний дараа:
```
✅  Slash командууд sync хийгдлээ
✅  Bot нэвтэрлээ: alwaysSaturday#4931
💬  Channel: #helper-boy
```

---

## 📦 Requirements

```
discord.py>=2.3.0
anthropic>=0.25.0          # helper-bot-д
google-auth>=2.20.0
google-api-python-client>=2.90.0
python-dotenv>=1.0.0
pdfplumber>=0.10.0         # PDF уншихад (заавал биш)
```

---

## 🐛 Нийтлэг алдаа ба шийдэл

| Алдаа | Шийдэл |
|-------|--------|
| `KeyError: 'DISCORD_TOKEN'` | `.env` файл bot.py-тай ижил folder-т байгааг шалгана |
| `pip` ажиллахгүй | `python -m pip install ...` гэж ашиглана |
| `.env` олдохгүй | `env.env` → `.env` болгон нэрийг өөрчилнө |
| `KeyError: 'GOOGLE_SHEET_ID'` | `sheets.py`-д `load_dotenv()` нэмнэ |
| Sheet permission алдаа | `credentials.json`-ий `client_email`-г Sheet-д share хийсэн эсэхийг шалгана |
| Slash команд харагдахгүй | Хэдэн минут хүлээнэ эсвэл bot-ыг дахин invite хийнэ |
