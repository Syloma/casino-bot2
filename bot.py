import sqlite3
import asyncio
import warnings
import random
import os
import time
import html
from pathlib import Path
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, ApplicationHandlerStop, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters

# Sarı renkli Python 3.12+ Deprecation uyarılarını gizler
warnings.filterwarnings("ignore", category=DeprecationWarning)

# --- 1. CONFIG VE YÖNETİCİ AYARLARI ---
BASE_DIR = Path(__file__).resolve().parent

def resolve_db_path():
    custom_db_path = os.getenv("CASINO_DB_PATH")
    if custom_db_path:
        return Path(custom_db_path)

    railway_volume_path = os.getenv("RAILWAY_VOLUME_MOUNT_PATH")
    if railway_volume_path:
        return Path(railway_volume_path) / "casino_database.db"

    is_railway = any(os.getenv(key) for key in [
        "RAILWAY_ENVIRONMENT",
        "RAILWAY_ENVIRONMENT_NAME",
        "RAILWAY_PROJECT_ID",
        "RAILWAY_SERVICE_ID",
    ])
    if is_railway:
        raise RuntimeError(
            "Railway'de kalıcı veritabanı yolu bulunamadı. "
            "Servise Volume bağla veya CASINO_DB_PATH=/data/casino_database.db ayarla."
        )

    return BASE_DIR / "data" / "casino_database.db"

DB_NAME = str(resolve_db_path())

# 🛑 YÖNETİCİ ID'LERİ VE BOT TOKENİ
ADMIN_IDS = [1282335065, 1553213587, 7244274042] 
TOKEN = "8900945222:AAF794z_zDLCs-RTkd9fTrKgh72Qp-nTnrU"

# --- 2. PARA BİRİMİ DÖNÜŞTÜRÜCÜLERİ ---
def parse_money(amount_str):
    """Metin tabanlı parayı (ör: 10t, 1.5kt) sayıya çevirir."""
    amount_str = str(amount_str).lower().strip()
    multipliers = {'kt': 10**15, 't': 10**12, 'b': 10**9, 'm': 10**6, 'k': 10**3}
    
    for suffix, mult in multipliers.items():
        if amount_str.endswith(suffix):
            try:
                num = float(amount_str.replace(suffix, ''))
                return int(num * mult)
            except ValueError:
                return None
    try:
        return int(float(amount_str))
    except ValueError:
        return None

def format_money(amount):
    """Sayıyı kısa metin formatına (ör: 1000000 -> 1m) çevirir."""
    if amount == 0: return "0"
    if amount >= 10**15: return f"{amount / 10**15:g}kt"
    if amount >= 10**12: return f"{amount / 10**12:g}t"
    if amount >= 10**9:  return f"{amount / 10**9:g}b"
    if amount >= 10**6:  return f"{amount / 10**6:g}m"
    if amount >= 10**3:  return f"{amount / 10**3:g}k"
    return str(amount)

def format_rate_percent(rate):
    return f"%{rate * 100:g}"

# --- OYUN LİMİTLERİ ---
MIN_BET_DART_BOWL = parse_money("25t")
MAX_BET_DART_BOWL = parse_money("250t")
MIN_BET_SLOT = parse_money("25t")
MAX_BET_SLOT = parse_money("250t")
MIN_BET_HORSE = parse_money("25t")
MAX_BET_HORSE = parse_money("250t")
MIN_BET_ROULETTE = parse_money("25t")
MAX_BET_ROULETTE = parse_money("250t")
MIN_BET_LCDP = parse_money("25t")
MAX_BET_LCDP = parse_money("250t")
MIN_BET_AVIATOR = parse_money("50t")
MAX_BET_AVIATOR = parse_money("200t")
MIN_BET_PVP = parse_money("20t")
MAX_BET_PVP = parse_money("500t")
PVP_COMMISSION_RATE = 0.10
PVP_PAYOUT_MULTIPLIER = 2 - PVP_COMMISSION_RATE
PVP_ROOMS = {}
XOX_SIZE = 6
XOX_EMPTY = "·"
PVP_TURN_SECONDS = 20
PVP_TURN_WARNING_SECONDS = 10
HORSE_CONFIG = {
    1: {"name": "Süleyman", "chance": 35, "multiplier": 1},
    2: {"name": "astral", "chance": 25, "multiplier": 2, "loss_message": "Astral kaybetti. Bana bastınız daha çok basın"},
    3: {"name": "ziyan", "chance": 15, "multiplier": 3, "loss_message": "Ziyan kaybetti. Yine ziyan oldu hayaller"},
    4: {"name": "jester", "chance": 12, "multiplier": 4, "loss_message": "Jester kaybetti. Daha 14 yaşındayım"},
    5: {"name": "rüştü", "chance": 8, "multiplier": 6, "loss_message": "Rüştü kaybetti. Yakşamlar gene düştü"},
    6: {"name": "Gölge", "chance": 2.5, "multiplier": 8},
    7: {"name": "Morning", "chance": 0.5, "multiplier": 50},
    8: {"name": "Roket", "chance": 2, "multiplier": 20},
}
ROULETTE_CONFIG = {
    "kirmizi": {"label": "Kırmızı", "chance": 48, "multiplier": 1.9, "icon": "🔴"},
    "kırmızı": {"label": "Kırmızı", "chance": 48, "multiplier": 1.9, "icon": "🔴"},
    "siyah": {"label": "Siyah", "chance": 48, "multiplier": 1.9, "icon": "⚫"},
    "yesil": {"label": "Yeşil", "chance": 1, "multiplier": 35, "icon": "🟢"},
    "yeşil": {"label": "Yeşil", "chance": 1, "multiplier": 35, "icon": "🟢"},
}
ROULETTE_OUTCOMES = [
    {"key": "kirmizi", "label": "Kırmızı", "chance": 48, "icon": "🔴"},
    {"key": "siyah", "label": "Siyah", "chance": 48, "icon": "⚫"},
    {"key": "yesil", "label": "Yeşil", "chance": 1, "icon": "🟢"},
]
LCDP_SYMBOL_CONFIG = [
    {"symbol": "🍇", "weight": 28, "pays": {8: 0.2, 10: 0.5, 12: 1, 15: 3}},
    {"symbol": "🏺", "weight": 23, "pays": {8: 0.3, 10: 0.7, 12: 1.5, 15: 4}},
    {"symbol": "🛡️", "weight": 18, "pays": {8: 0.42, 10: 1.125, 12: 3.0, 15: 7.5}},
    {"symbol": "🔥", "weight": 13, "pays": {8: 0.675, 10: 1.8, 12: 4.5, 15: 13.5}},
    {"symbol": "⚡", "weight": 9, "pays": {8: 1.2, 10: 3.3, 12: 9.0, 15: 33}},
    {"symbol": "👑", "weight": 5, "pays": {8: 2.25, 10: 6.75, 12: 21.0, 15: 67.5}},
    {"symbol": "💎", "weight": 3, "pays": {8: 3.75, 10: 12.0, 12: 42.0, 15: 135}},
    {"symbol": "💍", "weight": 1, "pays": {8: 7.5, 10: 27.0, 12: 90.0, 15: 270}},
]
LCDP_SYMBOLS = [item["symbol"] for item in LCDP_SYMBOL_CONFIG]
LCDP_SYMBOL_WEIGHTS = [item["weight"] for item in LCDP_SYMBOL_CONFIG]
LCDP_PAYTABLE = {item["symbol"]: item["pays"] for item in LCDP_SYMBOL_CONFIG}
LCDP_MULTIPLIER_TABLE = [
    (0, 60.0),
    (2, 20.0),
    (3, 10.0),
    (5, 5.0),
    (8, 3.0),
    (10, 1.0),
    (20, 0.65),
    (50, 0.25),
    (100, 0.10),
]
LCDP_FREE_SPIN_MULTIPLIER_TABLE = [
    (0, 51.55),
    (2, 2),
    (3, 10),
    (5, 5),
    (8, 3),
    (10, 1.8),
    (20, 1.0),
    (50, 0.5),
    (100, 0.15),
]
LCDP_FREE_SPIN_EXTRA_MULTIPLIER_ROLLS = [
    (0, 55),
    (1, 25),
    (2, 5),
    (3, 1.0),
]
LCDP_FREE_SPIN_SYMBOL = "💍"
LCDP_FREE_SPIN_TRIGGER_COUNT = 4
LCDP_FREE_SPIN_COUNT = 10
LCDP_FREE_SPIN_BUY_MULTIPLIER = 100
MIN_LCDP_FREE_SPIN_BUY = parse_money("100t")
MAX_LCDP_FREE_SPIN_BUY = parse_money("1kt")
LCDP_FREE_SPIN_BUY_ALIASES = {"freespin", "free", "fs", "satinal", "satınal", "satın", "satin"}
AVIATOR_HOUSE_EDGE = 0.02
AVIATOR_MAX_MULTIPLIER = 200.0
AVIATOR_MAX_AUTO_CASHOUT = 200.0
AVIATOR_TICK_SECONDS = 0.75
AVIATOR_MAX_TICKS = 90
AVIATOR_DISPLAY_UPDATE_SECONDS = 2.0
AVIATOR_CRASH_SYNC_DELAY_SECONDS = 2.0
AVIATOR_CHAT_ID = -1004258892386
AVIATOR_TOPIC_ID = 2
AVIATOR_ALLOWED_TOPICS = [
    (AVIATOR_CHAT_ID, AVIATOR_TOPIC_ID),
    (-1003294364148, 192915),
]
AVIATOR_MAX_PLAYERS_PER_ROUND = 25
AVIATOR_BET_START_DELAY_SECONDS = 20
AVIATOR_COUNTDOWN_SECONDS = 5
AVIATOR_CRASH_RANGES = [
    (24, 0.00, 1.00),
    (30, 1.01, 1.30),
    (24, 1.31, 2.00),
    (11, 2.01, 4.00),
    (6, 4.01, 10.00),
    (4, 10.01, 25.00),
    (0.5, 25.01, 99.99),
    (0.3, 100.00, 112.99),
    (0.1, 113.00, 180.99),
    (0.1, 181.00, 200.00),
]
AVIATOR_PENDING_BETS = {}
AVIATOR_CURRENT_ROUND = None
AVIATOR_LAST_STARTED_MINUTE = None
AVIATOR_START_TASKS = {}
AVIATOR_FORCED_CRASHES_SETTING = "aviator_forced_crashes"
AVIATOR_PROMO_SETTING = "aviator_promo"
NORMAL_GAME_TYPES = ['slot', 'dart', 'bowling', 'atyarisi', 'roulette', 'lcdp', 'aviator']
PVP_GAME_TYPES = ['pvp_zar', 'pvp_yirmibir', 'pvp_xox']
ACTIVE_GAME_TYPES = NORMAL_GAME_TYPES + PVP_GAME_TYPES
TEST_GAME_ALIASES = {
    "all": "all",
    "hepsi": "all",
    "tum": "all",
    "tüm": "all",
    "slot": "slot",
    "dart": "dart",
    "bowling": "bowling",
    "atyarisi": "atyarisi",
    "at": "atyarisi",
    "horse": "atyarisi",
    "rulet": "roulette",
    "roulette": "roulette",
    "lcdp": "lcdp",
    "aviator": "aviator",
    "av": "aviator",
    "ucak": "aviator",
    "uÃ§ak": "aviator",
}
HOUSE_MODE_WEIGHTS = {
    "normal": (1.0, 1.0),
}
HOUSE_MODE_ALIASES = {
    "normal": "normal",
    "standart": "normal",
}
FORCED_MODE_ALIASES = {
    "kazan": "win",
    "kazandir": "win",
    "kazandır": "win",
    "win": "win",
    "kaybet": "lose",
    "kaybettir": "lose",
    "lose": "lose",
    "oran": "rate",
    "rate": "rate",
}
HORSE_FINISH_LINE = 14
GAME_COOLDOWN_SECONDS = 1
TELEGRAM_MESSAGE_TIMEOUT_SECONDS = 5
MAINTENANCE_MODE = False
HOUSE_RESERVE_RATE = 0.20
PAYOUT_LIMIT_RATE = 1 - HOUSE_RESERVE_RATE
last_game_times = {}


# --- 3. VERİTABANI AYARLARI VE İSTATİSTİK ---
def init_db():
    Path(DB_NAME).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            balance INTEGER DEFAULT 0,
            username TEXT,
            first_name TEXT,
            last_name TEXT,
            total_added INTEGER DEFAULT 0,
            total_removed INTEGER DEFAULT 0
        )
    """)
    for column_name, column_type in [
        ("username", "TEXT"),
        ("first_name", "TEXT"),
        ("last_name", "TEXT"),
        ("total_added", "INTEGER DEFAULT 0"),
        ("total_removed", "INTEGER DEFAULT 0"),
    ]:
        try:
            cursor.execute(f"ALTER TABLE users ADD COLUMN {column_name} {column_type}")
        except sqlite3.OperationalError:
            pass
    # Oyun bazlı istatistikler tablosu
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS game_stats (
            game_type TEXT PRIMARY KEY,
            total_games INTEGER DEFAULT 0,
            winning_games INTEGER DEFAULT 0,
            total_wagered INTEGER DEFAULT 0,
            total_paid INTEGER DEFAULT 0
        )
    """)
    for game in ACTIVE_GAME_TYPES:
        cursor.execute("INSERT OR IGNORE INTO game_stats (game_type) VALUES (?)", (game,))

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_game_stats (
            user_id INTEGER NOT NULL,
            game_type TEXT NOT NULL,
            total_games INTEGER DEFAULT 0,
            winning_games INTEGER DEFAULT 0,
            total_wagered INTEGER DEFAULT 0,
            total_paid INTEGER DEFAULT 0,
            PRIMARY KEY (user_id, game_type)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS credit_requests (
            request_id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            amount INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            requested_at INTEGER NOT NULL,
            decided_at INTEGER,
            decided_by INTEGER,
            paid INTEGER DEFAULT 0,
            paid_at INTEGER,
            paid_marked_by INTEGER,
            deleted_at INTEGER,
            deleted_by INTEGER
        )
    """)
    for column_name, column_type in [
        ("paid", "INTEGER DEFAULT 0"),
        ("paid_at", "INTEGER"),
        ("paid_marked_by", "INTEGER"),
        ("deleted_at", "INTEGER"),
        ("deleted_by", "INTEGER"),
    ]:
        try:
            cursor.execute(f"ALTER TABLE credit_requests ADD COLUMN {column_name} {column_type}")
        except sqlite3.OperationalError:
            pass

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS aviator_rounds (
            round_id INTEGER PRIMARY KEY,
            crash_multiplier REAL NOT NULL,
            status TEXT NOT NULL,
            mode TEXT DEFAULT 'normal',
            total_bet INTEGER DEFAULT 0,
            paid_total INTEGER DEFAULT 0,
            started_at INTEGER NOT NULL,
            ended_at INTEGER,
            voided_at INTEGER,
            voided_by INTEGER,
            refunded_total INTEGER DEFAULT 0
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS aviator_round_bets (
            round_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            label TEXT,
            bet INTEGER NOT NULL,
            paid INTEGER DEFAULT 0,
            cashout_multiplier REAL,
            resolved INTEGER DEFAULT 0,
            refunded INTEGER DEFAULT 0,
            refund_amount INTEGER DEFAULT 0,
            PRIMARY KEY (round_id, user_id)
        )
    """)
    
    conn.commit()
    conn.close()

def escape_markdown(text):
    return (
        str(text)
        .replace("\\", "\\\\")
        .replace("_", "\\_")
        .replace("*", "\\*")
        .replace("`", "\\`")
        .replace("[", "\\[")
        .replace("]", "\\]")
        .replace("(", "\\(")
        .replace(")", "\\)")
    )

