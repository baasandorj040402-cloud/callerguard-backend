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
    raise RuntimeError("Missing SERPER_API_KEY or DEEPSEEK_API_KEY")

SERPER_URL = "https://google.serper.dev/search"
DEEPSEEK_URL = "https://api.deepseek.com/chat/completions"

app = FastAPI(title="CallerGuard Backend")

class Req(BaseModel):
    phone_number: str

@app.post("/analyze")
def analyze(req: Req):
    phone = req.phone_number.strip().replace(" ", "").replace("-", "")
    local8 = phone[4:] if phone.startswith("+976") else phone
    query = f"\"{phone}\" OR \"{local8}\""

    # 1) Google search via Serper
    serper_headers = {
        "X-API-KEY": SERPER_API_KEY,
        "Content-Type": "application/json",
    }
    serper_body = {
        "q": query,
        "gl": "mn",
        "hl": "mn"
    }

    s = requests.post(SERPER_URL, headers=serper_headers, json=serper_body, timeout=20)
    s.raise_for_status()
    serp = s.json()

    organic = serp.get("organic", [])[:6]
    people_also_ask = serp.get("peopleAlsoAsk", [])[:3]

    # Олдсон мэдээллийг жагсаах
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

    context = "\n".join(context_lines) if context_lines else "Олон нийтэд ил мэдээлэл олдсонгүй."

    # 2) DeepSeek-ээр дүгнэлт гаргуулах (зөвхөн 2–3 өгүүлбэр)
    ds_headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json",
    }

    prompt = f"""
Та бол утасны дугаарын талаарх мэдээллийг нэгтгэн дүгнэдэг туслах.

Доорх хайлтын мэдээлэлд тулгуурлан:
- ЯГ 2–3 өгүүлбэртэй
- Монгол хэлээр
- "энэ дугаар нь магадгүй ... төрлийн үйл ажиллагаа эрхэлдэг байж болох" гэсэн хэлбэрээр
дүгнэлт гарга.

Хэрвээ мэдээлэл хангалтгүй бол:
"Олон нийтэд ил мэдээлэл олдсонгүй, уг дугаарын үйл ажиллагааг тодорхойлох боломжгүй байна." гэж бич.

Хайлтаас олдсон мэдээлэл:
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

    # Эх сурвалжууд
    sources = [r.get("link") for r in organic if r.get("link")]

    return {
        "phone_number": phone,
        "summary": summary,
        "found_information": found_info[:6],
        "sources": sources[:5]
    }
