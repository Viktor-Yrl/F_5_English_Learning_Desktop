import json
import urllib.parse
import urllib.request


MYMEMORY_ENDPOINT = "https://api.mymemory.translated.net/get"


def mymemory_translate(
    text: str,
    source_lang: str = "en",
    target_lang: str = "ru",
    email: str = "",
) -> str:
    text = (text or "").strip()
    if not text:
        raise ValueError("Enter text to translate first.")

    params = {
        "q": text,
        "langpair": f"{source_lang}|{target_lang}",
    }
    if email.strip():
        params["de"] = email.strip()

    url = f"{MYMEMORY_ENDPOINT}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(url, headers={"User-Agent": "MemWord/1.0"})
    with urllib.request.urlopen(request, timeout=20) as response:
        payload = json.loads(response.read().decode("utf-8"))

    translated = (payload.get("responseData") or {}).get("translatedText", "")
    if translated:
        return translated.strip()

    matches = payload.get("matches") or []
    if matches:
        fallback = matches[0].get("translation", "")
        if fallback:
            return fallback.strip()

    message = payload.get("responseDetails") or "MyMemory returned no translation."
    raise ValueError(str(message))


def translate_text(provider: str, text: str, settings_getter) -> str:
    source_lang = str(settings_getter("mymemory_source_lang", "en") or "en")
    target_lang = str(settings_getter("mymemory_target_lang", "ru") or "ru")
    email = str(settings_getter("mymemory_email", "") or "")
    return mymemory_translate(text, source_lang, target_lang, email)


def reverso_context_url(text: str, source_lang: str = "english", target_lang: str = "russian") -> str:
    query = urllib.parse.quote((text or "").strip())
    return f"https://context.reverso.net/translation/{source_lang}-{target_lang}/{query}"
