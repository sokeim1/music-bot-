"""
Музыкальный Telegram бот для Koyeb с альтернативными источниками
Использует российские сайты для обхода блокировок YouTube
"""
import asyncio
import os
import logging
import json
from io import BytesIO
from typing import Optional
from datetime import datetime
import aiohttp
from aiohttp import web

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.types import Message, BufferedInputFile, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

from youtube_downloader import YouTubeDownloader
from mp3wr_parser import Mp3wrParser
from sefon_parser import SefonParser

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# Токен бота (замените на ваш)
BOT_TOKEN = "8353650126:AAGvR3EoPXWeyCMkDIB8gDR7NwXx1REMbwQ"

# Инициализация бота и диспетчера
bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# ID админа для доступа к статистике
ADMIN_ID = 7850455999

# Статистика в памяти
users_stats = {"users": []}


def add_user(user_id: int, username: str = None, first_name: str = None):
    """Добавляет пользователя в статистику"""
    global users_stats
    
    for user in users_stats['users']:
        if user['user_id'] == user_id:
            user['last_seen'] = datetime.now().isoformat()
            if username:
                user['username'] = username
            if first_name:
                user['first_name'] = first_name
            return False
    
    users_stats['users'].append({
        'user_id': user_id,
        'username': username,
        'first_name': first_name,
        'joined': datetime.now().isoformat(),
        'last_seen': datetime.now().isoformat()
    })
    return True


class MusicStates(StatesGroup):
    """Состояния FSM для работы с музыкой"""
    waiting_for_query = State()
    choosing_track = State()


async def search_all_sources(query: str, limit: int = 15):
    """Поиск по всем доступным источникам"""
    all_tracks = []
    
    # Сначала пробуем российские источники (более надежные)
    try:
        logger.info(f"Поиск в MP3WR: {query}")
        async with Mp3wrParser() as mp3wr:
            mp3wr_tracks = await mp3wr.search(query, limit=8)
            for track in mp3wr_tracks:
                track['source'] = 'mp3wr'
                track['source_emoji'] = '🎵'
                all_tracks.append(track)
        logger.info(f"MP3WR: найдено {len(mp3wr_tracks)} треков")
    except Exception as e:
        logger.error(f"Ошибка поиска в MP3WR: {e}")
    
    try:
        logger.info(f"Поиск в Sefon: {query}")
        async with SefonParser() as sefon:
            sefon_tracks = await sefon.search(query, limit=4)
            for track in sefon_tracks:
                track['source'] = 'sefon'
                track['source_emoji'] = '🎶'
                all_tracks.append(track)
        logger.info(f"Sefon: найдено {len(sefon_tracks)} треков")
    except Exception as e:
        logger.error(f"Ошибка поиска в Sefon: {e}")
    
    # YouTube как резервный источник
    try:
        logger.info(f"Поиск в YouTube: {query}")
        youtube = YouTubeDownloader()
        youtube_tracks = await youtube.search(query, limit=3)
        for track in youtube_tracks:
            track['source'] = 'youtube'
            track['source_emoji'] = '📺'
            all_tracks.append(track)
        logger.info(f"YouTube: найдено {len(youtube_tracks)} треков")
    except Exception as e:
        logger.error(f"Ошибка поиска в YouTube: {e}")
    
    # Ограничиваем общее количество
    if len(all_tracks) > limit:
        all_tracks = all_tracks[:limit]
    
    logger.info(f"Всего найдено {len(all_tracks)} треков")
    return all_tracks


async def download_track(track):
    """Скачивание трека в зависимости от источника"""
    source = track.get('source', 'youtube')
    
    try:
        if source == 'mp3wr':
            async with Mp3wrParser() as mp3wr:
                return await mp3wr.download_track(track['url'])
        elif source == 'sefon':
            async with SefonParser() as sefon:
                return await sefon.download_track(track.get('track_url', track['url']))
        elif source == 'youtube':
            youtube = YouTubeDownloader()
            return await youtube.download_track(track['url'])
        else:
            logger.error(f"Неизвестный источник: {source}")
            return None
    except Exception as e:
        logger.error(f"Ошибка скачивания из {source}: {e}")
        return None


