
import os
import sqlite3
from pathlib import Path
from datetime import datetime, timezone

from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import Application, CommandHandler, ContextTypes, CallbackQueryHandler

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
DB_PATH = os.getenv("DB_PATH", "playlistmusic.db")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is missing. Add it to Railway Variables.")

def now():
    return datetime.now(timezone.utc).isoformat()

def db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con

def init_db():
    con = db()
    con.executescript("""
    CREATE TABLE IF NOT EXISTS schema_meta (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY,
        username TEXT,
        first_name TEXT,
        last_name TEXT,
        language TEXT DEFAULT 'fa',
        notifications_enabled INTEGER DEFAULT 1,
        created_at TEXT NOT NULL,
        last_seen_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS artists (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        normalized_name TEXT NOT NULL UNIQUE,
        bio TEXT,
        image_file_id TEXT,
        created_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS albums (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        artist_id INTEGER,
        title TEXT NOT NULL,
        normalized_title TEXT NOT NULL,
        year INTEGER,
        cover_file_id TEXT,
        created_at TEXT NOT NULL,
        FOREIGN KEY (artist_id) REFERENCES artists(id) ON DELETE SET NULL,
        UNIQUE(artist_id, normalized_title)
    );

    CREATE TABLE IF NOT EXISTS tracks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        telegram_file_id TEXT,
        telegram_file_unique_id TEXT,
        file_hash TEXT,
        title TEXT NOT NULL,
        normalized_title TEXT NOT NULL,
        artist_id INTEGER,
        album_id INTEGER,
        duration INTEGER,
        language TEXT,
        genre TEXT,
        mood TEXT,
        year INTEGER,
        version TEXT DEFAULT 'Original',
        status TEXT DEFAULT 'approved',
        source_chat_id INTEGER,
        source_message_id INTEGER,
        created_at TEXT NOT NULL,
        FOREIGN KEY (artist_id) REFERENCES artists(id) ON DELETE SET NULL,
        FOREIGN KEY (album_id) REFERENCES albums(id) ON DELETE SET NULL
    );

    CREATE INDEX IF NOT EXISTS idx_tracks_title ON tracks(normalized_title);
    CREATE INDEX IF NOT EXISTS idx_tracks_artist ON tracks(artist_id);
    CREATE INDEX IF NOT EXISTS idx_tracks_hash ON tracks(file_hash);

    CREATE TABLE IF NOT EXISTS follows (
        user_id INTEGER NOT NULL,
        artist_id INTEGER NOT NULL,
        created_at TEXT NOT NULL,
        PRIMARY KEY(user_id, artist_id),
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
        FOREIGN KEY(artist_id) REFERENCES artists(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS likes (
        user_id INTEGER NOT NULL,
        track_id INTEGER NOT NULL,
        created_at TEXT NOT NULL,
        PRIMARY KEY(user_id, track_id),
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
        FOREIGN KEY(track_id) REFERENCES tracks(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS playlists (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        title TEXT NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS playlist_tracks (
        playlist_id INTEGER NOT NULL,
        track_id INTEGER NOT NULL,
        position INTEGER DEFAULT 0,
        created_at TEXT NOT NULL,
        PRIMARY KEY(playlist_id, track_id),
        FOREIGN KEY(playlist_id) REFERENCES playlists(id) ON DELETE CASCADE,
        FOREIGN KEY(track_id) REFERENCES tracks(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        track_id INTEGER NOT NULL,
        action TEXT NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
        FOREIGN KEY(track_id) REFERENCES tracks(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS searches (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        query TEXT NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE SET NULL
    );

    CREATE TABLE IF NOT EXISTS notifications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        artist_id INTEGER,
        track_id INTEGER,
        kind TEXT NOT NULL,
        sent_at TEXT,
        created_at TEXT NOT NULL,
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
        FOREIGN KEY(artist_id) REFERENCES artists(id) ON DELETE SET NULL,
        FOREIGN KEY(track_id) REFERENCES tracks(id) ON DELETE SET NULL
    );

    CREATE TABLE IF NOT EXISTS reports (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        track_id INTEGER,
        reason TEXT NOT NULL,
        status TEXT DEFAULT 'open',
        created_at TEXT NOT NULL,
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE SET NULL,
        FOREIGN KEY(track_id) REFERENCES tracks(id) ON DELETE SET NULL
    );

    CREATE TABLE IF NOT EXISTS required_channels (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        chat_id TEXT NOT NULL UNIQUE,
        title TEXT NOT NULL,
        invite_url TEXT,
        active INTEGER DEFAULT 1,
        created_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS ads (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        body TEXT NOT NULL,
        button_text TEXT,
        button_url TEXT,
        placement TEXT DEFAULT 'home',
        frequency INTEGER DEFAULT 0,
        starts_at TEXT,
        ends_at TEXT,
        active INTEGER DEFAULT 0,
        impressions INTEGER DEFAULT 0,
        clicks INTEGER DEFAULT 0,
        created_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS admin_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        admin_id INTEGER NOT NULL,
        action TEXT NOT NULL,
        details TEXT,
        created_at TEXT NOT NULL
    );

    INSERT OR IGNORE INTO schema_meta(key,value)
    VALUES ('schema_version','1');

    """)
    con.commit()
    con.close()

