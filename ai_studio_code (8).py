import os
import re
import time
import hmac
import html
import base64
import struct
import hashlib
import sqlite3
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, HTTPServer

import requests
import telebot
from telebot import types

# ==========================================
# CONFIGURATION
# ==========================================
BOT_TOKEN = os.getenv("BOT_TOKEN", "8993231954:AAGFqmTaRdxHa2SVsY7Rg8ozeLVnNPML0go")
BOT_USERNAME = os.getenv("BOT_USERNAME", "my_crownx_number_bot")
CHANNEL_LINK = os.getenv("CHANNEL_LINK", "https://t.me/+pDXDa3UyzRM5NmZl")
OTP_GROUP_LINK = os.getenv("OTP_GROUP_LINK", "https://t.me/+uqvvIt-Q5koyYjU1")
SUPPORT_USERNAME = os.getenv("SUPPORT_USERNAME", "@sakib6631")

ADMIN_ID = int(os.getenv("ADMIN_ID", "7931394632"))
OTP_GROUP_ID = int(os.getenv("OTP_GROUP_ID", "-1003973835205"))
DB_FILE = os.getenv("DB_FILE", "sk_bot_v2.db")
PORT = int(os.getenv("PORT", "8080"))

API_BASE_URL = os.getenv("API_BASE_URL", "https://api.2oo9.cloud/MXS47FLFX0U/tness/@public/api").rstrip("/")
DEFAULT_API_KEY = os.getenv("API_AUTH_KEY", "MTUAOZC4XJ1")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("SKNumberBot")
bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")

api_session = requests.Session()
db_lock = threading.Lock()
state_lock = threading.Lock()
user_states = {}

BTN_GET_NUM = "📞 𝗚𝗲𝘁 𝗡𝘂𝗺𝗯𝗲𝗿"
BTN_2FA = "🔐 𝟮𝗙𝗔 𝗔𝘂𝘁𝗵"
BTN_BALANCE = "💰 𝗕𝗮𝗹𝗮𝗻𝗰𝗲"
BTN_REFER = "👥 𝗥𝗲𝗳𝗲𝗿"
BTN_LEADERBOARD = "🏆 𝗟𝗲𝗮𝗱𝗲𝗿𝗯𝗼𝗮𝗿𝗱"
BTN_SUPPORT = "💬 𝗦𝘂𝗽𝗽𝗼𝗿𝘁"
BTN_ADMIN = "🛠 𝗔𝗱𝗺𝗶𝗻 𝗣𝗮𝗻𝗲𝗹"

SERVICE_ALIASES = {
    "FB": "FACEBOOK", "FACEBOOK": "FACEBOOK",
    "IG": "INSTAGRAM", "INSTA": "INSTAGRAM", "INSTAGRAM": "INSTAGRAM",
    "WA": "WHATSAPP", "WHATSAPP": "WHATSAPP",
    "TG": "TELEGRAM", "TELEGRAM": "TELEGRAM",
    "GG": "GOOGLE", "GOOGLE": "GOOGLE",
}

SERVICE_META = {
    "FACEBOOK": ("📘", "primary", "#FB"),
    "INSTAGRAM": ("📸", "danger", "#IG"),
    "WHATSAPP": ("💬", "success", "#WA"),
    "TELEGRAM": ("✈️", "primary", "#TG"),
    "GOOGLE": ("🔍", "danger", "#GG"),
}


class ColoredKeyboardButton(types.KeyboardButton):
    def __init__(self, text, style=None, icon_custom_emoji_id=None, **kwargs):
        super().__init__(text, **kwargs)
        self._btn_style = style
        self._icon_id = icon_custom_emoji_id

    def to_dict(self):
        d = super().to_dict()
        if self._btn_style:
            d["style"] = self._btn_style
        if self._icon_id:
            d["icon_custom_emoji_id"] = str(self._icon_id)
        return d


class ColoredInlineButton(types.InlineKeyboardButton):
    def __init__(self, text, style=None, copy_text=None, icon_custom_emoji_id=None, **kwargs):
        super().__init__(text, **kwargs)
        self._btn_style = style
        self._copy_text = copy_text
        self._icon_id = icon_custom_emoji_id

    def to_dict(self):
        d = super().to_dict()
        if self._btn_style:
            d["style"] = self._btn_style
        if self._copy_text:
            d["copy_text"] = {"text": str(self._copy_text)}
        if self._icon_id:
            d["icon_custom_emoji_id"] = str(self._icon_id)
        return d


def normalize_service(name):
    c = str(name).strip().upper()
    return SERVICE_ALIASES.get(c, c)


def clean_rid(rid):
    return re.sub(r"x+$", "", str(rid).strip(), flags=re.IGNORECASE)


def normalize_phone(phone):
    return re.sub(r"\D", "", str(phone)) if phone else ""


def mask_number(phone):
    raw = str(phone).strip()
    return (raw[:2] + "..SF.." + raw[-2:]) if len(raw) <= 7 else f"{raw[:4]}..SF..{raw[-4:]}"


def extract_flag(text):
    m = re.match(r"^\s*([\U0001F1E6-\U0001F1FF]{2})", str(text or ""))
    return m.group(1) if m else "🌍"


