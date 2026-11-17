"""AI chat brain for group conversations.

The provider is any OpenAI-compatible chat-completions endpoint.
By default it uses the free, key-less Pollinations endpoint so group
chat works out of the box. To upgrade quality later, set these in .env
(no code change needed):

    AI_API_KEY=...        e.g. a DeepSeek / OpenAI key
    AI_BASE_URL=...       e.g. https://api.deepseek.com/chat/completions
    AI_MODEL=...          e.g. deepseek-chat

Conversation memory is per-chat and in-memory only (last few turns);
it resets when the bot restarts, which is fine for casual group chat.

Provider priority: Groq (AI_GROQ=1, vault connection custom.groq,
model openai/gpt-oss-120b) first, then Gemini (AI_GEMINI=1, native
generateContent API) using the key stored in Muse's
Secure Vault connection custom.google-gemini. The real key never lives
on this machine: bot/services fetches an hsurr:* surrogate from the
local authd (dynamic_credentials) and the egress layer swaps in the
real key for the registered host. Any provider failure falls back
to the next one, so group chat never breaks because of one provider.
"""
import logging
import os
from collections import defaultdict, deque

import httpx

log = logging.getLogger(__name__)

BASE_URL = os.getenv("AI_BASE_URL", "https://text.pollinations.ai/openai")
_KEY = os.getenv("AI_API" + "_KEY", "")
MODEL = os.getenv("AI_MODEL", "openai")

SYSTEM_PROMPT = (
    "تو یه دستیار هوش مصنوعی و رفیقِ گروه تلگرامی «Ariya team» هستی که آریا تو رو به این ربات وصل کرده. "
    "همیشه فارسی و خودمونی و گرم جواب بده، مثل یه رفیق توی گروه؛ مگر اینکه طرف انگلیسی بنویسه. "
    "برای گپ و شوخی کوتاه جواب بده، ولی وقتی سؤال واقعی می‌پرسن جواب کامل و درست بده، حتی اگه چند جمله بشه. "
    "برای سؤال‌های حساب، منطق و معما اول با دقت توی ذهنت حساب و بررسی کن، بعد جواب نهایی رو بگو؛ جواب اشتباهِ با اعتمادبه‌نفس از جواب ندادن بدتره. "
    "ایموجی کم و به‌جا استفاده کن. درباره‌ی بازی War Thunder Mobile هم اطلاعات داری و می‌تونی راهنمایی کنی. "
    "اگه پرسیدن کی هستی، بگو یه هوش مصنوعی هستی که آریا به ربات گروه وصلت کرده؛ هرگز نگو ChatGPT هستی و وانمود نکن آدمی. "
    "اگه جواب چیزی رو نمی‌دونی، رک بگو نمی‌دونم و حدس الکی نزن."
)

_hist: dict[int, deque] = defaultdict(lambda: deque(maxlen=14))


def _client_kwargs() -> dict:
    kwargs: dict = {}
    proxy = os.getenv("HTTPS_PROXY") or os.getenv("https_proxy")
    if proxy:
        kwargs["proxy"] = proxy
    ca = os.getenv("SSL_CERT_FILE")
    kwargs["verify"] = ca or True
    return kwargs


GEMINI_ENABLED = os.getenv("AI_GEMINI", "").strip() in ("1", "true", "yes")
GEMINI_MODEL = os.getenv("AI_GEMINI_MODEL", "gemini-2.5-flash")
_GEMINI_HOST = "generativelanguage.googleapis.com"
_DYNCRED_PATH = "/opt/muse/skills/custom-connector-setup/bin"


def _gemini_surrogate_header() -> dict:
    """Fetch the vault surrogate for custom.google-gemini from authd.

    Returns headers carrying only the hsurr:* placeholder; the real key
    is swapped in at egress. Raises on any problem (caller falls back).
    """
    import sys

    if _DYNCRED_PATH not in sys.path:
        sys.path.insert(0, _DYNCRED_PATH)
    from dynamic_credentials import dynamic_credential_entry

    entry = dynamic_credential_entry("custom.google-gemini")
    surrogate = str(entry.get("surrogate", "")).strip()
    if not surrogate.startswith("hsurr:"):
        raise RuntimeError("authd did not return a surrogate")
    placement = entry.get("placement")
    if isinstance(placement, dict) and placement.get("custom_header"):
        return {str(placement["custom_header"]): surrogate}
    return {"x-goog-api-key": surrogate}