def normalize(s: str) -> str:
    return " ".join((s or "").strip().lower().replace("ي","ی").replace("ك","ک").split())

def upsert_user(tg_user):
    con = db()
    con.execute("""
        INSERT INTO users(id, username, first_name, last_name, created_at, last_seen_at)
        VALUES(?,?,?,?,?,?)
        ON CONFLICT(id) DO UPDATE SET
          username=excluded.username,
          first_name=excluded.first_name,
          last_name=excluded.last_name,
          last_seen_at=excluded.last_seen_at
    """, (
        tg_user.id, tg_user.username, tg_user.first_name, tg_user.last_name,
        now(), now()
    ))
    con.commit()
    con.close()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user:
        upsert_user(update.effective_user)

    keyboard = [
        [InlineKeyboardButton("🎵 جستجوی آهنگ", callback_data="search_info")],
        [InlineKeyboardButton("👤 خواننده‌ها", callback_data="artists_info"),
         InlineKeyboardButton("❤️ علاقه‌مندی‌ها", callback_data="likes_info")],
        [InlineKeyboardButton("📂 پلی‌لیست‌ها", callback_data="playlists_info"),
         InlineKeyboardButton("⚙️ تنظیمات", callback_data="settings_info")],
    ]
    await update.message.reply_text(
        "🎵 Playlist Music\n\n"
        "پایه ۱ با موفقیت فعال است.\n"
        "هسته دیتابیس، کاربران، خواننده‌ها، آلبوم‌ها، آهنگ‌ها، "
        "لایک، فالو، پلی‌لیست، تاریخچه، اعلان و گزارش آماده شده است.\n\n"
        "برای ورود به مرحله بعد، همین نسخه را تست می‌کنیم.",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or update.effective_user.id != ADMIN_ID:
        return
    con = db()
    stats = {}
    for table in ["users","artists","albums","tracks","follows","likes","playlists","history","searches","notifications","reports"]:
        stats[table] = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    con.close()
    text = "📊 آمار پایه ۱\n\n" + "\n".join(f"• {k}: {v}" for k,v in stats.items())
    await update.message.reply_text(text)

async def callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    messages = {
        "search_info": "🔎 جستجو در پایه بعدی به آرشیو واقعی آهنگ‌ها وصل می‌شود.",
        "artists_info": "👤 بخش خواننده‌ها در مرحله UX کامل می‌شود.",
        "likes_info": "❤️ ساختار لایک آماده است و در مرحله UX فعال می‌شود.",
        "playlists_info": "📂 ساختار پلی‌لیست آماده است و در مرحله UX فعال می‌شود.",
        "settings_info": "⚙️ تنظیمات کاربر در مرحله UX اضافه می‌شود.",
    }
    await q.message.reply_text(messages.get(q.data, "این بخش هنوز در حال توسعه است."))

async def post_init(app: Application):
    await app.bot.set_my_commands([
        BotCommand("start", "شروع"),
        BotCommand("admin", "پنل مدیریت"),
    ])

def main():
    init_db()
    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin))
    app.add_handler(CallbackQueryHandler(callback))
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
