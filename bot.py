import sqlite3
import asyncio
import warnings
import random
import os
import time
from pathlib import Path
from telegram import Update
from telegram.ext import Application, ApplicationHandlerStop, CommandHandler, ContextTypes, MessageHandler, filters

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

# --- OYUN LİMİTLERİ ---
MIN_BET_DART_BOWL = parse_money("10t")
MAX_BET_DART_BOWL = parse_money("100t")
MIN_BET_SLOT = parse_money("10t")
MAX_BET_SLOT = parse_money("100t")
MIN_BET_HORSE = parse_money("10t")
MAX_BET_HORSE = parse_money("100t")
MIN_BET_ROULETTE = parse_money("10t")
MAX_BET_ROULETTE = parse_money("100t")
MIN_BET_OLYMPOS = parse_money("10t")
MAX_BET_OLYMPOS = parse_money("100t")
HORSE_CONFIG = {
    1: {"name": "Süleyman", "chance": 17, "multiplier": 5},
    2: {"name": "Fırtına", "chance": 16, "multiplier": 6},
    3: {"name": "Rüzgar", "chance": 14, "multiplier": 6.5},
    4: {"name": "Kara İnci", "chance": 13, "multiplier": 7.5},
    5: {"name": "Kasırga", "chance": 12, "multiplier": 8},
    6: {"name": "Gölge", "chance": 10, "multiplier": 9},
    7: {"name": "Morning", "chance": 8, "multiplier": 20},
    8: {"name": "Roket", "chance": 10, "multiplier": 9},
}
ROULETTE_CONFIG = {
    "kirmizi": {"label": "Kırmızı", "chance": 48, "multiplier": 1.9, "icon": "🔴"},
    "kırmızı": {"label": "Kırmızı", "chance": 48, "multiplier": 1.9, "icon": "🔴"},
    "siyah": {"label": "Siyah", "chance": 48, "multiplier": 1.9, "icon": "⚫"},
    "yesil": {"label": "Yeşil", "chance": 2, "multiplier": 35, "icon": "🟢"},
    "yeşil": {"label": "Yeşil", "chance": 2, "multiplier": 35, "icon": "🟢"},
}
ROULETTE_OUTCOMES = [
    {"key": "kirmizi", "label": "Kırmızı", "chance": 48, "icon": "🔴"},
    {"key": "siyah", "label": "Siyah", "chance": 48, "icon": "⚫"},
    {"key": "yesil", "label": "Yeşil", "chance": 2, "icon": "🟢"},
]
OLYMPOS_SYMBOLS = ["⚡", "👑", "💎", "🔥", "🛡️", "🏺", "🍇", "💍"]
OLYMPOS_MULTIPLIERS = [2, 3, 5, 10, 25, 50, 100]
ACTIVE_GAME_TYPES = ['slot', 'dart', 'bowling', 'atyarisi', 'roulette']
HORSE_FINISH_LINE = 14
GAME_COOLDOWN_SECONDS = 1
TELEGRAM_MESSAGE_TIMEOUT_SECONDS = 5
MAINTENANCE_MODE = False
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
        CREATE TABLE IF NOT EXISTS free_game_stats (
            game_type TEXT PRIMARY KEY,
            total_games INTEGER DEFAULT 0,
            winning_games INTEGER DEFAULT 0
        )
    """)
    cursor.execute("INSERT OR IGNORE INTO free_game_stats (game_type) VALUES (?)", ("olympos1",))
    
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

def update_free_game_stats(game_type, is_win):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("INSERT OR IGNORE INTO free_game_stats (game_type) VALUES (?)", (game_type,))
    cursor.execute(
        """
        UPDATE free_game_stats
        SET total_games = total_games + 1,
            winning_games = winning_games + ?
        WHERE game_type = ?
        """,
        (1 if is_win else 0, game_type)
    )
    cursor.execute(
        "SELECT total_games, winning_games FROM free_game_stats WHERE game_type = ?",
        (game_type,)
    )
    total_games, winning_games = cursor.fetchone()
    conn.commit()
    conn.close()
    return total_games, winning_games

def get_free_game_stats(game_type):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("INSERT OR IGNORE INTO free_game_stats (game_type) VALUES (?)", (game_type,))
    cursor.execute(
        "SELECT total_games, winning_games FROM free_game_stats WHERE game_type = ?",
        (game_type,)
    )
    total_games, winning_games = cursor.fetchone()
    conn.commit()
    conn.close()
    return total_games, winning_games

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
        f"• `/olympos` -> Bahissiz Olympos oynar. 🏛️\n"
        f"• `/olympos1` -> Olympos genel istatistiğini gösterir. 📊\n\n"
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

    outcome = random.choices(
        ROULETTE_OUTCOMES,
        weights=[item["chance"] for item in ROULETTE_OUTCOMES],
        k=1
    )[0]

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

def render_olympos_grid(grid):
    return "\n".join(" ".join(row) for row in grid)

def draw_olympos_grid():
    return [
        [random.choice(OLYMPOS_SYMBOLS) for _ in range(6)]
        for _ in range(5)
    ]

def get_olympos_base_multiplier(match_count):
    if match_count >= 15:
        return 25
    if match_count >= 12:
        return 8
    if match_count >= 10:
        return 3
    if match_count >= 8:
        return 1.5
    return 0

async def play_olympos_free(update: Update, context: ContextTypes.DEFAULT_TYPE):
    remember_user(update.effective_user)
    thread_id = update.message.message_thread_id if update.message else None

    await update.message.reply_text("⚡ **OLYMPOS KAPILARI AÇILIYOR...** ⚡", parse_mode="Markdown", message_thread_id=thread_id)
    for spin_text in ["☁️ Bulutlar dağılıyor...", "⚡ Çarpanlar yükseliyor...", "🏛️ Tanrılar sonucu seçiyor..."]:
        await asyncio.sleep(0.45)
        await update.message.reply_text(spin_text, message_thread_id=thread_id)

    grid = draw_olympos_grid()
    counts = {symbol: sum(row.count(symbol) for row in grid) for symbol in OLYMPOS_SYMBOLS}
    best_symbol, best_count = max(counts.items(), key=lambda item: item[1])
    base_multiplier = get_olympos_base_multiplier(best_count)

    bonus_text = ""
    total_multiplier = base_multiplier
    if base_multiplier > 0 and random.randint(1, 100) <= 25:
        bonus_multiplier = random.choice(OLYMPOS_MULTIPLIERS)
        total_multiplier *= bonus_multiplier
        bonus_text = f"\n⚡ **Bonus Çarpan:** x{bonus_multiplier}"

    if total_multiplier > 0:
        update_free_game_stats("olympos1", True)
        result_text = (
            f"🏛️ **OLYMPOS PATLADI!**\n"
            f"En iyi sembol: {best_symbol} x{best_count}\n"
            f"Sanal kazanç: **x{total_multiplier:g}**{bonus_text}\n"
            f"_Bahissiz mod: bakiye değişmedi._"
        )
    else:
        update_free_game_stats("olympos1", False)
        result_text = (
            f"🌫️ **Olympos sessiz kaldı.**\n"
            f"En iyi sembol: {best_symbol} x{best_count}\n"
            f"Kazanç için en az 8 aynı sembol gerekiyordu.\n"
            f"_Bahissiz mod: bakiye değişmedi._"
        )

    await update.message.reply_text(
        f"```\n{render_olympos_grid(grid)}\n```\n{result_text}",
        parse_mode="Markdown",
        message_thread_id=thread_id
    )

async def olympوس_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    remember_user(update.effective_user)
    thread_id = update.message.message_thread_id if update.message else None
    total_games, winning_games = get_free_game_stats("olympos1")
    losing_games = total_games - winning_games
    win_rate = (winning_games / total_games * 100) if total_games else 0

    await update.message.reply_text(
        f"📊 **OLYMPOS GENEL İSTATİSTİK**\n\n"
        f"Toplam Oyun: **{total_games}**\n"
        f"Kazandı/Kaybetti: **{winning_games}/{losing_games}**\n"
        f"Kazanma Oranı: **%{win_rate:.1f}**\n\n"
        f"_Bu istatistik bahissiz Olympos içindir; kasa paneline dahil değildir._",
        parse_mode="Markdown",
        message_thread_id=thread_id
    )

async def olympus_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    remember_user(update.effective_user)
    thread_id = update.message.message_thread_id if update.message else None
    total_games, winning_games = get_free_game_stats("olympos1")
    losing_games = total_games - winning_games
    win_rate = (winning_games / total_games * 100) if total_games else 0

    await update.message.reply_text(
        f"📊 **OLYMPOS GENEL İSTATİSTİK**\n\n"
        f"Toplam Oyun: **{total_games}**\n"
        f"Kazandı/Kaybetti: **{winning_games}/{losing_games}**\n"
        f"Kazanma Oranı: **%{win_rate:.1f}**\n\n"
        f"_Bu istatistik bahissiz Olympos içindir; kasa paneline dahil değildir._",
        parse_mode="Markdown",
        message_thread_id=thread_id
    )

def render_horse_race(positions):
    lines = []
    for horse in HORSE_CONFIG:
        pos = min(positions[horse], HORSE_FINISH_LINE)
        track = "." * pos + "H" + "." * (HORSE_FINISH_LINE - pos) + "|"
        lines.append(f"{horse}: {track}")
    return "\n".join(lines)

def format_horse_options():
    return "\n".join(
        f"{horse}. At: %{config['chance']} | x{config['multiplier']:g}"
        for horse, config in HORSE_CONFIG.items()
    )

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

# 🐎 AT YARIŞI OYUNU
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
            f"Min: {format_money(MIN_BET_HORSE)} | Max: {format_money(MAX_BET_HORSE)} | At: 1-8\n\n"
            f"🎯 **Oranlar ve Çarpanlar:**\n{format_horse_options()}",
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
        horses = list(HORSE_CONFIG.keys())
        weights = [HORSE_CONFIG[horse]["chance"] for horse in horses]
        winner = random.choices(horses, weights=weights, k=1)[0]

        is_win = winner == selected_horse
        multiplier = HORSE_CONFIG[selected_horse]["multiplier"]
        win_amount = int(bet * multiplier) if is_win else 0

        if is_win:
            result_text = f"🎉 **TEBRİKLER!** #{winner} {horse_names[winner]} kazandı. Bahsinin **x{multiplier:g}** katını aldın! (+{format_money(win_amount)})"
        else:
            result_text = f"😔 **Kaybettin.** Kazanan at: #{winner} {horse_names[winner]} (-{format_money(bet)})"

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
        f"  Kırmızı/Siyah: %49 x1.9 | Yeşil: %2 x35\n\n"
        f"• `/olympos` - Bahissiz çarpanlı Olympos eğlence modu\n"
        f"• `/olympos1` - Herkesin Olympos genel istatistiğini gösterir\n\n"
        f"💡 *Bahislerde t, kt kısaltmalarını kullanabilirsin. (Örn: /slot 20t)*\n\n"
        f"🛠️ **Genel:**\n"
        f"• `/bakiye` - Mevcut çipini gösterir\n"
        f"• `/top10` - En zengin 10 oyuncuyu listeler\n"
        f"• `/bilgi` - Kendi oyun ve bakiye istatistiklerini gösterir\n"
        f"• `/transfer [ID/@kullanıcı] [Miktar]` - Başka kullanıcıya çip gönderir\n"
    )
    
    if user_id in ADMIN_IDS:
        help_text += (
            f"\n⚡ **[ADMİN ÖZEL] Yönetim Komutları:**\n"
            f"• `/bakiyeekle [ID/Yanıt] [Miktar]`\n"
            f"• `/bakiyesil [ID/Yanıt] [Miktar]`\n"
            f"• `/panel` - Kasa istatistiklerini ve oyun bazlı verileri gösterir\n"
            f"• `/bilgi [ID/@kullanıcı]` - Başka kullanıcıların istatistiklerini gösterir\n"
            f"• `/panelsifirla` - Kasa istatistiklerini temizler\n"
            f"• `/bakim ac|kapat|durum` - Bot bakım modunu yönetir\n"
            f"• `/duyuru [Mesaj]` - Herkese mesaj atar\n"
        )
        
    await update.message.reply_text(help_text, parse_mode="Markdown", message_thread_id=thread_id)


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

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    thread_id = update.message.message_thread_id if update.message else None
    
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(user_id), SUM(balance) FROM users")
    user_stats = cursor.fetchone()
    
    placeholders = ",".join("?" for _ in ACTIVE_GAME_TYPES)
    cursor.execute(
        f"SELECT game_type, total_games, winning_games, total_wagered, total_paid FROM game_stats WHERE game_type IN ({placeholders})",
        ACTIVE_GAME_TYPES
    )
    game_rows = cursor.fetchall()
    conn.close()
    
    toplam_oyuncu = user_stats[0] or 0
    piyasadaki_cip = user_stats[1] or 0
    
    panel_text = (
        f"📊 **CASINO ADMİN PANELİ** 📊\n\n"
        f"👥 **Genel Bilgiler:**\n"
        f"• Kayıtlı Oyuncu: {toplam_oyuncu}\n"
        f"• Piyasadaki Toplam Çip: {format_money(piyasadaki_cip)}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
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
        
        icon = {"slot": "🎰", "dart": "🎯", "bowling": "🎳", "atyarisi": "🐎", "roulette": "🎡"}.get(g_type, "🎮")
        
        panel_text += (
            f"{icon} **{g_type.upper()} İSTATİSTİKLERİ:**\n"
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
        icon = {"slot": "🎰", "dart": "🎯", "bowling": "🎳", "atyarisi": "🐎", "roulette": "🎡"}.get(game_type, "🎮")
        detail_text += (
            f"{icon} **{game_type.upper()}**\n"
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
    application = Application.builder().token(TOKEN).build()

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
    application.add_handler(CommandHandler("olympos", play_olympos_free))
    application.add_handler(CommandHandler("olympos1", olympus_stats))
    application.add_handler(MessageHandler(filters.Regex(r"(?i)^olympos$"), play_olympos_free))
    application.add_handler(MessageHandler(filters.Regex(r"(?i)^olympos1$"), olympus_stats))
    application.add_handler(CommandHandler("top10", top_players))
    application.add_handler(CommandHandler("bakiye", bakiye))
    application.add_handler(CommandHandler("transfer", transfer_command))
    application.add_handler(CommandHandler("komut", help_command))
    
    # Admin Komutları
    application.add_handler(CommandHandler("bakiyeekle", add_balance_admin))
    application.add_handler(CommandHandler("bakiyesil", remove_balance_admin))
    application.add_handler(CommandHandler("panel", admin_panel))
    application.add_handler(CommandHandler("bilgi", user_info_admin))
    application.add_handler(CommandHandler("panelsifirla", reset_panel_admin))
    application.add_handler(CommandHandler("bakim", maintenance_admin))
    application.add_handler(CommandHandler("duyuru", broadcast_admin))

    print(f"📁 Veritabanı: {DB_NAME}")
    print("🎰 Casino botu aktif... Oyun bazlı istatistikler devrede. (Polling başlatılıyor)")
    
    await application.initialize()
    await application.start()
    await application.updater.start_polling(drop_pending_updates=True)
    
    while True:
        await asyncio.sleep(3600)

if __name__ == "__main__":
    try:
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    except AttributeError:
        pass
        
    asyncio.run(main())