# ==========================================
# RENDER-READY HTTP HEALTH SERVER
# ==========================================
class ReusableHTTPServer(HTTPServer):
    allow_reuse_address = True


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"SK Number Bot is alive!")

    def do_HEAD(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain; charset=utf-8")
        self.end_headers()

    def log_message(self, format, *args):
        return


def start_health_server():
    server = ReusableHTTPServer(("0.0.0.0", PORT), HealthHandler)
    logger.info(f"Health server bound and listening on 0.0.0.0:{PORT}")
    threading.Thread(target=server.serve_forever, daemon=True).start()


# ==========================================
# THREAD-SAFE DATABASE
# ==========================================
conn = sqlite3.connect(DB_FILE, check_same_thread=False)
conn.row_factory = sqlite3.Row


def init_db():
    with db_lock:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY, username TEXT, full_name TEXT,
                balance REAL DEFAULT 0.0, otp_count INTEGER DEFAULT 0,
                referred_by INTEGER, ref_credited INTEGER DEFAULT 0, verified INTEGER DEFAULT 0,
                bkash TEXT DEFAULT '', nagad TEXT DEFAULT '', binance TEXT DEFAULT '', joined_at INTEGER
            )""")
        for sql in ("ALTER TABLE users ADD COLUMN verified INTEGER DEFAULT 0", "ALTER TABLE users ADD COLUMN ref_credited INTEGER DEFAULT 0"):
            try:
                cur.execute(sql)
            except sqlite3.OperationalError:
                pass
        cur.execute("""
            CREATE TABLE IF NOT EXISTS ranges (
                id INTEGER PRIMARY KEY AUTOINCREMENT, country TEXT NOT NULL,
                service TEXT NOT NULL, rid TEXT NOT NULL, rate REAL NOT NULL DEFAULT 0.01,
                UNIQUE(service, rid)
            )""")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS active_numbers (
                phone TEXT PRIMARY KEY, user_id INTEGER NOT NULL, country TEXT,
                service TEXT, rid TEXT, rate REAL DEFAULT 0.01, allocated_at INTEGER
            )""")
        cur.execute("CREATE TABLE IF NOT EXISTS sent_otps (otp_id TEXT PRIMARY KEY, sent_at INTEGER)")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS withdrawals (
                id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
                method TEXT NOT NULL, wallet TEXT NOT NULL, amount REAL NOT NULL,
                status TEXT DEFAULT 'pending', created_at INTEGER
            )""")
        cur.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)")

        defaults = {
            "ref_bonus": "3",
            "default_rate": "0.01",
            "min_withdraw": "10",
            "verify_channel_id": os.getenv("VERIFY_CHANNEL_ID", ""),
            "api_key": DEFAULT_API_KEY,
        }
        for k, v in defaults.items():
            cur.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (k, v))

        if cur.execute("SELECT COUNT(*) as c FROM ranges").fetchone()["c"] == 0:
            samples = [
                ("🇬🇧 United Kingdom", "FACEBOOK", "26134", 0.01), ("🇲🇬 Madagascar", "FACEBOOK", "26138", 0.01),
                ("🇬🇧 United Kingdom", "INSTAGRAM", "26134", 0.01), ("🇲🇬 Madagascar", "INSTAGRAM", "26138", 0.01),
                ("🇬🇧 United Kingdom", "WHATSAPP", "26134", 0.01), ("🇲🇬 Madagascar", "WHATSAPP", "26138", 0.01),
            ]
            cur.executemany("INSERT OR IGNORE INTO ranges (country, service, rid, rate) VALUES (?, ?, ?, ?)", samples)
        conn.commit()


def get_setting(key, default=""):
    with db_lock:
        r = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return r["value"] if r else default


def set_setting(key, value):
    with db_lock:
        conn.execute("INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, str(value)))
        conn.commit()


def get_api_headers():
    return {
        "mauthapi": get_setting("api_key", DEFAULT_API_KEY),
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def ensure_user(uid, uname, fname, ref_id=None):
    with db_lock:
        cur = conn.cursor()
        if not cur.execute("SELECT 1 FROM users WHERE user_id=?", (uid,)).fetchone():
            valid_ref = ref_id if (ref_id and ref_id != uid and cur.execute("SELECT 1 FROM users WHERE user_id=?", (ref_id,)).fetchone()) else None
            cur.execute(
                "INSERT INTO users (user_id, username, full_name, referred_by, verified, joined_at) VALUES (?, ?, ?, ?, ?, ?)",
                (uid, uname or "", fname or "User", valid_ref, 1 if uid == ADMIN_ID else 0, int(time.time())),
            )
        else:
            cur.execute("UPDATE users SET username=?, full_name=? WHERE user_id=?", (uname or "", fname or "User", uid))
        conn.commit()


def set_user_verified_flag(uid, val):
    with db_lock:
        conn.execute("UPDATE users SET verified=? WHERE user_id=?", (int(val), uid))
        conn.commit()


def reset_all_users_verify():
    with db_lock:
        conn.execute("UPDATE users SET verified=0 WHERE user_id != ?", (ADMIN_ID,))
        conn.commit()


def mark_user_verified(uid):
    bonus = float(get_setting("ref_bonus", "3"))
    credited_ref, uname = None, "User"
    with db_lock:
        cur = conn.cursor()
        row = cur.execute("SELECT full_name, referred_by, ref_credited FROM users WHERE user_id=?", (uid,)).fetchone()
        if row:
            uname = row["full_name"] or "User"
            cur.execute("UPDATE users SET verified=1 WHERE user_id=?", (uid,))
            if row["referred_by"] and not row["ref_credited"] and bonus > 0:
                cur.execute("UPDATE users SET balance=balance+? WHERE user_id=?", (bonus, row["referred_by"]))
                cur.execute("UPDATE users SET ref_credited=1 WHERE user_id=?", (uid,))
                credited_ref = row["referred_by"]
        conn.commit()
    return credited_ref, bonus, uname


def get_user(uid):
    with db_lock:
        r = conn.execute("SELECT * FROM users WHERE user_id=?", (uid,)).fetchone()
        return dict(r) if r else None


def get_referral_stats(uid):
    with db_lock:
        t = conn.execute("SELECT COUNT(*) as c FROM users WHERE referred_by=?", (uid,)).fetchone()["c"]
        q = conn.execute("SELECT COUNT(*) as c FROM users WHERE referred_by=? AND otp_count>0", (uid,)).fetchone()["c"]
        return t, q


def add_user_balance(uid, amount):
    with db_lock:
        cur = conn.cursor()
        r = cur.execute("SELECT balance FROM users WHERE user_id=?", (uid,)).fetchone()
        if not r:
            return False, 0.0
        nb = round(max(0.0, float(r["balance"]) + float(amount)), 4)
        cur.execute("UPDATE users SET balance=? WHERE user_id=?", (nb, uid))
        conn.commit()
        return True, nb


def set_user_wallet(uid, method, wallet):
    if method not in ("bkash", "nagad", "binance"):
        return False
    with db_lock:
        conn.execute(f"UPDATE users SET {method}=? WHERE user_id=?", (wallet, uid))
        conn.commit()
        return True


def create_withdrawal_atomic(uid, method, wallet, amount):
    with db_lock:
        cur = conn.cursor()
        cur.execute("UPDATE users SET balance=balance-? WHERE user_id=? AND balance>=?", (amount, uid, amount))
        if cur.rowcount != 1:
            conn.rollback()
            return None
        cur.execute("INSERT INTO withdrawals (user_id, method, wallet, amount, created_at) VALUES (?, ?, ?, ?, ?)", (uid, method, wallet, amount, int(time.time())))
        wid = cur.lastrowid
        conn.commit()
        return wid


def process_withdrawal_atomic(wid, approve=True):
    st = "approved" if approve else "rejected"
    with db_lock:
        cur = conn.cursor()
        cur.execute("UPDATE withdrawals SET status=? WHERE id=? AND status='pending'", (st, wid))
        if cur.rowcount != 1:
            conn.rollback()
            return None
        wd = dict(cur.execute("SELECT * FROM withdrawals WHERE id=?", (wid,)).fetchone())
        if not approve:
            cur.execute("UPDATE users SET balance=balance+? WHERE user_id=?", (wd["amount"], wd["user_id"]))
        conn.commit()
        return wd


def get_services():
    with db_lock:
        rows = [r["service"] for r in conn.execute("SELECT DISTINCT service FROM ranges").fetchall()]
    order = {"FACEBOOK": 1, "INSTAGRAM": 2, "WHATSAPP": 3}
    return sorted(rows, key=lambda s: (order.get(s, 99), s))


def get_ranges_by_service(service):
    with db_lock:
        return [dict(r) for r in conn.execute("SELECT * FROM ranges WHERE service=? ORDER BY id ASC", (normalize_service(service),)).fetchall()]


def get_range_by_id(rid_pk):
    with db_lock:
        r = conn.execute("SELECT * FROM ranges WHERE id=?", (rid_pk,)).fetchone()
        return dict(r) if r else None


def get_all_ranges():
    with db_lock:
        return [dict(r) for r in conn.execute("SELECT * FROM ranges ORDER BY service ASC, id ASC").fetchall()]


def add_or_update_range(service, country, rid, rate):
    srv, crid = normalize_service(service), clean_rid(rid)
    with db_lock:
        conn.execute(
            "INSERT INTO ranges (country, service, rid, rate) VALUES (?, ?, ?, ?) ON CONFLICT(service, rid) DO UPDATE SET country=excluded.country, rate=excluded.rate",
            (country.strip(), srv, crid, float(rate)),
        )
        conn.commit()
    return srv, crid


def delete_range(rid_pk):
    with db_lock:
        cur = conn.cursor()
        cur.execute("DELETE FROM ranges WHERE id=?", (rid_pk,))
        conn.commit()
        return cur.rowcount > 0


def delete_range_by_index(service, idx):
    rows = get_ranges_by_service(service)
    if 0 <= idx < len(rows):
        delete_range(rows[idx]["id"])
        return rows[idx]
    return None


def update_all_ranges_rate(new_rate):
    with db_lock:
        conn.execute("UPDATE ranges SET rate=?", (float(new_rate),))
        conn.commit()
    set_setting("default_rate", str(new_rate))


def save_user_active_numbers(phones, uid, country, service, rid, rate):
    now = int(time.time())
    with db_lock:
        cur = conn.cursor()
        cur.execute("DELETE FROM active_numbers WHERE allocated_at < ?", (now - 86400,))
        for ph in phones:
            norm = normalize_phone(ph)
            if norm:
                cur.execute(
                    "INSERT INTO active_numbers (phone, user_id, country, service, rid, rate, allocated_at) VALUES (?, ?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT(phone) DO UPDATE SET user_id=excluded.user_id, country=excluded.country, service=excluded.service, rid=excluded.rid, rate=excluded.rate, allocated_at=excluded.allocated_at",
                    (norm, uid, country, service, str(rid), float(rate), now),
                )
        conn.commit()


def find_active_number_owner(phone):
    norm = normalize_phone(phone)
    if not norm:
        return None
    with db_lock:
        cur = conn.cursor()
        r = cur.execute("SELECT * FROM active_numbers WHERE phone=?", (norm,)).fetchone()
        if r:
            return dict(r)
        if len(norm) >= 8:
            r2 = cur.execute("SELECT * FROM active_numbers WHERE phone LIKE ? ORDER BY allocated_at DESC LIMIT 1", (f"%{norm[-8:]}",)).fetchone()
            return dict(r2) if r2 else None
        return None


def credit_otp_to_user(uid, rate):
    with db_lock:
        conn.execute("UPDATE users SET balance=balance+?, otp_count=otp_count+1 WHERE user_id=?", (float(rate), uid))
        conn.commit()


def is_otp_sent(otp_id):
    with db_lock:
        return conn.execute("SELECT 1 FROM sent_otps WHERE otp_id=?", (str(otp_id),)).fetchone() is not None


def mark_otp_sent(otp_id):
    with db_lock:
        conn.execute("INSERT OR IGNORE INTO sent_otps (otp_id, sent_at) VALUES (?, ?)", (str(otp_id), int(time.time())))
        conn.commit()


def get_all_user_ids():
    with db_lock:
        return [r["user_id"] for r in conn.execute("SELECT user_id FROM users").fetchall()]


def get_users_paginated(page=0, per_page=8):
    with db_lock:
        tot = conn.execute("SELECT COUNT(*) as c FROM users").fetchone()["c"]
        rows = [dict(r) for r in conn.execute("SELECT user_id, username, full_name, balance, otp_count FROM users ORDER BY otp_count DESC, balance DESC LIMIT ? OFFSET ?", (per_page, page * per_page)).fetchall()]
        return tot, rows


def get_bot_stats():
    with db_lock:
        u = conn.execute("SELECT COUNT(*) as c, COALESCE(SUM(balance),0.0) as b, COALESCE(SUM(otp_count),0) as o FROM users").fetchone()
        r = conn.execute("SELECT COUNT(*) as c FROM ranges").fetchone()["c"]
        a = conn.execute("SELECT COUNT(*) as c FROM active_numbers").fetchone()["c"]
        w = conn.execute("SELECT COUNT(*) as c FROM withdrawals WHERE status='pending'").fetchone()["c"]
        return {"users": u["c"], "total_balance": float(u["b"]), "total_otps": u["o"], "ranges": r, "active_numbers": a, "pending_withdrawals": w}


# ==========================================
# VERIFICATION (NG - SMS STYLE)
# ==========================================
def check_chat_membership(chat_id, uid):
    if not chat_id:
        return None
    try:
        m = bot.get_chat_member(int(chat_id), uid)
        return m.status in ("member", "administrator", "creator", "restricted")
    except Exception:
        return None


def is_user_verified_gate(uid):
    if uid == ADMIN_ID:
        return True
    u = get_user(uid)
    if not u or u.get("verified") != 1:
        return False
    if check_chat_membership(OTP_GROUP_ID, uid) is False:
        set_user_verified_flag(uid, 0)
        return False
    ch_id = get_setting("verify_channel_id", "")
    if ch_id and check_chat_membership(ch_id, uid) is False:
        set_user_verified_flag(uid, 0)
        return False
    return True


def send_verify_prompt(chat_id):
    kb = types.InlineKeyboardMarkup(row_width=1)
    kb.add(
        ColoredInlineButton("Join CHANNEL", style="danger", url=CHANNEL_LINK),
        ColoredInlineButton("Join OTP GROUP", style="danger", url=OTP_GROUP_LINK),
        ColoredInlineButton("⭕ Verify Membership", style="success", callback_data="verify_join"),
    )
    bot.send_message(
        chat_id,
        "➡️ <b>Access Locked!</b>\n\n"
        "<blockquote>📢 <i>Join all our channels below and tap <b>Verify Membership</b> to unlock services.</i></blockquote>",
        reply_markup=kb,
    )


def send_welcome_menu(chat_id, uid, fname):
    bot.send_message(
        chat_id,
        f"✨ <b>স্বাগতম {html.escape(fname or 'User')}!</b>\n━━━━━━━━━━━━━━━━━━━━\n"
        f"⚡ দ্রুত ও নির্ভরযোগ্য ভার্চুয়াল নাম্বার এবং রিয়েল-টাইম OTP সার্ভিস।\n\n"
        f"👉 নাম্বার নিতে নিচের <b>{BTN_GET_NUM}</b> বাটনে ট্যাপ করুন।\n"
        f"📢 <b>Channel:</b> <a href=\"{CHANNEL_LINK}\">Join Here</a>\n"
        f"📩 <b>OTP Group:</b> <a href=\"{OTP_GROUP_LINK}\">Live OTPs</a>\n━━━━━━━━━━━━━━━━━━━━",
        reply_markup=main_reply_keyboard(uid),
        disable_web_page_preview=True,
    )


def set_state(uid, step, data=None):
    with state_lock:
        user_states[uid] = {"step": step, "data": data or {}}


def get_state(uid):
    with state_lock:
        return user_states.get(uid)


def clear_state(uid):
    with state_lock:
        user_states.pop(uid, None)


def generate_totp(secret):
    clean = re.sub(r"\s+", "", secret).upper()
    clean += "=" * ((-len(clean)) % 8)
    key = base64.b32decode(clean, casefold=True)
    now = int(time.time())
    digest = hmac.new(key, struct.pack(">Q", now // 30), hashlib.sha1).digest()
    off = digest[-1] & 0x0F
    code = (struct.unpack(">I", digest[off:off + 4])[0] & 0x7FFFFFFF) % 1000000
    return str(code).zfill(6), 30 - (now % 30)


def cancel_inline_kb():
    kb = types.InlineKeyboardMarkup()
    kb.add(ColoredInlineButton("❌ Cancel", style="danger", callback_data="cancel_state"))
    return kb


# ==========================================
# COLORED KEYBOARDS
# ==========================================
def main_reply_keyboard(uid):
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    kb.row(ColoredKeyboardButton(BTN_GET_NUM, style="success"))
    kb.row(ColoredKeyboardButton(BTN_2FA, style="primary"), ColoredKeyboardButton(BTN_BALANCE, style="danger"))
    kb.row(ColoredKeyboardButton(BTN_REFER, style="danger"), ColoredKeyboardButton(BTN_SUPPORT, style="primary"))
    kb.row(ColoredKeyboardButton(BTN_LEADERBOARD))
    if uid == ADMIN_ID:
        kb.row(ColoredKeyboardButton(BTN_ADMIN, style="danger"))
    return kb


def services_inline_kb():
    kb = types.InlineKeyboardMarkup(row_width=2)
    cycle_styles = ["primary", "danger", "success"]
    btns = []
    for idx, srv in enumerate(get_services()):
        icon, style, _ = SERVICE_META.get(srv, ("🔹", cycle_styles[idx % 3], f"#{srv[:3]}"))
        custom_id = get_setting(f"icon_{srv}", "") or None
        label = srv if custom_id else f"{icon} {srv}"
        btns.append(ColoredInlineButton(label, style=style, icon_custom_emoji_id=custom_id, callback_data=f"srv_{srv}"))
    for i in range(0, len(btns), 2):
        kb.row(*btns[i:i + 2])
    return kb


def countries_inline_kb(service):
    kb = types.InlineKeyboardMarkup(row_width=1)
    for r in get_ranges_by_service(service):
        kb.add(ColoredInlineButton(f"{r['country']} • {r['rate']}৳", style="success", callback_data=f"rng_{r['id']}"))
    kb.add(ColoredInlineButton("🔙 Back to Services", style="danger", callback_data="back_services"))
    return kb


def allocated_numbers_kb(phones, range_id, service, country):
    kb = types.InlineKeyboardMarkup()
    flag = extract_flag(country)
    for ph in phones:
        kb.row(ColoredInlineButton(f"{flag} {ph}", style="success", copy_text=ph))
    kb.row(
        ColoredInlineButton("🔄 CHANGE NUMBER", style="danger", callback_data=f"chg_{range_id}"),
        ColoredInlineButton("✉️ OTP", style="primary", url=OTP_GROUP_LINK),
    )
    kb.row(
        ColoredInlineButton("🌍 COUNTRY", style="primary", callback_data=f"srv_{service}"),
        ColoredInlineButton("🔙 BACK", callback_data="back_services"),
    )
    return kb


def admin_panel_kb():
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.row(ColoredInlineButton("➕ Add Range", style="success", callback_data="adm_add_range"), ColoredInlineButton("🗑 Delete Range", style="danger", callback_data="adm_del_range_list"))
    kb.row(ColoredInlineButton("📋 Ranges List", style="primary", callback_data="adm_ranges_view"), ColoredInlineButton("📡 Live Ranges", style="primary", callback_data="adm_liveaccess"))
    kb.row(ColoredInlineButton("🔥 Global Hits", style="primary", callback_data="adm_console"), ColoredInlineButton("👥 All Users & Bal", style="success", callback_data="adm_users_0"))
    kb.row(ColoredInlineButton("💰 Balance (+/-)", style="success", callback_data="adm_balance"), ColoredInlineButton("📈 Update Rate", style="primary", callback_data="adm_rate"))
    kb.row(ColoredInlineButton("🎁 Refer Bonus", style="primary", callback_data="adm_ref_bonus"), ColoredInlineButton("💸 Min Withdraw", style="primary", callback_data="adm_min_wd"))
    kb.row(ColoredInlineButton("📢 Broadcast", style="danger", callback_data="adm_broadcast"))
    return kb


# ==========================================
# STEX PUBLIC API & OTP FETCHER
# ==========================================
def api_get_single_number(rid):
    cleaned = clean_rid(rid)
    try:
        resp = api_session.post(f"{API_BASE_URL}/getnum", json={"rid": cleaned}, headers=get_api_headers(), timeout=10)
        logger.info(f"POST /getnum rid={cleaned} status={resp.status_code} body={resp.text[:200]}")
        data = resp.json()
    except requests.RequestException as e:
        return None, f"Network error: {e}"
    except ValueError:
        return None, f"Invalid JSON (HTTP {resp.status_code})"

    if isinstance(data, dict):
        meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}
        mc = meta.get("code")
        msg = data.get("message") or data.get("error") or meta.get("status")
        if mc == 2946:
            return None, msg or "এই রেঞ্জে এখন নাম্বার নেই (Out of Stock)।"
        if mc is not None and int(mc) not in (200, 201):
            return None, f"{msg or 'API Error'} (Code: {mc})"
        p = data.get("data")
        if isinstance(p, dict):
            ph = p.get("full_number") or p.get("no_plus_number") or p.get("number") or p.get("phone") or p.get("national_number")
            if ph:
                s = str(ph).strip()
                return (s if s.startswith("+") else f"+{s}"), None
        return None, str(msg or "No number returned.")
    return None, "Unexpected API response."


def api_get_three_numbers(rid):
    with ThreadPoolExecutor(max_workers=3) as ex:
        res = list(ex.map(lambda _: api_get_single_number(rid), range(3)))
    phones, seen, last_err = [], set(), None
    for ph, err in res:
        if ph and ph not in seen:
            seen.add(ph)
            phones.append(ph)
        elif err:
            last_err = err
    return phones, last_err


def api_get_json(endpoint):
    try:
        return api_session.get(f"{API_BASE_URL}/{endpoint.lstrip('/')}", headers=get_api_headers(), timeout=15).json(), None
    except Exception as e:
        return None, str(e)


def extract_otp_code(text):
    if not text:
        return None
    clean_text = str(text).replace("&lt;#&gt;", "").replace("<#>", "").strip()
    hm = re.search(r"\b(\d{3})-(\d{3})\b", clean_text)
    if hm:
        return hm.group(1) + hm.group(2)
    m = re.search(r"\b(\d{4,8})\b", clean_text)
    return m.group(1) if m else clean_text


def send_otp_to_group_safe(group_text, group_kb):
    try:
        bot.send_message(OTP_GROUP_ID, group_text, reply_markup=group_kb)
    except Exception as e1:
        logger.error(f"Group send failed (with styled kb): {e1}")
        try:
            fallback_kb = types.InlineKeyboardMarkup()
            fallback_kb.row(
                types.InlineKeyboardButton("🤖 BOT", url=f"https://t.me/{BOT_USERNAME}"),
                types.InlineKeyboardButton("📢 CHANNEL", url=CHANNEL_LINK),
            )
            bot.send_message(OTP_GROUP_ID, group_text, reply_markup=fallback_kb)
        except Exception as e2:
            logger.error(f"Group send completely failed: {e2}")
            try:
                bot.send_message(ADMIN_ID, f"⚠️ <b>OTP Group-এ মেসেজ যাচ্ছে না!</b>\nError: <code>{html.escape(str(e2))}</code>\nবটকে OTP Group-এ Admin করুন!")
            except Exception:
                pass


def otp_polling_worker():
    logger.info("OTP polling worker started (GET /success-otp).")
    url = f"{API_BASE_URL}/success-otp"
    while True:
        try:
            resp = api_session.get(url, headers=get_api_headers(), timeout=8)
            if resp.status_code == 200:
                payload = resp.json()
                if isinstance(payload, dict) and payload.get("meta", {}).get("code") == 200:
                    otps_data = payload.get("data", {})
                    items = otps_data.get("otps", []) if isinstance(otps_data, dict) else []

                    for item in items:
                        if not isinstance(item, dict):
                            continue
                        raw_ph = str(item.get("number") or "").strip()
                        raw_msg = str(item.get("message") or "").strip()
                        otp_id = str(item.get("otp_id") or hashlib.md5(f"{raw_ph}:{raw_msg}".encode()).hexdigest())

                        if not raw_ph or not raw_msg or is_otp_sent(otp_id):
                            continue

                        otp_code = extract_otp_code(raw_msg)
                        mark_otp_sent(otp_id)

                        d_phone = raw_ph if raw_ph.startswith("+") else f"+{raw_ph}"
                        masked = mask_number(d_phone)
                        country_name = str(item.get("country") or "Unknown")
                        service_name = str(item.get("service") or item.get("sid") or "OTP")

                        owner = find_active_number_owner(d_phone)
                        if owner:
                            country_name = owner.get("country") or country_name
                            service_name = owner.get("service") or service_name

                        flag = extract_flag(country_name)
                        c_btn = country_name[:18] if flag != "🌍" else f"🌍 {country_name[:15]}"

                        # 1. Group message: Successful above Service, ..SF.. mask, uniform font size
                        group_text = (
                            f"<b>✅ Successful</b>\n"
                            f"<b>{flag} {html.escape(service_name)}</b>\n"
                            f"<b>{html.escape(masked)}</b>"
                        )
                        group_kb = types.InlineKeyboardMarkup()
                        group_kb.row(
                            ColoredInlineButton(f"💬 {otp_code}", style="success", copy_text=otp_code),
                            ColoredInlineButton(c_btn, style="success", copy_text=country_name),
                        )
                        group_kb.row(
                            ColoredInlineButton("🤖 BOT", style="success", url=f"https://t.me/{BOT_USERNAME}"),
                            ColoredInlineButton("📢 CHANNEL", style="primary", url=CHANNEL_LINK),
                        )
                        send_otp_to_group_safe(group_text, group_kb)

                        # 2. User DM: ✅ Your OTP, Section name, full number, 💹 Added X tk
                        if owner:
                            rate = float(owner.get("rate") or get_setting("default_rate", "0.01"))
                            uid = owner["user_id"]
                            credit_otp_to_user(uid, rate)
                            srv_icon, _, _ = SERVICE_META.get(service_name.upper(), ("📱", "primary", ""))
                            dm_text = (
                                f"<b>✅ Your OTP</b>\n"
                                f"━━━━━━━━━━━━━━━━━━━━\n"
                                f"{srv_icon} <b>Section:</b> {html.escape(service_name)}\n"
                                f"{flag} <b>Number:</b> <code>{html.escape(d_phone)}</code>\n"
                                f"━━━━━━━━━━━━━━━━━━━━"
                            )
                            dm_kb = types.InlineKeyboardMarkup()
                            dm_kb.row(ColoredInlineButton(f"🛡️ {otp_code}", style="success", copy_text=otp_code))
                            dm_kb.row(ColoredInlineButton(f"💹 Added {rate} tk", style="primary", callback_data="noop"))
                            try:
                                bot.send_message(uid, dm_text, reply_markup=dm_kb)
                            except Exception as e:
                                logger.error(f"DM OTP error to {uid}: {e}")
        except Exception as e:
            logger.error(f"OTP polling error: {e}")
        time.sleep(2.0)


# ==========================================
# ADMIN HELPERS & AUTO-VERIFY
# ==========================================
def format_ranges_guide_text():
    grouped = {}
    for r in get_all_ranges():
        grouped.setdefault(r["service"], []).append(r)
    lines = ["📋 <b>𝗦𝗘𝗥𝗩𝗜𝗖𝗘 & 𝗥𝗔𝗡𝗚𝗘 𝗟𝗜𝗦𝗧</b>\n━━━━━━━━━━━━━━━━━━━━"]
    if not grouped:
        lines.append("⚠️ কোনো রেঞ্জ অ্যাড করা নেই।")
    else:
        for srv, items in grouped.items():
            lines.append(f"\n🔹 <b>{html.escape(srv)}:</b>")
            for idx, it in enumerate(items):
                lines.append(f"  <code>{idx}</code> {html.escape(it['country'])} (ID: <code>{html.escape(it['rid'])}</code>, Rate: <b>{it['rate']}tk</b>)")
    lines.append("\n━━━━━━━━━━━━━━━━━━━━\n➕ যোগ উদাহরণ: <code>/addrange FB|🇲🇱 Mali|26134|0.40</code>\n❌ ডিলিট উদাহরণ: <code>/delrange FB|0</code>")
    return "\n".join(lines)


def send_admin_dashboard(chat_id):
    s = get_bot_stats()
    ch_id = get_setting("verify_channel_id", "")
    ch_warn = "" if ch_id else "\n⚠️ <i>চ্যানেল ভেরিফাই চালু করতে দিন: /setchannel -100...</i>"
    bot.send_message(
        chat_id,
        f"🛠 <b>𝗔𝗗𝗠𝗜𝗡 𝗖𝗢𝗡𝗧𝗥𝗢𝗟 𝗣𝗔𝗡𝗘𝗟</b>\n━━━━━━━━━━━━━━━━━━━━\n"
        f"👥 <b>মোট ইউজার:</b> {s['users']}\n"
        f"💰 <b>সবার মোট ব্যালেন্স:</b> {s['total_balance']:.4f} tk\n"
        f"📩 <b>সবার মোট OTP:</b> {s['total_otps']}\n"
        f"🌍 <b>মোট রেঞ্জ:</b> {s['ranges']} | 📞 <b>অ্যাক্টিভ:</b> {s['active_numbers']}\n"
        f"⏳ <b>পেন্ডিং Withdraw:</b> {s['pending_withdrawals']}\n━━━━━━━━━━━━━━━━━━━━\n"
        f"⚙️ <b>ডিফল্ট রেট:</b> {get_setting('default_rate', '0.01')} | 🎁 <b>রেফার:</b> {get_setting('ref_bonus', '3')} | 💸 <b>Min WD:</b> {get_setting('min_withdraw', '10')}"
        f"{ch_warn}",
        reply_markup=admin_panel_kb(),
    )


@bot.chat_member_handler()
def handle_chat_member_update(update):
    try:
        uid = update.new_chat_member.user.id
        if update.new_chat_member.user.is_bot or uid == ADMIN_ID:
            return
        ch_id = get_setting("verify_channel_id", "")
        watched = {OTP_GROUP_ID}
        if ch_id and ch_id.lstrip("-").isdigit():
            watched.add(int(ch_id))
        if update.chat.id not in watched:
            return
        if update.new_chat_member.status in ("left", "kicked"):
            set_user_verified_flag(uid, 0)
            return
        if update.new_chat_member.status in ("member", "administrator", "creator", "restricted"):
            if check_chat_membership(OTP_GROUP_ID, uid) is True and (check_chat_membership(ch_id, uid) is True if ch_id else True):
                u = get_user(uid)
                if u and u.get("verified") == 0:
                    cref, bonus, uname = mark_user_verified(uid)
                    if cref:
                        try:
                            bot.send_message(cref, f"🎁 <b>𝗡𝗲𝘄 𝗥𝗲𝗳𝗲𝗿𝗿𝗮𝗹 𝗩𝗲𝗿𝗶𝗳𝗶𝗲𝗱!</b>\n👤 {html.escape(uname)}\n💰 Bonus: <b>+{bonus}</b>")
                        except Exception:
                            pass
                    try:
                        bot.send_message(uid, "✅ <b>ভেরিফিকেশন সম্পন্ন হয়েছে!</b>")
                        send_welcome_menu(uid, uid, uname)
                    except Exception:
                        pass
    except Exception as e:
        logger.warning(f"chat_member error: {e}")


# ==========================================
# USER & ADMIN COMMANDS
# ==========================================
@bot.message_handler(commands=["start"])
def handle_start(message):
    clear_state(message.from_user.id)
    parts = (message.text or "").split(maxsplit=1)
    ref_id = int(parts[1][4:].strip()) if (len(parts) > 1 and parts[1].startswith("ref_") and parts[1][4:].strip().isdigit()) else None
    fname = f"{message.from_user.first_name or ''} {message.from_user.last_name or ''}".strip()
    ensure_user(message.from_user.id, message.from_user.username, fname, ref_id)
    if not is_user_verified_gate(message.from_user.id):
        send_verify_prompt(message.chat.id)
        return
    send_welcome_menu(message.chat.id, message.from_user.id, fname)


@bot.message_handler(commands=["cancel"])
def handle_cancel(message):
    clear_state(message.from_user.id)
    bot.send_message(message.chat.id, "❌ কাজটি বাতিল করা হয়েছে।", reply_markup=main_reply_keyboard(message.from_user.id))


@bot.message_handler(commands=["setchannel", "setapikey", "seticon", "resetverify", "ranges", "testotp", "testgroup"])
def handle_simple_admin_cmds(message):
    if message.from_user.id != ADMIN_ID:
        return
    parts = (message.text or "").split()
    cmd = parts[0].lower()
    if cmd == "/setchannel":
        if len(parts) == 2:
            set_setting("verify_channel_id", parts[1].strip())
            bot.send_message(message.chat.id, f"✅ Channel ID সেট হয়েছে: <code>{html.escape(parts[1])}</code>")
        else:
            bot.send_message(message.chat.id, "উদাহরণ: <code>/setchannel -1001234567890</code>")
    elif cmd == "/setapikey":
        if len(parts) == 2:
            set_setting("api_key", parts[1].strip())
            bot.send_message(message.chat.id, f"✅ API Key আপডেট হয়েছে: <code>{html.escape(parts[1])}</code>")
        else:
            bot.send_message(message.chat.id, "উদাহরণ: <code>/setapikey MTUAOZC4XJ1</code>")
    elif cmd == "/seticon":
        if len(parts) == 3:
            srv = normalize_service(parts[1])
            set_setting(f"icon_{srv}", parts[2].strip())
            bot.send_message(message.chat.id, f"✅ {srv} Icon সেট হয়েছে: <code>{html.escape(parts[2])}</code>")
        else:
            bot.send_message(message.chat.id, "উদাহরণ: <code>/seticon FACEBOOK 5368324170671202286</code>")
    elif cmd == "/resetverify":
        reset_all_users_verify()
        bot.send_message(message.chat.id, "✅ সব ইউজারের ভেরিফিকেশন রিসেট হয়েছে।")
    elif cmd == "/ranges":
        bot.send_message(message.chat.id, format_ranges_guide_text())
    elif cmd == "/testotp":
        data, err = api_get_json("success-otp")
        bot.send_message(message.chat.id, f"❌ {err}" if err else f"📩 <b>/success-otp:</b>\n<pre>{html.escape(str(data)[:3500])}</pre>")
    elif cmd == "/testgroup":
        try:
            bot.send_message(OTP_GROUP_ID, f"✅ Test OTP Group Message from @{BOT_USERNAME}")
            bot.send_message(message.chat.id, "✅ OTP Group-এ টেস্ট মেসেজ সফলভাবে গেছে!")
        except Exception as e:
            bot.send_message(message.chat.id, f"❌ OTP Group Error: <code>{html.escape(str(e))}</code>")


@bot.message_handler(commands=["addrange"])
def handle_addrange_cmd(message):
    if message.from_user.id != ADMIN_ID:
        return
    parts = [p.strip() for p in (message.text or "").replace("/addrange", "", 1).strip().split("|")]
    if len(parts) != 4:
        bot.send_message(message.chat.id, "❌ উদাহরণ: <code>/addrange FB|🇲🇱 Mali|26134|0.40</code>")
        return
    try:
        srv, crid = add_or_update_range(parts[0], parts[1], parts[2], float(parts[3]))
        bot.send_message(message.chat.id, f"✅ যোগ হয়েছে: <b>{html.escape(srv)}</b> | {html.escape(parts[1])} | RID: <code>{crid}</code> | Rate: <b>{parts[3]}tk</b>")
    except ValueError:
        bot.send_message(message.chat.id, "❌ Rate অবশ্যই সংখ্যা হতে হবে।")


@bot.message_handler(commands=["delrange"])
def handle_delrange_cmd(message):
    if message.from_user.id != ADMIN_ID:
        return
    parts = [p.strip() for p in (message.text or "").replace("/delrange", "", 1).strip().split("|")]
    if len(parts) != 2 or not parts[1].isdigit():
        bot.send_message(message.chat.id, "❌ উদাহরণ: <code>/delrange FB|0</code>")
        return
    d = delete_range_by_index(parts[0], int(parts[1]))
    bot.send_message(message.chat.id, f"🗑 ডিলিট হয়েছে: {html.escape(d['service'])} — {html.escape(d['country'])}" if d else "❌ রেঞ্জ পাওয়া যায়নি।")


@bot.message_handler(commands=["addbal"])
def handle_addbal_cmd(message):
    if message.from_user.id != ADMIN_ID:
        return
    parts = (message.text or "").split()
    if len(parts) != 3:
        bot.send_message(message.chat.id, "উদাহরণ: <code>/addbal 7931394632 50</code>")
        return
    try:
        ok, nb = add_user_balance(int(parts[1]), float(parts[2]))
        bot.send_message(message.chat.id, f"✅ নতুন ব্যালেন্স: <b>{nb}</b>" if ok else "❌ ইউজার পাওয়া যায়নি।")
    except ValueError:
        bot.send_message(message.chat.id, "❌ সঠিক সংখ্যা দিন।")


@bot.message_handler(commands=["testapi"])
def handle_testapi_cmd(message):
    if message.from_user.id != ADMIN_ID:
        return
    parts = (message.text or "").split()
    if len(parts) != 2:
        bot.send_message(message.chat.id, "উদাহরণ: <code>/testapi 26134</code>")
        return
    try:
        r = api_session.post(f"{API_BASE_URL}/getnum", json={"rid": clean_rid(parts[1])}, headers=get_api_headers(), timeout=15)
        bot.send_message(message.chat.id, f"📡 <b>HTTP {r.status_code}:</b>\n<pre>{html.escape(r.text[:3500])}</pre>")
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Error: {html.escape(str(e))}")


def ensure_verified_or_prompt(message):
    ensure_user(message.from_user.id, message.from_user.username, message.from_user.first_name)
    if not is_user_verified_gate(message.from_user.id):
        send_verify_prompt(message.chat.id)
        return False
    return True


@bot.message_handler(func=lambda m: m.text in (BTN_GET_NUM, "📞 Get Number"))
def handle_get_num(message):
    clear_state(message.from_user.id)
    if ensure_verified_or_prompt(message):
        if not get_services():
            bot.send_message(message.chat.id, "⚠️ বর্তমানে কোনো সার্ভিস নেই।")
        else:
            bot.send_message(message.chat.id, "📌 <b>𝗦𝗘𝗟𝗘𝗖𝗧 𝗔 𝗦𝗘𝗥𝗩𝗜𝗖𝗘</b>\n━━━━━━━━━━━━━━━━━━━━", reply_markup=services_inline_kb())


@bot.message_handler(func=lambda m: m.text in (BTN_2FA, "🔐 2FA Auth"))
def handle_2fa(message):
    if ensure_verified_or_prompt(message):
        set_state(message.from_user.id, "awaiting_2fa_secret")
        bot.send_message(message.chat.id, "🔐 <b>𝟮𝗙𝗔 𝗔𝘂𝘁𝗵</b>\nআপনার 2FA Secret Key (Base32) পাঠান।\n<i>উদাহরণ: JBSWY3DPEHPK3PXP</i>", reply_markup=cancel_inline_kb())


@bot.message_handler(func=lambda m: m.text in (BTN_BALANCE, "💰 Balance"))
def handle_balance(message):
    clear_state(message.from_user.id)
    if not ensure_verified_or_prompt(message):
        return
    u = get_user(message.from_user.id)
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.row(ColoredInlineButton("💸 Withdraw Request", style="success", callback_data="wd_start"))
    kb.row(ColoredInlineButton("💳 Set bKash", style="danger", callback_data="set_wallet_bkash"), ColoredInlineButton("💳 Set Nagad", style="primary", callback_data="set_wallet_nagad"))
    kb.row(ColoredInlineButton("🪙 Set Binance", style="primary", callback_data="set_wallet_binance"))
    bot.send_message(
        message.chat.id,
        f"💰 <b>𝗔𝗖𝗖𝗢𝗨𝗡𝗧 & 𝗪𝗔𝗟𝗟𝗘𝗧</b>\n━━━━━━━━━━━━━━━━━━━━\n"
        f"🆔 <b>ID:</b> <code>{u['user_id']}</code>\n💵 <b>Balance:</b> <b>{u['balance']:.4f}</b>\n"
        f"📩 <b>Total OTPs:</b> <b>{u['otp_count']}</b>\n📉 <b>Min Withdraw:</b> <b>{get_setting('min_withdraw', '10')}</b>\n━━━━━━━━━━━━━━━━━━━━\n"
        f"• bKash: <code>{html.escape(u['bkash'] or 'Not Set')}</code>\n• Nagad: <code>{html.escape(u['nagad'] or 'Not Set')}</code>\n• Binance: <code>{html.escape(u['binance'] or 'Not Set')}</code>",
        reply_markup=kb,
    )


@bot.message_handler(func=lambda m: m.text in (BTN_REFER, "👥 Refer"))
def handle_refer(message):
    clear_state(message.from_user.id)
    if not ensure_verified_or_prompt(message):
        return
    bonus = float(get_setting("ref_bonus", "3"))
    tot, qual = get_referral_stats(message.from_user.id)
    link = f"https://t.me/{BOT_USERNAME}?start=ref_{message.from_user.id}"
    kb = types.InlineKeyboardMarkup()
    kb.row(ColoredInlineButton("🔗 Share Link", style="primary", url=f"https://t.me/share/url?url={link}&text=Get%20free%20OTP%20numbers!"))
    bot.send_message(
        message.chat.id,
        f"🎁 <b>𝗥𝗘𝗙𝗘𝗥 & 𝗘𝗔𝗥𝗡</b>\n━━━━━━━━━━━━━━━━━━━━\n🔗 <code>{link}</code>\n\n"
        f"💬 <b>Total Invited:</b> {tot}\n✅ <b>Qualified (Active):</b> {qual}\n"
        f"🎁 <b>Bonus Per Refer:</b> {bonus}\n💰 <b>Total Earned:</b> {tot * bonus:.2f}\n━━━━━━━━━━━━━━━━━━━━",
        reply_markup=kb,
    )


@bot.message_handler(func=lambda m: m.text in (BTN_LEADERBOARD, "🏆 Leaderboard"))
def handle_leaderboard(message):
    clear_state(message.from_user.id)
    if not ensure_verified_or_prompt(message):
        return
    with db_lock:
        rows = conn.execute("SELECT user_id, full_name, otp_count, balance FROM users ORDER BY otp_count DESC, balance DESC LIMIT 10").fetchall()
    if not rows:
        bot.send_message(message.chat.id, "🏆 লিডারবোর্ডে এখনো কোনো ডেটা নেই।")
        return
    lines = ["🏆 <b>𝗧𝗢𝗣 𝗨𝗦𝗘𝗥𝗦 — 𝗟𝗘𝗔𝗗𝗘𝗥𝗕𝗢𝗔𝗥𝗗</b>\n━━━━━━━━━━━━━━━━━━━━"]
    for i, r in enumerate(rows, 1):
        prefix = "👑" if i == 1 else "▶️"
        lines.append(f"{prefix} <b>{html.escape(r['full_name'] or 'User')}</b> — <b>{r['otp_count']} OTP</b> ({r['balance']:.2f} tk)")
    bot.send_message(message.chat.id, "\n".join(lines))


@bot.message_handler(func=lambda m: m.text in (BTN_SUPPORT, "💬 Support"))
def handle_support(message):
    clear_state(message.from_user.id)
    if not ensure_verified_or_prompt(message):
        return
    kb = types.InlineKeyboardMarkup()
    kb.row(ColoredInlineButton("👨‍💻 Contact Support", style="success", url=f"https://t.me/{SUPPORT_USERNAME.lstrip('@')}"))
    kb.row(ColoredInlineButton("📢 Channel", style="primary", url=CHANNEL_LINK), ColoredInlineButton("📩 OTP Group", style="primary", url=OTP_GROUP_LINK))
    bot.send_message(message.chat.id, f"💬 <b>𝗦𝗨𝗣𝗣𝗢𝗥𝗧</b>\n━━━━━━━━━━━━━━━━━━━━\nযোগাযোগ: {SUPPORT_USERNAME}", reply_markup=kb)


@bot.message_handler(func=lambda m: m.text in (BTN_ADMIN, "🛠 Admin Panel"))
def handle_admin(message):
    if message.from_user.id == ADMIN_ID:
        clear_state(ADMIN_ID)
        send_admin_dashboard(message.chat.id)


# ==========================================
# INLINE CALLBACKS
# ==========================================
@bot.callback_query_handler(func=lambda c: c.data == "noop")
def cb_noop(call):
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda c: c.data == "cancel_state")
def cb_cancel_state(call):
    clear_state(call.from_user.id)
    bot.answer_callback_query(call.id, "❌ বাতিল করা হয়েছে!")
    try:
        bot.edit_message_text("❌ কাজটি বাতিল করা হয়েছে।", call.message.chat.id, call.message.message_id)
    except Exception:
        pass


@bot.callback_query_handler(func=lambda c: c.data == "verify_join")
def cb_verify_join(call):
    uid = call.from_user.id
    fname = f"{call.from_user.first_name or ''} {call.from_user.last_name or ''}".strip()
    ensure_user(uid, call.from_user.username, fname)

    grp_ok = check_chat_membership(OTP_GROUP_ID, uid)
    if grp_ok is False:
        bot.answer_callback_query(call.id, "❌ আপনি এখনো OTP Group-এ জয়েন করেননি! আগে জয়েন করে Verify দিন।", show_alert=True)
        return
    if grp_ok is None and uid != ADMIN_ID:
        bot.answer_callback_query(call.id, "⚠️ বটকে আগে OTP Group-এ Admin করতে হবে!", show_alert=True)
        return

    ch_id = get_setting("verify_channel_id", "")
    if ch_id and check_chat_membership(ch_id, uid) is False:
        bot.answer_callback_query(call.id, "❌ আপনি এখনো Channel-এ জয়েন করেননি! আগে জয়েন করে Verify দিন।", show_alert=True)
        return

    cref, bonus, uname = mark_user_verified(uid)
    if cref:
        try:
            bot.send_message(cref, f"🎁 <b>𝗡𝗲𝘄 𝗥𝗲𝗳𝗲𝗿𝗿𝗮𝗹!</b>\n👤 {html.escape(uname)}\n💰 Bonus: <b>+{bonus}</b>")
        except Exception:
            pass
    bot.answer_callback_query(call.id, "✅ Membership Verified!")
    try:
        bot.delete_message(call.message.chat.id, call.message.message_id)
    except Exception:
        pass
    send_welcome_menu(call.message.chat.id, uid, fname)


@bot.callback_query_handler(func=lambda c: c.data == "back_services")
def cb_back_srv(call):
    if not is_user_verified_gate(call.from_user.id):
        bot.answer_callback_query(call.id, "🔐 আগে জয়েন করে Verify করুন!", show_alert=True)
        send_verify_prompt(call.message.chat.id)
        return
    bot.answer_callback_query(call.id)
    try:
        bot.edit_message_text("📌 <b>𝗦𝗘𝗟𝗘𝗖𝗧 𝗔 𝗦𝗘𝗥𝗩𝗜𝗖𝗘</b>\n━━━━━━━━━━━━━━━━━━━━", call.message.chat.id, call.message.message_id, reply_markup=services_inline_kb())
    except Exception:
        bot.send_message(call.message.chat.id, "📌 <b>𝗦𝗘𝗟𝗘𝗖𝗧 𝗔 𝗦𝗘𝗥𝗩𝗜𝗖𝗘</b>", reply_markup=services_inline_kb())


@bot.callback_query_handler(func=lambda c: c.data.startswith("srv_"))
def cb_srv(call):
    if not is_user_verified_gate(call.from_user.id):
        bot.answer_callback_query(call.id, "🔐 আগে জয়েন করে Verify করুন!", show_alert=True)
        send_verify_prompt(call.message.chat.id)
        return
    srv = call.data[4:]
    if not get_ranges_by_service(srv):
        bot.answer_callback_query(call.id, "কোনো দেশ নেই!", show_alert=True)
        return
    bot.answer_callback_query(call.id)
    txt = f"🌍 <b>{html.escape(srv)} — 𝗖𝗛𝗢𝗢𝗦𝗘 𝗖𝗢𝗨𝗡𝗧𝗥𝗬</b>\n━━━━━━━━━━━━━━━━━━━━"
    try:
        bot.edit_message_text(txt, call.message.chat.id, call.message.message_id, reply_markup=countries_inline_kb(srv))
    except Exception:
        bot.send_message(call.message.chat.id, txt, reply_markup=countries_inline_kb(srv))


@bot.callback_query_handler(func=lambda c: c.data.startswith("rng_") or c.data.startswith("chg_"))
def cb_alloc_change(call):
    if not is_user_verified_gate(call.from_user.id):
        bot.answer_callback_query(call.id, "🔐 আগে জয়েন করে Verify করুন!", show_alert=True)
        send_verify_prompt(call.message.chat.id)
        return
    try:
        range_id = int(call.data.split("_", 1)[1])
    except ValueError:
        return
    rng = get_range_by_id(range_id)
    if not rng:
        bot.answer_callback_query(call.id, "রেঞ্জ পাওয়া যায়নি!", show_alert=True)
        return
    bot.answer_callback_query(call.id, "⏳ ৩টি নতুন নাম্বার আনা হচ্ছে...")
    try:
        bot.edit_message_text(f"⏳ <b>{html.escape(rng['country'])}</b> থেকে নতুন ৩টি নাম্বার আনা হচ্ছে...", call.message.chat.id, call.message.message_id)
    except Exception:
        pass

    phones, err = api_get_three_numbers(rng["rid"])
    if not phones:
        kb = types.InlineKeyboardMarkup()
        kb.row(ColoredInlineButton("🔄 Try Again", style="danger", callback_data=f"chg_{range_id}"), ColoredInlineButton("🌍 Country", style="primary", callback_data=f"srv_{rng['service']}"))
        txt = f"⚠️ <b>নাম্বার পাওয়া যায়নি!</b>\n🌍 {html.escape(rng['country'])} (RID: <code>{rng['rid']}</code>)\n📝 <i>{html.escape(err or 'Out of Stock')}</i>"
        try:
            bot.edit_message_text(txt, call.message.chat.id, call.message.message_id, reply_markup=kb)
        except Exception:
            bot.send_message(call.message.chat.id, txt, reply_markup=kb)
        return

    save_user_active_numbers(phones, call.from_user.id, rng["country"], rng["service"], rng["rid"], rng["rate"])
    txt = f"✅ <b>{html.escape(rng['country'])} ({html.escape(rng['service'])}) Allocated</b>\n\n🕒 <b>Waiting for OTP........</b>"
    kb = allocated_numbers_kb(phones, range_id, rng["service"], rng["country"])
    try:
        bot.edit_message_text(txt, call.message.chat.id, call.message.message_id, reply_markup=kb)
    except Exception:
        bot.send_message(call.message.chat.id, txt, reply_markup=kb)


# ---------- WALLET & WITHDRAW ----------
@bot.callback_query_handler(func=lambda c: c.data.startswith("set_wallet_"))
def cb_set_wallet(call):
    if not is_user_verified_gate(call.from_user.id):
        bot.answer_callback_query(call.id, "🔐 আগে Verify করুন!", show_alert=True)
        return
    m = call.data.replace("set_wallet_", "")
    if m in ("bkash", "nagad", "binance"):
        bot.answer_callback_query(call.id)
        set_state(call.from_user.id, "awaiting_set_wallet", {"method": m})
        bot.send_message(call.message.chat.id, f"💳 আপনার <b>{m.upper()}</b> নাম্বার/আইডি লিখুন:\n<i>উদাহরণ: 01712345678</i>", reply_markup=cancel_inline_kb())


@bot.callback_query_handler(func=lambda c: c.data == "wd_start")
def cb_wd_start(call):
    if not is_user_verified_gate(call.from_user.id):
        bot.answer_callback_query(call.id, "🔐 আগে Verify করুন!", show_alert=True)
        return
    u = get_user(call.from_user.id)
    mw = float(get_setting("min_withdraw", "10"))
    if not u or u["balance"] < mw:
        bot.answer_callback_query(call.id, f"❌ সর্বনিম্ন Withdraw {mw}! ব্যালেন্স: {u['balance'] if u else 0:.2f}", show_alert=True)
        return
    bot.answer_callback_query(call.id)
    kb = types.InlineKeyboardMarkup(row_width=3)
    kb.row(
        ColoredInlineButton("bKash", style="danger", callback_data="wd_m_bkash"),
        ColoredInlineButton("Nagad", style="primary", callback_data="wd_m_nagad"),
        ColoredInlineButton("Binance", style="success", callback_data="wd_m_binance"),
    )
    bot.send_message(call.message.chat.id, "💸 <b>পেমেন্ট মাধ্যম সিলেক্ট করুন:</b>", reply_markup=kb)


@bot.callback_query_handler(func=lambda c: c.data.startswith("wd_m_"))
def cb_wd_method(call):
    m = call.data.replace("wd_m_", "")
    u = get_user(call.from_user.id)
    saved = u.get(m, "") if u else ""
    bot.answer_callback_query(call.id)
    set_state(call.from_user.id, "awaiting_wd_wallet", {"method": m})
    kb = types.InlineKeyboardMarkup()
    if saved:
        kb.add(ColoredInlineButton(f"✅ সেভ করা: {saved}", style="success", callback_data=f"wd_saved_{m}"))
    kb.add(ColoredInlineButton("❌ Cancel", style="danger", callback_data="cancel_state"))
    bot.send_message(call.message.chat.id, f"📞 আপনার <b>{m.upper()}</b> নাম্বার/আইডি লিখুন:\n<i>উদাহরণ: 01712345678</i>", reply_markup=kb)


@bot.callback_query_handler(func=lambda c: c.data.startswith("wd_saved_"))
def cb_wd_saved(call):
    m = call.data.replace("wd_saved_", "")
    u = get_user(call.from_user.id)
    saved = u.get(m, "") if u else ""
    if not saved:
        return
    bot.answer_callback_query(call.id)
    set_state(call.from_user.id, "awaiting_wd_amount", {"method": m, "wallet": saved})
    bot.send_message(call.message.chat.id, f"💵 কত টাকা Withdraw করবেন? (ব্যালেন্স: {u['balance']:.4f}, Min: {get_setting('min_withdraw', '10')})\n<i>উদাহরণ: 50</i>", reply_markup=cancel_inline_kb())


@bot.callback_query_handler(func=lambda c: c.data.startswith("wd_app_") or c.data.startswith("wd_rej_"))
def cb_wd_decision(call):
    if call.from_user.id != ADMIN_ID:
        return
    app = call.data.startswith("wd_app_")
    wd = process_withdrawal_atomic(int(call.data.split("_")[-1]), approve=app)
    if not wd:
        bot.answer_callback_query(call.id, "ইতিমধ্যে প্রসেস হয়েছে!", show_alert=True)
        return
    lbl = "✅ Approved" if app else "❌ Rejected (Refunded)"
    bot.answer_callback_query(call.id, lbl)
    try:
        bot.edit_message_text(f"{call.message.html_text}\n\n📌 <b>Status:</b> {lbl}", call.message.chat.id, call.message.message_id)
    except Exception:
        pass
    try:
        msg = f"✅ পেমেন্ট #{wd['id']} সফল হয়েছে ({wd['amount']} tk - {wd['method'].upper()})!" if app else f"❌ Withdraw #{wd['id']} বাতিল হয়েছে। {wd['amount']} tk ফেরত দেওয়া হয়েছে।"
        bot.send_message(wd["user_id"], msg)
    except Exception:
        pass


# ---------- ADMIN CALLBACKS ----------
@bot.callback_query_handler(func=lambda c: c.data.startswith("adm_"))
def cb_admin(call):
    if call.from_user.id != ADMIN_ID:
        return
    act = call.data
    bot.answer_callback_query(call.id)
    if act == "adm_ranges_view":
        bot.send_message(call.message.chat.id, format_ranges_guide_text())
    elif act == "adm_liveaccess":
        data, err = api_get_json("liveaccess")
        bot.send_message(call.message.chat.id, f"❌ {err}" if err else f"📡 <b>Live Ranges:</b>\n<pre>{html.escape(str(data)[:3500])}</pre>")
    elif act == "adm_console":
        data, err = api_get_json("console")
        bot.send_message(call.message.chat.id, f"❌ {err}" if err else f"🔥 <b>Global Hits:</b>\n<pre>{html.escape(str(data)[:3500])}</pre>")
    elif act.startswith("adm_users_"):
        page = int(act.replace("adm_users_", ""))
        tot, rows = get_users_paginated(page, 8)
        st = get_bot_stats()
        lines = [
            f"👥 <b>𝗦𝗘𝗥𝗩𝗘𝗥 𝗨𝗦𝗘𝗥𝗦 (Page {page+1})</b>",
            "━━━━━━━━━━━━━━━━━━━━",
            f"📊 মোট ইউজার: <b>{st['users']}</b> | মোট OTP: <b>{st['total_otps']}</b>",
            f"💰 সবার মোট ব্যালেন্স: <b>{st['total_balance']:.4f} tk</b>",
            "━━━━━━━━━━━━━━━━━━━━\n<i>👇 কারো ব্যালেন্স কম/বেশি করতে নামের বাটনে ক্লিক করুন:</i>",
        ]
        kb = types.InlineKeyboardMarkup(row_width=1)
        for i, u in enumerate(rows, page * 8 + 1):
            nm = u["full_name"] or "User"
            lines.append(f"{i}. <b>{html.escape(nm)}</b> (<code>{u['user_id']}</code>) | 📩 {u['otp_count']} | 💰 <b>{u['balance']:.2f}</b>")
            kb.add(ColoredInlineButton(f"💰 {nm[:15]} ({u['balance']:.2f}tk) — ±Balance", style="primary", callback_data=f"uadj_{u['user_id']}"))
        nav = []
        if page > 0:
            nav.append(ColoredInlineButton("⬅️ Prev", style="success", callback_data=f"adm_users_{page-1}"))
        if (page + 1) * 8 < tot:
            nav.append(ColoredInlineButton("Next ➡️", style="success", callback_data=f"adm_users_{page+1}"))
        if nav:
            kb.row(*nav)
        bot.send_message(call.message.chat.id, "\n".join(lines), reply_markup=kb)
    elif act == "adm_del_range_list":
        kb = types.InlineKeyboardMarkup(row_width=1)
        for r in get_all_ranges():
            kb.add(ColoredInlineButton(f"🗑 {r['service']} | {r['country']} (RID:{r['rid']})", style="danger", callback_data=f"delrng_{r['id']}"))
        bot.send_message(call.message.chat.id, "🗑 ডিলিট করতে ক্লিক করুন:", reply_markup=kb)
    elif act in ("adm_add_range", "adm_balance", "adm_rate", "adm_ref_bonus", "adm_min_wd", "adm_broadcast"):
        set_state(ADMIN_ID, act)
        prompts = {
            "adm_add_range": "➕ <b>নতুন রেঞ্জ যোগ করুন</b>\nফরম্যাট: <code>Service|Country|RID|Rate</code>\n\n✅ <b>উদাহরণ:</b>\n<code>FB|🇲🇱 Mali|26134|0.40</code>",
            "adm_balance": "💰 <b>ব্যালেন্স বাড়ানো বা কমানো</b>\nফরম্যাট: <code>UserID|Amount</code>\n\n✅ <b>উদাহরণ:</b> <code>7931394632|50</code> বা <code>7931394632|-20</code>",
            "adm_rate": "📈 <b>নতুন OTP রেট লিখুন</b>\n✅ <b>উদাহরণ:</b> <code>0.40</code>",
            "adm_ref_bonus": "🎁 <b>নতুন রেফারেল বোনাস লিখুন</b>\n✅ <b>উদাহরণ:</b> <code>5</code>",
            "adm_min_wd": "💸 <b>নতুন মিনিমাম Withdraw লিমিট লিখুন</b>\n✅ <b>উদাহরণ:</b> <code>50</code>",
            "adm_broadcast": "📢 <b>ব্রডকাস্ট মেসেজ</b>\nসব ইউজারকে পাঠানোর জন্য যেকোনো <b>টেক্সট, ছবি বা ভিডিও</b> এখন পাঠান:",
        }
        bot.send_message(call.message.chat.id, prompts[act], reply_markup=cancel_inline_kb())


@bot.callback_query_handler(func=lambda c: c.data.startswith("uadj_"))
def cb_user_quick_balance(call):
    if call.from_user.id != ADMIN_ID:
        return
    tuid = int(call.data.replace("uadj_", ""))
    u = get_user(tuid)
    if not u:
        bot.answer_callback_query(call.id, "ইউজার পাওয়া যায়নি!", show_alert=True)
        return
    bot.answer_callback_query(call.id)
    set_state(ADMIN_ID, "adm_single_bal", {"target_uid": tuid})
    bot.send_message(
        call.message.chat.id,
        f"💰 <b>{html.escape(u['full_name'] or 'User')}</b> (<code>{tuid}</code>)\n"
        f"বর্তমান ব্যালেন্স: <b>{u['balance']:.2f} tk</b>\n\n"
        f"✅ <b>উদাহরণ:</b> বাড়াতে <code>50</code>, কমাতে <code>-20</code>",
        reply_markup=cancel_inline_kb(),
    )


@bot.callback_query_handler(func=lambda c: c.data.startswith("delrng_"))
def cb_delrng(call):
    if call.from_user.id == ADMIN_ID and delete_range(int(call.data.replace("delrng_", ""))):
        bot.answer_callback_query(call.id, "✅ ডিলিট হয়েছে!")
        try:
            bot.delete_message(call.message.chat.id, call.message.message_id)
        except Exception:
            pass


# ==========================================
# STATEFUL INPUT HANDLER
# ==========================================
@bot.message_handler(content_types=["text", "photo", "video"])
def handle_inputs(message):
    uid = message.from_user.id
    st = get_state(uid)
    if not st:
        return
    step, data = st["step"], st["data"]

    if step == "adm_broadcast" and uid == ADMIN_ID:
        clear_state(uid)
        uids = get_all_user_ids()
        ok, fail = 0, 0
        bot.send_message(uid, f"⏳ {len(uids)} জন ইউজারকে পাঠানো হচ্ছে...")
        for t in uids:
            try:
                if message.content_type == "text":
                    bot.send_message(t, message.text, parse_mode=None)
                elif message.content_type == "photo":
                    bot.send_photo(t, message.photo[-1].file_id, caption=message.caption or "", parse_mode=None)
                elif message.content_type == "video":
                    bot.send_video(t, message.video.file_id, caption=message.caption or "", parse_mode=None)
                ok += 1
            except Exception:
                fail += 1
            time.sleep(0.05)
        bot.send_message(uid, f"✅ ব্রডকাস্ট শেষ! সফল: <b>{ok}</b>, ব্যর্থ: <b>{fail}</b>")
        return

    if message.content_type != "text":
        bot.send_message(message.chat.id, "⚠️ টেক্সট পাঠান অথবা Cancel বাটনে চাপুন।", reply_markup=cancel_inline_kb())
        return
    text = message.text.strip()

    if step == "awaiting_2fa_secret":
        clear_state(uid)
        try:
            code, rem = generate_totp(text)
            bot.send_message(message.chat.id, f"🔐 <b>2FA Code:</b> <code>{code}</code>\n⏳ মেয়াদ: <b>{rem}s</b>")
        except Exception:
            bot.send_message(message.chat.id, "❌ ভুল Base32 Secret Key!")
        return

    if step == "awaiting_set_wallet":
        clear_state(uid)
        set_user_wallet(uid, data["method"], text)
        bot.send_message(message.chat.id, f"✅ {data['method'].upper()} সেভ হয়েছে: <code>{html.escape(text)}</code>")
        return

    if step == "awaiting_wd_wallet":
        u = get_user(uid)
        set_state(uid, "awaiting_wd_amount", {"method": data["method"], "wallet": text})
        bot.send_message(message.chat.id, f"💵 কত টাকা Withdraw করবেন? (ব্যালেন্স: {u['balance']:.4f}, Min: {get_setting('min_withdraw', '10')})\n<i>উদাহরণ: 50</i>", reply_markup=cancel_inline_kb())
        return

    if step == "awaiting_wd_amount":
        try:
            amt = float(text)
        except ValueError:
            bot.send_message(message.chat.id, "❌ সঠিক সংখ্যা লিখুন (যেমন: <code>50</code>)।", reply_markup=cancel_inline_kb())
            return
        mw = float(get_setting("min_withdraw", "10"))
        if amt < mw or amt <= 0:
            bot.send_message(message.chat.id, f"❌ সর্বনিম্ন Withdraw {mw}!", reply_markup=cancel_inline_kb())
            return
        wid = create_withdrawal_atomic(uid, data["method"], data["wallet"], amt)
        clear_state(uid)
        if not wid:
            bot.send_message(message.chat.id, "❌ পর্যাপ্ত ব্যালেন্স নেই!")
            return
        u = get_user(uid)
        bot.send_message(message.chat.id, f"✅ Withdraw রিকোয়েস্ট #{wid} জমা হয়েছে! অবশিষ্ট ব্যালেন্স: <b>{u['balance']:.4f}</b>")
        akb = types.InlineKeyboardMarkup()
        akb.row(ColoredInlineButton("✅ Approve", style="success", callback_data=f"wd_app_{wid}"), ColoredInlineButton("❌ Reject", style="danger", callback_data=f"wd_rej_{wid}"))
        bot.send_message(ADMIN_ID, f"💸 <b>New Withdraw #{wid}</b>\n👤 {html.escape(u['full_name'])} (<code>{uid}</code>)\n💳 {data['method'].upper()}: <code>{html.escape(data['wallet'])}</code>\n💵 Amount: <b>{amt}</b>", reply_markup=akb)
        return

    if uid == ADMIN_ID:
        if step == "adm_single_bal":
            try:
                ok, nb = add_user_balance(data["target_uid"], float(text))
                clear_state(uid)
                bot.send_message(uid, f"✅ ইউজার <code>{data['target_uid']}</code>-এর নতুন ব্যালেন্স: <b>{nb} tk</b>" if ok else "❌ ইউজার পাওয়া যায়নি।")
            except ValueError:
                bot.send_message(uid, "❌ শুধু সংখ্যা লিখুন (যেমন: <code>50</code> বা <code>-20</code>)।", reply_markup=cancel_inline_kb())
        elif step == "adm_add_range":
            p = [x.strip() for x in text.split("|")]
            if len(p) != 4:
                bot.send_message(uid, "❌ উদাহরণ: <code>FB|🇲🇱 Mali|26134|0.40</code>", reply_markup=cancel_inline_kb())
                return
            try:
                srv, crid = add_or_update_range(p[0], p[1], p[2], float(p[3]))
                clear_state(uid)
                bot.send_message(uid, f"✅ যোগ হয়েছে: <b>{html.escape(srv)}</b> | {html.escape(p[1])} | <code>{crid}</code> | {p[3]}tk")
            except ValueError:
                bot.send_message(uid, "❌ Rate সংখ্যা হতে হবে।", reply_markup=cancel_inline_kb())
        elif step == "adm_balance":
            p = [x.strip() for x in text.split("|")]
            if len(p) != 2:
                bot.send_message(uid, "❌ উদাহরণ: <code>7931394632|50</code>", reply_markup=cancel_inline_kb())
                return
            try:
                ok, nb = add_user_balance(int(p[0]), float(p[1]))
                clear_state(uid)
                bot.send_message(uid, f"✅ নতুন ব্যালেন্স: <b>{nb}</b>" if ok else "❌ ইউজার পাওয়া যায়নি।")
            except ValueError:
                bot.send_message(uid, "❌ সঠিক সংখ্যা দিন।", reply_markup=cancel_inline_kb())
        elif step == "adm_rate":
            try:
                update_all_ranges_rate(float(text))
                clear_state(uid)
                bot.send_message(uid, f"✅ সব রেট <b>{text}</b> সেট হয়েছে।")
            except ValueError:
                bot.send_message(uid, "❌ সঠিক সংখ্যা দিন।", reply_markup=cancel_inline_kb())
        elif step == "adm_ref_bonus":
            try:
                set_setting("ref_bonus", str(float(text)))
                clear_state(uid)
                bot.send_message(uid, f"✅ রেফার বোনাস <b>{text}</b> সেট হয়েছে।")
            except ValueError:
                bot.send_message(uid, "❌ সঠিক সংখ্যা দিন।", reply_markup=cancel_inline_kb())
        elif step == "adm_min_wd":
            try:
                set_setting("min_withdraw", str(float(text)))
                clear_state(uid)
                bot.send_message(uid, f"✅ মিনিমাম Withdraw <b>{text}</b> সেট হয়েছে।")
            except ValueError:
                bot.send_message(uid, "❌ সঠিক সংখ্যা দিন।", reply_markup=cancel_inline_kb())


# ==========================================
# MAIN RUNNER
# ==========================================
if __name__ == "__main__":
    start_health_server()
    init_db()
    try:
        BOT_USERNAME = bot.get_me().username or BOT_USERNAME
    except Exception:
        pass
    threading.Thread(target=otp_polling_worker, daemon=True).start()
    logger.info(f"Starting @{BOT_USERNAME}...")
    while True:
        try:
            bot.polling(
                none_stop=True,
                interval=1,
                timeout=30,
                long_polling_timeout=30,
                allowed_updates=["message", "callback_query", "chat_member"],
            )
        except Exception as e:
            logger.error(f"Polling error: {e}. Retrying in 5s...")
            time.sleep(5)