@dp.message(CommandStart())
async def cmd_start(message: Message):
    """Обработчик команды /start"""
    user = message.from_user
    is_new = add_user(
        user_id=user.id,
        username=user.username,
        first_name=user.first_name
    )
    
    if is_new:
        logger.info(f"Новый пользователь: {user.id} (@{user.username}) - {user.first_name}")
    
    await message.answer(
        "🎵 <b>Привет! Я @DownloaderSSMusicBot</b>\n\n"
        "💫 Я помогу тебе найти и скачать любую музыку\n\n"
        "✨ Просто отправь мне название песни или исполнителя!\n\n"
        "🔍 <b>Источники музыки:</b>\n"
        "🎵 MP3WR - российский сайт\n"
        "🎶 Sefon - альтернативный источник\n"
        "📺 YouTube - резервный источник\n\n"
        "🌐 <i>Работаю на Koyeb хостинге</i>",
        parse_mode="HTML"
    )


@dp.message(Command('stats'))
async def cmd_stats(message: Message):
    """Статистика для админа"""
    if message.from_user.id != ADMIN_ID:
        await message.answer("❌ У вас нет доступа к этой команде")
        return
    
    users = users_stats.get('users', [])
    total_users = len(users)
    
    text = f"📊 <b>Статистика бота</b>\n\n"
    text += f"👥 <b>Всего пользователей:</b> {total_users}\n"
    
    await message.answer(text, parse_mode="HTML")


@dp.message(Command('search'))
async def cmd_search(message: Message, state: FSMContext):
    """Команда поиска"""
    await message.answer(
        "🔍 <b>Поиск музыки</b>\n\n"
        "Отправь название песни или исполнителя:",
        parse_mode="HTML"
    )
    await state.set_state(MusicStates.waiting_for_query)


@dp.message(Command('cancel'))
async def cmd_cancel(message: Message, state: FSMContext):
    """Отмена операции"""
    current_state = await state.get_state()
    if current_state is None:
        await message.answer("❌ Нечего отменять")
        return
    
    await state.clear()
    await message.answer("✅ Операция отменена")


async def show_tracks_page(message: Message, tracks: list, page: int, state: FSMContext):
    """Показывает страницу с треками"""
    TRACKS_PER_PAGE = 5
    total_pages = (len(tracks) + TRACKS_PER_PAGE - 1) // TRACKS_PER_PAGE
    
    start_idx = page * TRACKS_PER_PAGE
    end_idx = min(start_idx + TRACKS_PER_PAGE, len(tracks))
    page_tracks = tracks[start_idx:end_idx]
    
    keyboard = []
    
    for idx, track in enumerate(page_tracks):
        global_idx = start_idx + idx
        
        title = track['title']
        duration = track.get('duration', 'N/A')
        source_emoji = track.get('source_emoji', '🎵')
        
        max_title_length = 25
        if len(title) > max_title_length:
            title = title[:max_title_length] + "..."
        
        button_text = f"{global_idx + 1}. {source_emoji} {title} • {duration}"
        
        keyboard.append([InlineKeyboardButton(
            text=button_text,
            callback_data=f"download_{global_idx}"
        )])
    
    # Навигация
    nav_buttons = []
    
    if page > 0:
        nav_buttons.append(InlineKeyboardButton(
            text="⬅️ Назад",
            callback_data=f"page_{page - 1}"
        ))
    
    nav_buttons.append(InlineKeyboardButton(
        text=f"📄 {page + 1}/{total_pages}",
        callback_data="page_info"
    ))
    
    if page < total_pages - 1:
        nav_buttons.append(InlineKeyboardButton(
            text="Вперёд ➡️",
            callback_data=f"page_{page + 1}"
        ))
    
    if nav_buttons:
        keyboard.append(nav_buttons)
    
    keyboard.append([InlineKeyboardButton(
        text="❌ Отмена",
        callback_data="cancel"
    )])
    
    markup = InlineKeyboardMarkup(inline_keyboard=keyboard)
    
    text = (
        f"🎵 <b>Результаты поиска</b>\n"
        f"📊 Найдено: {len(tracks)} треков\n"
        f"📄 Страница {page + 1} из {total_pages}\n\n"
        f"⏬ Выбери трек для скачивания:"
    )
    
    await message.edit_text(text, reply_markup=markup, parse_mode="HTML")


@dp.message(MusicStates.waiting_for_query)
@dp.message(F.text & ~F.text.startswith('/'))
async def search_music(message: Message, state: FSMContext):
    """Поиск музыки"""
    query = message.text.strip()
    
    if not query:
        await message.answer("❌ Пожалуйста, отправь корректный запрос")
        return
    
    search_msg = await message.answer("🔍 Ищу музыку во всех источниках...")
    
    try:
        logger.info(f"Поиск музыки: '{query}' от пользователя {message.from_user.id}")
        
        tracks = await search_all_sources(query, limit=20)
        
        logger.info(f"Найдено {len(tracks)} треков для запроса: '{query}'")
        
        if not tracks:
            await search_msg.edit_text(
                "❌ <b>Ничего не найдено</b>\n\n"
                "💡 <b>Попробуйте:</b>\n"
                "• Изменить запрос\n"
                "• Указать исполнителя и название\n"
                "• Использовать английские названия",
                parse_mode="HTML"
            )
            await state.clear()
            return
        
        await state.update_data(tracks=tracks, page=0)
        await state.set_state(MusicStates.choosing_track)
        
        await show_tracks_page(search_msg, tracks, 0, state)
        
    except Exception as e:
        logger.error(f"Ошибка при поиске: {e}")
        await search_msg.edit_text(
            "❌ Произошла ошибка при поиске\n\n"
            "Попробуй еще раз позже"
        )
        await state.clear()