def remember_user(user):
    if user is None:
        return
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO users (user_id, balance, username, first_name, last_name)
        VALUES (?, 0, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            username = excluded.username,
            first_name = excluded.first_name,
            last_name = excluded.last_name
        """,
        (user.id, user.username, user.first_name, user.last_name)
    )
    conn.commit()
    conn.close()

async def check_game_cooldown(update):
    user_id = update.effective_user.id
    now = time.monotonic()
    last_time = last_game_times.get(user_id, 0)
    remaining = GAME_COOLDOWN_SECONDS - (now - last_time)
    if remaining > 0:
        thread_id = update.message.message_thread_id if update.message else None
        await update.message.reply_text(
            f"⏳ Çok hızlı oynuyorsun! {remaining:.1f} sn sonra tekrar dene.",
            message_thread_id=thread_id
        )
        return False

    last_game_times[user_id] = now
    return True

async def maintenance_gate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not MAINTENANCE_MODE or update.effective_user.id in ADMIN_IDS:
        return

    thread_id = update.message.message_thread_id if update.message else None
    await update.message.reply_text(
        "🛠️ Bot şu anda bakımda. Lütfen daha sonra tekrar dene.",
        message_thread_id=thread_id
    )
    raise ApplicationHandlerStop

def find_user_id_by_username(username):
    username = username.lower().lstrip("@")
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM users WHERE lower(username) = ?", (username,))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else None

def transfer_balance(sender_id, target_id, amount):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    try:
        cursor.execute("BEGIN IMMEDIATE")
        cursor.execute("SELECT balance FROM users WHERE user_id = ?", (sender_id,))
        sender_row = cursor.fetchone()
        sender_balance = sender_row[0] if sender_row else 0

        if sender_balance < amount:
            conn.rollback()
            return None

        cursor.execute("INSERT OR IGNORE INTO users (user_id, balance) VALUES (?, 0)", (target_id,))
        cursor.execute("UPDATE users SET balance = balance - ? WHERE user_id = ?", (amount, sender_id))
        cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, target_id))
        conn.commit()
        return sender_balance - amount
    finally:
        conn.close()

def get_balance(user_id):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    if row is None:
        cursor.execute("INSERT OR IGNORE INTO users (user_id, balance) VALUES (?, ?)", (user_id, 0))
        conn.commit()
        balance = 0
    else:
        balance = row[0]
    conn.close()
    return balance

def update_balance(user_id, amount):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    current = get_balance(user_id)
    new_balance = max(0, current + amount)
    cursor.execute("UPDATE users SET balance = ? WHERE user_id = ?", (new_balance, user_id))
    conn.commit()
    conn.close()
    return new_balance

def update_admin_balance_totals(user_id, added=0, removed=0):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("INSERT OR IGNORE INTO users (user_id, balance) VALUES (?, 0)", (user_id,))
    cursor.execute(
        "UPDATE users SET total_added = total_added + ?, total_removed = total_removed + ? WHERE user_id = ?",
        (added, removed, user_id)
    )
    conn.commit()
    conn.close()

def update_game_stats(game_type, wagered_amount, paid_amount, is_win, user_id=None):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    win_int = 1 if is_win else 0
    cursor.execute("""
        UPDATE game_stats 
        SET total_games = total_games + 1,
            winning_games = winning_games + ?,
            total_wagered = total_wagered + ?,
            total_paid = total_paid + ?
        WHERE game_type = ?
    """, (win_int, wagered_amount, paid_amount, game_type))

    if user_id is not None:
        cursor.execute(
            "INSERT OR IGNORE INTO user_game_stats (user_id, game_type) VALUES (?, ?)",
            (user_id, game_type)
        )
        cursor.execute("""
            UPDATE user_game_stats
            SET total_games = total_games + 1,
                winning_games = winning_games + ?,
                total_wagered = total_wagered + ?,
                total_paid = total_paid + ?
            WHERE user_id = ? AND game_type = ?
        """, (win_int, wagered_amount, paid_amount, user_id, game_type))
    conn.commit()
    conn.close()

def get_setting(key, default=None):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else default

def set_setting(key, value):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    if value is None:
        cursor.execute("DELETE FROM settings WHERE key = ?", (key,))
    else:
        cursor.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value)
        )
    conn.commit()
    conn.close()

def parse_percent(value):
    try:
        percent = float(str(value).replace("%", "").strip())
    except (TypeError, ValueError):
        return None
    if percent < 0 or percent > 100:
        return None
    return percent

def format_percent(value):
    return f"{value:g}"

def get_house_state(candidate_payout=0):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT SUM(total_added), SUM(total_removed) FROM users")
    total_added, total_removed = cursor.fetchone()
    placeholders = ",".join("?" for _ in ACTIVE_GAME_TYPES)
    cursor.execute(
        f"SELECT SUM(total_wagered), SUM(total_paid) FROM game_stats WHERE game_type IN ({placeholders})",
        ACTIVE_GAME_TYPES
    )
    total_wagered, total_paid = cursor.fetchone()
    conn.close()

    total_added = total_added or 0
    total_removed = total_removed or 0
    total_wagered = total_wagered or 0
    total_paid = total_paid or 0
    payout_limit = int(total_added * PAYOUT_LIMIT_RATE)
    projected_paid = total_paid + int(candidate_payout or 0)

    auto_mode = "normal"
    override_mode = get_setting("house_mode_override")
    if override_mode not in HOUSE_MODE_WEIGHTS:
        override_mode = None

    forced_win_rate = parse_percent(get_setting("forced_win_rate"))

    mode = override_mode or auto_mode
    win_weight, loss_weight = HOUSE_MODE_WEIGHTS[mode]

    return {
        "mode": mode,
        "auto_mode": auto_mode,
        "override_mode": override_mode,
        "total_added": total_added,
        "total_removed": total_removed,
        "total_wagered": total_wagered,
        "total_paid": total_paid,
        "payout_limit": payout_limit,
        "projected_paid": projected_paid,
        "win_weight": win_weight,
        "loss_weight": loss_weight,
        "forced_win_rate": forced_win_rate,
    }

def decide_forced_win(house_state):
    forced_win_rate = house_state.get("forced_win_rate")
    if forced_win_rate is None:
        return None
    if forced_win_rate >= 100:
        return True
    if forced_win_rate <= 0:
        return False
    return None

def get_forced_weight_factor(house_state):
    forced_win_rate = house_state.get("forced_win_rate")
    if forced_win_rate is None or forced_win_rate <= 0 or forced_win_rate >= 100:
        return 1.0
    return forced_win_rate / (100 - forced_win_rate)

def choose_roulette_outcome(selected_config, bet):
    candidate_payout = int(bet * selected_config["multiplier"])
    house_state = get_house_state(candidate_payout)
    forced_win = decide_forced_win(house_state)
    if forced_win is True:
        return next(item for item in ROULETTE_OUTCOMES if item["label"] == selected_config["label"])
    if forced_win is False:
        losing_outcomes = [item for item in ROULETTE_OUTCOMES if item["label"] != selected_config["label"]]
        return random.choices(losing_outcomes, weights=[item["chance"] for item in losing_outcomes], k=1)[0]

    weights = []
    for item in ROULETTE_OUTCOMES:
        weight = item["chance"]
        forced_factor = get_forced_weight_factor(house_state)
        if item["label"] == selected_config["label"]:
            weight *= forced_factor
        weights.append(weight)
    return random.choices(ROULETTE_OUTCOMES, weights=weights, k=1)[0]

def choose_horse_winner(selected_horse, bet):
    selected_multiplier = HORSE_CONFIG[selected_horse]["multiplier"]
    candidate_payout = int(bet * selected_multiplier)
    house_state = get_house_state(candidate_payout)
    forced_win = decide_forced_win(house_state)
    if forced_win is True:
        return selected_horse

    horses = list(HORSE_CONFIG.keys())
    if forced_win is False:
        losing_horses = [horse for horse in horses if horse != selected_horse]
        return random.choices(
            losing_horses,
            weights=[HORSE_CONFIG[horse]["chance"] for horse in losing_horses],
            k=1
        )[0]

    weights = []
    forced_factor = get_forced_weight_factor(house_state)
    for horse in horses:
        weight = HORSE_CONFIG[horse]["chance"]
        if horse == selected_horse:
            weight *= forced_factor
        weights.append(weight)
    return random.choices(horses, weights=weights, k=1)[0]

def build_house_mode_text():
    house_state = get_house_state()
    payout_limit = house_state["payout_limit"]
    total_paid = house_state["total_paid"]
    limit_usage = (total_paid / payout_limit * 100) if payout_limit > 0 else 0
    bar_filled = min(10, max(0, int(limit_usage // 10)))
    usage_bar = "█" * bar_filled + "░" * (10 - bar_filled)
    mode = house_state["mode"]
    mode_info = {
        "normal": ("⚪ NORMAL", "Yüzdeli mod kapalı; oyunlar kendi normal ihtimaliyle çalışıyor."),
    }
    mode_label, mode_desc = mode_info.get(mode, (mode.upper(), "Mod bilgisi hesaplandı."))
    control_text = "Yüzdeli mod kapalı"
    forced_win_rate = house_state["forced_win_rate"]
    if forced_win_rate is not None:
        if forced_win_rate == 50:
            control_text = "Yüzdeli mod aktif: **%50 normal ağırlık**"
        elif forced_win_rate >= 100:
            control_text = "Yüzdeli mod aktif: **%100 garanti kazanma**"
        elif forced_win_rate <= 0:
            control_text = "Yüzdeli mod aktif: **%100 garanti kaybetme**"
        else:
            control_text = (
                f"Yüzdeli ağırlık aktif: **%{format_percent(forced_win_rate)} kazanma tarafı** "
                f"| **%{format_percent(100 - forced_win_rate)} kaybetme tarafı**"
            )
    return (
        f"🧭 **KASA MODU**\n\n"
        f"Durum: **{mode_label}**\n"
        f"{mode_desc}\n\n"
        f"🎛️ Kontrol: {control_text}\n"
        f"🎯 Etkilenen oyunlar: **At Yarışı, Rulet, LCDP**\n"
        f"🎲 Slot/Dart/Bowling: Telegram sonucu değişmediği için mod dışı\n\n"
        f"💰 Toplam Yatırılan: **{format_money(house_state['total_added'])}**\n"
        f"🎯 Ödeme Limiti (%80): **{format_money(payout_limit)}**\n"
        f"💸 Toplam Dağıtılan: **{format_money(total_paid)}**\n"
        f"📊 Limit Kullanımı: **%{limit_usage:.1f}**\n"
        f"`{usage_bar}`\n\n"
        f"`/mod normal` yüzdeli modu kapatır\n"
        f"`/mod kazan 80`, `/mod kaybet 80`, `/mod oran 35`"
    )

# --- 4. OYUNCU KOMUTLARI VE OYUNLAR ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    remember_user(update.effective_user)
    balance = get_balance(user_id)
    
    welcome_text = (
        f"🎰 **Casino Botuna Hoş Geldin!** 🎰\n\n"
        f"💰 **Mevcut Bakiyen:** {format_money(balance)} Çip\n"
        f"🆔 **Senin ID'n:** `{user_id}`\n\n"
        f"🎯 **Hızlı Oyun Menüsü**\n"
        f"• `/slot [Bahis]` -> Slot çevirir. 🎰\n"
        f"• `/dart [Bahis]` -> Dart atar. 🎯\n"
        f"• `/bowling [Bahis]` -> Bowling topu fırlatır. 🎳\n"
        f"• `/atyarisi [Bahis] [At No]` -> At yarışı oynar. 🐎\n\n"
        f"• `/rulet [Bahis] [Renk]` -> Rulet oynar. 🎡\n\n"
        f"• `/lcdp [Bahis]` -> Bahisli LCDP oynar. 🏛️\n"
        f"• `/lcdpfs [Miktar]` -> LCDP free spin satin alir. 🎁\n\n"
        f"• `/aviator [Bahis] [Oto Çıkış]` -> Bahisten 20 saniye sonra ortak Aviator turuna katılır. ✈️\n\n"
        f"*(Bahislerde 10t, 20t, 100t gibi kısaltmalar kullanabilirsin)*\n"
        f"Tüm detaylar için **/komut** yazabilirsin!"
    )
    await update.message.reply_text(welcome_text, parse_mode="Markdown")

# 🎰 SLOT OYUNU
async def play_slot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    remember_user(update.effective_user)
    if not await check_game_cooldown(update):
        return
    chat_id = update.effective_chat.id
    thread_id = update.message.message_thread_id if update.message else None

    if not context.args:
        await update.message.reply_text(f"❌ Kullanım: /slot [Miktar] (Min {format_money(MIN_BET_SLOT)} - Max {format_money(MAX_BET_SLOT)})", message_thread_id=thread_id)
        return

    bet = parse_money(context.args[0])
    if bet is None or bet < MIN_BET_SLOT or bet > MAX_BET_SLOT:
        await update.message.reply_text(f"❌ Hatalı bahis! (Min {format_money(MIN_BET_SLOT)} - Max {format_money(MAX_BET_SLOT)})", message_thread_id=thread_id)
        return

    if get_balance(user_id) < bet:
        await update.message.reply_text("❌ Bakiyen yetersiz!", message_thread_id=thread_id)
        return

    # Bahsi düş
    update_balance(user_id, -bet)
    
    # Slot animasyonu
    slot_result = await context.bot.send_dice(chat_id=chat_id, emoji="🎰", message_thread_id=thread_id)
    val = slot_result.dice.value
    # Kazanma mantığı (Burada çarpanları kesin olarak ayırdık)
    win_amount = 0
    is_win = False
    result_text = ""

    if val == 64: # 777 durumu
        win_amount = bet * 24
        is_win = True
        result_text = f"🎉 **7-7-7 GELDİ!** 24 Katını kazandın! (+{format_money(win_amount)})"
    elif val in [1, 22, 43]: # 3'lü kombinasyon
        win_amount = bet * 7.5
        is_win = True
        result_text = f"🔥 **3'lü Kombinasyon!** 7.5 Katını kazandın! (+{format_money(win_amount)})"
    else:
        win_amount = 0
        is_win = False
        result_text = "😔 **Maalesef kazanamadın.**"

    # İstatistikleri güncelle (Önce stat, sonra bakiye)
    update_game_stats('slot', bet, win_amount, is_win, user_id)
    
    # Yeni bakiyeyi güncelle (Eğer win_amount 0 ise bakiye değişmez)
    new_bal = update_balance(user_id, win_amount)
    
    await update.message.reply_text(f"{result_text}\n💳 Güncel Bakiye: {format_money(new_bal)}", parse_mode="Markdown", message_thread_id=thread_id)
# 🎯 DART OYUNU
async def play_dart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    remember_user(update.effective_user)
    if not await check_game_cooldown(update):
        return
    chat_id = update.effective_chat.id
    thread_id = update.message.message_thread_id if update.message else None

    if not context.args:
        await update.message.reply_text(f"❌ **Kullanım:** `/dart [Miktar]`\n📌 Dart Min: {format_money(MIN_BET_DART_BOWL)} | Max: {format_money(MAX_BET_DART_BOWL)}", parse_mode="Markdown", message_thread_id=thread_id)
        return

    bet = parse_money(context.args[0])
    if bet is None or bet < MIN_BET_DART_BOWL or bet > MAX_BET_DART_BOWL:
        await update.message.reply_text(f"❌ **Geçersiz bahis!**\nDart için sadece **{format_money(MIN_BET_DART_BOWL)}** ile **{format_money(MAX_BET_DART_BOWL)}** arası oynayabilirsin.", parse_mode="Markdown", message_thread_id=thread_id)
        return

    current_balance = get_balance(user_id)
    if current_balance < bet:
        await update.message.reply_text("❌ **Bakiyen yetersiz!**", message_thread_id=thread_id)
        return

    update_balance(user_id, -bet)
    
    dart_result = await context.bot.send_dice(chat_id=chat_id, emoji="🎯", message_thread_id=thread_id)
    dice_value = dart_result.dice.value

    await asyncio.sleep(2) 

    win_amount = 0
    is_win = False
    
    if dice_value == 6:
        win_amount = bet * 4
        is_win = True
        result_text = f"🎯 **TAM İSABET! BAŞARILI ATIŞ!** 🎯\n🔥 **Bahsinin 4 Katını Kazandın! (+{format_money(win_amount)})**"
    else:
        result_text = f"😔 **Karavana!** (-{format_money(bet)})\nİstediğin atışı yapamadın."

    update_game_stats('dart', bet, win_amount, is_win, user_id)
    new_balance = update_balance(user_id, win_amount)
    final_message = f"{result_text}\n\n💳 **Güncel Bakiyen:** {format_money(new_balance)} Çip"
    await update.message.reply_text(final_message, parse_mode="Markdown", message_thread_id=thread_id)

# 🎳 BOWLING OYUNU
async def play_bowling(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    remember_user(update.effective_user)
    if not await check_game_cooldown(update):
        return
    chat_id = update.effective_chat.id
    thread_id = update.message.message_thread_id if update.message else None

    if not context.args:
        await update.message.reply_text(f"❌ **Kullanım:** `/bowling [Miktar]`\n📌 Bowling Min: {format_money(MIN_BET_DART_BOWL)} | Max: {format_money(MAX_BET_DART_BOWL)}", parse_mode="Markdown", message_thread_id=thread_id)
        return

    bet = parse_money(context.args[0])
    if bet is None or bet < MIN_BET_DART_BOWL or bet > MAX_BET_DART_BOWL:
        await update.message.reply_text(f"❌ **Geçersiz bahis!**\nBowling için sadece **{format_money(MIN_BET_DART_BOWL)}** ile **{format_money(MAX_BET_DART_BOWL)}** arası oynayabilirsin.", parse_mode="Markdown", message_thread_id=thread_id)
        return

    current_balance = get_balance(user_id)
    if current_balance < bet:
        await update.message.reply_text("❌ **Bakiyen yetersiz!**", message_thread_id=thread_id)
        return

    update_balance(user_id, -bet)
    
    bowling_result = await context.bot.send_dice(chat_id=chat_id, emoji="🎳", message_thread_id=thread_id)
    dice_value = bowling_result.dice.value

    await asyncio.sleep(2.5) 

    win_amount = 0
    is_win = False
    
    if dice_value == 6:
        win_amount = bet * 5
        is_win = True
        result_text = f"🎳 **STRIKE! BAŞARILI ATIŞ!** 🎳\n🔥 **Bahsinin 5 Katını Kazandın! (+{format_money(win_amount)})**"
    else:
        result_text = f"😔 **Oluk!** (-{format_money(bet)})\nTop yoldan çıktı veya az labut devrildi."

    update_game_stats('bowling', bet, win_amount, is_win, user_id)
    new_balance = update_balance(user_id, win_amount)
    final_message = f"{result_text}\n\n💳 **Güncel Bakiyen:** {format_money(new_balance)} Çip"
    await update.message.reply_text(final_message, parse_mode="Markdown", message_thread_id=thread_id)

async def play_roulette(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    remember_user(update.effective_user)
    if not await check_game_cooldown(update):
        return
    thread_id = update.message.message_thread_id if update.message else None

    if len(context.args) < 2:
        await update.message.reply_text(
            f"❌ **Kullanım:** `/rulet [Miktar] [Renk]`\n"
            f"Renkler: `kirmizi`, `siyah`, `yesil`\n"
            f"Min {format_money(MIN_BET_ROULETTE)} | Max {format_money(MAX_BET_ROULETTE)}",
            parse_mode="Markdown",
            message_thread_id=thread_id
        )
        return

    bet = parse_money(context.args[0])
    selected_color = context.args[1].lower().strip()
    selected_config = ROULETTE_CONFIG.get(selected_color)

    if bet is None or bet < MIN_BET_ROULETTE or bet > MAX_BET_ROULETTE:
        await update.message.reply_text(
            f"❌ Geçersiz bahis! Rulet için **{format_money(MIN_BET_ROULETTE)}** ile **{format_money(MAX_BET_ROULETTE)}** arası oynayabilirsin.",
            parse_mode="Markdown",
            message_thread_id=thread_id
        )
        return

    if selected_config is None:
        await update.message.reply_text("❌ Geçersiz renk! `kirmizi`, `siyah` veya `yesil` seç.", parse_mode="Markdown", message_thread_id=thread_id)
        return

    if get_balance(user_id) < bet:
        await update.message.reply_text("❌ **Bakiyen yetersiz!**", parse_mode="Markdown", message_thread_id=thread_id)
        return

    update_balance(user_id, -bet)

    outcome = choose_roulette_outcome(selected_config, bet)

    is_win = outcome["label"] == selected_config["label"]
    win_amount = int(bet * selected_config["multiplier"]) if is_win else 0
    update_game_stats('roulette', bet, win_amount, is_win, user_id)
    new_balance = update_balance(user_id, win_amount)

    if is_win:
        result_text = (
            f"🎡 Rulet sonucu: {outcome['icon']} **{outcome['label']}**\n"
            f"🎉 Kazandın! Bahsinin **x{selected_config['multiplier']:g}** katını aldın. (+{format_money(win_amount)})"
        )
    else:
        result_text = (
            f"🎡 Rulet sonucu: {outcome['icon']} **{outcome['label']}**\n"
            f"😔 Kaybettin. Seçimin: {selected_config['icon']} **{selected_config['label']}** (-{format_money(bet)})"
        )

    await update.message.reply_text(
        f"{result_text}\n\n💳 **Güncel Bakiyen:** {format_money(new_balance)} Çip",
        parse_mode="Markdown",
        message_thread_id=thread_id
    )

def render_lcdp_grid(grid):
    return "\n".join(" ".join(row) for row in grid)

def draw_lcdp_grid():
    return [
        [random.choices(LCDP_SYMBOLS, weights=LCDP_SYMBOL_WEIGHTS, k=1)[0] for _ in range(6)]
        for _ in range(5)
    ]

def build_lcdp_loss_grid():
    counts = [5, 5, 4, 4, 4, 4, 4, 2]
    cells = []
    for symbol, count in zip(LCDP_SYMBOLS, counts):
        cells.extend([symbol] * count)
    random.shuffle(cells)
    return [cells[row * 6:(row + 1) * 6] for row in range(5)]

def build_lcdp_win_grid():
    cells = [random.choices(LCDP_SYMBOLS, weights=LCDP_SYMBOL_WEIGHTS, k=1)[0] for _ in range(30)]
    winning_symbol = random.choices(LCDP_SYMBOLS, weights=LCDP_SYMBOL_WEIGHTS, k=1)[0]
    for index in random.sample(range(30), 8):
        cells[index] = winning_symbol
    return [cells[row * 6:(row + 1) * 6] for row in range(5)]

def get_lcdp_base_multiplier(match_count):
    if match_count >= 15:
        return 25
    if match_count >= 12:
        return 8
    if match_count >= 10:
        return 3
    if match_count >= 8:
        return 1.5
    return 0

def get_lcdp_symbol_multiplier(symbol, match_count):
    paytable = LCDP_PAYTABLE.get(symbol, {})
    multiplier = 0
    for threshold, payout in sorted(paytable.items()):
        if match_count >= threshold:
            multiplier = payout
    return multiplier

def choose_lcdp_multiplier_from_table(multiplier_table, house_state=None):
    weights = []
    forced_factor = get_forced_weight_factor(house_state) if house_state else 1.0
    for multiplier, chance in multiplier_table:
        weight = chance
        if house_state:
            weight *= 1.0 if multiplier == 0 else forced_factor
        weights.append(weight)
    multipliers = [item[0] for item in multiplier_table]
    return random.choices(multipliers, weights=weights, k=1)[0]

def choose_lcdp_multiplier(house_state=None):
    return choose_lcdp_multiplier_from_table(LCDP_MULTIPLIER_TABLE, house_state)

def choose_lcdp_free_spin_multipliers(house_state=None):
    extra_rolls = random.choices(
        [item[0] for item in LCDP_FREE_SPIN_EXTRA_MULTIPLIER_ROLLS],
        weights=[item[1] for item in LCDP_FREE_SPIN_EXTRA_MULTIPLIER_ROLLS],
        k=1
    )[0]
    multipliers = []
    for _ in range(1 + extra_rolls):
        multiplier = choose_lcdp_multiplier_from_table(LCDP_FREE_SPIN_MULTIPLIER_TABLE, house_state)
        if multiplier > 0:
            multipliers.append(multiplier)
    return multipliers

def evaluate_lcdp_spin(grid):
    counts = {symbol: sum(row.count(symbol) for row in grid) for symbol in LCDP_SYMBOLS}
    best_symbol, best_count = max(
        counts.items(),
        key=lambda item: get_lcdp_symbol_multiplier(item[0], item[1])
    )
    base_multiplier = get_lcdp_symbol_multiplier(best_symbol, best_count)
    scatter_count = counts.get(LCDP_FREE_SPIN_SYMBOL, 0)
    return best_symbol, best_count, base_multiplier, scatter_count

def draw_lcdp_grid_for_result(forced_win=None):
    if forced_win is None:
        return draw_lcdp_grid()

    for _ in range(100):
        grid = draw_lcdp_grid()
        _, _, base_multiplier, scatter_count = evaluate_lcdp_spin(grid)
        is_win_grid = base_multiplier > 0
        if forced_win and is_win_grid:
            return grid
        if not forced_win and not is_win_grid and scatter_count < LCDP_FREE_SPIN_TRIGGER_COUNT:
            return grid

    return build_lcdp_win_grid() if forced_win else build_lcdp_loss_grid()

def format_lcdp_multiplier(multiplier):
    return "yok" if multiplier == 0 else f"x{multiplier:g}"

def format_lcdp_multipliers(multipliers):
    return "yok" if not multipliers else " + ".join(f"x{multiplier:g}" for multiplier in multipliers)

def run_lcdp_free_spins(bet, house_state, forced_result=None):
    accumulated_multiplier = 0
    free_spin_total = 0
    free_spin_lines = []

    for spin_no in range(1, LCDP_FREE_SPIN_COUNT + 1):
        spin_forced_result = forced_result if spin_no == 1 else (False if forced_result is False else None)
        free_grid = draw_lcdp_grid_for_result(spin_forced_result)
        fs_symbol, fs_count, fs_base_multiplier, _ = evaluate_lcdp_spin(free_grid)
        fs_multipliers = [] if forced_result is False else choose_lcdp_free_spin_multipliers(house_state)
        accumulated_multiplier += sum(fs_multipliers)
        fs_paid_multiplier = fs_base_multiplier * (accumulated_multiplier if accumulated_multiplier > 0 else 1)
        fs_win = int(bet * fs_paid_multiplier) if fs_paid_multiplier > 0 else 0
        free_spin_total += fs_win
        free_spin_lines.append(
            f"{spin_no}. spin: {fs_symbol} x{fs_count} | carpanlar {format_lcdp_multipliers(fs_multipliers)} | biriken x{accumulated_multiplier:g} | +{format_money(fs_win)}"
        )

    return free_spin_total, free_spin_lines

async def play_lcdp(update: Update, context: ContextTypes.DEFAULT_TYPE, force_free_spin_buy=False):
    user_id = update.effective_user.id
    remember_user(update.effective_user)
    if not await check_game_cooldown(update):
        return
    thread_id = update.message.message_thread_id if update.message else None
    args = context.args or (update.message.text.split()[1:] if update.message and update.message.text else [])

    normalized_args = [arg.lower().strip() for arg in args]
    buy_mode = force_free_spin_buy or any(arg in LCDP_FREE_SPIN_BUY_ALIASES for arg in normalized_args)
    bet_arg = next((arg for arg in args if parse_money(arg) is not None), None)

    if not bet_arg:
        await update.message.reply_text(
            f"❌ **Kullanim:** `/lcdp [Miktar]`\n"
            f"Free spin satin alma: `/lcdp [Miktar] freespin` veya `/lcdpfs [Miktar]`\n"
            f"Normal oyun: {format_money(MIN_BET_LCDP)} - {format_money(MAX_BET_LCDP)}\n"
            f"Free spin satin alma: {format_money(MIN_LCDP_FREE_SPIN_BUY)} - {format_money(MAX_LCDP_FREE_SPIN_BUY)}\n"
            f"Free spinlerde ayni turda birden fazla carpan gelebilir ve carpan ihtimali daha yuksektir.",
            parse_mode="Markdown",
            message_thread_id=thread_id
        )
        return

    amount = parse_money(bet_arg)
    if amount is None:
        await update.message.reply_text("❌ Gecersiz miktar!", parse_mode="Markdown", message_thread_id=thread_id)
        return

    if buy_mode:
        if amount < MIN_LCDP_FREE_SPIN_BUY or amount > MAX_LCDP_FREE_SPIN_BUY:
            await update.message.reply_text(
                f"❌ Gecersiz free spin satin alma tutari! **{format_money(MIN_LCDP_FREE_SPIN_BUY)}** ile **{format_money(MAX_LCDP_FREE_SPIN_BUY)}** arasinda secmelisin.",
                parse_mode="Markdown",
                message_thread_id=thread_id
            )
            return
        charge_amount = amount
        bet = max(1, charge_amount // LCDP_FREE_SPIN_BUY_MULTIPLIER)
    else:
        bet = amount
        if bet < MIN_BET_LCDP or bet > MAX_BET_LCDP:
            await update.message.reply_text(
                f"❌ Gecersiz bahis! LCDP icin **{format_money(MIN_BET_LCDP)}** ile **{format_money(MAX_BET_LCDP)}** arasinda oynayabilirsin.",
                parse_mode="Markdown",
                message_thread_id=thread_id
            )
            return
        charge_amount = bet

    if get_balance(user_id) < charge_amount:
        await update.message.reply_text(
            f"❌ **Bakiyen yetersiz!** Gereken: {format_money(charge_amount)} Cip",
            parse_mode="Markdown",
            message_thread_id=thread_id
        )
        return

    update_balance(user_id, -charge_amount)

    if buy_mode:
        house_state = get_house_state()
        forced_result = decide_forced_win(house_state)
        free_spin_total, free_spin_lines = run_lcdp_free_spins(bet, house_state, forced_result)
        is_win = free_spin_total > 0
        update_game_stats('lcdp', charge_amount, free_spin_total, is_win, user_id)
        new_balance = update_balance(user_id, free_spin_total)
        result_header = "🏛️ **FREE SPIN KAZANDIRDI!**" if is_win else "🌫️ **Free spin sessiz kaldi.**"

        await update.message.reply_text(
            f"{result_header}\n"
            f"Satın alma tutari: **{format_money(charge_amount)}**\n"
            f"Spin degeri: **{format_money(bet)}**\n"
            f"Spin kazanci: **{format_money(free_spin_total)}**\n\n"
            f"{chr(10).join(free_spin_lines)}\n\n"
            f"Toplam kazanc: **{format_money(free_spin_total)}**\n"
            f"💳 Guncel Bakiyen: **{format_money(new_balance)}** Cip",
            parse_mode="Markdown",
            message_thread_id=thread_id
        )
        return

    house_state = get_house_state()
    forced_result = decide_forced_win(house_state)
    grid = draw_lcdp_grid_for_result(forced_result)
    best_symbol, best_count, base_multiplier, scatter_count = evaluate_lcdp_spin(grid)
    hand_multiplier = 0 if forced_result is False else choose_lcdp_multiplier(house_state)
    paid_multiplier = base_multiplier * (hand_multiplier if hand_multiplier > 0 else 1)
    main_win = int(bet * paid_multiplier) if paid_multiplier > 0 else 0
    free_spin_total = 0
    free_spin_lines = []

    if scatter_count >= LCDP_FREE_SPIN_TRIGGER_COUNT:
        free_spin_lines.append(f"\n🎁 **FREE SPIN:** {scatter_count} scatter ile {LCDP_FREE_SPIN_COUNT} spin acildi!")
        free_spin_total, triggered_free_spin_lines = run_lcdp_free_spins(bet, house_state, forced_result)
        free_spin_lines.extend(triggered_free_spin_lines)

    total_win = main_win + free_spin_total
    is_win = total_win > 0
    update_game_stats('lcdp', bet, total_win, is_win, user_id)
    new_balance = update_balance(user_id, total_win)
    result_header = "🏛️ **LCDP KAZANDIRDI!**" if is_win else "🌫️ **LCDP sessiz kaldi.**"
    free_text = "\n".join(free_spin_lines)

    result_text = (
        f"{result_header}\n"
        f"En iyi sembol: {best_symbol} x{best_count}\n"
        f"Sembol odemesi: **x{base_multiplier:g}**\n"
        f"El carpani: **{format_lcdp_multiplier(hand_multiplier)}**\n"
        f"Ana el kazanci: **{format_money(main_win)}**\n"
        f"Free spin kazanci: **{format_money(free_spin_total)}**"
        f"{free_text}\n\n"
        f"Toplam kazanc: **{format_money(total_win)}**\n"
        f"💳 Guncel Bakiyen: **{format_money(new_balance)}** Cip"
    )

    await update.message.reply_text(
        f"```\n{render_lcdp_grid(grid)}\n```\n{result_text}",
        parse_mode="Markdown",
        message_thread_id=thread_id
    )

async def buy_lcdp_free_spin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await play_lcdp(update, context, force_free_spin_buy=True)

def render_horse_race(positions):
    lines = []
    for horse in HORSE_CONFIG:
        pos = min(positions[horse], HORSE_FINISH_LINE)
        track = "." * pos + "H" + "." * (HORSE_FINISH_LINE - pos) + "|"
        lines.append(f"{horse}: {track}")
    return "\n".join(lines)

async def safe_edit_race_message(message, text):
    try:
        await asyncio.wait_for(
            message.edit_text(text, parse_mode="Markdown"),
            timeout=TELEGRAM_MESSAGE_TIMEOUT_SECONDS
        )
        return True
    except Exception:
        return False

async def safe_reply_text(update, text, parse_mode=None, message_thread_id=None):
    try:
        return await asyncio.wait_for(
            update.message.reply_text(
                text,
                parse_mode=parse_mode,
                message_thread_id=message_thread_id
            ),
            timeout=TELEGRAM_MESSAGE_TIMEOUT_SECONDS
        )
    except Exception:
        return None

async def safe_send_message(context, chat_id, text, parse_mode=None, message_thread_id=None):
    try:
        return await asyncio.wait_for(
            context.bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode=parse_mode,
                message_thread_id=message_thread_id
            ),
            timeout=TELEGRAM_MESSAGE_TIMEOUT_SECONDS
        )
    except Exception:
        return None

async def safe_query_answer(query, text=None, show_alert=False, timeout=1.0):
    try:
        await asyncio.wait_for(
            query.answer(text=text, show_alert=show_alert),
            timeout=timeout
        )
    except Exception:
        pass

async def safe_delete_message(message, timeout=1.0):
    try:
        await asyncio.wait_for(message.delete(), timeout=timeout)
    except Exception:
        pass

async def send_admin_private_notice(context, admin_id, text, parse_mode=None):
    return await safe_send_message(context, admin_id, text, parse_mode=parse_mode)

async def send_all_admin_private_notices(context, text, parse_mode=None):
    sent_count = 0
    for admin_id in ADMIN_IDS:
        sent_message = await send_admin_private_notice(context, admin_id, text, parse_mode=parse_mode)
        if sent_message is not None:
            sent_count += 1
    return sent_count

def split_telegram_text(text, limit=3800):
    chunks = []
    remaining = text
    while len(remaining) > limit:
        split_at = remaining.rfind("\n", 0, limit)
        if split_at <= 0:
            split_at = limit
        chunks.append(remaining[:split_at].strip())
        remaining = remaining[split_at:].strip()
    if remaining:
        chunks.append(remaining)
    return chunks

# 🐎 AT YARIŞI OYUNU
def parse_aviator_cashout_arg(value):
    if value is None:
        return None
    normalized = str(value).lower().strip().replace(",", ".").replace("x", "")
    try:
        multiplier = float(normalized)
    except ValueError:
        return None
    if multiplier < 1.01 or multiplier > AVIATOR_MAX_AUTO_CASHOUT:
        return None
    return round(multiplier, 2)

def format_aviator_multiplier(multiplier):
    return f"x{multiplier:.2f}"

def get_aviator_topic_key(update_or_message):
    message = getattr(update_or_message, "message", None) or getattr(update_or_message, "effective_message", None) or update_or_message
    chat = getattr(message, "chat", None)
    if chat is None:
        return None
    return chat.id, getattr(message, "message_thread_id", None)

def is_aviator_topic(update_or_message):
    return True

def get_aviator_pending_topic_key():
    if not AVIATOR_PENDING_BETS:
        return None
    first_bet = next(iter(AVIATOR_PENDING_BETS.values()))
    return first_bet.get("chat_id", AVIATOR_CHAT_ID), first_bet.get("thread_id", AVIATOR_TOPIC_ID)

def get_aviator_next_start_seconds():
    return AVIATOR_BET_START_DELAY_SECONDS


async def schedule_aviator_start(application, topic_key, delay=AVIATOR_BET_START_DELAY_SECONDS):
    """Schedule a start for the given topic_key (chat_id, thread_id).
    Waits `delay` seconds, performs a 5s countdown messages, then starts the round.
    Multiple calls for the same topic_key will be ignored while a task exists.
    """
    key = tuple(topic_key or (AVIATOR_CHAT_ID, AVIATOR_TOPIC_ID))
    if key in AVIATOR_START_TASKS:
        return

    async def _runner():
        try:
            # Wait until the final countdown window.
            await asyncio.sleep(max(0, delay - AVIATOR_COUNTDOWN_SECONDS))

            # If no pending bets for this topic, abort
            pending_for_topic = [b for b in AVIATOR_PENDING_BETS.values() if (b.get("chat_id"), b.get("thread_id")) == key]
            if not pending_for_topic:
                return

            chat_id, thread_id = key
            # Send the final countdown messages.
            for i in range(AVIATOR_COUNTDOWN_SECONDS, 0, -1):
                try:
                    await asyncio.wait_for(
                        application.bot.send_message(chat_id=chat_id, text=f"✈️ Kalkışa {i} saniye kaldı...", message_thread_id=thread_id),
                        timeout=TELEGRAM_MESSAGE_TIMEOUT_SECONDS
                    )
                except Exception:
                    pass
                await asyncio.sleep(1)

            # Before starting, ensure there are still pending bets and no active round
            if AVIATOR_CURRENT_ROUND is None and any((b for b in AVIATOR_PENDING_BETS.values() if (b.get("chat_id"), b.get("thread_id")) == key)):
                await start_aviator_round(application)
        except asyncio.CancelledError:
            return
        finally:
            AVIATOR_START_TASKS.pop(key, None)

    task = application.create_task(_runner())
    AVIATOR_START_TASKS[key] = task

def get_aviator_pending_total():
    return sum(item["bet"] for item in AVIATOR_PENDING_BETS.values())

def get_aviator_user_label(user):
    if user.username:
        return f"@{user.username}"
    full_name = " ".join(part for part in [user.first_name, user.last_name] if part)
    return full_name or str(user.id)

def parse_aviator_multiplier_value(value, min_value=0.0, max_value=AVIATOR_MAX_MULTIPLIER):
    normalized = str(value).lower().strip().replace(",", ".").replace("x", "")
    try:
        multiplier = float(normalized)
    except (TypeError, ValueError):
        return None
    if multiplier < min_value:
        return None
    if max_value is not None and multiplier > max_value:
        return None
    return round(multiplier, 2)

def split_aviator_multiplier_args(args):
    values = []
    for arg in args:
        normalized = str(arg).replace(";", ",").replace("|", ",")
        for part in normalized.split(","):
            part = part.strip()
            if part:
                values.append(part)
    return values

def format_aviator_sequence(values, limit=12):
    if not values:
        return "bos"
    visible = [format_aviator_multiplier(value) for value in values[:limit]]
    if len(values) > limit:
        visible.append(f"+{len(values) - limit} daha")
    return ", ".join(visible)

def get_aviator_forced_crashes():
    raw = get_setting(AVIATOR_FORCED_CRASHES_SETTING, "") or ""
    values = []
    for item in raw.split(","):
        multiplier = parse_aviator_multiplier_value(item, max_value=None)
        if multiplier is not None:
            values.append(multiplier)
    return values

def set_aviator_forced_crashes(values):
    if not values:
        set_setting(AVIATOR_FORCED_CRASHES_SETTING, None)
        return
    set_setting(AVIATOR_FORCED_CRASHES_SETTING, ",".join(f"{value:.2f}" for value in values))

def pop_aviator_forced_crash():
    values = get_aviator_forced_crashes()
    if not values:
        return None
    value = values.pop(0)
    set_aviator_forced_crashes(values)
    return value

def get_aviator_promo():
    raw = get_setting(AVIATOR_PROMO_SETTING, "") or ""
    if not raw:
        return None
    try:
        min_text, count_text = raw.split(",", 1)
        min_crash = parse_aviator_multiplier_value(min_text, min_value=1.0)
        count = int(count_text)
    except (ValueError, TypeError):
        return None
    if min_crash is None or count <= 0:
        return None
    return min_crash, count

def set_aviator_promo(min_crash=None, count=0):
    if min_crash is None or count <= 0:
        set_setting(AVIATOR_PROMO_SETTING, None)
        return
    set_setting(AVIATOR_PROMO_SETTING, f"{min_crash:.2f},{int(count)}")

def consume_aviator_promo():
    promo = get_aviator_promo()
    if promo is None:
        return None
    min_crash, count = promo
    set_aviator_promo(min_crash, count - 1)
    return min_crash

def choose_aviator_crash_multiplier(auto_cashout=None, bets=None):
    _, low, high = random.choices(
        AVIATOR_CRASH_RANGES,
        weights=[item[0] for item in AVIATOR_CRASH_RANGES],
        k=1
    )[0]
    if low == high:
        return low

    low_cents = int(round(low * 100))
    high_cents = int(round(high * 100))
    return random.randint(low_cents, high_cents) / 100

def choose_aviator_round_crash_multiplier():
    forced_crash = pop_aviator_forced_crash()
    if forced_crash is not None:
        return forced_crash, "avmod", None

    crash_multiplier = choose_aviator_crash_multiplier()
    promo_min = consume_aviator_promo()
    if promo_min is not None:
        return max(crash_multiplier, promo_min), "promo", promo_min

    return crash_multiplier, "normal", None

def get_aviator_multiplier_for_tick(tick):
    if tick <= 4:
        multiplier = (tick / 4) ** 1.15
    else:
        flight_progress = (tick - 4) / max(1, AVIATOR_MAX_TICKS - 4)
        multiplier = 1.0 + (flight_progress ** 2.2) * (AVIATOR_MAX_MULTIPLIER - 1.0)
    return round(multiplier, 2)

def get_aviator_multiplier_for_elapsed(elapsed_seconds):
    tick = max(0, elapsed_seconds / AVIATOR_TICK_SECONDS)
    if tick <= 4:
        multiplier = (tick / 4) ** 1.15
    else:
        flight_progress = (tick - 4) / max(1, AVIATOR_MAX_TICKS - 4)
        multiplier = 1.0 + (flight_progress ** 2.2) * (AVIATOR_MAX_MULTIPLIER - 1.0)
    return round(multiplier, 2)

def get_aviator_seconds_for_multiplier(multiplier):
    multiplier = max(0.0, float(multiplier))
    if multiplier <= 1.0:
        tick = 4 * (multiplier ** (1 / 1.15)) if multiplier > 0 else 0
    else:
        flight_progress = ((multiplier - 1.0) / (AVIATOR_MAX_MULTIPLIER - 1.0)) ** (1 / 2.2)
        tick = 4 + flight_progress * max(1, AVIATOR_MAX_TICKS - 4)
    return tick * AVIATOR_TICK_SECONDS

def get_aviator_visible_multiplier(round_state, elapsed_seconds):
    multiplier = get_aviator_multiplier_for_elapsed(elapsed_seconds)
    crash_multiplier = round_state.get("crash_multiplier", AVIATOR_MAX_MULTIPLIER)
    if crash_multiplier > 1.0:
        multiplier = min(multiplier, max(0.0, crash_multiplier - 0.01))
    else:
        multiplier = min(multiplier, crash_multiplier)
    return round(max(0.0, multiplier), 2)

def render_aviator_track(multiplier, crashed=False):
    width = 18
    progress = max(0, min(width - 1, int((max(multiplier, 0) / 5.0) * (width - 1))))
    marker = "💥" if crashed else "✈️"
    return "━" * progress + marker + "·" * (width - progress - 1)

def build_aviator_keyboard(round_id, multiplier):
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(
            f"💸 CASH OUT {format_aviator_multiplier(multiplier)}",
            callback_data=f"aviator_cashout:{round_id}"
        )
    ]])

def build_aviator_players_text(round_state, limit=8):
    lines = []
    for item in round_state["bets"].values():
        label = escape_markdown(item["label"])
        auto_text = format_aviator_multiplier(item["auto_cashout"]) if item["auto_cashout"] else "manuel"
        if item.get("voided"):
            lines.append(f"VOID {label}: {format_money(item['bet'])} | iade {format_money(item.get('refund_amount', 0))}")
        elif item.get("cashed_out"):
            lines.append(f"✅ {label}: {format_money(item['bet'])} -> {format_aviator_multiplier(item['cashout_multiplier'])}")
        else:
            lines.append(f"• {label}: {format_money(item['bet'])} | {auto_text}")
    if len(lines) > limit:
        visible = lines[:limit]
        visible.append(f"... +{len(lines) - limit} oyuncu")
        return "\n".join(visible)
    return "\n".join(lines) if lines else "Oyuncu yok"

def build_aviator_admin_player_status(item, current_multiplier):
    label = escape_markdown(item.get("label") or item.get("user_id") or "Oyuncu")
    user_id = item.get("user_id", "?")
    bet = item.get("bet", 0)
    paid = item.get("paid", 0) or 0
    auto_cashout = item.get("auto_cashout")
    auto_text = format_aviator_multiplier(auto_cashout) if auto_cashout else "manuel"

    if item.get("voided"):
        status = f"VOID | İade: **{format_money(item.get('refund_amount', 0))}**"
    elif item.get("cashed_out"):
        status = (
            f"ÇEKİLDİ | Oran: **{format_aviator_multiplier(item.get('cashout_multiplier', 0))}** "
            f"| Ödeme: **{format_money(paid)}**"
        )
    elif item.get("resolved"):
        status = "KAYBETTİ | Çekmedi"
    elif item.get("resolving"):
        status = "İŞLENİYOR"
    else:
        potential = int(bet * max(0.0, current_multiplier))
        status = f"OYUNDA | Şu an potansiyel: **{format_money(potential)}**"

    return (
        f"• `{user_id}` {label}\n"
        f"  Bahis: **{format_money(bet)}** | Çıkış: **{auto_text}**\n"
        f"  Durum: {status}"
    )

def build_aviator_pending_admin_text():
    if not AVIATOR_PENDING_BETS:
        return "Bekleyen Aviator bahsi yok."

    lines = []
    for item in AVIATOR_PENDING_BETS.values():
        label = escape_markdown(item.get("label") or item.get("user_id") or "Oyuncu")
        user_id = item.get("user_id", "?")
        auto_cashout = item.get("auto_cashout")
        auto_text = format_aviator_multiplier(auto_cashout) if auto_cashout else "manuel"
        lines.append(
            f"• `{user_id}` {label} | Bahis: **{format_money(item.get('bet', 0))}** | Çıkış: **{auto_text}**"
        )

    return "\n".join(lines)

def build_active_aviator_admin_report():
    round_state = AVIATOR_CURRENT_ROUND
    pending_total = get_aviator_pending_total()

    if round_state is None:
        return (
            f"📡 **AKTİF AVIATOR RAPORU**\n\n"
            f"Aktif uçan tur yok.\n"
            f"Bekleyen oyuncu: **{len(AVIATOR_PENDING_BETS)}**\n"
            f"Bekleyen toplam bahis: **{format_money(pending_total)}** Çip\n\n"
            f"**Bekleyen Bahisler**\n{build_aviator_pending_admin_text()}"
        )

    current_multiplier = get_aviator_cut_multiplier(round_state) if round_state.get("status") == "flying" else round_state.get("current_multiplier", 0.0)
    elapsed_seconds = max(0, int(time.monotonic() - round_state.get("started_at", time.monotonic())))
    mode = round_state.get("mode", "normal")
    promo_text = (
        f" | Promo min: **{format_aviator_multiplier(round_state['promo_min'])}**"
        if round_state.get("mode") == "promo" and round_state.get("promo_min") is not None
        else ""
    )
    players = list(round_state.get("bets", {}).values())
    active_count = sum(1 for item in players if not item.get("resolved"))
    cashed_count = sum(1 for item in players if item.get("cashed_out"))
    lost_count = sum(1 for item in players if item.get("resolved") and not item.get("cashed_out") and not item.get("voided"))
    player_lines = [
        build_aviator_admin_player_status(item, current_multiplier)
        for item in players
    ]

    return (
        f"📡 **AKTİF AVIATOR RAPORU**\n\n"
        f"Tur: `#{round_state['round_id']}`\n"
        f"Durum: **{round_state.get('status', 'bilinmiyor').upper()}**\n"
        f"Mod: **{mode}**{promo_text}\n"
        f"Anlık çarpan: **{format_aviator_multiplier(current_multiplier)}**\n"
        f"Admin crash hedefi: **{format_aviator_multiplier(round_state.get('crash_multiplier', 0.0))}**\n"
        f"Süre: **{elapsed_seconds} sn**\n"
        f"Oyuncu: **{len(players)}** | Oyunda: **{active_count}** | Çekilen: **{cashed_count}** | Kaybeden: **{lost_count}**\n"
        f"Toplam bahis: **{format_money(round_state.get('total_bet', 0))}** Çip\n"
        f"Ödenen: **{format_money(round_state.get('paid_total', 0))}** Çip\n\n"
        f"**Oyuncu Durumları**\n{chr(10).join(player_lines) if player_lines else 'Oyuncu yok.'}"
    )

def build_aviator_round_text(round_state, status_text):
    multiplier = round_state.get("current_multiplier", 1.0)
    crashed = round_state.get("status") == "crashed"
    mode_text = f"Mod: **PROMO min {format_aviator_multiplier(round_state['promo_min'])}**\n" if round_state.get("mode") == "promo" else ""
    return (
        f"✈️ **AVIATOR ORTAK TUR**\n\n"
        f"Tur: `#{round_state['round_id']}`\n"
        f"{mode_text}"
        f"Çarpan: **{format_aviator_multiplier(multiplier)}**\n"
        f"Toplam bahis: **{format_money(round_state['total_bet'])}** Çip\n"
        f"Ödenen: **{format_money(round_state.get('paid_total', 0))}** Çip\n"
        f"`{render_aviator_track(multiplier, crashed)}`\n\n"
        f"{status_text}\n\n"
        f"**Oyuncular**\n{build_aviator_players_text(round_state)}"
    )

def build_aviator_live_text(round_state):
    mode_text = f"PROMO min {format_aviator_multiplier(round_state['promo_min'])}\n" if round_state.get("mode") == "promo" else ""
    return (
        f"✈️ **AVIATOR UÇUYOR**\n\n"
        f"Tur: `#{round_state['round_id']}`\n"
        f"{mode_text}"
        f"Toplam bahis: **{format_money(round_state['total_bet'])}** Çip\n"
        f"Oyuncu: **{len(round_state['bets'])}**\n\n"
        f"Canlı cash out oranı butonda güncellenir."
    )

def build_aviator_queue_text():
    pending_count = len(AVIATOR_PENDING_BETS)
    pending_total = get_aviator_pending_total()
    return (
        f"✈️ **Aviator bahsi sıraya alındı.**\n"
        f"Sonraki kalkış bahisten 20 saniye sonra otomatik olur.\n"
        f"Sıradaki oyuncu: **{pending_count}/{AVIATOR_MAX_PLAYERS_PER_ROUND}**\n"
        f"Sıradaki toplam bahis: **{format_money(pending_total)}** Çip"
    )

def log_aviator_round_start(round_state):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT OR REPLACE INTO aviator_rounds
        (round_id, crash_multiplier, status, mode, total_bet, paid_total, started_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            round_state["round_id"],
            round_state["crash_multiplier"],
            "flying",
            round_state.get("mode", "normal"),
            round_state["total_bet"],
            0,
            int(time.time())
        )
    )
    for user_id, item in round_state["bets"].items():
        cursor.execute(
            """
            INSERT OR REPLACE INTO aviator_round_bets
            (round_id, user_id, label, bet, paid, cashout_multiplier, resolved)
            VALUES (?, ?, ?, ?, 0, NULL, 0)
            """,
            (round_state["round_id"], user_id, item.get("label"), item["bet"])
        )
    conn.commit()
    conn.close()

def record_aviator_bet_result(round_state, user_id):
    item = round_state["bets"].get(user_id)
    if item is None:
        return
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute(
        """
        UPDATE aviator_round_bets
        SET paid = ?, cashout_multiplier = ?, resolved = 1
        WHERE round_id = ? AND user_id = ?
        """,
        (
            item.get("paid", 0),
            item.get("cashout_multiplier"),
            round_state["round_id"],
            user_id
        )
    )
    conn.commit()
    conn.close()

def record_aviator_round_finish(round_state):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute(
        """
        UPDATE aviator_rounds
        SET status = ?, crash_multiplier = ?, paid_total = ?, ended_at = ?
        WHERE round_id = ?
        """,
        (
            round_state.get("status", "crashed"),
            round_state.get("crash_multiplier", 0),
            round_state.get("paid_total", 0),
            int(time.time()),
            round_state["round_id"]
        )
    )
    conn.commit()
    conn.close()

def reverse_aviator_stat(cursor, user_id, bet, paid):
    win_int = 1 if paid > bet else 0
    cursor.execute(
        """
        UPDATE game_stats
        SET total_games = MAX(0, total_games - 1),
            winning_games = MAX(0, winning_games - ?),
            total_wagered = MAX(0, total_wagered - ?),
            total_paid = MAX(0, total_paid - ?)
        WHERE game_type = 'aviator'
        """,
        (win_int, bet, paid)
    )
    cursor.execute(
        """
        UPDATE user_game_stats
        SET total_games = MAX(0, total_games - 1),
            winning_games = MAX(0, winning_games - ?),
            total_wagered = MAX(0, total_wagered - ?),
            total_paid = MAX(0, total_paid - ?)
        WHERE user_id = ? AND game_type = 'aviator'
        """,
        (win_int, bet, paid, user_id)
    )

def void_aviator_round(round_id, admin_id):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT status FROM aviator_rounds WHERE round_id = ?",
        (round_id,)
    )
    round_row = cursor.fetchone()
    if round_row is None or round_row[0] == "voided":
        conn.close()
        return None

    cursor.execute(
        "SELECT user_id, bet, paid, resolved, refunded FROM aviator_round_bets WHERE round_id = ?",
        (round_id,)
    )
    rows = cursor.fetchall()
    refunded_total = 0
    for user_id, bet, paid, resolved, refunded in rows:
        paid = paid or 0
        if resolved:
            reverse_aviator_stat(cursor, user_id, bet, paid)
        refund_amount = 0 if refunded else max(0, bet - paid)
        if refund_amount > 0:
            cursor.execute("INSERT OR IGNORE INTO users (user_id, balance) VALUES (?, 0)", (user_id,))
            cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (refund_amount, user_id))
            refunded_total += refund_amount
        cursor.execute(
            """
            UPDATE aviator_round_bets
            SET refunded = 1, refund_amount = refund_amount + ?
            WHERE round_id = ? AND user_id = ?
            """,
            (refund_amount, round_id, user_id)
        )

    cursor.execute(
        """
        UPDATE aviator_rounds
        SET status = 'voided', voided_at = ?, voided_by = ?, refunded_total = refunded_total + ?
        WHERE round_id = ?
        """,
        (int(time.time()), admin_id, refunded_total, round_id)
    )
    conn.commit()
    conn.close()
    return {"players": len(rows), "refunded_total": refunded_total}

async def pay_aviator_bet(round_state, user_id, multiplier, auto=False):
    item = round_state["bets"].get(user_id)
    if item is None or item.get("resolved"):
        return 0

    raw_paid = int(item["bet"] * multiplier)
    paid = raw_paid

    item["resolved"] = True
    item["resolving"] = False
    item["cashed_out"] = True
    item["cashout_multiplier"] = multiplier
    item["paid"] = paid
    round_state["paid_total"] = round_state.get("paid_total", 0) + paid

    is_win = paid > item["bet"]
    update_game_stats('aviator', item["bet"], paid, is_win, user_id)
    if paid > 0:
        update_balance(user_id, paid)
    record_aviator_bet_result(round_state, user_id)
    return paid

def lose_aviator_bet(round_state, user_id):
    item = round_state["bets"].get(user_id)
    if item is None or item.get("resolved") or item.get("resolving"):
        return
    item["resolved"] = True
    item["paid"] = 0
    update_game_stats('aviator', item["bet"], 0, False, user_id)
    record_aviator_bet_result(round_state, user_id)

async def start_aviator_round(application):
    global AVIATOR_CURRENT_ROUND
    if AVIATOR_CURRENT_ROUND is not None or not AVIATOR_PENDING_BETS:
        return

    target_chat_id, target_thread_id = get_aviator_pending_topic_key() or (AVIATOR_CHAT_ID, AVIATOR_TOPIC_ID)
    # Cancel any pending start task for this topic
    topic_key = (target_chat_id, target_thread_id)
    task = AVIATOR_START_TASKS.pop(topic_key, None)
    current_task = asyncio.current_task()
    if task is not None and task is not current_task and not task.done():
        try:
            task.cancel()
        except Exception:
            pass

    bets = dict(AVIATOR_PENDING_BETS)
    AVIATOR_PENDING_BETS.clear()
    crash_multiplier, aviator_mode, promo_min = choose_aviator_round_crash_multiplier()
    started_at = time.monotonic()
    crash_after_seconds = get_aviator_seconds_for_multiplier(crash_multiplier)
    close_after_seconds = crash_after_seconds + AVIATOR_CRASH_SYNC_DELAY_SECONDS
    round_state = {
        "round_id": random.randint(100000, 999999),
        "chat_id": target_chat_id,
        "thread_id": target_thread_id,
        "bets": bets,
        "total_bet": sum(item["bet"] for item in bets.values()),
        "paid_total": 0,
        "current_multiplier": 0.0,
        "last_live_multiplier": 0.0,
        "crash_multiplier": crash_multiplier,
        "started_at": started_at,
        "crash_after_seconds": crash_after_seconds,
        "actual_crash_at": started_at + crash_after_seconds,
        "close_after_seconds": close_after_seconds,
        "crash_at": started_at + close_after_seconds,
        "status": "flying",
        "mode": aviator_mode,
        "promo_min": promo_min,
        "message": None,
    }
    AVIATOR_CURRENT_ROUND = round_state

    message = await asyncio.wait_for(
        application.bot.send_message(
            chat_id=target_chat_id,
            message_thread_id=target_thread_id,
            text=build_aviator_live_text(round_state),
            parse_mode="Markdown",
            reply_markup=build_aviator_keyboard(round_state["round_id"], 0.0)
        ),
        timeout=TELEGRAM_MESSAGE_TIMEOUT_SECONDS
    )
    round_state["message"] = message
    log_aviator_round_start(round_state)
    application.create_task(update_aviator_live_display(round_state))
    application.create_task(run_aviator_round(round_state, application))

async def update_aviator_live_display(round_state):
    while round_state.get("status") == "flying":
        await asyncio.sleep(AVIATOR_DISPLAY_UPDATE_SECONDS)
        if round_state.get("status") != "flying" or round_state.get("finalizing"):
            return

        now = time.monotonic()
        if now >= round_state.get("crash_at", now):
            return

        elapsed = now - round_state.get("started_at", now)
        multiplier = get_aviator_visible_multiplier(round_state, elapsed)
        round_state["current_multiplier"] = multiplier

        if multiplier == round_state.get("last_live_multiplier"):
            continue

        if round_state.get("live_editing"):
            continue

        round_state["live_editing"] = True
        try:
            if round_state.get("status") != "flying" or round_state.get("finalizing"):
                return
            await asyncio.wait_for(
                round_state["message"].edit_reply_markup(
                    reply_markup=build_aviator_keyboard(round_state["round_id"], multiplier)
                ),
                timeout=0.9
            )
            round_state["last_live_multiplier"] = multiplier
        except Exception:
            pass
        finally:
            round_state["live_editing"] = False

def get_aviator_cut_multiplier(round_state):
    now = time.monotonic()
    elapsed = max(0.0, now - round_state.get("started_at", now))
    visible_multiplier = get_aviator_visible_multiplier(round_state, elapsed)
    live_multiplier = max(
        round_state.get("last_live_multiplier", 0.0) or 0.0,
        round_state.get("current_multiplier", 0.0) or 0.0,
    )
    return round(max(0.0, visible_multiplier, live_multiplier), 2)

async def finish_aviator_round(round_state, application, crash_multiplier=None, cut_by_admin=False):
    if round_state.get("status") != "flying" or round_state.get("finalizing"):
        return False

    if crash_multiplier is None:
        crash_multiplier = round_state.get("crash_multiplier", 0.0)
    crash_multiplier = parse_aviator_multiplier_value(crash_multiplier, max_value=None)
    if crash_multiplier is None:
        crash_multiplier = 0.0

    round_state["finalizing"] = True
    round_state["status"] = "crashed"
    round_state["crash_multiplier"] = crash_multiplier
    round_state["current_multiplier"] = crash_multiplier

    for user_id, item in list(round_state["bets"].items()):
        auto_cashout = item.get("auto_cashout")
        if (
            auto_cashout is not None
            and auto_cashout >= 1.0
            and auto_cashout < crash_multiplier
            and not item.get("resolved")
            and not item.get("resolving")
        ):
            await pay_aviator_bet(round_state, user_id, auto_cashout, auto=True)
        else:
            lose_aviator_bet(round_state, user_id)

    status_text = (
        f"💥 **BUST!** Uçak **{format_aviator_multiplier(crash_multiplier)}** seviyesinde düştü."
        if crash_multiplier <= 1.0
        else f"💥 **PATLADI!** Uçak **{format_aviator_multiplier(crash_multiplier)}** seviyesinde düştü."
    )

    record_aviator_round_finish(round_state)
    final_text = build_aviator_round_text(round_state, status_text)
    try:
        await asyncio.wait_for(
            round_state["message"].edit_text(final_text, parse_mode="Markdown", reply_markup=None),
            timeout=TELEGRAM_MESSAGE_TIMEOUT_SECONDS
        )
    except Exception:
        try:
            await asyncio.wait_for(
                round_state["message"].edit_reply_markup(reply_markup=None),
                timeout=1.0
            )
        except Exception:
            pass
        try:
            await asyncio.wait_for(
                application.bot.send_message(
                    chat_id=round_state.get("chat_id", AVIATOR_CHAT_ID),
                    text=final_text,
                    parse_mode="Markdown",
                    message_thread_id=round_state.get("thread_id", AVIATOR_TOPIC_ID)
                ),
                timeout=TELEGRAM_MESSAGE_TIMEOUT_SECONDS
            )
        except Exception:
            pass
    return True

async def run_aviator_round(round_state, application):
    global AVIATOR_CURRENT_ROUND
    try:
        await asyncio.sleep(round_state.get("close_after_seconds", round_state.get("crash_after_seconds", 0)))
        if round_state.get("status") != "flying":
            return

        await finish_aviator_round(round_state, application)
    finally:
        if AVIATOR_CURRENT_ROUND is round_state:
            AVIATOR_CURRENT_ROUND = None

async def run_aviator_scheduler(application):
    global AVIATOR_LAST_STARTED_MINUTE
    last_minute = time.localtime().tm_min
    while True:
        await asyncio.sleep(0.5)
        now = time.localtime()
        if now.tm_min == last_minute:
            continue

        last_minute = now.tm_min
        minute_key = (now.tm_year, now.tm_yday, now.tm_hour, now.tm_min)
        if AVIATOR_LAST_STARTED_MINUTE == minute_key:
            continue

        AVIATOR_LAST_STARTED_MINUTE = minute_key
        if AVIATOR_CURRENT_ROUND is None and AVIATOR_PENDING_BETS:
            topic_key = get_aviator_pending_topic_key()
            if topic_key is not None and tuple(topic_key) not in AVIATOR_START_TASKS:
                try:
                    application.create_task(schedule_aviator_start(application, topic_key))
                except Exception:
                    pass

async def play_aviator(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    remember_user(update.effective_user)
    thread_id = update.message.message_thread_id if update.message else None

    topic_key = get_aviator_topic_key(update)
    args = context.args or (update.message.text.split()[1:] if update.message and update.message.text else [])
    if not args:
        await update.message.reply_text(
            f"❌ **Kullanım:** `/aviator [Miktar] [Oto Çıkış]`\n"
            f"Örnek: `/aviator 10t` veya `/aviator 10t 2x`\n"
            f"Tur bahisten 20 saniye sonra otomatik kalkar.\n"
            f"Min {format_money(MIN_BET_AVIATOR)} | Max {format_money(MAX_BET_AVIATOR)} | Oto: x1.01 - x{AVIATOR_MAX_AUTO_CASHOUT:g}",
            parse_mode="Markdown",
            message_thread_id=thread_id
        )
        return

    bet = parse_money(args[0])
    auto_cashout = parse_aviator_cashout_arg(args[1]) if len(args) >= 2 else None

    if bet is None or bet < MIN_BET_AVIATOR or bet > MAX_BET_AVIATOR:
        await update.message.reply_text(
            f"❌ Geçersiz bahis! Aviator için **{format_money(MIN_BET_AVIATOR)}** ile **{format_money(MAX_BET_AVIATOR)}** arası oynayabilirsin.",
            parse_mode="Markdown",
            message_thread_id=thread_id
        )
        return

    if len(args) >= 2 and auto_cashout is None:
        await update.message.reply_text(
            f"❌ Oto çıkış çarpanı **x1.01** ile **x{AVIATOR_MAX_AUTO_CASHOUT:g}** arasında olmalı. Örnek: `/aviator 10t 2x`",
            parse_mode="Markdown",
            message_thread_id=thread_id
        )
        return

    if user_id in AVIATOR_PENDING_BETS:
        await update.message.reply_text(
            "⏳ Sıradaki Aviator turunda zaten bahsin var. Tur başlayınca yeni bahis alabilirsin.",
            message_thread_id=thread_id
        )
        return

    pending_topic_key = get_aviator_pending_topic_key()
    if pending_topic_key is not None and pending_topic_key != topic_key:
        await update.message.reply_text(
            "⏳ Şu an diğer Aviator konusunda bekleyen tur var. O tur başlayınca bu konuda yeni sıra açılır.",
            message_thread_id=thread_id
        )
        return

    if len(AVIATOR_PENDING_BETS) >= AVIATOR_MAX_PLAYERS_PER_ROUND:
        await update.message.reply_text("❌ Bu Aviator turu oyuncu limitine ulaştı.", message_thread_id=thread_id)
        return

    if get_balance(user_id) < bet:
        await update.message.reply_text("❌ Bakiyen yetersiz!", message_thread_id=thread_id)
        return
    was_empty = len(AVIATOR_PENDING_BETS) == 0

    update_balance(user_id, -bet)
    AVIATOR_PENDING_BETS[user_id] = {
        "user_id": user_id,
        "label": get_aviator_user_label(update.effective_user),
        "chat_id": topic_key[0],
        "thread_id": topic_key[1],
        "bet": bet,
        "auto_cashout": auto_cashout,
        "resolved": False,
        "cashed_out": False,
        "paid": 0,
    }

    await update.message.reply_text(
        build_aviator_queue_text(),
        parse_mode="Markdown",
        message_thread_id=thread_id
    )

    # If this was the first pending bet for this topic, schedule a start after the bet delay.
    if was_empty:
        try:
            context.application.create_task(schedule_aviator_start(context.application, topic_key))
        except Exception:
            pass

async def force_start_aviator_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return

    thread_id = update.message.message_thread_id if update.message else None
    if AVIATOR_CURRENT_ROUND is not None:
        await update.message.reply_text(
            "⏳ Aktif Aviator turu bitmeden yeni tur başlatılmaz.",
            message_thread_id=thread_id
        )
        return

    if not AVIATOR_PENDING_BETS:
        await update.message.reply_text(
            "❌ Sırada Aviator bahsi yok. Önce `/aviator 10t` ile bahis alın.",
            parse_mode="Markdown",
            message_thread_id=thread_id
        )
        return

    await update.message.reply_text("✈️ Test kalkışı başlatılıyor.", message_thread_id=thread_id)
    await start_aviator_round(context.application)

async def cut_aviator_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global AVIATOR_CURRENT_ROUND
    if update.effective_user.id not in ADMIN_IDS:
        return

    admin_id = update.effective_user.id
    chat_type = getattr(update.effective_chat, "type", None)
    is_private_chat = chat_type == "private"

    async def notify_admin(text, parse_mode=None):
        sent_message = await send_admin_private_notice(context, admin_id, text, parse_mode=parse_mode)
        if sent_message is None and is_private_chat and update.message:
            await update.message.reply_text(text, parse_mode=parse_mode)

    round_state = AVIATOR_CURRENT_ROUND
    if round_state is None or round_state.get("status") != "flying":
        await notify_admin("Aktif Aviator turu yok.")
        return

    if round_state.get("finalizing"):
        await notify_admin("Tur zaten sonuçlanıyor.")
        return

    cut_multiplier = get_aviator_cut_multiplier(round_state)
    finished = await finish_aviator_round(
        round_state,
        context.application,
        crash_multiplier=cut_multiplier,
        cut_by_admin=True
    )
    if not finished:
        await notify_admin("Tur kesilemedi; muhtemelen zaten kapandı.")
        return

    if AVIATOR_CURRENT_ROUND is round_state:
        AVIATOR_CURRENT_ROUND = None

    await notify_admin(
        f"Kes uygulandı.\nTur: `#{round_state['round_id']}`\nÇarpan: **{format_aviator_multiplier(cut_multiplier)}**\nOyuncu ekranında normal patlama olarak görünür.",
        parse_mode="Markdown"
    )

async def active_aviator_report_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return

    report_text = build_active_aviator_admin_report()
    chat_type = getattr(update.effective_chat, "type", None)
    thread_id = update.message.message_thread_id if update.message else None
    chunks = split_telegram_text(report_text)

    if chat_type == "private":
        sent_count = 0
        for chunk in chunks:
            sent_count = max(
                sent_count,
                await send_all_admin_private_notices(context, chunk, parse_mode="Markdown")
            )

        if sent_count == 0 and update.message:
            await update.message.reply_text(
                "Rapor admin özel mesajlarına gönderilemedi.",
                message_thread_id=thread_id
            )
        return

    for chunk in chunks:
        await update.message.reply_text(
            chunk,
            parse_mode="Markdown",
            message_thread_id=thread_id
        )

async def aviator_mod_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return

    thread_id = update.message.message_thread_id if update.message else None
    args = context.args or []
    action = args[0].lower().strip() if args else "durum"

    if action in {"durum", "status"}:
        values = get_aviator_forced_crashes()
        if not values:
            await update.message.reply_text("AVMOD kapali. Aviator normal sansla calisiyor.", message_thread_id=thread_id)
            return
        await update.message.reply_text(
            f"AVMOD aktif.\nKalan tur: {len(values)}\nSiradaki crashler: {format_aviator_sequence(values)}",
            message_thread_id=thread_id
        )
        return

    if action in {"kapat", "off", "sil", "temizle", "normal", "stop", "dur"}:
        set_aviator_forced_crashes([])
        await update.message.reply_text("AVMOD kapatildi. Aviator normal sansa dondu.", message_thread_id=thread_id)
        return

    try:
        round_count = int(args[0])
    except (IndexError, ValueError):
        await update.message.reply_text(
            "Kullanim: `/avmod [TurSayisi] [Crashler]`\nOrnek: `/avmod 5 0 1.12 1.80 4x 25x`\nKapat: `/avmod kapat`",
            parse_mode="Markdown",
            message_thread_id=thread_id
        )
        return

    if round_count <= 0 or round_count > 200:
        await update.message.reply_text("Tur sayisi 1 ile 200 arasinda olmali.", message_thread_id=thread_id)
        return

    crash_args = split_aviator_multiplier_args(args[1:])
    if len(crash_args) < round_count:
        await update.message.reply_text(
            f"{round_count} tur icin {round_count} crash degeri lazim. Girilen: {len(crash_args)}",
            message_thread_id=thread_id
        )
        return

    values = []
    for raw_value in crash_args[:round_count]:
        multiplier = parse_aviator_multiplier_value(raw_value, max_value=None)
        if multiplier is None:
            await update.message.reply_text(
                f"Gecersiz crash: `{raw_value}`\nDeger x0 veya daha buyuk bir sayi olmali.",
                parse_mode="Markdown",
                message_thread_id=thread_id
            )
            return
        values.append(multiplier)

    set_aviator_forced_crashes(values)
    await update.message.reply_text(
        f"AVMOD aktif edildi.\nKalan tur: {len(values)}\nCrash sirasi: {format_aviator_sequence(values)}",
        message_thread_id=thread_id
    )

async def aviator_promo_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return

    thread_id = update.message.message_thread_id if update.message else None
    args = context.args or []
    action = args[0].lower().strip() if args else "durum"

    if action in {"durum", "status"}:
        promo = get_aviator_promo()
        if promo is None:
            await update.message.reply_text("Aviator promo kapali.", message_thread_id=thread_id)
            return
        min_crash, count = promo
        await update.message.reply_text(
            f"Aviator promo aktif.\nKalan tur: {count}\nMinimum crash: {format_aviator_multiplier(min_crash)}",
            message_thread_id=thread_id
        )
        return

    if action in {"kapat", "off", "sil", "temizle", "normal", "stop", "dur"}:
        set_aviator_promo()
        await update.message.reply_text("Aviator promo kapatildi.", message_thread_id=thread_id)
        return

    min_crash = parse_aviator_multiplier_value(args[0], min_value=1.0)
    if min_crash is None:
        await update.message.reply_text(
            f"Kullanim: `/avpromo [MinCrash] [TurSayisi]`\nOrnek: `/avpromo 2x 10`\nMin crash x1 ile x{AVIATOR_MAX_MULTIPLIER:g} arasinda olmali.",
            parse_mode="Markdown",
            message_thread_id=thread_id
        )
        return

    try:
        round_count = int(args[1]) if len(args) >= 2 else 1
    except ValueError:
        round_count = 0

    if round_count <= 0 or round_count > 200:
        await update.message.reply_text("Promo tur sayisi 1 ile 200 arasinda olmali.", message_thread_id=thread_id)
        return

    set_aviator_promo(min_crash, round_count)
    await update.message.reply_text(
        f"Aviator promo aktif edildi.\nKalan tur: {round_count}\nMinimum crash: {format_aviator_multiplier(min_crash)}",
        message_thread_id=thread_id
    )

async def aviator_void_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global AVIATOR_CURRENT_ROUND
    if update.effective_user.id not in ADMIN_IDS:
        return

    thread_id = update.message.message_thread_id if update.message else None
    target_round_id = None

    if context.args:
        try:
            target_round_id = int(str(context.args[0]).lstrip("#"))
        except ValueError:
            target_round_id = None
    elif AVIATOR_CURRENT_ROUND is not None:
        target_round_id = AVIATOR_CURRENT_ROUND.get("round_id")

    if target_round_id is None:
        await update.message.reply_text(
            "Kullanim: `/avvoid [TurNo]`\nAktif tur varsa tur no yazmadan da iptal eder.",
            parse_mode="Markdown",
            message_thread_id=thread_id
        )
        return

    current_round = AVIATOR_CURRENT_ROUND
    is_current_round = current_round is not None and current_round.get("round_id") == target_round_id
    result = void_aviator_round(target_round_id, update.effective_user.id)
    if result is None:
        await update.message.reply_text("Tur bulunamadi veya zaten void edilmis.", message_thread_id=thread_id)
        return

    if is_current_round:
        current_round["status"] = "voided"
        current_round["finalizing"] = True
        current_round["current_multiplier"] = current_round.get("current_multiplier", 0.0)
        for item in current_round["bets"].values():
            paid = item.get("paid", 0) or 0
            refund_amount = max(0, item["bet"] - paid)
            item["resolved"] = True
            item["resolving"] = False
            item["voided"] = True
            item["refund_amount"] = refund_amount

        status_text = (
            f"VOID: Tur admin tarafindan iptal edildi.\n"
            f"Iade: **{format_money(result['refunded_total'])}** Chip | Oyuncu: **{result['players']}**"
        )
        final_text = build_aviator_round_text(current_round, status_text)
        try:
            await asyncio.wait_for(
                current_round["message"].edit_text(final_text, parse_mode="Markdown", reply_markup=None),
                timeout=TELEGRAM_MESSAGE_TIMEOUT_SECONDS
            )
        except Exception:
            try:
                await asyncio.wait_for(current_round["message"].edit_reply_markup(reply_markup=None), timeout=1.0)
            except Exception:
                pass
            try:
                await asyncio.wait_for(
                    context.bot.send_message(
                        chat_id=current_round.get("chat_id", AVIATOR_CHAT_ID),
                        text=final_text,
                        parse_mode="Markdown",
                        message_thread_id=current_round.get("thread_id", AVIATOR_TOPIC_ID)
                    ),
                    timeout=TELEGRAM_MESSAGE_TIMEOUT_SECONDS
                )
            except Exception:
                pass
        AVIATOR_CURRENT_ROUND = None

    await update.message.reply_text(
        f"VOID tamamlandi.\nTur: #{target_round_id}\nIade: {format_money(result['refunded_total'])} Chip | Oyuncu: {result['players']}",
        message_thread_id=thread_id
    )

async def finalize_aviator_cashout(round_state, user_id, multiplier):
    try:
        return await pay_aviator_bet(round_state, user_id, multiplier)
    except Exception:
        item = round_state["bets"].get(user_id)
        if item is not None:
            item["resolving"] = False
        return None

async def aviator_cashout_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    message = query.message

    try:
        _, round_id_text = query.data.split(":", 1)
        round_id = int(round_id_text)
    except (ValueError, AttributeError):
        await safe_query_answer(query)
        return

    round_state = AVIATOR_CURRENT_ROUND
    if (
        round_state is None
        or round_state.get("status") != "flying"
        or round_state.get("finalizing")
        or round_state.get("round_id") != round_id
    ):
        await safe_query_answer(query, "Bu tur kapandı. Sonuç mesajını kontrol et.", show_alert=True)
        return

    user_id = query.from_user.id
    item = round_state["bets"].get(user_id)
    if item is None:
        await safe_query_answer(query, "Bu turda bahsin yok.", show_alert=True)
        return
    if item.get("resolved") or item.get("resolving"):
        await safe_query_answer(query, "Bu bahis zaten kapandı.", show_alert=True)
        return

    now = time.monotonic()
    if now >= round_state.get("crash_at", now):
        await safe_query_answer(query, "Uçak düştü, cash out kaçtı.", show_alert=True)
        return

    multiplier = round_state.get("last_live_multiplier", round_state.get("current_multiplier", 0.0))
    if multiplier >= round_state.get("crash_multiplier", 0.0):
        await safe_query_answer(query, "Uçak düştü, cash out kaçtı.", show_alert=True)
        return

    if multiplier < 1.0:
        await safe_query_answer(query, "Çarpan x1.00 olmadan cash out açılmaz.", show_alert=True)
        return

    item["resolving"] = True
    paid = await finalize_aviator_cashout(round_state, user_id, multiplier)
    if paid is None:
        await safe_query_answer(query, "Cash out işlenemedi, tekrar dene.", show_alert=True)
        return

    await safe_query_answer(
        query,
        f"{format_aviator_multiplier(multiplier)} cash out: {format_money(paid)}",
        show_alert=False
    )

async def play_horse_race(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    remember_user(update.effective_user)
    if not await check_game_cooldown(update):
        return
    thread_id = update.message.message_thread_id if update.message else None

    if len(context.args) < 2:
        await update.message.reply_text(
            f"❌ **Kullanım:** `/atyarisi [Miktar] [At No]`\n"
            f"📌 Örnek: `/atyarisi 10t 3`\n"
            f"Min: {format_money(MIN_BET_HORSE)} | Max: {format_money(MAX_BET_HORSE)} | At: 1-8",
            parse_mode="Markdown",
            message_thread_id=thread_id
        )
        return

    bet = parse_money(context.args[0])
    try:
        selected_horse = int(context.args[1])
    except ValueError:
        selected_horse = None

    if bet is None or bet < MIN_BET_HORSE or bet > MAX_BET_HORSE:
        await update.message.reply_text(
            f"❌ **Geçersiz bahis!**\nAt yarışı için **{format_money(MIN_BET_HORSE)}** ile **{format_money(MAX_BET_HORSE)}** arası oynayabilirsin.",
            parse_mode="Markdown",
            message_thread_id=thread_id
        )
        return

    if selected_horse is None or selected_horse not in HORSE_CONFIG:
        await update.message.reply_text("❌ Geçersiz at numarası! 1 ile 8 arasında bir at seç.", message_thread_id=thread_id)
        return

    current_balance = get_balance(user_id)
    if current_balance < bet:
        await update.message.reply_text("❌ **Bakiyen yetersiz!**", parse_mode="Markdown", message_thread_id=thread_id)
        return

    bet_charged = False
    try:
        update_balance(user_id, -bet)
        bet_charged = True

        horse_names = {horse: config["name"] for horse, config in HORSE_CONFIG.items()}
        await safe_reply_text(
            update,
            f"🐎 **At yarışı başladı!**\n"
            f"Senin atın: **#{selected_horse} {horse_names[selected_horse]}**\n"
            f"Sonuç hazırlanıyor...",
            parse_mode="Markdown",
            message_thread_id=thread_id
        )

        await asyncio.sleep(1.2)
        winner = choose_horse_winner(selected_horse, bet)

        is_win = winner == selected_horse
        multiplier = HORSE_CONFIG[selected_horse]["multiplier"]
        win_amount = int(bet * multiplier) if is_win else 0

        if is_win:
            result_text = f"🎉 **TEBRİKLER!** #{winner} {horse_names[winner]} kazandı. Bahsinin **x{multiplier:g}** katını aldın! (+{format_money(win_amount)})"
        else:
            result_text = f"😔 **Kaybettin.** Kazanan at: #{winner} {horse_names[winner]} (-{format_money(bet)})"

            loss_message = HORSE_CONFIG[selected_horse].get("loss_message")
            if loss_message:
                result_text += f"\n{loss_message}"

        projected_balance = get_balance(user_id) + win_amount
        final_message = f"{result_text}\n\n💳 **Güncel Bakiyen:** {format_money(projected_balance)} Çip"
        sent_msg = await safe_reply_text(
            update,
            final_message,
            parse_mode="Markdown",
            message_thread_id=thread_id
        )
        if sent_msg is None:
            sent_msg = await safe_send_message(
                context,
                update.effective_chat.id,
                final_message,
                parse_mode="Markdown",
                message_thread_id=thread_id
            )
        if sent_msg is None:
            new_balance = update_balance(user_id, bet)
            bet_charged = False
            await safe_send_message(
                context,
                update.effective_chat.id,
                f"⚠️ At yarışı sonucu gönderilemediği için bahis iade edildi.\n💳 Güncel Bakiyen: {format_money(new_balance)} Çip",
                message_thread_id=thread_id
            )
            return

        update_game_stats('atyarisi', bet, win_amount, is_win, user_id)
        update_balance(user_id, win_amount)
        bet_charged = False
    except Exception:
        if bet_charged:
            new_balance = update_balance(user_id, bet)
            await safe_reply_text(
                update,
                f"⚠️ At yarışı sırasında bağlantı takıldı. Bahsin iade edildi.\n💳 Güncel Bakiyen: {format_money(new_balance)} Çip",
                message_thread_id=thread_id
            )

def build_progress_bar(current, total, width=20):
    filled = int((current / total) * width) if total else width
    return "█" * filled + "░" * (width - filled)

def get_user_label(user):
    if user is None:
        return "Oyuncu"
    if user.username:
        return f"@{user.username}"
    full_name = " ".join(part for part in [user.first_name, user.last_name] if part)
    return full_name or f"ID:{user.id}"

def pvp_html_mention(user_id, label):
    display = str(label or user_id)
    if display.startswith("@"):
        display = display[1:]
    return f'<a href="tg://user?id={user_id}">{html.escape(display)}</a>'

def cancel_pvp_turn_timers(room):
    try:
        current_task = asyncio.current_task()
    except RuntimeError:
        current_task = None
    for key in ("warning_task", "timeout_task"):
        task = room.pop(key, None)
        if task and not task.done() and task is not current_task:
            task.cancel()

def get_pvp_active_player(room):
    if room.get("game") == "yirmibir":
        side = room.get("active_side")
        user_id = room.get("creator_id") if side == "creator" else room.get("opponent_id")
        label = room.get("creator_label") if side == "creator" else room.get("opponent_label")
        hint = "Kart çek veya dur."
        return user_id, label, hint
    if room.get("game") == "xox":
        symbol = room.get("xox_turn")
        user_id = room.get("xox_players", {}).get(symbol)
        label = xox_player_label(room, symbol) if user_id else symbol
        hint = "XOX tahtasından bir kutu seç."
        return user_id, label, hint
    return None, None, None

async def pvp_turn_warning(context, room, turn_token):
    await asyncio.sleep(max(0, PVP_TURN_SECONDS - PVP_TURN_WARNING_SECONDS))
    if PVP_ROOMS.get(room.get("code")) is not room or room.get("turn_token") != turn_token:
        return
    user_id, label, hint = get_pvp_active_player(room)
    if not user_id:
        return
    mention = pvp_html_mention(user_id, label)
    await safe_send_message(
        context,
        room["chat_id"],
        f"⏳ {mention} sıra sende. {PVP_TURN_WARNING_SECONDS} saniyen kaldı. {html.escape(hint)}",
        parse_mode="HTML",
        message_thread_id=room.get("thread_id"),
    )

async def pvp_turn_timeout(context, room, turn_token):
    await asyncio.sleep(PVP_TURN_SECONDS)
    if PVP_ROOMS.get(room.get("code")) is not room or room.get("turn_token") != turn_token:
        return
    if room.get("game") == "yirmibir":
        loser_side = room.get("active_side")
        winner_side = "opponent" if loser_side == "creator" else "creator"
        loser_label = room.get("creator_label") if loser_side == "creator" else room.get("opponent_label")
        reason = f"⏰ {escape_markdown(loser_label)} 20 saniye içinde hamle yapmadı ve hükmen kaybetti."
        await finish_pvp_21_room(context, room, forced_winner_side=winner_side, reason_text=reason)
    elif room.get("game") == "xox":
        loser_symbol = room.get("xox_turn")
        winner_symbol = "O" if loser_symbol == "X" else "X"
        loser_label = xox_player_label(room, loser_symbol)
        reason = f"⏰ {escape_markdown(loser_label)} 20 saniye içinde hamle yapmadı ve hükmen kaybetti."
        await finish_pvp_xox_room(context, room, winner_symbol, reason_text=reason)

def start_pvp_turn_timer(context, room):
    cancel_pvp_turn_timers(room)
    room["turn_token"] = room.get("turn_token", 0) + 1
    token = room["turn_token"]
    room["warning_task"] = context.application.create_task(pvp_turn_warning(context, room, token))
    room["timeout_task"] = context.application.create_task(pvp_turn_timeout(context, room, token))

def cleanup_pvp_rooms(max_age_seconds=900):
    now = time.time()
    expired_codes = []
    for code, room in PVP_ROOMS.items():
        age = now - room.get("created_at", now)
        if room.get("status") == "waiting" and age > max_age_seconds:
            expired_codes.append(code)
        elif room.get("status") == "playing" and age > 3600:
            expired_codes.append(code)
    for code in expired_codes:
        room = PVP_ROOMS.pop(code, None)
        if room:
            cancel_pvp_turn_timers(room)

def make_pvp_code():
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    while True:
        code = "".join(random.choice(alphabet) for _ in range(5))
        if code not in PVP_ROOMS:
            return code

def build_pvp_keyboard(code):
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("Katıl", callback_data=f"pvp_join:{code}")
    ]])

def pvp_room_text(room):
    game = PVP_GAME_CONFIG[room["game"]]
    return (
        f"⚔️ **1v1 {game['title']} odası açıldı!**\n\n"
        f"Oda Kodu: `{room['code']}`\n"
        f"Kurucu: **{escape_markdown(room['creator_label'])}**\n"
        f"Bahis: **{format_money(room['bet'])}** Çip\n\n"
        f"**1v1 Kuralları**\n"
        f"Bu kanalda 1v1 dışında hiçbir oyun oynamayınız.\n"
        f"Minimum bahis tutarı **{format_money(MIN_BET_PVP)}**, maksimum bahis tutarı **{format_money(MAX_BET_PVP)}** dir.\n"
        f"Yapmış olduğunuz bahis, kazandığınız/kaybettiğiniz takdirde sizin/rakibinizin bakiyesinden düşer.\n"
        f"Casino oyun başına **{format_rate_percent(PVP_COMMISSION_RATE)}** güvence bedeli komisyon alır.\n"
        f"Kazanılacak tutar, **x{PVP_PAYOUT_MULTIPLIER:g}** katıdır.\n\n"
        f"Sırası gelen oyuncunun her tur için **{PVP_TURN_SECONDS} saniyesi** vardır. "
        f"**{PVP_TURN_WARNING_SECONDS} saniye** kala etiketlenir; süre dolarsa hükmen kaybeder.\n\n"
        f"Katılmak için butona bas veya `/oyna {room['code']}` yaz."
    )

def roll_pvp_dice(creator_label, opponent_label):
    creator_roll = random.randint(1, 6)
    opponent_roll = random.randint(1, 6)
    winner_side = None
    if creator_roll > opponent_roll:
        winner_side = "creator"
    elif opponent_roll > creator_roll:
        winner_side = "opponent"
    detail = (
        f"🎲 **Zar sonucu**\n"
        f"{escape_markdown(creator_label)}: **{creator_roll}**\n"
        f"{escape_markdown(opponent_label)}: **{opponent_roll}**"
    )
    return winner_side, detail

PVP_21_RANKS = ["A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K"]

def draw_pvp_21_card():
    return random.choice(PVP_21_RANKS)

def pvp_21_score(cards):
    total = 0
    aces = 0
    for card in cards:
        if card == "A":
            total += 11
            aces += 1
        elif card in {"J", "Q", "K"}:
            total += 10
        else:
            total += int(card)
    while total > 21 and aces:
        total -= 10
        aces -= 1
    return total

def pvp_21_cards_text(cards):
    return " ".join(cards)

def build_pvp_21_keyboard(code):
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("Kart Çek", callback_data=f"pvp21_hit:{code}"),
        InlineKeyboardButton("Dur", callback_data=f"pvp21_stand:{code}"),
    ]])

def build_pvp_21_text(room):
    active_side = room["active_side"]
    creator_score = pvp_21_score(room["hands"]["creator"])
    opponent_score = pvp_21_score(room["hands"]["opponent"])
    active_label = room["creator_label"] if active_side == "creator" else room["opponent_label"]
    return (
        f"🃏 **1v1 21 başladı!**\n\n"
        f"Oda Kodu: `{room['code']}`\n"
        f"Bahis: **{format_money(room['bet'])}** Çip | Ödeme: **x{PVP_PAYOUT_MULTIPLIER:g}**\n\n"
        f"**{escape_markdown(room['creator_label'])}**\n"
        f"Kartlar: `{pvp_21_cards_text(room['hands']['creator'])}` = **{creator_score}**\n"
        f"Durum: **{room['states']['creator']}**\n\n"
        f"**{escape_markdown(room['opponent_label'])}**\n"
        f"Kartlar: `{pvp_21_cards_text(room['hands']['opponent'])}` = **{opponent_score}**\n"
        f"Durum: **{room['states']['opponent']}**\n\n"
        f"Sıra: **{escape_markdown(active_label)}**\n"
        f"Butonları kullan veya `/cek` / `/kal` yaz."
    )

def start_pvp_21_round(room, opponent_id, opponent_label, message):
    room.update({
        "status": "playing",
        "opponent_id": opponent_id,
        "opponent_label": opponent_label,
        "hands": {
            "creator": [draw_pvp_21_card(), draw_pvp_21_card()],
            "opponent": [draw_pvp_21_card(), draw_pvp_21_card()],
        },
        "states": {"creator": "oynuyor", "opponent": "bekliyor"},
        "active_side": "creator",
        "message_id": message.message_id if message else room.get("message_id"),
    })

def get_pvp_21_side(room, user_id):
    if user_id == room.get("creator_id"):
        return "creator"
    if user_id == room.get("opponent_id"):
        return "opponent"
    return None

def find_active_pvp_21_room(user_id, chat_id=None):
    for room in PVP_ROOMS.values():
        if room.get("game") != "yirmibir" or room.get("status") != "playing":
            continue
        if chat_id is not None and room.get("chat_id") != chat_id:
            continue
        if user_id in {room.get("creator_id"), room.get("opponent_id")}:
            return room
    return None

def resolve_pvp_21_winner(room):
    creator_total = pvp_21_score(room["hands"]["creator"])
    opponent_total = pvp_21_score(room["hands"]["opponent"])
    creator_score = creator_total if creator_total <= 21 else -1
    opponent_score = opponent_total if opponent_total <= 21 else -1
    if creator_score > opponent_score:
        return "creator"
    if opponent_score > creator_score:
        return "opponent"
    return None

def build_pvp_21_result_text(room, winner_side, payout, reason_text=None):
    creator_total = pvp_21_score(room["hands"]["creator"])
    opponent_total = pvp_21_score(room["hands"]["opponent"])
    detail = (
        f"🃏 **21 sonucu**\n"
        f"{escape_markdown(room['creator_label'])}: `{pvp_21_cards_text(room['hands']['creator'])}` = **{creator_total}**\n"
        f"{escape_markdown(room['opponent_label'])}: `{pvp_21_cards_text(room['hands']['opponent'])}` = **{opponent_total}**"
    )
    if winner_side is None:
        return (
            (f"{reason_text}\n\n" if reason_text else "") +
            f"🤝 **Berabere! Bahisler iade edildi.**\n\n"
            f"{detail}\n\n"
            f"💳 İade: **{format_money(room['bet'])}** Çip"
        )
    winner_label = room["creator_label"] if winner_side == "creator" else room["opponent_label"]
    return (
        (f"{reason_text}\n\n" if reason_text else "") +
        f"🏆 **Kazanan: {escape_markdown(winner_label)}**\n\n"
        f"{detail}\n\n"
        f"Bahis: **{format_money(room['bet'])}** Çip\n"
        f"Ödeme: **{format_money(payout)}** Çip (x{PVP_PAYOUT_MULTIPLIER:g})\n"
        f"Casino komisyonu: **{format_rate_percent(PVP_COMMISSION_RATE)}**"
    )

async def finish_pvp_21_room(context, room, forced_winner_side=None, reason_text=None):
    if room.get("finished"):
        return
    room["finished"] = True
    cancel_pvp_turn_timers(room)
    winner_side = forced_winner_side if forced_winner_side is not None else resolve_pvp_21_winner(room)
    payout = int(room["bet"] * PVP_PAYOUT_MULTIPLIER)
    game = PVP_GAME_CONFIG["yirmibir"]
    if winner_side is None:
        update_balance(room["creator_id"], room["bet"])
        update_balance(room["opponent_id"], room["bet"])
        update_game_stats(game["stats_type"], room["bet"] * 2, room["bet"] * 2, False)
    else:
        winner_id = room["creator_id"] if winner_side == "creator" else room["opponent_id"]
        update_balance(winner_id, payout)
        update_game_stats(game["stats_type"], room["bet"] * 2, payout, True)
    result_text = build_pvp_21_result_text(room, winner_side, payout, reason_text=reason_text)
    PVP_ROOMS.pop(room["code"], None)
    try:
        await context.bot.edit_message_text(chat_id=room["chat_id"], message_id=room["message_id"], text=result_text, parse_mode="Markdown")
    except Exception:
        await safe_send_message(context, room["chat_id"], result_text, parse_mode="Markdown", message_thread_id=room.get("thread_id"))

async def update_pvp_21_message(context, room):
    await context.bot.edit_message_text(
        chat_id=room["chat_id"],
        message_id=room["message_id"],
        text=build_pvp_21_text(room),
        parse_mode="Markdown",
        reply_markup=build_pvp_21_keyboard(room["code"]),
    )

async def handle_pvp_21_action(update: Update, context: ContextTypes.DEFAULT_TYPE, action, code=None):
    user = update.effective_user
    remember_user(user)
    query = update.callback_query
    is_callback = query is not None
    message = query.message if is_callback else update.message
    room = PVP_ROOMS.get(str(code).upper()) if code else find_active_pvp_21_room(user.id, update.effective_chat.id)
    if room is None or room.get("game") != "yirmibir" or room.get("status") != "playing":
        text = "Aktif 21 oyunun bulunamadı."
        if is_callback:
            await safe_query_answer(query, text, show_alert=True)
        else:
            await message.reply_text(text, message_thread_id=getattr(message, "message_thread_id", None))
        return
    side = get_pvp_21_side(room, user.id)
    if side is None:
        if is_callback:
            await safe_query_answer(query, "Bu oyunda oyuncu değilsin.", show_alert=True)
        return
    if room.get("active_side") != side:
        active_label = room["creator_label"] if room.get("active_side") == "creator" else room["opponent_label"]
        text = f"Sıra {active_label} oyuncusunda."
        if is_callback:
            await safe_query_answer(query, text, show_alert=True)
        else:
            await message.reply_text(text, message_thread_id=getattr(message, "message_thread_id", None))
        return
    cancel_pvp_turn_timers(room)
    if action == "hit":
        room["hands"][side].append(draw_pvp_21_card())
        if pvp_21_score(room["hands"][side]) > 21:
            room["states"][side] = "battı"
            await finish_pvp_21_room(context, room)
        else:
            await update_pvp_21_message(context, room)
            start_pvp_turn_timer(context, room)
    elif action == "stand":
        room["states"][side] = "durdu"
        if side == "creator":
            room["active_side"] = "opponent"
            room["states"]["opponent"] = "oynuyor"
            await update_pvp_21_message(context, room)
            start_pvp_turn_timer(context, room)
        else:
            await finish_pvp_21_room(context, room)
    if is_callback:
        await safe_query_answer(query, "Hamle alındı.", show_alert=False)
    elif room.get("code") in PVP_ROOMS:
        await message.reply_text("Hamle alındı.", message_thread_id=getattr(message, "message_thread_id", None))

async def pvp_21_hit_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    code = query.data.split(":", 1)[1] if query and query.data else ""
    await handle_pvp_21_action(update, context, "hit", code)

async def pvp_21_stand_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    code = query.data.split(":", 1)[1] if query and query.data else ""
    await handle_pvp_21_action(update, context, "stand", code)

async def pvp_21_hit_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await handle_pvp_21_action(update, context, "hit")

async def pvp_21_stand_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await handle_pvp_21_action(update, context, "stand")

PVP_GAME_CONFIG = {
    "zar": {"title": "Zar", "stats_type": "pvp_zar", "resolver": roll_pvp_dice},
    "yirmibir": {"title": "21", "stats_type": "pvp_yirmibir", "resolver": None},
    "xox": {"title": "6x6 XOX", "stats_type": "pvp_xox", "resolver": None},
}

async def create_pvp_room(update: Update, context: ContextTypes.DEFAULT_TYPE, game_key):
    user_id = update.effective_user.id
    remember_user(update.effective_user)
    thread_id = update.message.message_thread_id if update.message else None
    if not context.args:
        await update.message.reply_text(f"❌ Kullanım: `/{game_key} [Miktar]`\nMin {format_money(MIN_BET_PVP)} | Max {format_money(MAX_BET_PVP)}", parse_mode="Markdown", message_thread_id=thread_id)
        return
    bet = parse_money(context.args[0])
    if bet is None or bet < MIN_BET_PVP or bet > MAX_BET_PVP:
        await update.message.reply_text(f"❌ Geçersiz bahis! 1v1 oyunlarda **{format_money(MIN_BET_PVP)}** ile **{format_money(MAX_BET_PVP)}** arası oynayabilirsin.", parse_mode="Markdown", message_thread_id=thread_id)
        return
    if get_balance(user_id) < bet:
        await update.message.reply_text("❌ **Bakiyen yetersiz!**", parse_mode="Markdown", message_thread_id=thread_id)
        return
    cleanup_pvp_rooms()
    code = make_pvp_code()
    room = {
        "code": code,
        "game": game_key,
        "creator_id": user_id,
        "creator_label": get_user_label(update.effective_user),
        "bet": bet,
        "chat_id": update.effective_chat.id,
        "thread_id": thread_id,
        "created_at": time.time(),
        "status": "waiting",
    }
    PVP_ROOMS[code] = room
    sent_message = await update.message.reply_text(pvp_room_text(room), parse_mode="Markdown", reply_markup=build_pvp_keyboard(code), message_thread_id=thread_id)
    room["message_id"] = sent_message.message_id

async def play_pvp_dice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await create_pvp_room(update, context, "zar")

async def play_pvp_21(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await create_pvp_room(update, context, "yirmibir")

async def play_pvp_xox(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await create_pvp_room(update, context, "xox")

async def join_pvp_room(update: Update, context: ContextTypes.DEFAULT_TYPE, code=None):
    user = update.effective_user
    remember_user(user)
    is_callback = update.callback_query is not None
    query = update.callback_query
    message = query.message if is_callback else update.message
    thread_id = getattr(message, "message_thread_id", None)
    if code is None:
        if not context.args:
            await message.reply_text("❌ Kullanım: `/oyna [OdaKodu]`", parse_mode="Markdown", message_thread_id=thread_id)
            return
        code = context.args[0]
    code = str(code).upper().strip()
    cleanup_pvp_rooms()
    room = PVP_ROOMS.get(code)
    if room is None or room.get("status") != "waiting":
        text = "❌ Oda bulunamadı veya oyun zaten başladı."
        if is_callback:
            await safe_query_answer(query, text, show_alert=True)
        else:
            await message.reply_text(text, message_thread_id=thread_id)
        return
    if user.id == room["creator_id"]:
        text = "❌ Kendi açtığın odaya katılamazsın."
        if is_callback:
            await safe_query_answer(query, text, show_alert=True)
        else:
            await message.reply_text(text, message_thread_id=thread_id)
        return
    if get_balance(room["creator_id"]) < room["bet"]:
        PVP_ROOMS.pop(code, None)
        text = "❌ Kurucunun bakiyesi artık yetersiz. Oda kapatıldı."
        if is_callback:
            await safe_query_answer(query, text, show_alert=True)
            await query.edit_message_text(text)
        else:
            await message.reply_text(text, message_thread_id=thread_id)
        return
    if get_balance(user.id) < room["bet"]:
        text = "❌ Bakiyen bu odaya katılmak için yetersiz."
        if is_callback:
            await safe_query_answer(query, text, show_alert=True)
        else:
            await message.reply_text(text, message_thread_id=thread_id)
        return
    room["status"] = "playing"
    opponent_label = get_user_label(user)
    update_balance(room["creator_id"], -room["bet"])
    update_balance(user.id, -room["bet"])
    game = PVP_GAME_CONFIG[room["game"]]
    if room["game"] == "yirmibir":
        start_pvp_21_round(room, user.id, opponent_label, message)
        result_text = build_pvp_21_text(room)
        if is_callback:
            await safe_query_answer(query, "21 başladı!", show_alert=False)
            await query.edit_message_text(result_text, parse_mode="Markdown", reply_markup=build_pvp_21_keyboard(code))
            room["message_id"] = query.message.message_id
        else:
            sent_message = await message.reply_text(result_text, parse_mode="Markdown", reply_markup=build_pvp_21_keyboard(code), message_thread_id=thread_id)
            room["message_id"] = sent_message.message_id
        start_pvp_turn_timer(context, room)
        return
    if room["game"] == "xox":
        start_pvp_xox_round(room, user.id, opponent_label)
        result_text = build_xox_text(room)
        if is_callback:
            await safe_query_answer(query, "XOX başladı!", show_alert=False)
            await query.edit_message_text(result_text, parse_mode="Markdown", reply_markup=build_xox_keyboard(room))
            room["message_id"] = query.message.message_id
        else:
            sent_message = await message.reply_text(result_text, parse_mode="Markdown", reply_markup=build_xox_keyboard(room), message_thread_id=thread_id)
            room["message_id"] = sent_message.message_id
        start_pvp_turn_timer(context, room)
        return
    winner_side, detail = game["resolver"](room["creator_label"], opponent_label)
    payout = int(room["bet"] * PVP_PAYOUT_MULTIPLIER)
    if winner_side is None:
        update_balance(room["creator_id"], room["bet"])
        update_balance(user.id, room["bet"])
        result_text = f"🤝 **Berabere! Bahisler iade edildi.**\n\n{detail}\n\n💳 İade: **{format_money(room['bet'])}** Çip"
        update_game_stats(game["stats_type"], room["bet"] * 2, room["bet"] * 2, False)
    else:
        winner_id = room["creator_id"] if winner_side == "creator" else user.id
        winner_label = room["creator_label"] if winner_side == "creator" else opponent_label
        update_balance(winner_id, payout)
        result_text = (
            f"🏆 **Kazanan: {escape_markdown(winner_label)}**\n\n{detail}\n\n"
            f"Bahis: **{format_money(room['bet'])}** Çip\n"
            f"Ödeme: **{format_money(payout)}** Çip (x{PVP_PAYOUT_MULTIPLIER:g})\n"
            f"Casino komisyonu: **{format_rate_percent(PVP_COMMISSION_RATE)}**"
        )
        update_game_stats(game["stats_type"], room["bet"] * 2, payout, True)
    PVP_ROOMS.pop(code, None)
    if is_callback:
        await safe_query_answer(query, "Oyun başladı!", show_alert=False)
        await query.edit_message_text(result_text, parse_mode="Markdown")
    else:
        await message.reply_text(result_text, parse_mode="Markdown", message_thread_id=thread_id)

async def join_pvp_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    code = query.data.split(":", 1)[1] if query and query.data else ""
    await join_pvp_room(update, context, code)

async def join_pvp_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await join_pvp_room(update, context)

def build_xox_keyboard(room):
    rows = []
    board = room["xox_board"]
    for row in range(XOX_SIZE):
        buttons = []
        for col in range(XOX_SIZE):
            index = row * XOX_SIZE + col
            buttons.append(InlineKeyboardButton(board[index], callback_data=f"xox6:{room['code']}:{index}"))
        rows.append(buttons)
    return InlineKeyboardMarkup(rows)

def start_pvp_xox_round(room, opponent_id, opponent_label):
    room.update({
        "status": "playing",
        "opponent_id": opponent_id,
        "opponent_label": opponent_label,
        "xox_board": [XOX_EMPTY] * (XOX_SIZE * XOX_SIZE),
        "xox_turn": "X",
        "xox_players": {"X": room["creator_id"], "O": opponent_id},
        "xox_labels": {room["creator_id"]: room["creator_label"], opponent_id: opponent_label},
    })

def get_xox_symbol(room, user_id):
    for symbol, player_id in room["xox_players"].items():
        if player_id == user_id:
            return symbol
    return None

def xox_player_label(room, symbol):
    player_id = room["xox_players"].get(symbol)
    if not player_id:
        return symbol
    return room["xox_labels"].get(player_id, symbol)

def check_xox6_winner(board):
    directions = [(1, 0), (0, 1), (1, 1), (1, -1)]
    for row in range(XOX_SIZE):
        for col in range(XOX_SIZE):
            symbol = board[row * XOX_SIZE + col]
            if symbol == XOX_EMPTY:
                continue
            for dr, dc in directions:
                cells = []
                for step in range(4):
                    nr = row + dr * step
                    nc = col + dc * step
                    if nr < 0 or nr >= XOX_SIZE or nc < 0 or nc >= XOX_SIZE:
                        break
                    cells.append(board[nr * XOX_SIZE + nc])
                if len(cells) == 4 and all(cell == symbol for cell in cells):
                    return symbol
    if XOX_EMPTY not in board:
        return "draw"
    return None

def build_xox_text(room):
    turn_label = xox_player_label(room, room["xox_turn"])
    x_label = xox_player_label(room, "X")
    o_label = xox_player_label(room, "O")
    return (
        f"❌⭕ **6x6 XOX**\n\n"
        f"Oda Kodu: `{room['code']}`\n"
        f"Bahis: **{format_money(room['bet'])}** Çip | Ödeme: **x{PVP_PAYOUT_MULTIPLIER:g}**\n\n"
        f"X: **{escape_markdown(x_label)}**\n"
        f"O: **{escape_markdown(o_label)}**\n\n"
        f"Sıra: **{room['xox_turn']}** - {escape_markdown(turn_label)}\n"
        f"4 tane aynı sembolü yatay, dikey veya çapraz denk getiren kazanır."
    )

async def start_xox6(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await play_pvp_xox(update, context)

async def finish_pvp_xox_room(context, room, winner_symbol, reason_text=None):
    if room.get("finished"):
        return
    room["finished"] = True
    cancel_pvp_turn_timers(room)
    payout = int(room["bet"] * PVP_PAYOUT_MULTIPLIER)
    game = PVP_GAME_CONFIG["xox"]
    if winner_symbol is None:
        update_balance(room["creator_id"], room["bet"])
        update_balance(room["opponent_id"], room["bet"])
        update_game_stats(game["stats_type"], room["bet"] * 2, room["bet"] * 2, False)
        text = (
            (f"{reason_text}\n\n" if reason_text else "") +
            f"🤝 **6x6 XOX berabere bitti. Bahisler iade edildi.**\n\n💳 İade: **{format_money(room['bet'])}** Çip"
        )
    else:
        winner_id = room["xox_players"][winner_symbol]
        winner_label = xox_player_label(room, winner_symbol)
        update_balance(winner_id, payout)
        update_game_stats(game["stats_type"], room["bet"] * 2, payout, True)
        text = (
            (f"{reason_text}\n\n" if reason_text else "") +
            f"🏆 **{winner_symbol} kazandı: {escape_markdown(winner_label)}**\n\n"
            f"Bahis: **{format_money(room['bet'])}** Çip\n"
            f"Ödeme: **{format_money(payout)}** Çip (x{PVP_PAYOUT_MULTIPLIER:g})\n"
            f"Casino komisyonu: **{format_rate_percent(PVP_COMMISSION_RATE)}**"
        )
    PVP_ROOMS.pop(room["code"], None)
    try:
        await context.bot.edit_message_text(chat_id=room["chat_id"], message_id=room["message_id"], text=text, parse_mode="Markdown")
    except Exception:
        await safe_send_message(context, room["chat_id"], text, parse_mode="Markdown", message_thread_id=room.get("thread_id"))

async def xox6_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    parts = query.data.split(":") if query and query.data else []
    if len(parts) != 3:
        await safe_query_answer(query, "Bu eski XOX butonu artık geçersiz.", show_alert=True)
        return
    code = parts[1].upper()
    room = PVP_ROOMS.get(code)
    if room is None or room.get("game") != "xox" or room.get("status") != "playing":
        await safe_query_answer(query, "Bu XOX oyunu bulunamadı veya bitti.", show_alert=True)
        return
    symbol = get_xox_symbol(room, query.from_user.id)
    if symbol is None:
        await safe_query_answer(query, "Bu oyunda oyuncu değilsin.", show_alert=True)
        return
    if symbol != room["xox_turn"]:
        await safe_query_answer(query, f"Sıra {room['xox_turn']} oyuncusunda.", show_alert=True)
        return
    index = int(parts[2])
    if room["xox_board"][index] != XOX_EMPTY:
        await safe_query_answer(query, "Bu kutu dolu.", show_alert=True)
        return
    cancel_pvp_turn_timers(room)
    room["xox_board"][index] = symbol
    result = check_xox6_winner(room["xox_board"])
    if result == "draw":
        await safe_query_answer(query, "Hamle alındı.", show_alert=False)
        await finish_pvp_xox_room(context, room, None)
        return
    if result:
        await safe_query_answer(query, "Hamle alındı.", show_alert=False)
        await finish_pvp_xox_room(context, room, result)
        return
    room["xox_turn"] = "O" if room["xox_turn"] == "X" else "X"
    await query.edit_message_text(build_xox_text(room), parse_mode="Markdown", reply_markup=build_xox_keyboard(room))
    start_pvp_turn_timer(context, room)
    await safe_query_answer(query, "Hamle alındı.", show_alert=False)

def get_forced_mode_label():
    forced_win_rate = get_house_state().get("forced_win_rate")
    if forced_win_rate is None:
        return "Kapalı"
    if forced_win_rate == 50:
        return "%50 normal ağırlık"
    if forced_win_rate >= 100:
        return "%100 garanti kazan"
    if forced_win_rate <= 0:
        return "%100 garanti kaybet"
    return f"%{format_percent(forced_win_rate)} kazan ağırlığı / %{format_percent(100 - forced_win_rate)} kayıp ağırlığı"

def simulate_slot_round(bet):
    val = random.randint(1, 64)
    if val == 64:
        return bet * 24
    if val in [1, 22, 43]:
        return int(bet * 7.5)
    return 0

def simulate_dart_round(bet):
    return bet * 4 if random.randint(1, 6) == 6 else 0

def simulate_bowling_round(bet):
    return bet * 5 if random.randint(1, 6) == 6 else 0

def simulate_lcdp_round(bet):
    house_state = get_house_state()
    forced_result = decide_forced_win(house_state)
    grid = draw_lcdp_grid_for_result(forced_result)
    _, _, base_multiplier, scatter_count = evaluate_lcdp_spin(grid)
    hand_multiplier = 0 if forced_result is False else choose_lcdp_multiplier(house_state)
    paid_multiplier = base_multiplier * (hand_multiplier if hand_multiplier > 0 else 1)
    paid = int(bet * paid_multiplier) if paid_multiplier > 0 else 0

    if scatter_count >= LCDP_FREE_SPIN_TRIGGER_COUNT:
        free_paid, _ = run_lcdp_free_spins(bet, house_state, forced_result)
        paid += free_paid

    return paid

def simulate_roulette_round(bet):
    selected_key = random.choice(["kirmizi", "siyah", "yesil"])
    selected_config = ROULETTE_CONFIG[selected_key]
    outcome = choose_roulette_outcome(selected_config, bet)
    is_win = outcome["label"] == selected_config["label"]
    return int(bet * selected_config["multiplier"]) if is_win else 0

def simulate_horse_round(bet):
    selected_horse = random.choice(list(HORSE_CONFIG.keys()))
    winner = choose_horse_winner(selected_horse, bet)
    return int(bet * HORSE_CONFIG[selected_horse]["multiplier"]) if winner == selected_horse else 0

def simulate_aviator_round(bet):
    auto_cashout = random.choices(
        [1.25, 1.5, 2.0, 3.0, 5.0, 10.0],
        weights=[18, 28, 25, 16, 9, 4],
        k=1
    )[0]
    crash_multiplier = choose_aviator_crash_multiplier(auto_cashout)
    return int(bet * auto_cashout) if crash_multiplier >= auto_cashout else 0

async def test_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return

    thread_id = update.message.message_thread_id if update.message else None
    total_games = 1000
    bet = MIN_BET_LCDP
    games = NORMAL_GAME_TYPES
    requested_game = context.args[0].lower().strip() if context.args else "all"
    selected_game = TEST_GAME_ALIASES.get(requested_game)
    if selected_game is None:
        await update.message.reply_text(
            "❌ Kullanım: `/test` veya `/test [slot/dart/bowling/atyarisi/rulet/lcdp/aviator]`",
            parse_mode="Markdown",
            message_thread_id=thread_id
        )
        return
    if selected_game != "all":
        games = [selected_game]

    stats = {
        game: {"games": 0, "wins": 0, "wagered": 0, "paid": 0}
        for game in games
    }

    progress_message = await update.message.reply_text(
        f"🧪 **Test başladı**\n`{build_progress_bar(0, total_games)}` %0",
        parse_mode="Markdown",
        message_thread_id=thread_id
    )

    for index in range(total_games):
        current_game_no = index + 1
        game_type = games[index % len(games)]
        if game_type == "slot":
            paid = simulate_slot_round(bet)
        elif game_type == "dart":
            paid = simulate_dart_round(bet)
        elif game_type == "bowling":
            paid = simulate_bowling_round(bet)
        elif game_type == "lcdp":
            paid = simulate_lcdp_round(bet)
        elif game_type == "atyarisi":
            paid = simulate_horse_round(bet)
        elif game_type == "aviator":
            paid = simulate_aviator_round(bet)
        else:
            paid = simulate_roulette_round(bet)

        stats[game_type]["games"] += 1
        stats[game_type]["wins"] += 1 if paid > 0 else 0
        stats[game_type]["wagered"] += bet
        stats[game_type]["paid"] += paid

        if current_game_no % 100 == 0 or current_game_no == total_games:
            percent = int(current_game_no / total_games * 100)
            try:
                await progress_message.edit_text(
                    f"🧪 **Test çalışıyor**\n`{build_progress_bar(current_game_no, total_games)}` %{percent}",
                    parse_mode="Markdown"
                )
            except Exception:
                pass
            await asyncio.sleep(0)

    total_wins = sum(item["wins"] for item in stats.values())
    total_wagered = sum(item["wagered"] for item in stats.values())
    total_paid = sum(item["paid"] for item in stats.values())
    total_losses = total_games - total_wins
    win_rate = (total_wins / total_games * 100) if total_games else 0
    rtp = (total_paid / total_wagered * 100) if total_wagered else 0
    net = total_wagered - total_paid

    detail_lines = []
    labels = {
        "slot": "SLOT",
        "dart": "DART",
        "bowling": "BOWLING",
        "atyarisi": "AT YARIŞI",
        "roulette": "RULET",
        "lcdp": "LCDP",
        "aviator": "AVIATOR",
    }
    for game_type in games:
        item = stats[game_type]
        game_win_rate = (item["wins"] / item["games"] * 100) if item["games"] else 0
        game_rtp = (item["paid"] / item["wagered"] * 100) if item["wagered"] else 0
        detail_lines.append(
            f"• **{labels[game_type]}:** {item['wins']}/{item['games'] - item['wins']} | Win %{game_win_rate:.1f} | RTP %{game_rtp:.1f}"
        )

    final_text = (
        f"🧪 **TEST TAMAMLANDI**\n"
        f"`{build_progress_bar(total_games, total_games)}` %100\n\n"
        f"Yüzdeli Mod: **{get_forced_mode_label()}**\n"
        f"Oyun: **{'TÜMÜ' if selected_game == 'all' else labels[selected_game]}**\n"
        f"Simülasyon: **{total_games} oyun**\n"
        f"Bahis: **{format_money(bet)}**\n\n"
        f"Kazandı/Kaybetti: **{total_wins}/{total_losses}**\n"
        f"Win Rate: **%{win_rate:.1f}**\n"
        f"Toplam Dönen: **{format_money(total_wagered)}**\n"
        f"Toplam Ödenen: **{format_money(total_paid)}**\n"
        f"Kasa Net: **{format_money(net)}**\n"
        f"RTP: **%{rtp:.1f}**\n\n"
        f"{chr(10).join(detail_lines)}\n\n"
        f"_Gerçek bakiye ve panel verilerine işlenmedi._"
    )

    try:
        await progress_message.edit_text(final_text, parse_mode="Markdown")
    except Exception:
        await update.message.reply_text(final_text, parse_mode="Markdown", message_thread_id=thread_id)

async def top_players(update: Update, context: ContextTypes.DEFAULT_TYPE):
    remember_user(update.effective_user)
    thread_id = update.message.message_thread_id if update.message else None
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, username, first_name, last_name, balance FROM users ORDER BY balance DESC LIMIT 10")
    rows = cursor.fetchall()
    conn.close()
    
    leaderboard = "🏆 **KUMARBAZLAR KRALLIĞI - TOP 10** 🏆\n\n"
    medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
    
    for index, row in enumerate(rows):
        target_id, username, first_name, last_name, balance = row
        if username:
            display_name = f"@{username}"
        else:
            full_name = " ".join(part for part in [first_name, last_name] if part)
            display_name = full_name or f"ID: {target_id}"

        leaderboard += f"{medals[index]} {escape_markdown(display_name)} — 💰 **{format_money(balance)} Çip**\n"
        
    await update.message.reply_text(leaderboard, parse_mode="Markdown", message_thread_id=thread_id)

async def bakiye(update: Update, context: ContextTypes.DEFAULT_TYPE):
    remember_user(update.effective_user)
    balance = get_balance(update.effective_user.id)
    await update.message.reply_text(f"💰 Bakiyen: {format_money(balance)} Çip")

async def transfer_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sender_id = update.effective_user.id
    remember_user(update.effective_user)
    thread_id = update.message.message_thread_id if update.message else None

    target_id = None
    amount_arg = None

    if update.message.reply_to_message:
        target_user = update.message.reply_to_message.from_user
        remember_user(target_user)
        target_id = target_user.id
        amount_arg = context.args[0] if context.args else None
    elif len(context.args) >= 2:
        target_arg = context.args[0]
        amount_arg = context.args[1]
        if target_arg.startswith("@"):
            target_id = find_user_id_by_username(target_arg)
        else:
            try:
                target_id = int(target_arg)
            except ValueError:
                target_id = None

    amount = parse_money(amount_arg) if amount_arg else None
    if target_id is None or amount is None or amount <= 0:
        await update.message.reply_text(
            "❌ Kullanım: `/transfer [ID/@kullanıcı] [Miktar]`\n"
            "Ya da bir kullanıcı mesajına yanıt ver: `/transfer 10t`",
            parse_mode="Markdown",
            message_thread_id=thread_id
        )
        return

    if target_id == sender_id:
        await update.message.reply_text("❌ Kendine transfer yapamazsın.", message_thread_id=thread_id)
        return

    new_balance = transfer_balance(sender_id, target_id, amount)
    if new_balance is None:
        await update.message.reply_text("❌ Bakiyen yetersiz!", message_thread_id=thread_id)
        return

    await update.message.reply_text(
        f"✅ `{target_id}` ID'li kullanıcıya **{format_money(amount)}** çip transfer edildi.\n"
        f"💳 Kalan bakiyen: **{format_money(new_balance)}** Çip",
        parse_mode="Markdown",
        message_thread_id=thread_id
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    is_admin = user_id in ADMIN_IDS
    remember_user(update.effective_user)
    thread_id = update.message.message_thread_id if update.message else None
    
    help_text = (
        f"📖 **CASINO BOTU KOMUT LİSTESİ** 📖\n\n"
        f"🎮 **Oyunlar:**\n"
        f"• `/slot [Miktar]` (Min {format_money(MIN_BET_SLOT)} | Max {format_money(MAX_BET_SLOT)})\n"
        f"• `/dart [Miktar]` (Min {format_money(MIN_BET_DART_BOWL)} | Max {format_money(MAX_BET_DART_BOWL)})\n"
        f"• `/bowling [Miktar]` (Min {format_money(MIN_BET_DART_BOWL)} | Max {format_money(MAX_BET_DART_BOWL)})\n"
        f"• `/atyarisi [Miktar] [At No]` (Min {format_money(MIN_BET_HORSE)} | Max {format_money(MAX_BET_HORSE)} | At: 1-8)\n\n"
        f"• `/rulet [Miktar] [kirmizi/siyah/yesil]` (Min {format_money(MIN_BET_ROULETTE)} | Max {format_money(MAX_BET_ROULETTE)})\n"
        f"• `/lcdp [Miktar]` (Min {format_money(MIN_BET_LCDP)} | Max {format_money(MAX_BET_LCDP)})\n"
        f"• `/lcdp [Miktar] freespin` veya `/lcdpfs [Miktar]` (Min {format_money(MIN_LCDP_FREE_SPIN_BUY)} | Max {format_money(MAX_LCDP_FREE_SPIN_BUY)})\n\n"
        f"• `/aviator [Miktar] [Oto Çıkış]` (Bahisten 20 sn sonra ortak tur | Min {format_money(MIN_BET_AVIATOR)} | Max {format_money(MAX_BET_AVIATOR)} | Örn: `/aviator 10t 2x`)\n"
        f"• `/zar [Miktar]` - Bahisli 1v1 zar odası açar (Min {format_money(MIN_BET_PVP)} | Max {format_money(MAX_BET_PVP)} | Kazanç x{PVP_PAYOUT_MULTIPLIER:g})\n"
        f"• `/yirmibir [Miktar]` veya `/21 [Miktar]` - Butonlu 1v1 21 odası açar (`/cek`, `/kal`)\n"
        f"• `/xox [Miktar]` - Bahisli 1v1 6x6 XOX açar; 4'lü yatay/dikey/çapraz kazandırır\n"
        f"• `/oyna [OdaKodu]` - Açık 1v1 odasına katılır\n"
        f"💡 *Bahislerde t, kt kısaltmalarını kullanabilirsin. (Örn: /slot 20t)*\n\n"
        f"🛠️ **Genel:**\n"
        f"• `/bakiye` - Mevcut çipini gösterir\n"
        f"• `/kreditalep [Miktar]` - Admin onayı için kredi talebi açar\n"
        f"• `/top10` - En zengin 10 oyuncuyu listeler\n"
        f"• `/bilgi` - Kendi oyun ve bakiye bilgilerini gösterir\n"
        f"• `/transfer [ID/@kullanıcı] [Miktar]` - Başka kullanıcıya çip gönderir\n"
    )
    
    if is_admin:
        help_text += (
            f"\n⚡ Admin komutları için `/admin`\n"
        )
        
    await update.message.reply_text(help_text, parse_mode="Markdown", message_thread_id=thread_id)

async def admin_help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return

    thread_id = update.message.message_thread_id if update.message else None
    admin_text = (
        f"⚡ **ADMİN KOMUTLARI**\n\n"
        f"• `/bakiyeekle [ID/Yanıt] [Miktar]`\n"
        f"• `/bakiyesil [ID/Yanıt] [Miktar]`\n"
        f"• `/kredi` - Kredi alanları ve bekleyen talepleri gösterir\n"
        f"• `/kredionay [TalepNo]` - Kredi talebini onaylar\n"
        f"• `/krediret [TalepNo]` - Kredi talebini reddeder\n"
        f"• `/krediodendi [TalepNo]` - Krediyi ödendi işaretler\n"
        f"• `/krediodenmedi [TalepNo]` - Krediyi ödenmedi işaretler\n"
        f"• `/kredisil [TalepNo]` - Kredi kaydını listeden siler\n"
        f"• `/panel` - Normal oyunların kasa ve oyun verilerini gösterir\n"
        f"• `/panel1` veya `/panel 1` - 1v1 oyunların kasa ve oyun verilerini gösterir\n"
        f"• `/mod normal` - Yüzdeli modu kapatır\n"
        f"• `/mod kazan 80`, `/mod kaybet 80`, `/mod oran 35` - Yüzdeli test modunu ayarlar\n"
        f"• `/test [oyun]` - 1000 oyun simülasyonu yapar\n"
        f"• `/avbaslat` veya `/aviatorbaslat` - Aviator test turunu dakika beklemeden başlatır\n"
        f"• `/aktifoyun` veya `/avdurum` - Aktif Aviator oyuncu/cashout raporunu adminlere yollar\n"
        f"• `/kes` - Aktif Aviator turunu anlık çarpandan bitirir\n"
        f"• `/avmod [TurSayısı] [Crashler]` - Sonraki Aviator turlarına crash sırası verir\n"
        f"• `/avpromo [MinCrash] [TurSayısı]` - Sonraki Aviator turlarına minimum crash promosu verir\n"
        f"• `/avvoid [TurNo]` - Aviator turunu iptal edip kalan/kaybeden bahisleri iade eder\n"
        f"• `/bilgi [ID/@kullanıcı]` - Başka kullanıcıların bilgilerini gösterir\n"
        f"• `/panelsifirla` - Kasa geçmişini temizler\n"
        f"• `/bakim ac|kapat|durum` - Bot bakım modunu yönetir\n"
        f"• `/duyuru [Mesaj]` - Herkese mesaj atar\n"
    )
    await update.message.reply_text(admin_text, parse_mode="Markdown", message_thread_id=thread_id)


# --- 5. GÜVENLİ ADMİN KOMUTLARI ---

async def maintenance_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global MAINTENANCE_MODE
    if update.effective_user.id not in ADMIN_IDS:
        return

    thread_id = update.message.message_thread_id if update.message else None
    action = context.args[0].lower() if context.args else "durum"

    if action in ["ac", "aç", "on"]:
        MAINTENANCE_MODE = True
        await update.message.reply_text(
            "🛠️ Bakım modu açıldı. Adminler hariç kimse bot komutlarını kullanamaz.",
            message_thread_id=thread_id
        )
    elif action in ["kapat", "off"]:
        MAINTENANCE_MODE = False
        await update.message.reply_text(
            "✅ Bakım modu kapatıldı. Bot herkes için aktif.",
            message_thread_id=thread_id
        )
    elif action == "durum":
        status = "AÇIK" if MAINTENANCE_MODE else "KAPALI"
        await update.message.reply_text(f"🛠️ Bakım modu: {status}", message_thread_id=thread_id)
    else:
        await update.message.reply_text(
            "❌ Kullanım: `/bakim ac`, `/bakim kapat` veya `/bakim durum`",
            parse_mode="Markdown",
            message_thread_id=thread_id
        )

async def house_mode_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return

    thread_id = update.message.message_thread_id if update.message else None
    if context.args:
        requested_mode = context.args[0].lower().strip()
        forced_action = FORCED_MODE_ALIASES.get(requested_mode)
        if forced_action:
            if len(context.args) < 2:
                await update.message.reply_text(
                    "❌ Kullanım: `/mod kazan 80`, `/mod kaybet 80` veya `/mod oran 35`",
                    parse_mode="Markdown",
                    message_thread_id=thread_id
                )
                return

            requested_percent = parse_percent(context.args[1])
            if requested_percent is None:
                await update.message.reply_text("❌ Yüzde 0 ile 100 arasında olmalı.", message_thread_id=thread_id)
                return

            forced_win_rate = 100 - requested_percent if forced_action == "lose" else requested_percent
            set_setting("forced_win_rate", format_percent(forced_win_rate))
            set_setting("house_mode_override", None)
            await update.message.reply_text(
                build_house_mode_text(),
                parse_mode="Markdown",
                message_thread_id=thread_id
            )
            return

        mode = HOUSE_MODE_ALIASES.get(requested_mode)
        if mode is None:
            await update.message.reply_text(
                "❌ Kullanım: `/mod normal`, `/mod kazan 80`, `/mod kaybet 80` veya `/mod oran 35`",
                parse_mode="Markdown",
                message_thread_id=thread_id
            )
            return

        set_setting("house_mode_override", None)
        set_setting("forced_win_rate", None)

    await update.message.reply_text(
        build_house_mode_text(),
        parse_mode="Markdown",
        message_thread_id=thread_id
    )

def get_target_and_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.reply_to_message:
        target_id = update.message.reply_to_message.from_user.id
        amount = parse_money(context.args[0]) if context.args else None
        return target_id, amount
    else:
        if not context.args or len(context.args) < 2:
            return None, None
        try:
            target_id = int(context.args[0])
            amount = parse_money(context.args[1])
            return target_id, amount
        except ValueError:
            return None, None

def get_info_target(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.reply_to_message:
        remember_user(update.message.reply_to_message.from_user)
        return update.message.reply_to_message.from_user.id

    if not context.args:
        return None

    target_arg = context.args[0]
    if target_arg.startswith("@"):
        return find_user_id_by_username(target_arg)

    try:
        return int(target_arg)
    except ValueError:
        return None

def get_user_display_name(user_id, username, first_name, last_name):
    if username:
        return f"@{username}"
    full_name = " ".join(part for part in [first_name, last_name] if part)
    return full_name or f"ID: {user_id}"

def format_timestamp(timestamp):
    if not timestamp:
        return "-"
    return time.strftime("%d.%m.%Y %H:%M", time.localtime(int(timestamp)))

def create_credit_request(user_id, amount):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT request_id FROM credit_requests WHERE user_id = ? AND status = 'pending'",
        (user_id,)
    )
    existing = cursor.fetchone()
    if existing:
        conn.close()
        return None, existing[0]

    cursor.execute(
        "INSERT INTO credit_requests (user_id, amount, requested_at) VALUES (?, ?, ?)",
        (user_id, amount, int(time.time()))
    )
    request_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return request_id, None

def get_pending_credit_request(target):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    if target is None:
        conn.close()
        return None

    mode, value = target
    try:
        value = int(value)
    except (TypeError, ValueError):
        conn.close()
        return None

    if mode == "request":
        cursor.execute(
            """
            SELECT request_id, user_id, amount, status, requested_at
            FROM credit_requests
            WHERE request_id = ? AND status = 'pending'
            """,
            (value,)
        )
    else:
        cursor.execute(
            """
            SELECT request_id, user_id, amount, status, requested_at
            FROM credit_requests
            WHERE user_id = ? AND status = 'pending'
            ORDER BY request_id DESC
            LIMIT 1
            """,
            (value,)
        )
    row = cursor.fetchone()
    conn.close()
    return row

def decide_credit_request(request_id, status, admin_id):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT user_id, amount
        FROM credit_requests
        WHERE request_id = ? AND status = 'pending'
        """,
        (request_id,)
    )
    row = cursor.fetchone()
    if row is None:
        conn.close()
        return None

    user_id, amount = row
    cursor.execute(
        """
        UPDATE credit_requests
        SET status = ?, decided_at = ?, decided_by = ?
        WHERE request_id = ? AND status = 'pending'
        """,
        (status, int(time.time()), admin_id, request_id)
    )
    conn.commit()
    conn.close()
    return user_id, amount

