import os
import requests
import logging
from dotenv import load_dotenv
from fastapi import FastAPI
from pydantic import BaseModel

# -----------------------
# Logging тохиргоо
# -----------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)
logger = logging.getLogger(__name__)

# -----------------------
# .env файлыг унших
# -----------------------
load_dotenv("key.env")

SERPER_API_KEY = os.getenv("SERPER_API_KEY")
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")

if not SERPER_API_KEY or not DEEPSEEK_API_KEY:
    logger.error("Missing SERPER_API_KEY or DEEPSEEK_API_KEY")
    raise RuntimeError("Missing SERPER_API_KEY or DEEPSEEK_API_KEY")

SERPER_URL = "https://google.serper.dev/search"
DEEPSEEK_URL = "https://api.deepseek.com/chat/completions"

app = FastAPI(title="CallerGuard Backend")

# -----------------------
# Request model
# -----------------------
class Req(BaseModel):
    phone_number: str

# -----------------------
# Монгол текст шалгах функцууд
# -----------------------
def is_mongolian(text: str) -> bool:
    count = sum(1 for c in text if '\u0410' <= c <= '\u044F')  # unicode зөв
    return count >= 2

def extract_mongolian_text(text: str) -> str:
    return ''.join([c if '\u0410' <= c <= '\u044F' or c == ' ' else ' ' for c in text]).strip()  # unicode зөв

def has_phone_keywords(text: str) -> bool:
    t = text.lower()
    return "утас" in t or "дугаар" in t

# -----------------------
# Main endpoint
# -----------------------
@app.post("/analyze")
def analyze(req: Req):
    phone = req.phone_number.strip().replace(" ", "").replace("-", "")
    local8 = phone[4:] if phone.startswith("+976") else phone
    query = f"(\"{phone}\" OR \"{local8}\") (утас OR дугаар)"

    logger.info(f"Analyzing phone: {phone}")
    logger.info(f"Search query: {query}")

    # -----------------------
    # 1️⃣ Serper search
    # -----------------------
    serper_headers = {
        "X-API-KEY": SERPER_API_KEY,
        "Content-Type": "application/json",
    }
    serper_body = {"q": query, "gl": "mn", "hl": "mn"}

    try:
        s = requests.post(SERPER_URL, headers=serper_headers, json=serper_body, timeout=20)
        s.raise_for_status()
        serp = s.json()
        logger.info("Serper API call successful")
    except requests.exceptions.RequestException as e:
        logger.error("Serper API error", exc_info=True)
        return {
            "phone_number": phone,
            "error": "Serper хайлтын сервис рүү холбогдоход алдаа гарлаа."
        }

    organic_all = serp.get("organic", [])
    organic = [
        r for r in organic_all
        if r.get("snippet") and is_mongolian(r["snippet"]) and has_phone_keywords(r["snippet"])
    ][:6]

    for r in organic:
        r['snippet'] = extract_mongolian_text(r['snippet'])

    if not organic:
        logger.info("No relevant results found in Serper")
        return {
            "phone_number": phone,
            "summary": "Олон нийтэд ил мэдээлэл олдсонгүй, уг дугаарын үйл ажиллагааг тодорхойлох боломжгүй байна.",
            "found_information": [],
            "sources": []
        }

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
    context = "\n".join(context_lines)

    # -----------------------
    # 2️⃣ DeepSeek
    # -----------------------
    ds_headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json",
    }

    prompt = f"""
Та бол утасны дугаарын талаарх мэдээллийг нэгтгэн дүгнэдэг туслах.
- ЯГ 2–3 өгүүлбэртэй хэтэрхий урт биш байх. Товч бөгөөд тодорхой байх.
- Монгол хэлээр
- "энэ дугаарын эзэн иймэрхүү зүйлс цахим орчинд бичсэн тул ийм төрлийн хүн байж магадгүй" гэсэн хэлбэрээр дүгнэлт гарга.

Хэрвээ мэдээлэл хангалтгүй бол:
"Олон нийтэд ил мэдээлэл олдсонгүй, уг дугаарын үйл ажиллагааг тодорхойлох боломжгүй байна." гэж бич.

Хайлтаас олдсон snippet-үүд:
{context}
""".strip()

    ds_body = {
        "model": "deepseek-chat",
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 400,
        "stream": False,
        "temperature": 0.3  # <--- temperature 0.3
    }

    try:
        d = requests.post(DEEPSEEK_URL, headers=ds_headers, json=ds_body, timeout=40)
        d.raise_for_status()
        ds = d.json()
        logger.info(f"DeepSeek raw response: {ds}")
        try:
            summary = ds["choices"][0]["message"]["content"].strip()
        except (KeyError, IndexError, TypeError) as e:
            logger.error("DeepSeek response parsing error", exc_info=True)
            summary = "AI response parsing хийхэд алдаа гарлаа."
    except requests.exceptions.RequestException as e:
        logger.error("DeepSeek API error", exc_info=True)
        return {
            "phone_number": phone,
            "error": "AI дүгнэлт гаргах үед алдаа гарлаа."
        }

    sources = [r.get("link") for r in organic if r.get("link")]

    return {
        "phone_number": phone,
        "summary": summary,
        "found_information": found_info,
        "sources": sources
    }
