from aiogram import Router, F
import logging
import re
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from services.crypto_api import CryptoAPI
from database.db import add_user, is_premium, add_alert, get_user_alerts, delete_alert
from bot.keyboards import get_alert_type_keyboard, get_premium_keyboard, get_alerts_list_keyboard

router = Router()

class AlertStates(StatesGroup):
    waiting_for_price = State()

@router.message(Command("search"))
async def search_coin_handler(message: Message):
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("Please provide a coin name or symbol.\nExample: <code>/search BTC</code>")
        return

    query = args[1]
    msg = await message.answer(f"🔍 Searching for <b>{query}</b>...")

    try:
        pair_data = await CryptoAPI.search_coin(query)
    except Exception as e:
        logging.error(f"Search error: {e}")
        await msg.edit_text("❌ An error occurred while searching. Please try again.")
        return

    if pair_data:
        text = CryptoAPI.format_coin_info(pair_data)
        
        # Only show alert buttons in private chat
        keyboard = None
        if message.chat.type == "private":
            symbol = pair_data.get("baseToken", {}).get("symbol", "COIN")
            price = pair_data.get("priceUsd", "0")
            keyboard = get_alert_type_keyboard(symbol, price)

        await msg.edit_text(
            text,
            reply_markup=keyboard,
            disable_web_page_preview=True
        )
    else:
        await msg.edit_text(f"❌ Could not find any data for <b>{query}</b>.")

@router.message(Command("trending"))
async def trending_coins_handler(message: Message):
    msg = await message.answer("🔥 <b>Fetching live trending tokens from DexScreener...</b>")
    
    try:
        trending_pairs = await CryptoAPI.get_trending_coins()
        if not trending_pairs:
            await msg.edit_text("❌ No trending tokens found at the moment. Please try again later.")
            return
            
        lines = ["🔥 <b>Trending DexScreener Boosts</b> 🔥\n"]
        for i, pair in enumerate(trending_pairs, 1):
            base_token = pair.get("baseToken", {})
            name = base_token.get("name", "Unknown")
            symbol = base_token.get("symbol", "Unknown")
            price_usd = pair.get("priceUsd", "N/A")
            change_24h = pair.get("priceChange", {}).get("h24", 0)
            chain = pair.get("chainId", "N/A").capitalize()
            addr = base_token.get("address", "")
            
            try:
                change_val = float(change_24h) if change_24h else 0
            except (ValueError, TypeError):
                change_val = 0
            emoji = "📈" if change_val >= 0 else "📉"
            
            line = (
                f"{i}. <b>{name} ({symbol})</b> on <b>{chain}</b>\n"
                f"   💰 Price: <code>${price_usd}</code>\n"
                f"   {emoji} 24h: <code>{change_24h}%</code>\n"
                f"   📝 CA: <code>{addr}</code>\n"
                f"   📊 <a href='{pair.get('url', '')}'>View Chart</a>\n"
            )
            lines.append(line)
            
        await msg.edit_text("\n".join(lines), disable_web_page_preview=True)
    except Exception as e:
        logging.error(f"Trending error: {e}")
        await msg.edit_text("❌ An error occurred while fetching trending tokens.")