@dp.callback_query(F.data == "cancel")
async def callback_cancel(callback: CallbackQuery, state: FSMContext):
    """Отмена выбора"""
    await callback.message.edit_text("✅ Поиск отменен")
    await state.clear()
    await callback.answer()


@dp.callback_query(F.data.startswith("page_"))
async def callback_page(callback: CallbackQuery, state: FSMContext):
    """Навигация по страницам"""
    if callback.data == "page_info":
        await callback.answer("ℹ️ Используй кнопки для навигации", show_alert=False)
        return
    
    page = int(callback.data.split("_")[1])
    
    data = await state.get_data()
    tracks = data.get('tracks', [])
    
    if not tracks:
        await callback.answer("❌ Треки не найдены", show_alert=True)
        return
    
    await state.update_data(page=page)
    await show_tracks_page(callback.message, tracks, page, state)
    await callback.answer()


@dp.callback_query(F.data.startswith("download_"))
async def callback_download(callback: CallbackQuery, state: FSMContext):
    """Скачивание трека"""
    await callback.answer("⏳ Скачиваю...")
    
    try:
        track_idx = int(callback.data.split("_")[1])
        
        data = await state.get_data()
        tracks = data.get('tracks', [])
        
        if track_idx >= len(tracks):
            await callback.message.edit_text("❌ Трек не найден")
            await state.clear()
            return
        
        track = tracks[track_idx]
        source = track.get('source', 'unknown')
        
        logger.info(f"Скачивание из {source}: '{track['title']}' для пользователя {callback.from_user.id}")
        
        # Прогресс
        progress_msg = await callback.message.edit_text(
            f"⬜⬜⬜⬜⬜⬜⬜⬜⬜⬜ 0%\n"
            f"📥 <b>Подготовка...</b>\n\n"
            f"🎵 {track['title']}\n"
            f"📍 Источник: {track.get('source_emoji', '🎵')} {source.upper()}",
            parse_mode="HTML"
        )
        
        await asyncio.sleep(0.3)
        await progress_msg.edit_text(
            f"🟦🟦⬜⬜⬜⬜⬜⬜⬜⬜ 25%\n"
            f"📥 <b>Скачивание...</b>\n\n"
            f"🎵 {track['title']}\n"
            f"📍 Источник: {track.get('source_emoji', '🎵')} {source.upper()}",
            parse_mode="HTML"
        )
        
        # Скачиваем
        audio_data = await download_track(track)
        
        if not audio_data:
            await callback.message.edit_text(
                f"❌ <b>Не удалось скачать</b>\n\n"
                f"🎵 {track['title']}\n"
                f"📍 Источник: {source.upper()}\n\n"
                f"💡 <b>Попробуйте:</b>\n"
                f"• Выбрать другой трек\n"
                f"• Выполнить новый поиск",
                parse_mode="HTML"
            )
            await state.clear()
            return
        
        file_size_mb = len(audio_data) / 1024 / 1024
        logger.info(f"Трек скачан: {file_size_mb:.2f} МБ из {source}")
        
        await progress_msg.edit_text(
            f"🟦🟦🟦🟦🟦🟦🟦⬜⬜⬜ 75%\n"
            f"📤 <b>Отправка...</b>\n\n"
            f"🎵 {track['title']}\n"
            f"📍 Источник: {track.get('source_emoji', '🎵')} {source.upper()}",
            parse_mode="HTML"
        )
        
        # Отправляем файл
        audio_file = BufferedInputFile(
            file=audio_data,
            filename=f"{track.get('artist', 'Unknown')} - {track['title']}.mp3"
        )
        
        formatted_title = f"♫ {track['title']}"
        performer = f"{track.get('artist', 'Unknown')} ✦ @DownloaderSSMusicBot"
        
        # Обложка
        thumbnail_path = os.path.join(os.path.dirname(__file__), 'thumbnail.jpg')
        thumbnail = None
        if os.path.exists(thumbnail_path):
            with open(thumbnail_path, 'rb') as f:
                thumbnail = BufferedInputFile(f.read(), filename='thumbnail.jpg')
        
        await callback.message.answer_audio(
            audio=audio_file,
            title=formatted_title,
            performer=performer,
            thumbnail=thumbnail,
            caption=f"🎵 <b>{track['title']}</b>\n"
                   f"👤 <i>{track.get('artist', 'Unknown')}</i>\n"
                   f"⏱ {track.get('duration', 'N/A')}\n"
                   f"📍 Источник: {track.get('source_emoji', '🎵')} {source.upper()}\n\n"
                   f"📥 Downloaded by @DownloaderSSMusicBot\n"
                   f"🌐 Powered by Koyeb",
            parse_mode="HTML"
        )
        
        await progress_msg.delete()
        logger.info(f"Трек отправлен пользователю {callback.from_user.id}")
        await state.clear()
        
    except Exception as e:
        logger.error(f"Ошибка при скачивании: {e}", exc_info=True)
        await callback.message.edit_text(
            "❌ <b>Произошла ошибка</b>\n\n"
            "Попробуй выбрать другой трек",
            parse_mode="HTML"
        )
        await state.clear()


