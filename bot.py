import asyncio
import os
import sqlite3
import html
import logging
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from openai import AsyncOpenAI
from fastapi import FastAPI
import uvicorn

# --- КОНФИГУРАЦИЯ (Бери из переменных окружения или впиши сюда) ---
TOKEN = "8266678556:AAG_SWdM2g8XqRZGfE81k-HVkXHHgkU2j1U"
OPENAI_API_KEY = "sk-proj-..." # Твой ключ
BASE_URL = "https://api.vveai.com/v1" # Твой прокси

# Инициализация
bot = Bot(token=TOKEN)
dp = Dispatcher()
client = AsyncOpenAI(api_key=OPENAI_API_KEY, base_url=BASE_URL)
app = FastAPI()

# --- БАЗА ДАННЫХ ---
def init_db():
    conn = sqlite3.connect('users.db')
    conn.execute('''CREATE TABLE IF NOT EXISTS users 
                    (user_id INTEGER PRIMARY KEY, prompts_left INTEGER DEFAULT 10)''')
    conn.commit()
    conn.close()

def get_user_data(user_id):
    conn = sqlite3.connect('users.db')
    res = conn.execute("SELECT user_id, prompts_left FROM users WHERE user_id = ?", (user_id,)).fetchone()
    if not res:
        conn.execute("INSERT INTO users (user_id, prompts_left) VALUES (?, 10)", (user_id,))
        conn.commit()
        res = (user_id, 10)
    conn.close()
    return res

# --- ФЕЙКОВЫЙ СЕРВЕР ДЛЯ RENDER (Health Check) ---
@app.get("/")
async def health_check():
    return {"status": "alive"}

# --- КЛАВИАТУРА ---
def get_main_menu():
    kb = [
        [types.KeyboardButton(text="💎 Мой профиль"), types.KeyboardButton(text="⚙️ Помощь")]
    ]
    return types.ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

# --- ОБРАБОТЧИКИ ---
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    get_user_data(message.from_user.id)
    await message.answer("🤖 Привет! Я твой ИИ помощник.", reply_markup=get_main_menu())

@dp.message(F.text == "💎 Мой профиль")
async def profile_handler(message: types.Message):
    user = get_user_data(message.from_user.id)
    await message.answer(f"👤 <b>Профиль</b>\nID: <code>{user[0]}</code>\nОсталось промптов: {user[1]}", parse_mode="HTML")

@dp.message(F.text)
async def chat_handler(message: types.Message):
    if message.text.startswith("/") or message.text in ["💎 Мой профиль", "⚙️ Помощь"]: return
    
    user = get_user_data(message.from_user.id)
    if user[1] <= 0:
        await message.answer("❌ Лимиты исчерпаны!")
        return

    # Списываем авансом
    conn = sqlite3.connect('users.db')
    conn.execute("UPDATE users SET prompts_left = prompts_left - 1 WHERE user_id = ?", (message.from_user.id,))
    conn.commit()
    conn.close()

    msg = await message.answer("⏳ Думаю...")
    
    try:
        resp = await client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": message.text}]
        )
        answer = resp.choices[0].message.content
        await msg.edit_text(answer)
    except Exception as e:
        # ВОЗВРАТ КРЕДИТА ПРИ ОШИБКЕ
        conn = sqlite3.connect('users.db')
        conn.execute("UPDATE users SET prompts_left = prompts_left + 1 WHERE user_id = ?", (message.from_user.id,))
        conn.commit()
        conn.close()
        await msg.edit_text(f"❌ Ошибка API. Кредит возвращен. ({e})")

# --- ЗАПУСК ---
async def start_polling():
    init_db()
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    loop = asyncio.get_event_loop()
    loop.create_task(start_polling()) # Бот в фоне
    uvicorn.run(app, host="0.0.0.0", port=port) # Сервер держит процесс
