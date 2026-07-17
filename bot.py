import logging
import os
import random
import sqlite3
from datetime import datetime

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

BOT_TOKEN = os.environ["BOT_TOKEN"]  # обязателен, без него бот не запустится
START_BALANCE = 1000

# --- Каталог: предметы и кейсы ---
# value — виртуальные очки, начисляются в инвентарь. Без реальных денег и
# без вывода в реальные скины/деньги — только коллекционная механика.
ITEMS = {
    "common_1": {"name": "AK-47 | Safari Mesh", "rarity": "common", "value": 20, "emoji": "⚪"},
    "common_2": {"name": "Glock-18 | Sand Dune", "rarity": "common", "value": 15, "emoji": "⚪"},
    "uncommon_1": {"name": "M4A4 | Faded Zebra", "rarity": "uncommon", "value": 60, "emoji": "🟢"},
    "uncommon_2": {"name": "Five-SeveN | Case Hardened", "rarity": "uncommon", "value": 75, "emoji": "🟢"},
    "rare_1": {"name": "AWP | Pit Viper", "rarity": "rare", "value": 250, "emoji": "🔵"},
    "rare_2": {"name": "SG 553 | Basket Halftone", "rarity": "rare", "value": 300, "emoji": "🔵"},
    "epic_1": {"name": "AK-47 | Bloodsport", "rarity": "epic", "value": 900, "emoji": "🟣"},
    "legendary_1": {"name": "AWP | Dragon Lore", "rarity": "legendary", "value": 5000, "emoji": "🟡"},
}

CASES = {
    "eco": {
        "name": "Эко",
        "price": 500,
        "odds": [
            ("common_1", 40), ("common_2", 35),
            ("uncommon_1", 15), ("uncommon_2", 7),
            ("rare_1", 2.5), ("rare_2", 0.4),
            ("epic_1", 0.09), ("legendary_1", 0.01),
        ],
    },
    "premium": {
        "name": "Premium",
        "price": 1500,
        "odds": [
            ("common_1", 20), ("common_2", 20),
            ("uncommon_1", 25), ("uncommon_2", 20),
            ("rare_1", 10), ("rare_2", 4.5),
            ("epic_1", 0.45), ("legendary_1", 0.05),
        ],
    },
}

# --- База данных ---
DB_PATH = os.environ.get("DB_PATH", "shop.db")