# HTTP endpoints
async def health_check(request):
    """Health check endpoint"""
    return web.Response(
        text=f"🎵 Multi-Source Music Bot is alive!\n⏰ {datetime.now().isoformat()}\n👥 Users: {len(users_stats['users'])}",
        status=200,
        content_type='text/plain'
    )


async def stats_endpoint(request):
    """Stats endpoint"""
    return web.json_response({
        'status': 'alive',
        'users_count': len(users_stats['users']),
        'timestamp': datetime.now().isoformat(),
        'sources': ['mp3wr', 'sefon', 'youtube']
    })


async def keep_alive():
    """Keep-alive function"""
    while True:
        try:
            await asyncio.sleep(300)  # 5 минут
            logger.info("Keep-alive ping")
        except Exception as e:
            logger.error(f"Keep-alive error: {e}")


async def start_web_server():
    """Запуск веб-сервера"""
    app = web.Application()
    app.router.add_get('/', health_check)
    app.router.add_get('/health', health_check)
    app.router.add_get('/stats', stats_endpoint)
    
    port = int(os.getenv('PORT', 8080))
    
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    
    logger.info(f"🌐 HTTP сервер запущен на порту {port}")
    return runner


async def main():
    """Главная функция"""
    logger.info("🚀 Запуск мульти-источникового бота на Koyeb...")
    
    web_runner = None
    keep_alive_task = None
    
    try:
        web_runner = await start_web_server()
        keep_alive_task = asyncio.create_task(keep_alive())
        
        # Проверяем соединение с Telegram
        try:
            me = await asyncio.wait_for(bot.get_me(), timeout=15.0)
            logger.info(f"✅ Подключение к Telegram успешно: @{me.username}")
        except asyncio.TimeoutError:
            logger.error("❌ Таймаут при подключении к Telegram")
            return
        except Exception as e:
            logger.error(f"❌ Ошибка подключения к Telegram: {e}")
            return
        
        # Удаляем webhook с обработкой таймаута
        try:
            await asyncio.wait_for(
                bot.delete_webhook(drop_pending_updates=True), 
                timeout=10.0
            )
            logger.info("✅ Webhook удален успешно")
        except asyncio.TimeoutError:
            logger.warning("⚠️ Таймаут при удалении webhook, продолжаем...")
        except Exception as e:
            logger.warning(f"⚠️ Ошибка при удалении webhook: {e}, продолжаем...")
        
        logger.info("✅ Бот готов к работе с несколькими источниками!")
        
        # Запускаем polling с обработкой ошибок
        while True:
            try:
                await dp.start_polling(bot, skip_updates=True)
            except Exception as e:
                logger.error(f"❌ Ошибка polling: {e}")
                logger.info("🔄 Перезапуск через 5 секунд...")
                await asyncio.sleep(5)
        
    except KeyboardInterrupt:
        logger.info("👋 Получен сигнал остановки")
    except Exception as e:
        logger.error(f"❌ Критическая ошибка: {e}", exc_info=True)
    finally:
        logger.info("🛑 Завершение работы бота...")
        
        if keep_alive_task:
            keep_alive_task.cancel()
            try:
                await keep_alive_task
            except asyncio.CancelledError:
                pass
        
        try:
            await bot.session.close()
        except:
            pass
            
        if web_runner:
            try:
                await web_runner.cleanup()
            except:
                pass


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("👋 Бот остановлен")