async def _ask_gemini(messages: list[dict]) -> str | None:
    """Ask Gemini (native API) with the vault-backed key. None on failure."""
    contents = []
    for m in messages:
        if m["role"] == "system":
            continue
        role = "model" if m["role"] == "assistant" else "user"
        contents.append({"role": role, "parts": [{"text": m["content"]}]})
    payload = {
        "system_instruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "contents": contents,
    }
    try:
        headers = _gemini_surrogate_header()
        url = (
            f"https://{_GEMINI_HOST}/v1beta/models/"
            f"{GEMINI_MODEL}:generateContent"
        )
        async with httpx.AsyncClient(timeout=30, **_client_kwargs()) as client:
            r = await client.post(url, json=payload, headers=headers)
            r.raise_for_status()
            data = r.json()
        parts = data["candidates"][0]["content"]["parts"]
        reply = "".join(p.get("text", "") for p in parts).strip()
        return reply or None
    except Exception:
        log.warning("ai_chat Gemini call failed; falling back", exc_info=True)
        return None


GROQ_ENABLED = os.getenv("AI_GROQ", "").strip() in ("1", "true", "yes")
GROQ_MODEL = os.getenv("AI_GROQ_MODEL", "openai/gpt-oss-120b")
_GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"


def _groq_surrogate_header() -> dict:
    """Fetch the vault surrogate for custom.groq from authd (Bearer)."""
    import sys

    if _DYNCRED_PATH not in sys.path:
        sys.path.insert(0, _DYNCRED_PATH)
    from dynamic_credentials import dynamic_credential_entry

    entry = dynamic_credential_entry("custom.groq")
    surrogate = str(entry.get("surrogate", "")).strip()
    if not surrogate.startswith("hsurr:"):
        raise RuntimeError("authd did not return a surrogate")
    return {"Authorization": f"Bearer {surrogate}"}


async def _ask_groq(messages: list[dict]) -> str | None:
    """Ask Groq (OpenAI-compatible) with the vault-backed key."""
    payload = {"model": GROQ_MODEL, "messages": messages}
    try:
        headers = _groq_surrogate_header()
        async with httpx.AsyncClient(timeout=45, **_client_kwargs()) as client:
            r = await client.post(_GROQ_URL, json=payload, headers=headers)
            r.raise_for_status()
            reply = r.json()["choices"][0]["message"]["content"].strip()
        return reply or None
    except Exception:
        log.warning("ai_chat Groq call failed; falling back", exc_info=True)
        return None


async def _ask_openai_compat(messages: list[dict]) -> str | None:
    payload = {"model": MODEL, "messages": messages}
    headers = {}
    if _KEY:
        headers["Authorization"] = f"Bearer {_KEY}"
    try:
        async with httpx.AsyncClient(timeout=90, **_client_kwargs()) as client:
            r = await client.post(BASE_URL, json=payload, headers=headers)
            r.raise_for_status()
            reply = r.json()["choices"][0]["message"]["content"].strip()
    except Exception:
        log.warning("ai_chat provider call failed", exc_info=True)
        return None
    return reply or None


async def ask_brain(chat_id: int, user_name: str, text: str) -> str | None:
    """Return the brain's reply, or None if the provider failed."""
    history = _hist[chat_id]
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.extend(history)
    messages.append({"role": "user", "content": f"{user_name}: {text}"})
    reply = None
    if GROQ_ENABLED:
        reply = await _ask_groq(messages)
    if not reply and GEMINI_ENABLED:
        reply = await _ask_gemini(messages)
    if not reply:
        reply = await _ask_openai_compat(messages)
    if not reply:
        return None
    reply = reply[:1800]
    history.append({"role": "user", "content": f"{user_name}: {text}"})
    history.append({"role": "assistant", "content": reply})
    return reply
