import os, re, sqlite3, hashlib
from datetime import datetime, timezone
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
ARCHIVE_CHANNEL = os.getenv("ARCHIVE_CHANNEL", "")
DB_PATH = os.getenv("DB_PATH", "playlistmusic.db")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is missing")

def now(): return datetime.now(timezone.utc).isoformat()
def norm(s): return " ".join((s or "").strip().lower().replace("ي","ی").replace("ك","ک").split())
def db():
    c=sqlite3.connect(DB_PATH); c.row_factory=sqlite3.Row
    c.execute("PRAGMA foreign_keys=ON"); return c

def init_db():
    c=db()
    c.executescript("""
    CREATE TABLE IF NOT EXISTS users(
      id INTEGER PRIMARY KEY, username TEXT, first_name TEXT, last_name TEXT,
      language TEXT DEFAULT 'fa', notifications_enabled INTEGER DEFAULT 1,
      created_at TEXT NOT NULL, last_seen_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS artists(
      id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
      normalized_name TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS tracks(
      id INTEGER PRIMARY KEY AUTOINCREMENT, telegram_file_id TEXT,
      telegram_file_unique_id TEXT, file_hash TEXT, title TEXT NOT NULL,
      normalized_title TEXT NOT NULL, artist_id INTEGER, duration INTEGER,
      language TEXT, genre TEXT, mood TEXT, year INTEGER,
      version TEXT DEFAULT 'Original', status TEXT DEFAULT 'approved',
      source_chat_id INTEGER, source_message_id INTEGER, description TEXT,
      created_at TEXT NOT NULL,
      FOREIGN KEY(artist_id) REFERENCES artists(id) ON DELETE SET NULL);
    CREATE INDEX IF NOT EXISTS idx_tracks_title ON tracks(normalized_title);
    CREATE INDEX IF NOT EXISTS idx_tracks_artist ON tracks(artist_id);
    CREATE INDEX IF NOT EXISTS idx_tracks_file_unique ON tracks(telegram_file_unique_id);
    CREATE TABLE IF NOT EXISTS searches(
      id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER,
      query TEXT NOT NULL, created_at TEXT NOT NULL);
    """)
    c.commit(); c.close()

def upsert_user(u):
    c=db()
    c.execute("""INSERT INTO users VALUES(?,?,?,?,?,?,?,?)
    ON CONFLICT(id) DO UPDATE SET username=excluded.username,
    first_name=excluded.first_name,last_name=excluded.last_name,
    last_seen_at=excluded.last_seen_at""",
    (u.id,u.username,u.first_name,u.last_name,"fa",1,now(),now()))
    c.commit(); c.close()

def parse_caption(caption, audio_title=None, performer=None):
    lines=[x.strip() for x in (caption or "").splitlines() if x.strip()]
    lines=[x for x in lines if not re.fullmatch(r"@\w+",x)]
    title=lines[0] if lines else (audio_title or "Unknown")
    artist=lines[1] if len(lines)>1 else (performer or "Unknown")
    desc=lines[2] if len(lines)>2 else ""
    return title,artist,desc

def is_demo(text):
    t=norm(text)
    return any(w in t for w in ("demo","preview","teaser","snippet","دمو","پیش نمایش","پیش‌نمایش","تیزر","نمونه"))

def ensure_artist(c,name):
    n=norm(name)
    row=c.execute("SELECT id FROM artists WHERE normalized_name=?",(n,)).fetchone()
    if row: return row["id"]
    cur=c.execute("INSERT INTO artists(name,normalized_name,created_at) VALUES(?,?,?)",(name,n,now()))
    return cur.lastrowid

