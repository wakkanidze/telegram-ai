import asyncio
import sqlite3
import html
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, CommandObject
from aiogram.types import LabeledPrice, PreCheckoutQuery, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.enums import ParseMode
from openai import OpenAI

# --- КОНФИГУРАЦИЯ ---
TELEGRAM_TOKEN = "8266678556:AAG_SWdM2g8XqRZGfE81k-HVkXHHgkU2j1U"
OPENAI_API_KEY = "sk-d38jHMFQHUVlctqkWbNKdvlWIW7p2jNfCKj6deTotX5N5sGR"
BASE_URL = "https://api.chatanywhere.tech/v1"

DEFAULT_DAILY_LIMIT = 15
SYSTEM_PROMPT = "Ты — продвинутый ИИ. Используй HTML (<b>, <i>, <code>) для ответов. Всегда форматируй текст под Telegram."

client = OpenAI(api_key=OPENAI_API_KEY, base_url=BASE_URL)
bot = Bot(token=TELEGRAM_TOKEN)
dp = Dispatcher()

# --- БАЗА ДАННЫХ ---
def init_db():
    conn = sqlite3.connect('users.db')
    cur = conn.cursor()
    # Удаляем старую таблицу если нужно сбросить или просто создаем новую
    cur.execute('''CREATE TABLE IF NOT EXISTS users 
                   (user_id INTEGER PRIMARY KEY, 
                    prompts_left INTEGER, 
                    last_reset TEXT, 
                    plan_type TEXT DEFAULT 'free', 
                    plan_until TEXT DEFAULT 'none',
                    referred_by INTEGER)''')
    conn.commit()
    conn.close()

def get_user_data(user_id):
    conn = sqlite3.connect('users.db')
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    user = cur.fetchone()
    today = datetime.now().date().isoformat()
    
    if not user:
        cur.execute("INSERT INTO users VALUES (?, ?, ?, ?, ?, ?)", 
                    (user_id, DEFAULT_DAILY_LIMIT, today, 'free', 'none', None))
        conn.commit()
        user = (user_id, DEFAULT_DAILY_LIMIT, today, 'free', 'none', None)
    
    # ПРОВЕРКА ИСТЕЧЕНИЯ ПОДПИСКИ
    plan_until = user[4]
    if plan_until and plan_until != 'none':
        try:
            expire_date = datetime.fromisoformat(plan_until)
            if datetime.now() > expire_date:
                # Подписка истекла — возвращаем на фри
                cur.execute("UPDATE users SET plan_type = 'free', plan_until = 'none', prompts_left = ? WHERE user_id = ?", 
                            (DEFAULT_DAILY_LIMIT, user_id))
                conn.commit()
                user = (user_id, DEFAULT_DAILY_LIMIT, today, 'free', 'none', user[5])
        except ValueError:
            pass

    # Сброс лимитов для бесплатных пользователей каждый день
    if user[3] == 'free' and user[2] != today:
        cur.execute("UPDATE users SET prompts_left = ?, last_reset = ? WHERE user_id = ?", 
                    (DEFAULT_DAILY_LIMIT, today, user_id))
        conn.commit()
        user = (user_id, DEFAULT_DAILY_LIMIT, today, 'free', user[4], user[5])
        
    conn.close()
    return user