def get_credit_summary(user_id):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT
            COALESCE(SUM(CASE WHEN status = 'approved' THEN amount ELSE 0 END), 0),
            COALESCE(SUM(CASE WHEN status = 'pending' THEN amount ELSE 0 END), 0),
            COALESCE(SUM(CASE WHEN status = 'rejected' THEN amount ELSE 0 END), 0),
            COALESCE(SUM(CASE WHEN status = 'approved' AND paid = 1 THEN amount ELSE 0 END), 0),
            COALESCE(SUM(CASE WHEN status = 'approved' AND COALESCE(paid, 0) = 0 THEN amount ELSE 0 END), 0),
            SUM(CASE WHEN status = 'approved' THEN 1 ELSE 0 END),
            SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END),
            SUM(CASE WHEN status = 'rejected' THEN 1 ELSE 0 END),
            SUM(CASE WHEN status = 'approved' AND paid = 1 THEN 1 ELSE 0 END),
            SUM(CASE WHEN status = 'approved' AND COALESCE(paid, 0) = 0 THEN 1 ELSE 0 END),
            MAX(CASE WHEN status = 'approved' THEN decided_at ELSE NULL END)
        FROM credit_requests
        WHERE user_id = ?
        """,
        (user_id,)
    )
    row = cursor.fetchone()
    conn.close()
    (
        approved_amount, pending_amount, rejected_amount,
        paid_amount, unpaid_amount,
        approved_count, pending_count, rejected_count,
        paid_count, unpaid_count, latest_approved_at
    ) = row
    return {
        "approved_amount": approved_amount or 0,
        "pending_amount": pending_amount or 0,
        "rejected_amount": rejected_amount or 0,
        "paid_amount": paid_amount or 0,
        "unpaid_amount": unpaid_amount or 0,
        "approved_count": approved_count or 0,
        "pending_count": pending_count or 0,
        "rejected_count": rejected_count or 0,
        "paid_count": paid_count or 0,
        "unpaid_count": unpaid_count or 0,
        "latest_approved_at": latest_approved_at,
    }

def resolve_credit_target(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.args:
        target_arg = context.args[0]
        if target_arg.startswith("@"):
            user_id = find_user_id_by_username(target_arg)
            return ("user", user_id) if user_id is not None else None
        return ("request", target_arg)
    if update.message.reply_to_message:
        remember_user(update.message.reply_to_message.from_user)
        return ("user", update.message.reply_to_message.from_user.id)
    return None

def get_credit_user_rows():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT cr.user_id, u.username, u.first_name, u.last_name,
               SUM(CASE WHEN cr.status = 'approved' THEN cr.amount ELSE 0 END) AS approved_total,
               SUM(CASE WHEN cr.status = 'pending' THEN cr.amount ELSE 0 END) AS pending_total,
               SUM(CASE WHEN cr.status = 'approved' AND COALESCE(cr.paid, 0) = 0 THEN cr.amount ELSE 0 END) AS unpaid_total,
               SUM(CASE WHEN cr.status = 'approved' THEN 1 ELSE 0 END) AS approved_count,
               SUM(CASE WHEN cr.status = 'pending' THEN 1 ELSE 0 END) AS pending_count,
               MAX(CASE WHEN cr.status = 'approved' THEN cr.decided_at ELSE NULL END) AS latest_approved_at
        FROM credit_requests cr
        LEFT JOIN users u ON u.user_id = cr.user_id
        WHERE cr.status != 'deleted'
        GROUP BY cr.user_id
        HAVING approved_total > 0 OR pending_total > 0
        ORDER BY pending_total DESC, unpaid_total DESC, approved_total DESC
        LIMIT 20
    """)
    rows = cursor.fetchall()
    conn.close()
    return rows

