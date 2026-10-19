#!/usr/bin/env python3
"""
NumToD Phone Lookup Telegram Bot
API: https://numtod.netlify.app/api/results?num=XXXXXXXXXX

Usage:
  python numtod_telegram_bot.py

Commands:
  /start          welcome
  /num <10-digit> lookup
  paste any 10-digit Indian mobile
"""

import os
import re
import html
import time
import logging
from typing import Optional, Dict, Any, List

import requests
import telebot
from telebot import types

# ================== CONFIG ==================
BOT_TOKEN = os.getenv(
    "BOT_TOKEN",
    "7831522709:AAEt91TDlDT8n1PxGrcknJCOW6_-iZVx9RM",
)
API_URL = "https://numtod.netlify.app/api/results"
REQUEST_TIMEOUT = 55
MAX_RETRIES = 2
RETRY_DELAY = 2.0

ADMIN_IDS: List[int] = []

# ================== LOGGING ==================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("numtod-bot")

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")

# ================== HELPERS ==================
MOBILE_RE = re.compile(r"(?:\+?91[\s\-]*)?([6-9]\d{9})\b")


def extract_mobile(text: str) -> Optional[str]:
    if not text:
        return None
    cleaned = re.sub(r"[^\d+]", "", text)
    if cleaned.startswith("+91") and len(cleaned) >= 13:
        cleaned = cleaned[3:]
    elif cleaned.startswith("91") and len(cleaned) == 12:
        cleaned = cleaned[2:]
    m = re.search(r"[6-9]\d{9}", cleaned)
    if m:
        return m.group(0)
    m2 = MOBILE_RE.search(text)
    if m2:
        return m2.group(1)
    return None


def is_valid_mobile(num: str) -> bool:
    return bool(num) and len(num) == 10 and num[0] in "6789" and num.isdigit()


def _safe(val, default="—") -> str:
    if val is None or val == "" or val == []:
        return default
    s = str(val).strip()
    if not s or s.lower() in ("null", "none", "n/a"):
        return default
    return html.escape(s)


def clean_address(addr: Any) -> str:
    if not addr:
        return "—"
    s = str(addr).replace("!", " ").strip()
    s = re.sub(r"\s+", " ", s)
    return html.escape(s) if s else "—"


def fetch_numtod(num: str) -> Dict[str, Any]:
    params = {"num": num}
    headers = {
        "Accept": "application/json",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Referer": "https://numtod.netlify.app/",
        "Origin": "https://numtod.netlify.app",
    }

    last_error = "Unknown error"
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            r = requests.get(
                API_URL, params=params, headers=headers, timeout=REQUEST_TIMEOUT
            )
            try:
                data = r.json()
            except Exception:
                data = {}

            if r.status_code != 200:
                last_error = data.get("error") or f"HTTP {r.status_code}"
                if attempt < MAX_RETRIES:
                    time.sleep(RETRY_DELAY)
                    continue
                return {"ok": False, "error": last_error, "raw": data}

            if data.get("success") is False:
                last_error = data.get("error") or "Unknown error"
                # timeout from source — retry
                if "timeout" in str(last_error).lower() and attempt < MAX_RETRIES:
                    time.sleep(RETRY_DELAY)
                    continue
                return {"ok": False, "error": last_error, "raw": data}

            if (
                data.get("status") is True
                or data.get("success") is True
                or (isinstance(data.get("data"), dict) and data.get("data"))
            ):
                return {"ok": True, "raw": data}

            last_error = (
                data.get("error")
                or data.get("message")
                or "Empty / unexpected response"
            )
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY)
                continue
            return {"ok": False, "error": last_error, "raw": data}

        except requests.Timeout:
            last_error = "Source API timed out"
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY)
                continue
            return {"ok": False, "error": f"{last_error}. Try again in a few seconds."}
        except requests.RequestException as e:
            last_error = f"Network error: {e}"
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY)
                continue
            return {"ok": False, "error": last_error}

    return {"ok": False, "error": last_error}


def format_record(rec: Dict[str, Any], idx: int) -> str:
    """Style 25 — Split Header field block."""
    mobile = _safe(rec.get("mobile"))
    name = _safe(rec.get("name"))
    fname = _safe(rec.get("fname"))
    address = clean_address(rec.get("address"))
    alt = _safe(rec.get("alt"))
    circle = _safe(rec.get("circle"))
    rid = _safe(rec.get("id"))

    return (
        f"<b>#{idx}</b>\n"
        f"Mobile   → <code>{mobile}</code>\n"
        f"Name     → {name}\n"
        f"Fname    → {fname}\n"
        f"Address  → {address}\n"
        f"Alt      → <code>{alt}</code>\n"
        f"Circle   → {circle}\n"
        f"Id       → <code>{rid}</code>"
    )


