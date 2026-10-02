
import os
import sqlite3
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, MessageHandler,
    ContextTypes, filters, ConversationHandler
)

load_dotenv()
TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_ID = int(os.getenv("ADMIN_ID", "509506756"))
CHANNEL_USERNAME = os.getenv("CHANNEL_USERNAME", "playlist").strip().lstrip("@")

if not TOKEN:
    raise RuntimeError("BOT_TOKEN is missing. Put your BotFather token in .env")

DB = "playlist.db"

def db():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    return con

def init_db():
    con = db()
    con.execute("""CREATE TABLE IF NOT EXISTS tracks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        artist TEXT NOT NULL,
        mood TEXT NOT NULL,
        file_id TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")
    con.execute("""CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")
    con.commit()
    con.close()

def add_user(user_id):
    con = db()
    con.execute("INSERT OR IGNORE INTO users(user_id) VALUES(?)", (user_id,))
    con.commit()
    con.close()

def moods():
    return [
        ("🌙 Night", "night"),
        ("🚗 Night Drive", "night_drive"),
        ("☔ Rainy Day", "rainy_day"),
        ("🖤 Sad", "sad"),
        ("❤️ Love", "love"),
        ("🔥 Energy", "energy"),
        ("☀️ Morning", "morning"),
        ("🌃 Late Night", "late_night"),
        ("✈️ Travel", "travel"),
        ("💿 Old But Gold", "old_gold"),
    ]

def main_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎵 آهنگ‌ها", callback_data="songs"),
         InlineKeyboardButton("🎧 پلی‌لیست‌ها", callback_data="playlists")],
        [InlineKeyboardButton("🔥 آهنگ‌های جدید", callback_data="new"),
         InlineKeyboardButton("🔎 جستجو", callback_data="search")],
        [InlineKeyboardButton("🌙 Mood", callback_data="moods")],
        [InlineKeyboardButton("📢 کانال playlist", url=f"https://t.me/{CHANNEL_USERNAME}")]
    ])

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    add_user(update.effective_user.id)
    text = (
        "🎧 <b>به playlist خوش اومدی</b>\n\n"
        "اینجا برای هر حس، یه آهنگ داریم. 🖤\n\n"
        "🎵 آهنگ‌ها\n"
        "🎧 پلی‌لیست‌ها\n"
        "🔥 آهنگ‌های جدید\n"
        "🌙 موسیقی بر اساس حس\n\n"
        "<i>Music for every mood.</i>"
    )
    await update.message.reply_text(text, parse_mode="HTML", reply_markup=main_menu())

async def menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data

    if data == "home":
        await q.edit_message_text(
            "🎧 <b>playlist</b>\n\nبرای هر حس، یک آهنگ. 🖤",
            parse_mode="HTML", reply_markup=main_menu()
        )
        return

    if data == "moods":
        rows = []
        m = moods()
        for i in range(0, len(m), 2):
            rows.append([
                InlineKeyboardButton(m[i][0], callback_data=f"mood:{m[i][1]}"),
                InlineKeyboardButton(m[i+1][0], callback_data=f"mood:{m[i+1][1]}") if i+1 < len(m) else InlineKeyboardButton("🏠", callback_data="home")
            ])
        rows.append([InlineKeyboardButton("🏠 منوی اصلی", callback_data="home")])
        await q.edit_message_text("🌙 <b>یک حس انتخاب کن:</b>", parse_mode="HTML",
                                  reply_markup=InlineKeyboardMarkup(rows))
        return

    if data.startswith("mood:"):
        mood = data.split(":",1)[1]
        await send_tracks(update, context, mood=mood)
        return

    if data in ("songs", "new"):
        await send_tracks(update, context, latest=(data=="new"))
        return

    if data == "playlists":
        await q.edit_message_text(
            "🎧 <b>Playlists</b>\n\n"
            "در این بخش می‌تونی پلی‌لیست‌های کانال رو به ربات اضافه کنی.\n"
            "فعلاً از بخش Mood آهنگ‌ها رو انتخاب کن.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🌙 Mood", callback_data="moods"),
                                                InlineKeyboardButton("🏠 خانه", callback_data="home")]])
        )
        return

    if data == "search":
        await q.edit_message_text(
            "🔎 برای جستجو، از دستور زیر استفاده کن:\n\n"
            "<code>/search نام آهنگ یا خواننده</code>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 خانه", callback_data="home")]])
        )
        return