def get_credit_detail_rows():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT cr.request_id, cr.user_id, u.username, u.first_name, u.last_name,
               cr.amount, cr.decided_at, COALESCE(cr.paid, 0), cr.paid_at
        FROM credit_requests cr
        LEFT JOIN users u ON u.user_id = cr.user_id
        WHERE cr.status = 'approved'
        ORDER BY COALESCE(cr.paid, 0) ASC, cr.decided_at DESC, cr.request_id DESC
        LIMIT 20
    """)
    rows = cursor.fetchall()
    conn.close()
    return rows

def get_pending_credit_rows():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT cr.request_id, cr.user_id, u.username, u.first_name, u.last_name, cr.amount, cr.requested_at
        FROM credit_requests cr
        LEFT JOIN users u ON u.user_id = cr.user_id
        WHERE cr.status = 'pending'
        ORDER BY cr.request_id DESC
        LIMIT 15
    """)
    rows = cursor.fetchall()
    conn.close()
    return rows

def get_credit_request_for_action(target, allowed_statuses=None):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    if target is None:
        conn.close()
        return None

    mode, value = target
    try:
        value = int(value)
    except (TypeError, ValueError):
        conn.close()
        return None

    allowed_statuses = allowed_statuses or ["approved", "pending", "rejected"]
    placeholders = ",".join("?" for _ in allowed_statuses)
    if mode == "request":
        cursor.execute(
            f"""
            SELECT request_id, user_id, amount, status, requested_at, decided_at, COALESCE(paid, 0), paid_at
            FROM credit_requests
            WHERE request_id = ? AND status IN ({placeholders})
            """,
            [value, *allowed_statuses]
        )
    else:
        cursor.execute(
            f"""
            SELECT request_id, user_id, amount, status, requested_at, decided_at, COALESCE(paid, 0), paid_at
            FROM credit_requests
            WHERE user_id = ? AND status IN ({placeholders})
            ORDER BY request_id DESC
            LIMIT 1
            """,
            [value, *allowed_statuses]
        )
    row = cursor.fetchone()
    conn.close()
    return row

