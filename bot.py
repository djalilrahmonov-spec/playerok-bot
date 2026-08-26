import asyncio
import json
import time
import os
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
import aiohttp

# ========== НАСТРОЙКИ (из переменных окружения) ==========
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
PLAYEROK_TOKEN = os.getenv("PLAYEROK_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))

# Настройки авторежимов
AUTO_CONFIRM = True
AUTO_REPLY = True
AUTO_RISE = True
RISE_INTERVAL = 3600
REPLY_TEXT = "✅ Ваш товар отправлен! Спасибо за покупку! 🙌"

stats = {"today": 0, "total": 0, "revenue": 0, "last_sale": None}
products_cache = []
# =========================================================

async def playerok_request(method, endpoint, data=None):
    url = f"https://api.playerok.com/v1/{endpoint}"
    headers = {
        "Authorization": f"Bearer {PLAYEROK_TOKEN}",
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
    }
    async with aiohttp.ClientSession() as session:
        try:
            async with session.request(method, url, headers=headers, json=data) as resp:
                if resp.status == 200:
                    return await resp.json()
                return None
        except:
            return None

async def get_orders():
    result = await playerok_request("GET", "orders?status=waiting&limit=50")
    return result.get("items", []) if result else []

async def confirm_order(order_id):
    return await playerok_request("POST", f"orders/{order_id}/confirm") is not None

async def deliver_product(order_id, keys):
    data = {"text": "\n".join(keys) if isinstance(keys, list) else keys}
    return await playerok_request("POST", f"orders/{order_id}/message", data) is not None

async def rise_product(product_id):
    return await playerok_request("POST", f"products/{product_id}/rise") is not None

async def send_message(order_id, text):
    return await playerok_request("POST", f"orders/{order_id}/message", {"text": text}) is not None

async def get_products():
    result = await playerok_request("GET", "products?limit=100")
    return result.get("items", []) if result else []

async def send_telegram(text):
    try:
        await app.bot.send_message(ADMIN_ID, text)
    except:
        pass

async def auto_confirm_and_deliver():
    global stats
    orders = await get_orders()
    if not orders:
        return
    
    for order in orders:
        order_id = order.get("id")
        keys = ["KEY1-XXXX-YYYY", "KEY2-ZZZZ-WWWW"]
        
        if await deliver_product(order_id, keys):
            print(f"✅ Товар выдан для заказа #{order_id}")
        
        if await confirm_order(order_id):
            stats["today"] += 1
            stats["total"] += 1
            stats["revenue"] += order.get("price", 0)
            stats["last_sale"] = datetime.now().strftime("%H:%M")
            
            await send_telegram(
                f"💰 НОВАЯ ПРОДАЖА!\n"
                f"Заказ #{order_id}\n"
                f"Сумма: {order.get('price', 0)}₽\n"
                f"Покупатель: {order.get('buyer_name', 'Аноним')}"
            )

async def auto_reply():
    messages = await playerok_request("GET", "messages?unread=true")
    if not messages or "items" not in messages:
        return
    for msg in messages["items"]:
        order_id = msg.get("order_id")
        if order_id:
            await send_message(order_id, REPLY_TEXT)

async def auto_rise():
    global products_cache
    if not products_cache:
        products_cache = await get_products()
        products_cache = [p["id"] for p in products_cache[:10]]
    
    for pid in products_cache:
        await rise_product(pid)
    await send_telegram("⬆️ Товары подняты!")

# ========== КОМАНДЫ TELEGRAM ==========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ Доступ запрещен")
        return
    
    keyboard = [
        [InlineKeyboardButton("📊 Статистика", callback_data="stats")],
        [InlineKeyboardButton("⬆️ Поднять товары", callback_data="rise")],
        [InlineKeyboardButton("✅ Подтвердить заказы", callback_data="confirm")],
        [InlineKeyboardButton("📦 Список товаров", callback_data="products")],
        [InlineKeyboardButton("⚙️ Настройки", callback_data="settings")]
    ]
    await update.message.reply_text(
        "🤖 **Playerok Auto-Bot**\n\n"
        f"🟢 Автоподтверждение: {'ВКЛ' if AUTO_CONFIRM else 'ВЫКЛ'}\n"
        f"🟢 Автоответ: {'ВКЛ' if AUTO_REPLY else 'ВЫКЛ'}\n"
        f"🟢 Автоподнятие: {'ВКЛ' if AUTO_RISE else 'ВЫКЛ'}\n"
        f"⏱ Интервал: {RISE_INTERVAL//60} мин\n\n"
        "Выбери действие:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global AUTO_CONFIRM, AUTO_REPLY, AUTO_RISE
    query = update.callback_query
    await query.answer()
    
    if query.data == "stats":
        text = (
            f"📊 **Статистика**\n\n"
            f"📅 Сегодня: {stats['today']} шт.\n"
            f"💰 Всего: {stats['total']} шт.\n"
            f"💵 Выручка: {stats['revenue']}₽\n"
            f"🕐 Последняя: {stats['last_sale'] or 'Нет'}"
        )
        await query.edit_message_text(text, parse_mode="Markdown")
    
    elif query.data == "rise":
        await query.edit_message_text("⬆️ Поднимаю...")
        await auto_rise()
        await query.edit_message_text("✅ Готово!")
    
    elif query.data == "confirm":
        await query.edit_message_text("✅ Обрабатываю...")
        await auto_confirm_and_deliver()
        await query.edit_message_text("✅ Готово!")
    
    elif query.data == "products":
        prods = await get_products()
        if prods:
            text = "📦 **Твои товары:**\n\n"
            for i, p in enumerate(prods[:10], 1):
                text += f"{i}. {p.get('name', 'Без названия')} - {p.get('price', 0)}₽\n"
            await query.edit_message_text(text, parse_mode="Markdown")
        else:
            await query.edit_message_text("❌ Товаров нет")
    
    elif query.data == "settings":
        keyboard = [
            [InlineKeyboardButton(f"{'🔛' if AUTO_CONFIRM else '🔕'} Автоподтверждение", callback_data="toggle_confirm")],
            [InlineKeyboardButton(f"{'🔛' if AUTO_REPLY else '🔕'} Автоответ", callback_data="toggle_reply")],
            [InlineKeyboardButton(f"{'🔛' if AUTO_RISE else '🔕'} Автоподнятие", callback_data="toggle_rise")],
            [InlineKeyboardButton("◀️ Назад", callback_data="back")]
        ]
        await query.edit_message_text("⚙️ Настройки", reply_markup=InlineKeyboardMarkup(keyboard))
    
    elif query.data == "toggle_confirm":
        AUTO_CONFIRM = not AUTO_CONFIRM
        await query.answer(f"Автоподтверждение: {'ВКЛ' if AUTO_CONFIRM else 'ВЫКЛ'}")
    
    elif query.data == "toggle_reply":
        AUTO_REPLY = not AUTO_REPLY
        await query.answer(f"Автоответ: {'ВКЛ' if AUTO_REPLY else 'ВЫКЛ'}")
    
    elif query.data == "toggle_rise":
        AUTO_RISE = not AUTO_RISE
        await query.answer(f"Автоподнятие: {'ВКЛ' if AUTO_RISE else 'ВЫКЛ'}")
    
    elif query.data == "back":
        await start(update, context)

# ========== ЗАПУСК ==========
app = None

async def main():
    global app
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    
    async def bg_loop():
        last_rise = 0
        while True:
            try:
                if AUTO_CONFIRM:
                    await auto_confirm_and_deliver()
                if AUTO_REPLY:
                    await auto_reply()
                if AUTO_RISE and time.time() - last_rise >= RISE_INTERVAL:
                    await auto_rise()
                    last_rise = time.time()
                await asyncio.sleep(30)
            except Exception as e:
                print(f"Ошибка: {e}")
                await asyncio.sleep(10)
    
    asyncio.create_task(bg_loop())
    print("🤖 Бот запущен! Напиши /start в Telegram")
    
    # Запуск через новый метод
    await app.initialize()
    await app.start()
    await app.updater.start_polling()
    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(main())