async def send_tracks(update, context, mood=None, latest=False):
    con = db()
    if mood:
        rows = con.execute(
            "SELECT * FROM tracks WHERE mood=? ORDER BY id DESC LIMIT 10", (mood,)
        ).fetchall()
    else:
        rows = con.execute(
            "SELECT * FROM tracks ORDER BY id DESC LIMIT 10"
        ).fetchall()
    con.close()

    if not rows:
        text = "🎵 هنوز آهنگی در این بخش قرار نگرفته."
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🏠 خانه", callback_data="home")]])
        if update.callback_query:
            await update.callback_query.edit_message_text(text, reply_markup=kb)
        return

    target = update.callback_query.message if update.callback_query else update.message
    for r in rows:
        await context.bot.send_audio(
            chat_id=target.chat_id,
            audio=r["file_id"],
            caption=f"🎵 <b>{r['title']}</b>\n👤 {r['artist']}\n🌙 {r['mood']}",
            parse_mode="HTML"
        )
    if update.callback_query:
        await update.callback_query.message.reply_text(
            "🏠", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("منوی اصلی", callback_data="home")]])
        )

async def search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    add_user(update.effective_user.id)
    query = " ".join(context.args).strip()
    if not query:
        await update.message.reply_text("مثال:\n/search The Weeknd")
        return
    con = db()
    rows = con.execute(
        "SELECT * FROM tracks WHERE title LIKE ? OR artist LIKE ? ORDER BY id DESC LIMIT 10",
        (f"%{query}%", f"%{query}%")
    ).fetchall()
    con.close()
    if not rows:
        await update.message.reply_text("🔎 چیزی پیدا نشد.")
        return
    for r in rows:
        await context.bot.send_audio(
            update.effective_chat.id, r["file_id"],
            caption=f"🎵 <b>{r['title']}</b>\n👤 {r['artist']}\n🌙 {r['mood']}",
            parse_mode="HTML"
        )

# ---- Admin add flow ----
TITLE, ARTIST, MOOD, FILE = range(4)

def admin_only(update):
    return update.effective_user and update.effective_user.id == ADMIN_ID

async def add_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not admin_only(update):
        await update.message.reply_text("⛔ این بخش فقط برای ادمین است.")
        return ConversationHandler.END
    await update.message.reply_text("🎵 نام آهنگ را بفرست:")
    return TITLE

async def add_title(update, context):
    context.user_data["title"] = update.message.text.strip()
    await update.message.reply_text("👤 نام خواننده را بفرست:")
    return ARTIST

async def add_artist(update, context):
    context.user_data["artist"] = update.message.text.strip()
    await update.message.reply_text(
        "🌙 دسته‌بندی را بفرست.\nمثال: night / love / sad / energy"
    )
    return MOOD

async def add_mood(update, context):
    context.user_data["mood"] = update.message.text.strip().lower()
    await update.message.reply_text("🎧 حالا فایل آهنگ را به‌صورت Audio بفرست:")
    return FILE

async def add_file(update, context):
    if not update.message.audio:
        await update.message.reply_text("لطفاً خود فایل آهنگ را به‌صورت Audio ارسال کن.")
        return FILE
    a = update.message.audio
    con = db()
    con.execute(
        "INSERT INTO tracks(title,artist,mood,file_id) VALUES(?,?,?,?)",
        (context.user_data["title"], context.user_data["artist"],
         context.user_data["mood"], a.file_id)
    )
    con.commit()
    con.close()
    await update.message.reply_text(
        f"✅ اضافه شد!\n\n🎵 {context.user_data['title']}\n👤 {context.user_data['artist']}\n🌙 {context.user_data['mood']}"
    )
    context.user_data.clear()
    return ConversationHandler.END

async def cancel(update, context):
    context.user_data.clear()
    await update.message.reply_text("لغو شد.")
    return ConversationHandler.END

async def admin(update, context):
    if not admin_only(update):
        await update.message.reply_text("⛔ دسترسی ندارید.")
        return
    con=db()
    count=con.execute("SELECT COUNT(*) c FROM tracks").fetchone()["c"]
    users=con.execute("SELECT COUNT(*) c FROM users").fetchone()["c"]
    con.close()
    await update.message.reply_text(
        f"👑 <b>Admin Panel</b>\n\n🎵 آهنگ‌ها: {count}\n👥 کاربران: {users}\n\n"
        "/add — افزودن آهنگ\n/search — جستجو",
        parse_mode="HTML"
    )

def main():
    init_db()
    app=Application.builder().token(TOKEN).build()

    conv=ConversationHandler(
        entry_points=[CommandHandler("add", add_start)],
        states={
            TITLE:[MessageHandler(filters.TEXT & ~filters.COMMAND, add_title)],
            ARTIST:[MessageHandler(filters.TEXT & ~filters.COMMAND, add_artist)],
            MOOD:[MessageHandler(filters.TEXT & ~filters.COMMAND, add_mood)],
            FILE:[MessageHandler(filters.AUDIO, add_file)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("search", search))
    app.add_handler(CommandHandler("admin", admin))
    app.add_handler(conv)
    app.add_handler(CallbackQueryHandler(menu_callback))
    print("playlist bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()