def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = db()
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            telegram_id INTEGER PRIMARY KEY,
            username TEXT,
            balance INTEGER NOT NULL DEFAULT 1000
        );
        CREATE TABLE IF NOT EXISTS inventory (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id INTEGER NOT NULL,
            item_id TEXT NOT NULL,
            obtained_at TEXT NOT NULL
        );
        """
    )
    conn.commit()
    conn.close()


def get_or_create_user(telegram_id: int, username: str) -> sqlite3.Row:
    conn = db()
    row = conn.execute("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,)).fetchone()
    if row is None:
        conn.execute(
            "INSERT INTO users (telegram_id, username, balance) VALUES (?, ?, ?)",
            (telegram_id, username, START_BALANCE),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,)).fetchone()
    conn.close()
    return row


def get_balance(telegram_id: int) -> int:
    conn = db()
    row = conn.execute("SELECT balance FROM users WHERE telegram_id = ?", (telegram_id,)).fetchone()
    conn.close()
    return row["balance"] if row else 0


def try_spend(telegram_id: int, amount: int) -> bool:
    conn = db()
    cur = conn.execute(
        "UPDATE users SET balance = balance - ? WHERE telegram_id = ? AND balance >= ?",
        (amount, telegram_id, amount),
    )
    conn.commit()
    ok = cur.rowcount == 1
    conn.close()
    return ok


def add_inventory(telegram_id: int, item_id: str):
    conn = db()
    conn.execute(
        "INSERT INTO inventory (telegram_id, item_id, obtained_at) VALUES (?, ?, ?)",
        (telegram_id, item_id, datetime.utcnow().isoformat()),
    )
    conn.commit()
    conn.close()


def get_inventory(telegram_id: int):
    conn = db()
    rows = conn.execute(
        "SELECT item_id, obtained_at FROM inventory WHERE telegram_id = ? ORDER BY obtained_at DESC LIMIT 30",
        (telegram_id,),
    ).fetchall()
    conn.close()
    return rows


def roll_case(case_id: str) -> str:
    odds = CASES[case_id]["odds"]
    total = sum(w for _, w in odds)
    r = random.uniform(0, total)
    upto = 0
    for item_id, weight in odds:
        upto += weight
        if r <= upto:
            return item_id
    return odds[-1][0]  # fallback на случай погрешности float


# --- Экраны ---
def main_menu_keyboard():
    buttons = [
        [InlineKeyboardButton(f"📦 {c['name']} — {c['price']} ⭐", callback_data=f"case:{cid}")]
        for cid, c in CASES.items()
    ]
    buttons.append([InlineKeyboardButton("🎒 Инвентарь", callback_data="inventory")])
    return InlineKeyboardMarkup(buttons)


def case_keyboard(case_id: str):
    buttons = [
        [InlineKeyboardButton("🎲 Открыть", callback_data=f"open:{case_id}")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="back")],
    ]
    return InlineKeyboardMarkup(buttons)


def after_open_keyboard(case_id: str):
    buttons = [
        [InlineKeyboardButton("🎲 Открыть ещё", callback_data=f"open:{case_id}")],
        [InlineKeyboardButton("⬅️ В магазин", callback_data="back")],
    ]
    return InlineKeyboardMarkup(buttons)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    row = get_or_create_user(user.id, user.username or user.first_name)
    text = (
        f"🏪 <b>Магазин кейсов</b>\n\n"
        f"⭐ Баланс: <b>{row['balance']}</b>\n\n"
        f"Выбери кейс:"
    )
    await update.message.reply_html(text, reply_markup=main_menu_keyboard())


async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    data = query.data

    if data == "back":
        balance = get_balance(user_id)
        text = f"🏪 <b>Магазин кейсов</b>\n\n⭐ Баланс: <b>{balance}</b>\n\nВыбери кейс:"
        await query.edit_message_text(text, reply_markup=main_menu_keyboard(), parse_mode="HTML")
        return

    if data == "inventory":
        rows = get_inventory(user_id)
        if not rows:
            text = "🎒 Инвентарь пуст. Открой кейс, чтобы получить первый предмет."
        else:
            lines = []
            for r in rows:
                item = ITEMS[r["item_id"]]
                lines.append(f"{item['emoji']} {item['name']} (+{item['value']})")
            text = "🎒 <b>Инвентарь</b>\n\n" + "\n".join(lines)
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад", callback_data="back")]])
        await query.edit_message_text(text, reply_markup=keyboard, parse_mode="HTML")
        return

    if data.startswith("case:"):
        case_id = data.split(":", 1)[1]
        case = CASES[case_id]
        items_preview = "\n".join(
            f"{ITEMS[i]['emoji']} {ITEMS[i]['name']}" for i, _ in case["odds"]
        )
        text = (
            f"📦 <b>{case['name']}</b>\n"
            f"Цена: {case['price']} ⭐\n\n"
            f"Возможные предметы:\n{items_preview}"
        )
        await query.edit_message_text(text, reply_markup=case_keyboard(case_id), parse_mode="HTML")
        return

    if data.startswith("open:"):
        case_id = data.split(":", 1)[1]
        case = CASES[case_id]

        if not try_spend(user_id, case["price"]):
            await query.answer("Недостаточно баланса!", show_alert=True)
            return

        item_id = roll_case(case_id)
        item = ITEMS[item_id]
        add_inventory(user_id, item_id)
        balance = get_balance(user_id)

        text = (
            f"📦 Открыт кейс «{case['name']}»\n\n"
            f"{item['emoji']} <b>{item['name']}</b>\n"
            f"Редкость: {item['rarity']}\n"
            f"+{item['value']} очков в инвентарь\n\n"
            f"⭐ Баланс: <b>{balance}</b>"
        )
        await query.edit_message_text(text, reply_markup=after_open_keyboard(case_id), parse_mode="HTML")
        return


async def balance_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    row = get_or_create_user(update.effective_user.id, update.effective_user.username)
    await update.message.reply_text(f"⭐ Баланс: {row['balance']}")


def main():
    init_db()
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("balance", balance_cmd))
    app.add_handler(CallbackQueryHandler(on_callback))
    log.info("Bot started")
    app.run_polling()


if __name__ == "__main__":
    main()