@router.callback_query(F.data.startswith("a:"))
async def process_alert_callback(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    premium = await is_premium(user_id)
    alerts = await get_user_alerts(user_id)

    if len(alerts) >= 3 and not premium:
        await callback.message.answer(
            "⚠️ <b>Alert Limit Reached!</b>\n\n"
            "Free users can have 3 alerts.\n"
            "Upgrade to Premium for unlimited! 🚀",
            reply_markup=get_premium_keyboard()
        )
        await callback.answer()
        return

    parts = callback.data.split(":")
    condition = parts[1]  # above or below
    symbol = parts[2]

    await state.update_data(symbol=symbol, condition=condition)

    await callback.message.answer(
        f"You want to be alerted when <b>{symbol}</b> goes <b>{condition}</b>.\n\n"
        "Enter the target price (USD):"
    )
    await state.set_state(AlertStates.waiting_for_price)
    await callback.answer()

@router.message(AlertStates.waiting_for_price)
async def process_target_price(message: Message, state: FSMContext):
    try:
        target_price = float(message.text.replace("$", "").strip())
    except ValueError:
        await message.answer("Please enter a valid number.")
        return

    data = await state.get_data()
    await add_alert(
        user_id=message.from_user.id,
        coin_id=data['symbol'],
        symbol=data['symbol'],
        target_price=target_price,
        condition=data['condition']
    )

    await message.answer(
        f"✅ <b>Alert Set!</b>\n"
        f"I'll notify you when <b>{data['symbol']}</b> is <b>{data['condition']}</b> <b>${target_price}</b>."
    )
    await state.clear()

@router.message(Command("alerts"))
async def list_alerts_handler(message: Message):
    alerts = await get_user_alerts(message.from_user.id)
    if not alerts:
        await message.answer("You have no active alerts.\nUse /search to find a coin and set one!")
        return

    await message.answer(
        "🔔 <b>Your Active Alerts:</b>\nTap to delete.",
        reply_markup=get_alerts_list_keyboard(alerts)
    )

@router.callback_query(F.data.startswith("del:"))
async def process_delete_alert(callback: CallbackQuery):
    alert_id = int(callback.data.split(":")[1])
    await delete_alert(alert_id)

    alerts = await get_user_alerts(callback.from_user.id)
    if not alerts:
        await callback.message.edit_text("You have no active alerts.")
    else:
        await callback.message.edit_reply_markup(reply_markup=get_alerts_list_keyboard(alerts))

    await callback.answer("Alert deleted.")

@router.message(Command("help"))
async def help_handler(message: Message):
    help_text = (
        "<b>Available Commands:</b>\n"
        "/start - Start the bot\n"
        "/search &lt;coin&gt; - Get live price\n"
        "/trending - View trending DexScreener coins\n"
        "/alerts - Manage your alerts\n"
        "/help - Show this help\n\n"
        "💡 <b>Tip:</b> You can also just type <code>price btc</code> in any chat!"
    )
    await message.answer(help_text)


@router.message(F.text)
async def flexible_price_handler(message: Message):
    """Handles 'price btc' style messages. Only triggers for non-command text."""
    if not message.text:
        return
    
    # Skip if it's a command that should be handled by other handlers
    if message.text.startswith("/"):
        return
    
    # Only match "price <coin>" pattern
    match = re.search(r'^price\s+(\w+)', message.text.strip().lower())
    if not match:
        return
        
    query = match.group(1)
    logging.info(f"Flexible price lookup in {message.chat.type}: {query}")
    msg = await message.answer(f"🔍 Checking <b>{query.upper()}</b>...")

    try:
        pair_data = await CryptoAPI.search_coin(query)
    except Exception as e:
        logging.error(f"Price lookup error: {e}")
        await msg.edit_text("❌ An error occurred. Please try again.")
        return

    if pair_data:
        text = CryptoAPI.format_coin_info(pair_data)
        
        # Only show alert buttons in private chat
        keyboard = None
        if message.chat.type == "private":
            symbol = pair_data.get("baseToken", {}).get("symbol", "COIN")
            price = pair_data.get("priceUsd", "0")
            keyboard = get_alert_type_keyboard(symbol, price)

        await msg.edit_text(
            text,
            reply_markup=keyboard,
            disable_web_page_preview=True
        )
    else:
        await msg.edit_text(f"❌ No data found for <b>{query.upper()}</b>.")

@router.callback_query(F.data == "upgrade_premium")
async def upgrade_callback(callback: CallbackQuery):
    await callback.message.answer("To upgrade to Premium, send 100 ⭐️ Stars or contact @Admin.")
    await callback.answer()
