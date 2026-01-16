import os
import json
from dotenv import load_dotenv
import requests
from fastapi import FastAPI
from pydantic import BaseModel

# .env файлыг унших
load_dotenv("key.env")

SERPER_API_KEY = os.getenv("SERPER_API_KEY")
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")

if not SERPER_API_KEY or not DEEPSEEK_API_KEY:
    raise RuntimeError("Missing SERPER_API_KEY or DEEPSEEK_API_KEY env vars")

SERPER_URL = "https://google.serper.dev/search"
DEEPSEEK_URL = "https://api.deepseek.com/chat/completions"

app = FastAPI(title="CallerGuard Backend")

class Req(BaseModel):
    phone_number: str

# 1️⃣ Хүчтэй Монгол шалгуур
def is_strict_mongolian(text: str) -> bool:
    """Snippet-д кирилл үсэг давамгай байх эсэхийг шалгана"""
    mongolian_chars = sum(1 for c in text if '\u0400' <= c <= '\u04FF')  # Кирилл
    alpha_chars = sum(1 for c in text if c.isalpha())
    return alpha_chars > 0 and (mongolian_chars / alpha_chars) >= 0.7  # >=70% кирилл

# 2️⃣ Зөвхөн Монгол үсэг авах
def extract_mongolian_text(text: str) -> str:
    return ''.join([c if '\u0400' <= c <= '\u04FF' or c == ' ' else ' ' for c in text]).strip()

@app.post("/analyze")
def analyze(req: Req):
    phone = req.phone_number.strip().replace(" ", "").replace("-", "")
    local8 = phone[4:] if phone.startswith("+976") else phone
    query = f"\"{phone}\" OR \"{local8}\""

    # Google search via Serper
    serper_headers = {
        "X-API-KEY": SERPER_API_KEY,
        "Content-Type": "application/json",
    }
    serper_body = {"q": query, "gl": "mn", "hl": "mn"}

    s = requests.post(SERPER_URL, headers=serper_headers, json=serper_body, timeout=20)
    s.raise_for_status()
    serp = s.json()

    # Organic үр дүнг шүүх
    organic_all = serp.get("organic", [])
    organic = [
        r for r in organic_all
        if r.get("snippet") and is_strict_mongolian(r["snippet"])
    ][:10]  # эхний 10 snippet
    for r in organic:
        r['snippet'] = extract_mongolian_text(r['snippet'])

    # People Also Ask үр дүнг шүүх
    people_all = serp.get("peopleAlsoAsk", [])
    people_also_ask = [
        p for p in people_all
        if p.get("snippet") and is_strict_mongolian(p["snippet"])
    ][:6]
    for p in people_also_ask:
        p['snippet'] = extract_mongolian_text(p['snippet'])

    # Хэрвээ Монгол мэдээлэл олдоогүй бол шууд мэдэгдэл
    if not organic and not people_also_ask:
        return {
            "phone_number": phone,
            "summary": "Олон нийтэд ил мэдээлэл олдсонгүй, уг дугаарын үйл ажиллагааг тодорхойлох боломжгүй байна.",
            "found_information": [],
            "sources": []
        }

    # Мэдээллийг жагсаах
    found_info = []
    context_lines = []

    for r in organic:
        item = {
            "title": r.get("title", ""),
            "snippet": r.get("snippet", ""),
            "link": r.get("link", "")
        }
        found_info.append(item)
        context_lines.append(f"- {item['title']} | {item['snippet']}")

    for p in people_also_ask:
        item = {
            "title": p.get("question", ""),
            "snippet": p.get("snippet", ""),
            "link": p.get("link", "")
        }
        found_info.append(item)
        context_lines.append(f"- {item['title']} | {item['snippet']}")

    context = "\n".join(context_lines)

    # 2️⃣ DeepSeek prompt (зөвхөн олдсон snippet-г илгээх)
    summary = "Олон нийтэд ил мэдээлэл олдсонгүй, уг дугаарын үйл ажиллагааг тодорхойлох боломжгүй байна."
    if context:  # snippet байгаа үед л DeepSeek рүү явуулах
        ds_headers = {
            "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
            "Content-Type": "application/json",
        }

        prompt = f"""
Та бол утасны дугаарын талаарх мэдээллийг нэгтгэн дүгнэдэг туслах.
- ЯГ 2–3 өгүүлбэртэй. Урт өгүүлбэр хэрэггүй товч тодорхой.
- Монгол хэлээр
- "энэ дугаарын эзэн иймэрхүү зүйлс цахим сүлжээнд тавьсан учир ийм хүн байж магадгүй" гэсэн хэлбэрээр дүгнэлт гарга.

Хэрвээ мэдээлэл хангалтгүй бол:
"Олон нийтэд ил мэдээлэл олдсонгүй, уг дугаарын үйл ажиллагааг тодорхойлох боломжгүй байна." гэж бич.

Хайлтын snippet-үүд:
{context}
""".strip()

        ds_body = {
            "model": "deepseek-chat",
            "messages": [
                {"role": "user", "content": prompt},
            ],
            "max_tokens": 200,
            "stream": False,
        }

        d = requests.post(DEEPSEEK_URL, headers=ds_headers, json=ds_body, timeout=25)
        d.raise_for_status()
        ds = d.json()

        summary = ds["choices"][0]["message"]["content"].strip()

    sources = [r.get("link") for r in organic if r.get("link")]

    return {
        "phone_number": phone,
        "summary": summary,
        "found_information": found_info[:6],
        "sources": sources[:5]
    }
