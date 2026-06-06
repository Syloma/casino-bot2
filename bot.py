import sqlite3
import asyncio
import warnings
import random
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# Sarı renkli Python 3.12+ Deprecation uyarılarını gizler
warnings.filterwarnings("ignore", category=DeprecationWarning)

# --- 1. CONFIG VE YÖNETİCİ AYARLARI ---
DB_NAME = "casino_database.db"

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
MAX_BET_DART_BOWL = parse_money("200t")
MIN_BET_SLOT = parse_money("20t")
MAX_BET_SLOT = parse_money("250t")
MIN_BET_HORSE = parse_money("10t")
MAX_BET_HORSE = parse_money("100t")


# --- 3. VERİTABANI AYARLARI VE İSTATİSTİK ---
def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            balance INTEGER DEFAULT 0
        )
    """)
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
    for game in ['slot', 'dart', 'bowling', 'atyarisi']:
        cursor.execute("INSERT OR IGNORE INTO game_stats (game_type) VALUES (?)", (game,))
    
    conn.commit()
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

def update_game_stats(game_type, wagered_amount, paid_amount, is_win):
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
    conn.commit()
    conn.close()


# --- 4. OYUNCU KOMUTLARI VE OYUNLAR ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
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
        f"*(Bahislerde 10t, 20t, 100t gibi kısaltmalar kullanabilirsin)*\n"
        f"Tüm detaylar için **/komut** yazabilirsin!"
    )
    await update.message.reply_text(welcome_text, parse_mode="Markdown")

# 🎰 SLOT OYUNU
async def play_slot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
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
        win_amount = bet * 20
        is_win = True
        result_text = f"🎉 **7-7-7 GELDİ!** 20 Katını kazandın! (+{format_money(win_amount)})"
    elif val in [1, 22, 43]: # 3'lü kombinasyon
        win_amount = bet * 9
        is_win = True
        result_text = f"🔥 **3'lü Kombinasyon!** 9 Katını kazandın! (+{format_money(win_amount)})"
    else:
        win_amount = 0
        is_win = False
        result_text = "😔 **Maalesef kazanamadın.**"

    # İstatistikleri güncelle (Önce stat, sonra bakiye)
    update_game_stats('slot', bet, win_amount, is_win)
    
    # Yeni bakiyeyi güncelle (Eğer win_amount 0 ise bakiye değişmez)
    new_bal = update_balance(user_id, win_amount)
    
    await update.message.reply_text(f"{result_text}\n💳 Güncel Bakiye: {format_money(new_bal)}", parse_mode="Markdown", message_thread_id=thread_id)
# 🎯 DART OYUNU
async def play_dart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
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
        win_amount = bet * 5
        is_win = True
        result_text = f"🎯 **TAM İSABET! BAŞARILI ATIŞ!** 🎯\n🔥 **Bahsinin 5 Katını Kazandın! (+{format_money(win_amount)})**"
    else:
        result_text = f"😔 **Karavana!** (-{format_money(bet)})\nİstediğin atışı yapamadın."

    update_game_stats('dart', bet, win_amount, is_win)
    new_balance = update_balance(user_id, win_amount)
    final_message = f"{result_text}\n\n💳 **Güncel Bakiyen:** {format_money(new_balance)} Çip"
    await update.message.reply_text(final_message, parse_mode="Markdown", message_thread_id=thread_id)

# 🎳 BOWLING OYUNU
async def play_bowling(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
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
        win_amount = bet * 5.5
        is_win = True
        result_text = f"🎳 **STRIKE! BAŞARILI ATIŞ!** 🎳\n🔥 **Bahsinin 5.5 Katını Kazandın! (+{format_money(win_amount)})**"
    else:
        result_text = f"😔 **Oluk!** (-{format_money(bet)})\nTop yoldan çıktı veya az labut devrildi."

    update_game_stats('bowling', bet, win_amount, is_win)
    new_balance = update_balance(user_id, win_amount)
    final_message = f"{result_text}\n\n💳 **Güncel Bakiyen:** {format_money(new_balance)} Çip"
    await update.message.reply_text(final_message, parse_mode="Markdown", message_thread_id=thread_id)

def render_horse_race(positions):
    finish_line = 12
    lines = []
    for horse in range(1, 6):
        pos = min(positions[horse], finish_line)
        track = "." * pos + "H" + "." * (finish_line - pos) + "|"
        lines.append(f"{horse}: {track}")
    return "\n".join(lines)

# 🐎 AT YARIŞI OYUNU
async def play_horse_race(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    thread_id = update.message.message_thread_id if update.message else None

    if len(context.args) < 2:
        await update.message.reply_text(
            f"❌ **Kullanım:** `/atyarisi [Miktar] [At No]`\n"
            f"📌 Örnek: `/atyarisi 10t 3`\n"
            f"Min: {format_money(MIN_BET_HORSE)} | Max: {format_money(MAX_BET_HORSE)} | At: 1-5",
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

    if selected_horse is None or selected_horse < 1 or selected_horse > 5:
        await update.message.reply_text("❌ Geçersiz at numarası! 1 ile 5 arasında bir at seç.", message_thread_id=thread_id)
        return

    current_balance = get_balance(user_id)
    if current_balance < bet:
        await update.message.reply_text("❌ **Bakiyen yetersiz!**", parse_mode="Markdown", message_thread_id=thread_id)
        return

    update_balance(user_id, -bet)

    horse_names = {
        1: "Şimşek",
        2: "Fırtına",
        3: "Rüzgar",
        4: "Kara İnci",
        5: "Kasırga",
    }
    positions = {horse: 0 for horse in horse_names}
    race_msg = await update.message.reply_text(
        f"🐎 **At yarışı başladı!**\nSenin atın: **#{selected_horse} {horse_names[selected_horse]}**\n\n"
        f"```\n{render_horse_race(positions)}\n```",
        parse_mode="Markdown",
        message_thread_id=thread_id
    )

    winner = None
    finish_line = 12
    for _ in range(8):
        await asyncio.sleep(0.8)
        horses = list(horse_names.keys())
        random.shuffle(horses)
        for horse in horses:
            positions[horse] += random.randint(0, 3)

        leaders = [horse for horse, pos in positions.items() if pos >= finish_line]
        if leaders:
            winner = max(leaders, key=lambda horse: positions[horse])
            positions[winner] = finish_line
            await race_msg.edit_text(
                f"🐎 **Final virajı!**\nSenin atın: **#{selected_horse} {horse_names[selected_horse]}**\n\n"
                f"```\n{render_horse_race(positions)}\n```",
                parse_mode="Markdown"
            )
            break

        await race_msg.edit_text(
            f"🐎 **Atlar koşuyor!**\nSenin atın: **#{selected_horse} {horse_names[selected_horse]}**\n\n"
            f"```\n{render_horse_race(positions)}\n```",
            parse_mode="Markdown"
        )

    if winner is None:
        winner = max(positions, key=positions.get)
        positions[winner] = finish_line
        await race_msg.edit_text(
            f"🐎 **Foto finish!**\nSenin atın: **#{selected_horse} {horse_names[selected_horse]}**\n\n"
            f"```\n{render_horse_race(positions)}\n```",
            parse_mode="Markdown"
        )

    is_win = winner == selected_horse
    win_amount = bet * 4 if is_win else 0
    update_game_stats('atyarisi', bet, win_amount, is_win)
    new_balance = update_balance(user_id, win_amount)

    if is_win:
        result_text = f"🎉 **TEBRİKLER!** #{winner} {horse_names[winner]} kazandı. Bahsinin **4 katını** aldın! (+{format_money(win_amount)})"
    else:
        result_text = f"😔 **Kaybettin.** Kazanan at: #{winner} {horse_names[winner]} (-{format_money(bet)})"

    await update.message.reply_text(
        f"{result_text}\n\n💳 **Güncel Bakiyen:** {format_money(new_balance)} Çip",
        parse_mode="Markdown",
        message_thread_id=thread_id
    )

async def top_players(update: Update, context: ContextTypes.DEFAULT_TYPE):
    thread_id = update.message.message_thread_id if update.message else None
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, balance FROM users ORDER BY balance DESC LIMIT 10")
    rows = cursor.fetchall()
    conn.close()
    
    leaderboard = "🏆 **KUMARBAZLAR KRALLIĞI - TOP 10** 🏆\n\n"
    medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
    
    for index, row in enumerate(rows):
        target_id = row[0]
        balance = row[1]
        leaderboard += f"{medals[index]} ID: `{target_id}` — 💰 **{format_money(balance)} Çip**\n"
        
    await update.message.reply_text(leaderboard, parse_mode="Markdown", message_thread_id=thread_id)

async def bakiye(update: Update, context: ContextTypes.DEFAULT_TYPE):
    balance = get_balance(update.effective_user.id)
    await update.message.reply_text(f"💰 Bakiyen: {format_money(balance)} Çip")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    thread_id = update.message.message_thread_id if update.message else None
    
    help_text = (
        f"📖 **CASINO BOTU KOMUT LİSTESİ** 📖\n\n"
        f"🎮 **Oyunlar:**\n"
        f"• `/slot [Miktar]` (Min {format_money(MIN_BET_SLOT)} | Max {format_money(MAX_BET_SLOT)})\n"
        f"• `/dart [Miktar]` (Min {format_money(MIN_BET_DART_BOWL)} | Max {format_money(MAX_BET_DART_BOWL)})\n"
        f"• `/bowling [Miktar]` (Min {format_money(MIN_BET_DART_BOWL)} | Max {format_money(MAX_BET_DART_BOWL)})\n"
        f"• `/atyarisi [Miktar] [At No]` (Min {format_money(MIN_BET_HORSE)} | Max {format_money(MAX_BET_HORSE)} | At: 1-5)\n\n"
        f"💡 *Bahislerde t, kt kısaltmalarını kullanabilirsin. (Örn: /slot 20t)*\n\n"
        f"🛠️ **Genel:**\n"
        f"• `/bakiye` - Mevcut çipini gösterir\n"
        f"• `/top10` - En zengin 10 oyuncuyu listeler\n"
    )
    
    if user_id in ADMIN_IDS:
        help_text += (
            f"\n⚡ **[ADMİN ÖZEL] Yönetim Komutları:**\n"
            f"• `/bakiyeekle [ID/Yanıt] [Miktar]`\n"
            f"• `/bakiyesil [ID/Yanıt] [Miktar]`\n"
            f"• `/panel` - Kasa istatistiklerini ve oyun bazlı verileri gösterir\n"
            f"• `/panelsifirla` - Kasa istatistiklerini temizler\n"
            f"• `/duyuru [Mesaj]` - Herkese mesaj atar\n"
        )
        
    await update.message.reply_text(help_text, parse_mode="Markdown", message_thread_id=thread_id)


# --- 5. GÜVENLİ ADMİN KOMUTLARI ---

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

async def add_balance_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    thread_id = update.message.message_thread_id if update.message else None
    target_id, amount = get_target_and_amount(update, context)
    if target_id is None or amount is None or amount <= 0: 
        await update.message.reply_text("❌ Hatalı kullanım. Örn: `/bakiyeekle 123456789 10t`", message_thread_id=thread_id)
        return

    update_balance(target_id, amount)
    await update.message.reply_text(f"✅ `{target_id}` ID'li kullanıcıya **{format_money(amount)}** çip eklendi.", parse_mode="Markdown", message_thread_id=thread_id)

async def remove_balance_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    thread_id = update.message.message_thread_id if update.message else None
    target_id, amount = get_target_and_amount(update, context)
    if target_id is None or amount is None or amount <= 0: 
        await update.message.reply_text("❌ Hatalı kullanım. Örn: `/bakiyesil 123456789 5t`", message_thread_id=thread_id)
        return

    update_balance(target_id, -amount)
    await update.message.reply_text(f"📉 `{target_id}` ID'li kullanıcıdan **{format_money(amount)}** çip silindi.", parse_mode="Markdown", message_thread_id=thread_id)

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    thread_id = update.message.message_thread_id if update.message else None
    
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(user_id), SUM(balance) FROM users")
    user_stats = cursor.fetchone()
    
    cursor.execute("SELECT game_type, total_games, winning_games, total_wagered, total_paid FROM game_stats")
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
        
        icon = {"slot": "🎰", "dart": "🎯", "bowling": "🎳", "atyarisi": "🐎"}.get(g_type, "🎮")
        
        panel_text += (
            f"{icon} **{g_type.upper()} İSTATİSTİKLERİ:**\n"
            f"Oyun: {g_total} | Kazanç: %{g_win_rate:.1f} | RTP: %{g_rtp:.1f}\n"
            f"Kasa Karı: {format_money(g_net)}\n\n"
        )

    win_rate_genel = (k_oyun_genel / t_oyun_genel * 100) if t_oyun_genel > 0 else 0
    rtp_genel = (t_odenen_genel / t_bahis_genel * 100) if t_bahis_genel > 0 else 0
    net_kar_genel = t_bahis_genel - t_odenen_genel

    panel_text += (
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🏦 **GENEL KASA DURUMU:**\n"
        f"• Toplam Dönen: {format_money(t_bahis_genel)}\n"
        f"• Toplam Dağıtılan: {format_money(t_odenen_genel)}\n"
        f"• **Toplam Kasa Karı:** {format_money(net_kar_genel)}\n"
        f"• **Genel Win Rate:** %{win_rate_genel:.1f}\n"
        f"• **Genel RTP:** %{rtp_genel:.1f}"
    )

    await update.message.reply_text(panel_text, parse_mode="Markdown", message_thread_id=thread_id)

async def reset_panel_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    thread_id = update.message.message_thread_id if update.message else None
    
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("UPDATE game_stats SET total_games=0, winning_games=0, total_wagered=0, total_paid=0")
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

    # Oyuncu Komutları
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("slot", play_slot))
    application.add_handler(CommandHandler("dart", play_dart))
    application.add_handler(CommandHandler("bowling", play_bowling))
    application.add_handler(CommandHandler("atyarisi", play_horse_race))
    application.add_handler(CommandHandler("top10", top_players))
    application.add_handler(CommandHandler("bakiye", bakiye))
    application.add_handler(CommandHandler("komut", help_command))
    
    # Admin Komutları
    application.add_handler(CommandHandler("bakiyeekle", add_balance_admin))
    application.add_handler(CommandHandler("bakiyesil", remove_balance_admin))
    application.add_handler(CommandHandler("panel", admin_panel))
    application.add_handler(CommandHandler("panelsifirla", reset_panel_admin))
    application.add_handler(CommandHandler("duyuru", broadcast_admin))

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