def format_reply(num: str, payload: Dict[str, Any]) -> str:
    """Style 25 — Split Header."""
    raw = payload.get("raw") or {}
    data = raw.get("data") or raw
    if isinstance(data, dict) and "Data" in data:
        data = data["Data"]
    if not isinstance(data, dict):
        data = {}

    main: List[Dict] = data.get("Main_Records") or data.get("main_records") or []
    alt: List[Dict] = data.get("Alt_Records") or data.get("alt_records") or []

    if not main and not alt:
        if isinstance(data, list):
            main = data
        else:
            return (
                f"<b>PHONE LOOKUP</b> · <code>{num}</code>\n"
                f"─────────────────────────\n"
                f"No records found."
            )

    seen = set()
    unique_main: List[Dict] = []
    for r in main:
        if not isinstance(r, dict):
            continue
        key = (
            str(r.get("name") or "").strip().lower(),
            str(r.get("address") or "")[:50].strip().lower(),
        )
        if key in seen:
            continue
        seen.add(key)
        unique_main.append(r)

    # Split Header
    parts: List[str] = [
        f"<b>PHONE LOOKUP</b> · <code>{num}</code>",
        "─────────────────────────",
        f"Main {len(unique_main)}{' ' * 20}Linked {len(alt)}",
        "",
    ]

    if unique_main:
        parts.append("<b>── Main ──</b>")
        parts.append("")
        for i, rec in enumerate(unique_main[:12], 1):
            parts.append(format_record(rec, i))
            parts.append("")
        if len(unique_main) > 12:
            parts.append(f"<i>… +{len(unique_main) - 12} more main</i>")
            parts.append("")

    if alt:
        parts.append("<b>── Linked ──</b>")
        parts.append("")
        for i, rec in enumerate(alt[:12], 1):
            parts.append(format_record(rec, i))
            parts.append("")
        if len(alt) > 12:
            parts.append(f"<i>… +{len(alt) - 12} more linked</i>")

    text = "\n".join(parts).strip()
    if len(text) > 4000:
        text = text[:3950] + "\n\n<i>… truncated</i>"
    return text


def build_reply(num: str) -> str:
    result = fetch_numtod(num)
    if not result.get("ok"):
        err = result.get("error", "Unknown error")
        return (
            f"<b>Lookup failed</b>\n"
            f"<code>{num}</code>\n\n"
            f"{html.escape(str(err))}\n\n"
            f"<i>Source is sometimes slow. Wait a few seconds and try again.</i>"
        )
    return format_reply(num, result)


# ================== HANDLERS ==================
@bot.message_handler(commands=["start", "help"])
def cmd_start(message: types.Message):
    text = (
        "<b>NumToD Phone Lookup</b>\n\n"
        "Send any 10-digit Indian mobile number.\n\n"
        "<b>Examples</b>\n"
        "• <code>/num 9876543210</code>\n"
        "• <code>9876543210</code>\n"
        "• <code>+91 98765 43210</code>\n\n"
        "Shows: Mobile · Name · Fname · Address · Alt · Circle · Id"
    )
    bot.reply_to(message, text)


@bot.message_handler(commands=["num", "lookup", "phone", "mobile"])
def cmd_num(message: types.Message):
    parts = (message.text or "").split(maxsplit=1)
    raw = parts[1] if len(parts) > 1 else ""
    num = extract_mobile(raw)
    if not num or not is_valid_mobile(num):
        bot.reply_to(
            message,
            "Send a valid 10-digit Indian mobile.\n"
            "Example: <code>/num 9876543210</code>",
        )
        return

    status_msg = bot.reply_to(message, f"Looking up <code>{num}</code> …")
    try:
        reply = build_reply(num)
        bot.edit_message_text(
            reply,
            chat_id=status_msg.chat.id,
            message_id=status_msg.message_id,
            parse_mode="HTML",
        )
    except Exception as e:
        log.exception("lookup failed")
        bot.edit_message_text(
            f"Error:\n<code>{html.escape(str(e))}</code>",
            chat_id=status_msg.chat.id,
            message_id=status_msg.message_id,
            parse_mode="HTML",
        )


@bot.message_handler(func=lambda m: True, content_types=["text"])
def on_text(message: types.Message):
    text = (message.text or "").strip()
    if text.startswith("/"):
        return
    num = extract_mobile(text)
    if not num or not is_valid_mobile(num):
        bot.reply_to(
            message,
            "Send a 10-digit Indian mobile.\n"
            "Example: <code>9876543210</code>",
        )
        return

    status_msg = bot.reply_to(message, f"Looking up <code>{num}</code> …")
    try:
        reply = build_reply(num)
        bot.edit_message_text(
            reply,
            chat_id=status_msg.chat.id,
            message_id=status_msg.message_id,
            parse_mode="HTML",
        )
    except Exception as e:
        log.exception("lookup failed")
        bot.edit_message_text(
            f"Error:\n<code>{html.escape(str(e))}</code>",
            chat_id=status_msg.chat.id,
            message_id=status_msg.message_id,
            parse_mode="HTML",
        )


# ================== MAIN ==================
if __name__ == "__main__":
    if not BOT_TOKEN or BOT_TOKEN.startswith("PUT_YOUR"):
        print("Set BOT_TOKEN first.")
        raise SystemExit(1)
    me = bot.get_me()
    log.info("NumToD bot online as @%s", me.username)
    bot.infinity_polling(timeout=60, long_polling_timeout=40)