# --- КЛАВИАТУРЫ ---
def get_main_menu():
    buttons = [[InlineKeyboardButton(text="💎 Добавить промпты", callback_data="add_prompts")]]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_shop_menu():
    buttons = [
        [InlineKeyboardButton(text="🌟 50 промптов / 7 дней — 25 ⭐", callback_data="buy_p1")],
        [InlineKeyboardButton(text="🔥 50/день / 30 дн — 100 ⭐ (вместо 200)", callback_data="buy_p2")],
        [InlineKeyboardButton(text="🚀 100/день / 30 дн — 200 ⭐ (вместо 400)", callback_data="buy_p3")],
        [InlineKeyboardButton(text="👥 Пригласить друга (+10 шт)", callback_data="invite_friend")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_main")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

# --- ОБРАБОТЧИКИ ---

@dp.message(Command("start"))
async def start_cmd(message: types.Message, command: CommandObject):
    user = get_user_data(message.from_user.id)
    
    # Реферальная логика
    if command.args and command.args.isdigit():
        ref_id = int(command.args)
        if ref_id != message.from_user.id and not user[5]:
            conn = sqlite3.connect('users.db')
            conn.execute("UPDATE users SET referred_by = ?, prompts_left = prompts_left + 10 WHERE user_id = ?", (ref_id, message.from_user.id))
            conn.execute("UPDATE users SET prompts_left = prompts_left + 10 WHERE user_id = ?", (ref_id,))
            conn.commit()
            conn.close()
            try: await bot.send_message(ref_id, "🤝 Друг присоединился! Вам начислено <b>+10 промптов</b>!", parse_mode="HTML")
            except: pass

    status_name = (user[3] or "FREE").upper()
    text = (
        f"🤖 <b>Добро пожаловать в AI Терминал!</b>\n\n"
        f"💳 Твой статус: <code>{status_name}</code>\n"
        f"🔋 Осталось запросов: <b>{user[1]}</b>\n\n"
        f"<i>Просто напиши свой вопрос ниже...</i>"
    )
    await message.answer(text, reply_markup=get_main_menu(), parse_mode="HTML")

@dp.callback_query(F.data == "add_prompts")
async def show_shop(callback: types.CallbackQuery):
    await callback.message.edit_text("🛍 <b>Выберите выгодный тариф:</b>", reply_markup=get_shop_menu(), parse_mode="HTML")

@dp.callback_query(F.data == "back_main")
async def back_to_main(callback: types.CallbackQuery):
    user = get_user_data(callback.from_user.id)
    status_name = (user[3] or "FREE").upper()
    text = (
        f"🤖 <b>Добро пожаловать в AI Терминал!</b>\n\n"
        f"💳 Твой статус: <code>{status_name}</code>\n"
        f"🔋 Осталось запросов: <b>{user[1]}</b>"
    )
    await callback.message.edit_text(text, reply_markup=get_main_menu(), parse_mode="HTML")

@dp.callback_query(F.data == "invite_friend")
async def invite_info(callback: types.CallbackQuery):
    ref_link = f"https://t.me/{(await bot.get_me()).username}?start={callback.from_user.id}"
    await callback.message.edit_text(
        f"🎁 <b>Акция: Пригласи друга!</b>\n\n"
        f"За каждого, кто перейдет по ссылке, оба получите по <b>10 промптов</b>.\n\n"
        f"🔗 Твоя ссылка:\n<code>{ref_link}</code>",
        reply_markup=get_shop_menu(), parse_mode="HTML"
    )

# --- ПЛАТЕЖИ ---
@dp.callback_query(F.data.startswith("buy_p"))
async def process_buy(callback: types.CallbackQuery):
    plans = {
        "buy_p1": ("50 промптов (7 дней)", 25, "plan_week_50"),
        "buy_p2": ("50 промптов/день (30 дней)", 100, "plan_month_50"),
        "buy_p3": ("100 промптов/день (30 дней)", 200, "plan_month_100")
    }
    title, price, payload = plans[callback.data]
    await callback.message.answer_invoice(
        title=title, description=f"Активация: {title}",
        payload=payload, currency="XTR", prices=[LabeledPrice(label="Оплата", amount=price)]
    )
    await callback.answer()

@dp.pre_checkout_query()
async def pre_checkout(query: PreCheckoutQuery):
    await query.answer(ok=True)

@dp.message(F.successful_payment)
async def success_pay(message: types.Message):
    payload = message.successful_payment.invoice_payload
    days = 7 if "week" in payload else 30
    limit = 100 if "100" in payload else 50
    until = (datetime.now() + timedelta(days=days)).isoformat()
    
    conn = sqlite3.connect('users.db')
    cur = conn.cursor()
    cur.execute("UPDATE users SET plan_type = ?, plan_until = ?, prompts_left = ? WHERE user_id = ?", 
                 (payload, until, limit, message.from_user.id))
    conn.commit()
    conn.close()
    await message.answer(f"🚀 <b>Успешно!</b>\nТариф активирован до {until[:10]}.\nДоступно: {limit} промптов.", parse_mode="HTML")

# --- ЧАТ ---
@dp.message()
async def chat_handler(message: types.Message):
    if not message.text: return
    user = get_user_data(message.from_user.id)
    
    if user[1] <= 0:
        await message.answer("❌ <b>Лимиты исчерпаны!</b>\nПополни баланс или пригласи друга.", reply_markup=get_main_menu(), parse_mode="HTML")
        return

    await bot.send_chat_action(message.chat.id, "typing")
    try:
        loop = asyncio.get_event_loop()
        resp = await loop.run_in_executor(None, lambda: client.chat.completions.create(
            model="gpt-4o", 
            messages=[{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": message.text}]
        ))
        
        # Экранируем HTML и возвращаем важные теги
        raw_answer = resp.choices[0].message.content
        safe_answer = html.escape(raw_answer).replace("&lt;b&gt;", "<b>").replace("&lt;/b&gt;", "</b>").replace("&lt;code&gt;", "<code>").replace("&lt;/code&gt;", "</code>").replace("&lt;i&gt;", "<i>").replace("&lt;/i&gt;", "</i>")
        
        conn = sqlite3.connect('users.db')
        conn.execute("UPDATE users SET prompts_left = prompts_left - 1 WHERE user_id = ?", (message.from_user.id,))
        conn.commit()
        conn.close()

        await message.answer(safe_answer, parse_mode="HTML")
    except Exception as e:
        print(f"Ошибка чата: {e}")
        await message.answer("🤖 Кажется, я переутомился. Попробуйте еще раз через минуту.")

async def main():
    init_db()
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())