def set_credit_paid_status(request_id, paid, admin_id):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT user_id, amount FROM credit_requests WHERE request_id = ? AND status = 'approved'",
        (request_id,)
    )
    row = cursor.fetchone()
    if row is None:
        conn.close()
        return None

    paid_at = int(time.time()) if paid else None
    cursor.execute(
        """
        UPDATE credit_requests
        SET paid = ?, paid_at = ?, paid_marked_by = ?
        WHERE request_id = ? AND status = 'approved'
        """,
        (1 if paid else 0, paid_at, admin_id, request_id)
    )
    conn.commit()
    conn.close()
    return row

def delete_credit_request_record(request_id, admin_id):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT user_id, amount, status
        FROM credit_requests
        WHERE request_id = ? AND status != 'deleted'
        """,
        (request_id,)
    )
    row = cursor.fetchone()
    if row is None:
        conn.close()
        return None

    cursor.execute(
        """
        UPDATE credit_requests
        SET status = 'deleted', deleted_at = ?, deleted_by = ?
        WHERE request_id = ? AND status != 'deleted'
        """,
        (int(time.time()), admin_id, request_id)
    )
    conn.commit()
    conn.close()
    return row

async def credit_request_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    remember_user(update.effective_user)
    thread_id = update.message.message_thread_id if update.message else None

    if not context.args:
        await update.message.reply_text(
            "❌ Kullanım: `/kreditalep [Miktar]`\nÖrnek: `/kreditalep 10t`",
            parse_mode="Markdown",
            message_thread_id=thread_id
        )
        return

    amount = parse_money(context.args[0])
    if amount is None or amount <= 0:
        await update.message.reply_text("❌ Geçersiz kredi miktarı.", message_thread_id=thread_id)
        return

    request_id, existing_id = create_credit_request(user_id, amount)
    if existing_id is not None:
        await update.message.reply_text(
            f"⏳ Zaten bekleyen kredi talebin var: `#{existing_id}`\nAdmin onay/ret verince tekrar talep açabilirsin.",
            parse_mode="Markdown",
            message_thread_id=thread_id
        )
        return

    await update.message.reply_text(
        f"✅ Kredi talebin alındı.\n"
        f"Talep No: `#{request_id}`\n"
        f"Miktar: **{format_money(amount)}** Çip\n"
        f"Talep Tarihi: {format_timestamp(int(time.time()))}\n"
        f"Admin `/kredionay {request_id}` veya `/krediret {request_id}` ile karar verebilir.",
        parse_mode="Markdown",
        message_thread_id=thread_id
    )

async def approve_credit_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return

    thread_id = update.message.message_thread_id if update.message else None
    target = resolve_credit_target(update, context)
    request_row = get_pending_credit_request(target)
    if request_row is None:
        await update.message.reply_text(
            "❌ Bekleyen kredi talebi bulunamadı.\nKullanım: `/kredionay [TalepNo]` veya talep mesajına yanıt verip `/kredionay`",
            parse_mode="Markdown",
            message_thread_id=thread_id
        )
        return

    request_id, target_id, amount, _, requested_at = request_row
    approved_at = int(time.time())
    decided = decide_credit_request(request_id, "approved", update.effective_user.id)
    if decided is None:
        await update.message.reply_text("❌ Talep artık beklemede değil.", message_thread_id=thread_id)
        return

    update_balance(target_id, amount)
    update_admin_balance_totals(target_id, added=amount)
    await update.message.reply_text(
        f"✅ Kredi onaylandı.\n"
        f"Talep: `#{request_id}`\n"
        f"Kullanıcı: `{target_id}`\n"
        f"Eklenen: **{format_money(amount)}** Çip\n"
        f"Talep Tarihi: {format_timestamp(requested_at)}\n"
        f"Alındığı Tarih: {format_timestamp(approved_at)}",
        parse_mode="Markdown",
        message_thread_id=thread_id
    )

async def reject_credit_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return

    thread_id = update.message.message_thread_id if update.message else None
    target = resolve_credit_target(update, context)
    request_row = get_pending_credit_request(target)
    if request_row is None:
        await update.message.reply_text(
            "❌ Bekleyen kredi talebi bulunamadı.\nKullanım: `/krediret [TalepNo]` veya talep mesajına yanıt verip `/krediret`",
            parse_mode="Markdown",
            message_thread_id=thread_id
        )
        return

    request_id, target_id, amount, _, requested_at = request_row
    decided = decide_credit_request(request_id, "rejected", update.effective_user.id)
    if decided is None:
        await update.message.reply_text("❌ Talep artık beklemede değil.", message_thread_id=thread_id)
        return

    await update.message.reply_text(
        f"🚫 Kredi reddedildi.\n"
        f"Talep: `#{request_id}`\n"
        f"Kullanıcı: `{target_id}`\n"
        f"Miktar: **{format_money(amount)}** Çip\n"
        f"Talep Tarihi: {format_timestamp(requested_at)}",
        parse_mode="Markdown",
        message_thread_id=thread_id
    )

async def credit_list_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return

    thread_id = update.message.message_thread_id if update.message else None
    pending_rows = get_pending_credit_rows()
    credit_rows = get_credit_user_rows()
    credit_detail_rows = get_credit_detail_rows()

    pending_lines = []
    for request_id, user_id, username, first_name, last_name, amount, requested_at in pending_rows:
        display_name = escape_markdown(get_user_display_name(user_id, username, first_name, last_name))
        pending_lines.append(f"`#{request_id}` {display_name} (`{user_id}`) -> **{format_money(amount)}** | Talep: {format_timestamp(requested_at)}")

    detail_lines = []
    for request_id, user_id, username, first_name, last_name, amount, decided_at, paid, paid_at in credit_detail_rows:
        display_name = escape_markdown(get_user_display_name(user_id, username, first_name, last_name))
        paid_text = f"Ödendi ({format_timestamp(paid_at)})" if paid else "Ödenmedi"
        detail_lines.append(
            f"`#{request_id}` {display_name} (`{user_id}`) -> **{format_money(amount)}** | Alındı: {format_timestamp(decided_at)} | {paid_text}"
        )

    credit_lines = []
    for user_id, username, first_name, last_name, approved_total, pending_total, unpaid_total, approved_count, pending_count, latest_approved_at in credit_rows:
        display_name = escape_markdown(get_user_display_name(user_id, username, first_name, last_name))
        credit_lines.append(
            f"{display_name} (`{user_id}`) | Onaylı: **{format_money(approved_total or 0)}** ({approved_count or 0}) | Ödenmedi: **{format_money(unpaid_total or 0)}** | Bekleyen: **{format_money(pending_total or 0)}** ({pending_count or 0}) | Son: {format_timestamp(latest_approved_at)}"
        )

    text = (
        f"💳 **KREDİ PANELİ**\n\n"
        f"**Bekleyen Talepler**\n"
        f"{chr(10).join(pending_lines) if pending_lines else 'Bekleyen talep yok.'}\n\n"
        f"**Onaylı Kredi Kayıtları**\n"
        f"{chr(10).join(detail_lines) if detail_lines else 'Onaylı kredi kaydı yok.'}\n\n"
        f"**Kullanıcı Özeti**\n"
        f"{chr(10).join(credit_lines) if credit_lines else 'Henüz kredi alan yok.'}\n\n"
        f"Onay: `/kredionay [TalepNo]` | Ret: `/krediret [TalepNo]`\n"
        f"Ödendi: `/krediodendi [TalepNo]` | Ödenmedi: `/krediodenmedi [TalepNo]` | Sil: `/kredisil [TalepNo]`"
    )
    await update.message.reply_text(text, parse_mode="Markdown", message_thread_id=thread_id)

async def mark_credit_paid_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return

    thread_id = update.message.message_thread_id if update.message else None
    target = resolve_credit_target(update, context)
    request_row = get_credit_request_for_action(target, ["approved"])
    if request_row is None:
        await update.message.reply_text(
            "❌ Onaylı kredi kaydı bulunamadı.\nKullanım: `/krediodendi [TalepNo]`",
            parse_mode="Markdown",
            message_thread_id=thread_id
        )
        return

    request_id, target_id, amount, _, _, decided_at, _, _ = request_row
    result = set_credit_paid_status(request_id, True, update.effective_user.id)
    if result is None:
        await update.message.reply_text("❌ Kredi işaretlenemedi.", message_thread_id=thread_id)
        return

    await update.message.reply_text(
        f"✅ Kredi ödendi olarak işaretlendi.\n"
        f"Talep: `#{request_id}`\n"
        f"Kullanıcı: `{target_id}`\n"
        f"Miktar: **{format_money(amount)}** Çip\n"
        f"Alındı: {format_timestamp(decided_at)}\n"
        f"Ödendi: {format_timestamp(int(time.time()))}",
        parse_mode="Markdown",
        message_thread_id=thread_id
    )

async def mark_credit_unpaid_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return

    thread_id = update.message.message_thread_id if update.message else None
    target = resolve_credit_target(update, context)
    request_row = get_credit_request_for_action(target, ["approved"])
    if request_row is None:
        await update.message.reply_text(
            "❌ Onaylı kredi kaydı bulunamadı.\nKullanım: `/krediodenmedi [TalepNo]`",
            parse_mode="Markdown",
            message_thread_id=thread_id
        )
        return

    request_id, target_id, amount, _, _, decided_at, _, _ = request_row
    result = set_credit_paid_status(request_id, False, update.effective_user.id)
    if result is None:
        await update.message.reply_text("❌ Kredi işaretlenemedi.", message_thread_id=thread_id)
        return

    await update.message.reply_text(
        f"↩️ Kredi ödenmedi olarak işaretlendi.\n"
        f"Talep: `#{request_id}`\n"
        f"Kullanıcı: `{target_id}`\n"
        f"Miktar: **{format_money(amount)}** Çip\n"
        f"Alındı: {format_timestamp(decided_at)}",
        parse_mode="Markdown",
        message_thread_id=thread_id
    )

async def delete_credit_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return

    thread_id = update.message.message_thread_id if update.message else None
    target = resolve_credit_target(update, context)
    request_row = get_credit_request_for_action(target, ["approved", "pending", "rejected"])
    if request_row is None:
        await update.message.reply_text(
            "❌ Silinecek kredi kaydı bulunamadı.\nKullanım: `/kredisil [TalepNo]`",
            parse_mode="Markdown",
            message_thread_id=thread_id
        )
        return

    request_id, target_id, amount, status, requested_at, decided_at, _, _ = request_row
    result = delete_credit_request_record(request_id, update.effective_user.id)
    if result is None:
        await update.message.reply_text("❌ Kredi kaydı silinemedi.", message_thread_id=thread_id)
        return

    date_label = decided_at if status == "approved" else requested_at
    await update.message.reply_text(
        f"🗑️ Kredi kaydı listeden silindi.\n"
        f"Talep: `#{request_id}`\n"
        f"Kullanıcı: `{target_id}`\n"
        f"Miktar: **{format_money(amount)}** Çip\n"
        f"Tarih: {format_timestamp(date_label)}\n"
        f"Not: Bakiye değiştirilmedi.",
        parse_mode="Markdown",
        message_thread_id=thread_id
    )

async def add_balance_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    thread_id = update.message.message_thread_id if update.message else None
    target_id, amount = get_target_and_amount(update, context)
    if target_id is None or amount is None or amount <= 0: 
        await update.message.reply_text("❌ Hatalı kullanım. Örn: `/bakiyeekle 123456789 10t`", message_thread_id=thread_id)
        return

    update_balance(target_id, amount)
    update_admin_balance_totals(target_id, added=amount)
    await update.message.reply_text(f"✅ `{target_id}` ID'li kullanıcıya **{format_money(amount)}** çip eklendi.", parse_mode="Markdown", message_thread_id=thread_id)

async def remove_balance_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    thread_id = update.message.message_thread_id if update.message else None
    target_id, amount = get_target_and_amount(update, context)
    if target_id is None or amount is None or amount <= 0: 
        await update.message.reply_text("❌ Hatalı kullanım. Örn: `/bakiyesil 123456789 5t`", message_thread_id=thread_id)
        return

    update_balance(target_id, -amount)
    update_admin_balance_totals(target_id, removed=amount)
    await update.message.reply_text(f"📉 `{target_id}` ID'li kullanıcıdan **{format_money(amount)}** çip silindi.", parse_mode="Markdown", message_thread_id=thread_id)

async def send_admin_panel(update: Update, game_types, panel_title):
    if update.effective_user.id not in ADMIN_IDS: return
    thread_id = update.message.message_thread_id if update.message else None
    
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(user_id), SUM(balance) FROM users")
    user_stats = cursor.fetchone()
    
    placeholders = ",".join("?" for _ in game_types)
    cursor.execute(
        f"SELECT game_type, total_games, winning_games, total_wagered, total_paid FROM game_stats WHERE game_type IN ({placeholders})",
        game_types
    )
    game_rows = cursor.fetchall()
    conn.close()
    
    toplam_oyuncu = user_stats[0] or 0
    piyasadaki_cip = user_stats[1] or 0
    house_state = get_house_state()
    limit_usage = (
        house_state["total_paid"] / house_state["payout_limit"] * 100
        if house_state["payout_limit"] > 0 else 0
    )
    
    panel_text = (
        f"📊 **{panel_title}** 📊\n\n"
        f"👥 **Genel Bilgiler:**\n"
        f"• Kayıtlı Oyuncu: {toplam_oyuncu}\n"
        f"• Piyasadaki Toplam Çip: {format_money(piyasadaki_cip)}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
    )

    panel_text += (
        f"Toplam Yatirilan: {format_money(house_state['total_added'])}\n"
        f"%80 Odeme Limiti: {format_money(house_state['payout_limit'])} | Kullanim: %{limit_usage:.1f}\n\n"
    )

    t_oyun_genel, k_oyun_genel, t_bahis_genel, t_odenen_genel = 0, 0, 0, 0

    for row in game_rows:
        g_type, g_total, g_win, g_wag, g_paid = row
        t_oyun_genel += g_total
        k_oyun_genel += g_win
        t_bahis_genel += g_wag
        t_odenen_genel += g_paid
        
        g_win_rate = (g_win / g_total * 100) if g_total > 0 else 0
        g_rtp = (g_paid / g_wag * 100) if g_wag > 0 else 0
        g_net = g_wag - g_paid
        g_loss = g_total - g_win
        
        icon = {
            "slot": "🎰",
            "dart": "🎯",
            "bowling": "🎳",
            "atyarisi": "🐎",
            "roulette": "🎡",
            "lcdp": "🏛️",
            "aviator": "✈️",
            "pvp_zar": "🎲",
            "pvp_yirmibir": "🃏",
            "pvp_xox": "❌⭕",
        }.get(g_type, "🎮")
        game_label = {
            "slot": "SLOT",
            "dart": "DART",
            "bowling": "BOWLING",
            "atyarisi": "AT YARIŞI",
            "roulette": "RULET",
            "lcdp": "LCDP",
            "aviator": "AVIATOR",
            "pvp_zar": "1V1 ZAR",
            "pvp_yirmibir": "1V1 21",
            "pvp_xox": "1V1 XOX",
        }.get(g_type, g_type.upper().replace("_", " "))
        
        panel_text += (
            f"{icon} **{game_label} İSTATİSTİKLERİ:**\n"
            f"Oyun: {g_total} | Kazandı/Kaybetti: {g_win}/{g_loss} | Kazanç: %{g_win_rate:.1f} | RTP: %{g_rtp:.1f}\n"
            f"Kasa Karı: {format_money(g_net)}\n\n"
        )

    win_rate_genel = (k_oyun_genel / t_oyun_genel * 100) if t_oyun_genel > 0 else 0
    rtp_genel = (t_odenen_genel / t_bahis_genel * 100) if t_bahis_genel > 0 else 0
    net_kar_genel = t_bahis_genel - t_odenen_genel
    kayip_oyun_genel = t_oyun_genel - k_oyun_genel

    panel_text += (
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🏦 **GENEL KASA DURUMU:**\n"
        f"• Kazandı/Kaybetti: {k_oyun_genel}/{kayip_oyun_genel}\n"
        f"• Toplam Dönen: {format_money(t_bahis_genel)}\n"
        f"• Toplam Dağıtılan: {format_money(t_odenen_genel)}\n"
        f"• **Toplam Kasa Karı:** {format_money(net_kar_genel)}\n"
        f"• **Genel Win Rate:** %{win_rate_genel:.1f}\n"
        f"• **Genel RTP:** %{rtp_genel:.1f}"
    )

    await update.message.reply_text(panel_text, parse_mode="Markdown", message_thread_id=thread_id)

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message_text = update.message.text.strip() if update.message and update.message.text else ""
    if (context.args and context.args[0].strip() == "1") or message_text.lower().replace("/", "").replace(" ", "") == "panel1":
        await admin_pvp_panel(update, context)
        return
    await send_admin_panel(update, NORMAL_GAME_TYPES, "NORMAL OYUNLAR PANELİ")

async def admin_pvp_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_admin_panel(update, PVP_GAME_TYPES, "1V1 OYUNLAR PANELİ")

async def user_info_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    is_admin = update.effective_user.id in ADMIN_IDS
    thread_id = update.message.message_thread_id if update.message else None
    target_id = get_info_target(update, context) if is_admin else update.effective_user.id
    remember_user(update.effective_user)

    if target_id is None:
        await update.message.reply_text(
            "❌ Kullanım: `/bilgi [ID/@kullanıcı]`\n"
            "Adminsen kullanıcının mesajına yanıt verip `/bilgi` de yazabilirsin.",
            parse_mode="Markdown",
            message_thread_id=thread_id
        )
        return

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT user_id, balance, username, first_name, last_name, total_added, total_removed FROM users WHERE user_id = ?",
        (target_id,)
    )
    user_row = cursor.fetchone()

    if user_row is None:
        conn.close()
        await update.message.reply_text("❌ Kullanıcı veritabanında bulunamadı.", message_thread_id=thread_id)
        return

    cursor.execute("""
        SELECT game_type, total_games, winning_games, total_wagered, total_paid
        FROM user_game_stats
        WHERE user_id = ?
    """, (target_id,))
    stat_rows = {row[0]: row[1:] for row in cursor.fetchall()}
    conn.close()

    user_id, balance, username, first_name, last_name, total_added, total_removed = user_row
    display_name = escape_markdown(get_user_display_name(user_id, username, first_name, last_name))
    total_added = total_added or 0
    total_removed = total_removed or 0
    credit_summary = get_credit_summary(user_id)

    total_games = 0
    total_wins = 0
    total_wagered = 0
    total_paid = 0
    detail_text = ""

    for game_type in ACTIVE_GAME_TYPES:
        games, wins, wagered, paid = stat_rows.get(game_type, (0, 0, 0, 0))
        total_games += games
        total_wins += wins
        total_wagered += wagered
        total_paid += paid
        win_rate = (wins / games * 100) if games else 0
        losses = games - wins
        net = wagered - paid
        icon = {
            "slot": "🎰",
            "dart": "🎯",
            "bowling": "🎳",
            "atyarisi": "🐎",
            "roulette": "🎡",
            "lcdp": "🏛️",
            "aviator": "✈️",
            "pvp_zar": "🎲",
            "pvp_yirmibir": "🃏",
            "pvp_xox": "❌⭕",
        }.get(game_type, "🎮")
        game_label = {
            "slot": "SLOT",
            "dart": "DART",
            "bowling": "BOWLING",
            "atyarisi": "AT YARIŞI",
            "roulette": "RULET",
            "lcdp": "LCDP",
            "aviator": "AVIATOR",
            "pvp_zar": "1V1 ZAR",
            "pvp_yirmibir": "1V1 21",
            "pvp_xox": "1V1 XOX",
        }.get(game_type, game_type.upper().replace("_", " "))
        detail_text += (
            f"{icon} **{game_label}**\n"
            f"Oyun: {games} | Kazandı/Kaybetti: {wins}/{losses} | Kazanç: %{win_rate:.1f}\n"
            f"Yatırılan/Oynanan: {format_money(wagered)} | Kazanılan: {format_money(paid)}\n"
            f"Kasa Net: {format_money(net)}\n\n"
        )

    win_rate_total = (total_wins / total_games * 100) if total_games else 0
    total_losses = total_games - total_wins
    net_total = total_wagered - total_paid

    info_text = (
        f"👤 **KULLANICI BİLGİ PANELİ**\n\n"
        f"İsim: **{display_name}**\n"
        f"ID: `{user_id}`\n"
        f"💰 Bakiye: **{format_money(balance)}** Çip\n"
        f"➕ Admin Eklenen: {format_money(total_added)}\n"
        f"➖ Admin Silinen: {format_money(total_removed)}\n\n"
        f"💳 **Kredi Bilgisi**\n"
        f"Onaylı: **{format_money(credit_summary['approved_amount'])}** ({credit_summary['approved_count']})\n"
        f"Ödenen: **{format_money(credit_summary['paid_amount'])}** ({credit_summary['paid_count']})\n"
        f"Ödenmeyen: **{format_money(credit_summary['unpaid_amount'])}** ({credit_summary['unpaid_count']})\n"
        f"Bekleyen: **{format_money(credit_summary['pending_amount'])}** ({credit_summary['pending_count']})\n"
        f"Reddedilen: **{format_money(credit_summary['rejected_amount'])}** ({credit_summary['rejected_count']})\n"
        f"Son Alınan Kredi: **{format_timestamp(credit_summary['latest_approved_at'])}**\n\n"
        f"📊 **Genel Oyun Özeti**\n"
        f"Toplam Oyun: {total_games}\n"
        f"Kazandı/Kaybetti: {total_wins}/{total_losses}\n"
        f"Toplam Kazanma: {total_wins} (%{win_rate_total:.1f})\n"
        f"Toplam Yatırılan/Oynanan: {format_money(total_wagered)}\n"
        f"Toplam Kazanılan: {format_money(total_paid)}\n"
        f"Kasa Net: **{format_money(net_total)}**\n\n"
        f"🎮 **Oyun Bazlı Detay**\n"
        f"{detail_text}"
    )

    await update.message.reply_text(info_text, parse_mode="Markdown", message_thread_id=thread_id)

async def reset_panel_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    thread_id = update.message.message_thread_id if update.message else None
    
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("UPDATE game_stats SET total_games=0, winning_games=0, total_wagered=0, total_paid=0")
    cursor.execute("UPDATE user_game_stats SET total_games=0, winning_games=0, total_wagered=0, total_paid=0")
    conn.commit()
    conn.close()
    
    await update.message.reply_text("✅ **Tüm oyun istatistikleri ve kasa geçmişi sıfırlandı!**", parse_mode="Markdown", message_thread_id=thread_id)


async def broadcast_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    thread_id = update.message.message_thread_id if update.message else None
    if not context.args: return
        
    broadcast_msg = "📢 **ADMİN DUYURUSU** 📢\n\n" + " ".join(context.args)
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM users")
    users = cursor.fetchall()
    conn.close()
    
    await update.message.reply_text(f"⏳ {len(users)} kişiye duyuru gönderiliyor...", message_thread_id=thread_id)
    basarili = 0
    for user in users:
        try:
            await context.bot.send_message(chat_id=user[0], text=broadcast_msg, parse_mode="Markdown")
            basarili += 1
        except Exception: pass
            
    await update.message.reply_text(f"✅ Tamamlandı! Ulaşılan: {basarili}/{len(users)}", message_thread_id=thread_id)


# --- 6. ANA ÇALIŞTIRICI ---
async def main():
    init_db()
    application = (
        Application.builder()
        .token(TOKEN)
        .connection_pool_size(32)
        .pool_timeout(1.0)
        .connect_timeout(3.0)
        .read_timeout(6.0)
        .write_timeout(6.0)
        .get_updates_connection_pool_size(8)
        .get_updates_pool_timeout(1.0)
        .get_updates_connect_timeout(3.0)
        .get_updates_read_timeout(30.0)
        .get_updates_write_timeout(6.0)
        .build()
    )

    try:
        await application.bot.delete_webhook(drop_pending_updates=True)
    except Exception:
        pass

    application.add_handler(MessageHandler(filters.COMMAND, maintenance_gate), group=-1)

    # Oyuncu Komutları
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("slot", play_slot))
    application.add_handler(CommandHandler("dart", play_dart))
    application.add_handler(CommandHandler("bowling", play_bowling))
    application.add_handler(CommandHandler("atyarisi", play_horse_race))
    application.add_handler(CommandHandler("rulet", play_roulette))
    application.add_handler(CommandHandler("lcdp", play_lcdp))
    application.add_handler(CommandHandler("lcdpfs", buy_lcdp_free_spin))
    application.add_handler(CommandHandler("zar", play_pvp_dice))
    application.add_handler(CommandHandler("yirmibir", play_pvp_21))
    application.add_handler(CommandHandler("21", play_pvp_21))
    application.add_handler(CommandHandler("xox", start_xox6))
    application.add_handler(CommandHandler("oyna", join_pvp_command))
    application.add_handler(CommandHandler("cek", pvp_21_hit_command))
    application.add_handler(CommandHandler("kal", pvp_21_stand_command))
    application.add_handler(CommandHandler("aviator", play_aviator))
    application.add_handler(CommandHandler("av", play_aviator))
    application.add_handler(CommandHandler("avbaslat", force_start_aviator_admin))
    application.add_handler(CommandHandler("aviatorbaslat", force_start_aviator_admin))
    application.add_handler(CommandHandler("aktifoyun", active_aviator_report_admin))
    application.add_handler(CommandHandler("avdurum", active_aviator_report_admin))
    application.add_handler(CommandHandler("kes", cut_aviator_admin))
    application.add_handler(CommandHandler("avmod", aviator_mod_admin))
    application.add_handler(CommandHandler("avpromo", aviator_promo_admin))
    application.add_handler(CommandHandler("avvoid", aviator_void_admin))
    application.add_handler(CallbackQueryHandler(aviator_cashout_callback, pattern=r"^aviator_cashout:"))
    application.add_handler(CallbackQueryHandler(pvp_21_hit_callback, pattern=r"^pvp21_hit:"))
    application.add_handler(CallbackQueryHandler(pvp_21_stand_callback, pattern=r"^pvp21_stand:"))
    application.add_handler(CallbackQueryHandler(join_pvp_callback, pattern=r"^pvp_join:"))
    application.add_handler(CallbackQueryHandler(xox6_callback, pattern=r"^xox6:"))
    application.add_handler(MessageHandler(filters.Regex(r"(?i)^lcdp$"), play_lcdp))
    application.add_handler(MessageHandler(filters.Regex(r"(?i)^lcdp\s+\S+"), play_lcdp))
    application.add_handler(MessageHandler(filters.Regex(r"(?i)^lcdpfs$"), buy_lcdp_free_spin))
    application.add_handler(MessageHandler(filters.Regex(r"(?i)^lcdpfs\s+\S+"), buy_lcdp_free_spin))
    application.add_handler(MessageHandler(filters.Regex(r"(?i)^(aviator|av)$"), play_aviator))
    application.add_handler(MessageHandler(filters.Regex(r"(?i)^(aviator|av)\s+\S+"), play_aviator))
    application.add_handler(MessageHandler(filters.Regex(r"(?i)^/çek(@\w+)?(?:\s|$)"), pvp_21_hit_command))
    application.add_handler(MessageHandler(filters.Regex(r"(?i)^/?panel(?:@\w+)?\s*1\s*$|^/?panel1(?:@\w+)?\s*$"), admin_pvp_panel))
    application.add_handler(CommandHandler("top10", top_players))
    application.add_handler(CommandHandler("bakiye", bakiye))
    application.add_handler(CommandHandler("kreditalep", credit_request_command))
    application.add_handler(CommandHandler("transfer", transfer_command))
    application.add_handler(CommandHandler("komut", help_command))
    application.add_handler(CommandHandler("admin", admin_help_command))
    application.add_handler(CommandHandler("test", test_command))
    
    # Admin Komutları
    application.add_handler(CommandHandler("kredi", credit_list_admin))
    application.add_handler(CommandHandler("kredionay", approve_credit_admin))
    application.add_handler(CommandHandler("krediret", reject_credit_admin))
    application.add_handler(CommandHandler("krediodendi", mark_credit_paid_admin))
    application.add_handler(CommandHandler("krediodenmedi", mark_credit_unpaid_admin))
    application.add_handler(CommandHandler("kredisil", delete_credit_admin))
    application.add_handler(CommandHandler("bakiyeekle", add_balance_admin))
    application.add_handler(CommandHandler("bakiyesil", remove_balance_admin))
    application.add_handler(CommandHandler("panel", admin_panel))
    application.add_handler(CommandHandler("panel1", admin_pvp_panel))
    application.add_handler(CommandHandler("mod", house_mode_admin))
    application.add_handler(CommandHandler("bilgi", user_info_admin))
    application.add_handler(CommandHandler("panelsifirla", reset_panel_admin))
    application.add_handler(CommandHandler("bakim", maintenance_admin))
    application.add_handler(CommandHandler("duyuru", broadcast_admin))

    print(f"📁 Veritabanı: {DB_NAME}")
    print("🎰 Casino botu aktif... Oyun bazlı istatistikler devrede. (Polling başlatılıyor)")
    
    await application.initialize()
    await application.start()
    application.create_task(run_aviator_scheduler(application))
    await application.updater.start_polling(drop_pending_updates=True)
    
    while True:
        await asyncio.sleep(3600)

if __name__ == "__main__":
    try:
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    except AttributeError:
        pass
        
    asyncio.run(main())