async def channel_post(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg=update.channel_post
    if not msg or not msg.audio: return
    if ARCHIVE_CHANNEL and msg.chat.username and norm(msg.chat.username)!=norm(ARCHIVE_CHANNEL.lstrip("@")): return
    caption=msg.caption or ""; audio=msg.audio
    if is_demo(caption) or is_demo(audio.title or "") or is_demo(audio.performer or ""): return
    title,artist,desc=parse_caption(caption,audio.title,audio.performer)
    if not title or title=="Unknown": return
    c=db()
    if audio.file_unique_id and c.execute("SELECT id FROM tracks WHERE telegram_file_unique_id=?",(audio.file_unique_id,)).fetchone():
        c.close(); return
    artist_id=ensure_artist(c,artist)
    file_hash=hashlib.sha256((audio.file_unique_id or "").encode()).hexdigest()
    if c.execute("""SELECT id FROM tracks WHERE normalized_title=? AND artist_id=?
                    AND COALESCE(version,'Original')='Original'""",(norm(title),artist_id)).fetchone():
        c.close(); return
    c.execute("""INSERT INTO tracks(telegram_file_id,telegram_file_unique_id,file_hash,title,
      normalized_title,artist_id,duration,status,source_chat_id,source_message_id,description,created_at)
      VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
      (audio.file_id,audio.file_unique_id,file_hash,title,norm(title),artist_id,audio.duration,
       "approved",msg.chat.id,msg.message_id,desc,now()))
    c.commit(); c.close()

async def start(update,context):
    upsert_user(update.effective_user)
    kb=[[InlineKeyboardButton("🔎 جستجوی آهنگ",callback_data="search")],
        [InlineKeyboardButton("👤 خواننده‌ها",callback_data="artists")]]
    await update.message.reply_text("🎵 Playlist Music\n\nمرحله ۲ فعال است.\nآهنگ‌های کامل کانال آرشیو می‌شوند و از طریق جستجو قابل ارسال هستند.",reply_markup=InlineKeyboardMarkup(kb))

async def search(update,context):
    upsert_user(update.effective_user)
    q=" ".join(context.args).strip()
    if not q:
        await update.message.reply_text("مثال:\n/search بارون\n\nیا /search نام خواننده"); return
    c=db(); c.execute("INSERT INTO searches(user_id,query,created_at) VALUES(?,?,?)",(update.effective_user.id,q,now()))
    nq=norm(q)
    rows=c.execute("""SELECT t.*,a.name artist FROM tracks t LEFT JOIN artists a ON a.id=t.artist_id
      WHERE t.normalized_title LIKE ? OR a.normalized_name LIKE ? ORDER BY t.id DESC LIMIT 10""",(f"%{nq}%",f"%{nq}%")).fetchall()
    c.commit(); c.close()
    if not rows:
        await update.message.reply_text("❌ آهنگ موردنظر در آرشیو پیدا نشد."); return
    for r in rows:
        kb=InlineKeyboardMarkup([[InlineKeyboardButton("🎧 ارسال آهنگ",callback_data=f"send:{r['id']}")]])
        await update.message.reply_text(f"🎵 {r['title']}\n👤 {r['artist'] or 'نامشخص'}\n📝 {r['description'] or ''}",reply_markup=kb)

def get_artist(aid):
    c=db(); r=c.execute("SELECT name FROM artists WHERE id=?",(aid,)).fetchone(); c.close()
    return r["name"] if r else "نامشخص"

async def callback(update,context):
    q=update.callback_query; await q.answer()
    if q.data=="search":
        await q.message.reply_text("برای جستجو فعلاً از این فرمت استفاده کن:\n/search نام آهنگ یا نام خواننده"); return
    if q.data=="artists":
        await q.message.reply_text("فهرست کامل خواننده‌ها در مرحله UX تکمیل می‌شود."); return
    if q.data.startswith("send:"):
        tid=int(q.data.split(":")[1]); c=db(); r=c.execute("SELECT * FROM tracks WHERE id=?",(tid,)).fetchone(); c.close()
        if not r or not r["telegram_file_id"]:
            await q.message.reply_text("❌ فایل آرشیوشده پیدا نشد."); return
        await context.bot.send_audio(chat_id=q.from_user.id,audio=r["telegram_file_id"],
          caption=f"🎵 {r['title']}\n👤 {get_artist(r['artist_id'])}\n\n@Playlistmusicbox")

async def admin(update,context):
    if update.effective_user.id!=ADMIN_ID: return
    c=db(); n=c.execute("SELECT COUNT(*) FROM tracks").fetchone()[0]; a=c.execute("SELECT COUNT(*) FROM artists").fetchone()[0]; u=c.execute("SELECT COUNT(*) FROM users").fetchone()[0]; c.close()
    await update.message.reply_text(f"📊 Stage 2\nکاربران: {u}\nآهنگ‌ها: {n}\nخواننده‌ها: {a}")

async def post_init(app):
    await app.bot.set_my_commands([BotCommand("start","شروع"),BotCommand("search","جستجوی آهنگ"),BotCommand("admin","پنل مدیریت")])

def main():
    init_db()
    app=Application.builder().token(BOT_TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("start",start))
    app.add_handler(CommandHandler("search",search))
    app.add_handler(CommandHandler("admin",admin))
    app.add_handler(CallbackQueryHandler(callback))
    app.add_handler(MessageHandler(filters.UpdateType.CHANNEL_POST,channel_post))
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__=="__main__": main()
