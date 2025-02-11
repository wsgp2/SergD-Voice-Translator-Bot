import os
import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from telegram.constants import ChatType
from openai import OpenAI
from dotenv import load_dotenv
import tempfile
import json
import re
from google.cloud import texttospeech

# Загружаем переменные окружения
load_dotenv()

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('bot.log')
    ]
)
logger = logging.getLogger(__name__)
logger.info('🚀 Бот запускается...')

# Инициализация OpenAI
openai_client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))
google_client = texttospeech.TextToSpeechClient()

LANG_EMOJIS = {
    'ru': '🇷🇺',
    'id': '🇮🇩',
    'en': '🇺🇸'
}

VOICES = {
    'ru': 'shimmer',  # женский голос 👩
    'id': 'nova',     # женский голос 👩
    'en': 'echo'      # мужской голос 👨
}

def clean_text(text: str) -> str:
    """Очищает текст от лишних пробелов и знаков препинания"""
    text = re.sub(r'\s+', ' ', text)
    text = re.sub(r'\s+([.,!?])', r'\1', text)
    text = re.sub(r'[«»"""]', '"', text)
    return text.strip()

async def transcribe_audio(audio_file_path: str) -> tuple[str, str]:
    """Преобразует аудио в текст используя Whisper API"""
    try:
        logger.info(f"Начинаем транскрибацию файла: {audio_file_path}")
        with open(audio_file_path, "rb") as audio_file:
            response = openai_client.audio.transcriptions.create(
                model="whisper-1",
                file=audio_file,
                response_format="verbose_json"
            )
            logger.info(f"Получен ответ от Whisper API: {response}")
            return response.text, 'ru' if 'russian' in response.language.lower() else 'id'
    except Exception as e:
        logger.error(f"Ошибка при транскрибации: {str(e)}", exc_info=True)
        raise

async def translate_with_gpt(text: str, source_lang: str) -> dict:
    """Переводит текст используя ChatGPT"""
    translations = {source_lang: clean_text(text)}
    
    try:
        logger.info(f"🔄 Начинаем перевод текста: {text} с языка {source_lang}")
        # Формируем промпт для GPT
        if source_lang == 'ru':
            system_prompt = """You are a professional translator with expertise in Russian, English, and Indonesian languages. 
            Your task is to translate the given Russian text while:
            1. 🎯 Preserving the original meaning and context
            2. 💫 Using natural, fluent language in the target languages
            3. 🎭 Maintaining the tone and style of the original text
            4. 🔍 Being attentive to cultural nuances
            5. 📚 Using appropriate idioms when applicable
            
            Return translations in this exact JSON format:
            {"english": "translation", "indonesian": "translation"}"""
        else:
            system_prompt = """You are a professional translator with expertise in Indonesian, English, and Russian languages.
            Your task is to translate the given Indonesian text while:
            1. 🎯 Preserving the original meaning and context
            2. 💫 Using natural, fluent language in the target languages
            3. 🎭 Maintaining the tone and style of the original text
            4. 🔍 Being attentive to cultural nuances
            5. 📚 Using appropriate idioms when applicable
            
            Return translations in this exact JSON format:
            {"english": "translation", "russian": "translation"}"""
            
        user_prompt = f"Translate this text with attention to context and cultural nuances: {text}"

        response = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            response_format={ "type": "json_object" }
        )
        
        # Парсим JSON ответ
        result = json.loads(response.choices[0].message.content)
        logger.info(f"Получен перевод: {result}")
        
        if source_lang == 'ru':
            translations['en'] = clean_text(result['english'])
            translations['id'] = clean_text(result['indonesian'])
        else:
            translations['en'] = clean_text(result['english'])
            translations['ru'] = clean_text(result['russian'])
            
    except Exception as e:
        logger.error(f"Ошибка при переводе: {str(e)}", exc_info=True)
        translations['en'] = "Error during translation"
        translations['id' if source_lang == 'ru' else 'ru'] = "Error during translation"
    
    return translations

async def generate_audio(text: str, lang: str) -> bytes:
    """Генерирует аудио из текста используя OpenAI TTS или Google TTS для индонезийского языка"""
    try:
        logger.info(f"🔊 Генерируем аудио для текста: {text} на языке {lang}")
        
        # Для индонезийского языка используем Google Cloud TTS
        if lang == 'id':
            input_text = texttospeech.SynthesisInput(text=text)
            
            voice = texttospeech.VoiceSelectionParams(
                language_code='id-ID',
                name='id-ID-Standard-A'
            )
            
            audio_config = texttospeech.AudioConfig(
                audio_encoding=texttospeech.AudioEncoding.MP3
            )
            
            response = google_client.synthesize_speech(
                input=input_text,
                voice=voice,
                audio_config=audio_config
            )
            
            return response.audio_content
            
        # Для остальных языков используем OpenAI TTS как раньше
        if lang not in VOICES:
            logger.error(f"❌ Неподдерживаемый язык для TTS: {lang}")
            raise ValueError(f"Unsupported language for TTS: {lang}")
            
        response = openai_client.audio.speech.create(
            model="tts-1",
            voice=VOICES[lang],
            input=text
        )
        return response.content
        
    except Exception as e:
        logger.error(f"❌ Ошибка при генерации аудио: {str(e)}", exc_info=True)
        raise

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start"""
    await update.message.reply_text(
        'Привет! Я бот для перевода голосовых сообщений.\n\n'
        'Я автоматически определяю язык (русский или индонезийский) и перевожу:\n'
        'Русский → Индонезийский\n'
        'Индонезийский → Русский\n'
        ' + добавляю перевод на английский\n\n'
        'Просто отправь мне голосовое сообщение!'
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /help"""
    await update.message.reply_text(
        'Как использовать бота:\n\n'
        '1. Отправьте голосовое сообщение\n'
        '2. Бот определит язык\n'
        '3. Переведет на другие языки\n'
        '4. Покажет все переводы\n'
        '5. Отправит аудио с переводом\n\n'
        'Поддерживаемые языки:\n'
        'Русский\n'
        'Индонезийский\n'
        'Английский (дополнительно)'
    )

async def handle_business_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработка голосовых сообщений в бизнес-режиме"""
    chat_type = update.message.chat.type if update.message and update.message.chat else "unknown"
    logger.info(f"🎯 Получено бизнес-сообщение. Тип чата: {chat_type}")
    await handle_voice(update, context)

async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка голосовых сообщений"""
    try:
        # Отправляем сообщение о начале обработки
        processing_msg = await update.message.reply_text("🎯 Обрабатываю голосовое сообщение...\n\n🔄 Это займет несколько секунд")
        
        # Скачиваем голосовое сообщение
        voice = await update.message.voice.get_file()
        
        # Создаем временный файл для аудио
        with tempfile.NamedTemporaryFile(suffix='.ogg', delete=False) as temp_audio:
            # Скачиваем аудио во временный файл
            await voice.download_to_drive(temp_audio.name)
            logger.info(f"💾 Сохранено голосовое сообщение: {temp_audio.name}")
            
            try:
                # Распознаем речь и определяем язык через Whisper API
                detected_text, detected_lang = await transcribe_audio(temp_audio.name)
                logger.info(f"🎯 Распознан текст: {detected_text}, язык: {detected_lang}")
                
                # Получаем переводы через ChatGPT
                translations = await translate_with_gpt(detected_text, detected_lang)
                logger.info(f"📝 Получены переводы: {translations}")
                
                # Формируем текстовое сообщение с эмодзи
                message = f"""🎯 Определен язык: {LANG_EMOJIS[detected_lang]}

💭 Исходный текст:
{LANG_EMOJIS[detected_lang]} {translations[detected_lang]}

🌟 Переводы:
{LANG_EMOJIS['en']} {translations['en']}

{LANG_EMOJIS['id' if detected_lang == 'ru' else 'ru']} {translations['id' if detected_lang == 'ru' else 'ru']}

🎤 Отправляю озвученный перевод..."""
                
                # Отправляем текстовый перевод
                await update.message.reply_text(message.strip())
                
                # Генерируем и отправляем аудио перевода на целевом языке
                target_lang = 'id' if detected_lang == 'ru' else 'ru'
                target_text = translations[target_lang]
                logger.info(f"🎤 Генерируем аудио перевода на языке {target_lang}: {target_text}")
                audio_content = await generate_audio(target_text, target_lang)
                
                # Сохраняем аудио во временный файл
                with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as temp_tts:
                    temp_tts.write(audio_content)
                    logger.info(f"💾 Сохранено аудио перевода: {temp_tts.name}")
                    # Отправляем аудио перевода
                    await update.message.reply_voice(temp_tts.name)
                    
            finally:
                # Удаляем временные файлы
                os.unlink(temp_audio.name)
                if 'temp_tts' in locals():
                    os.unlink(temp_tts.name)
        
        # Удаляем сообщение о обработке
        await processing_msg.delete()
        
    except Exception as e:
        logger.error(f"❌ Ошибка при обработке голосового сообщения: {str(e)}", exc_info=True)
        await update.message.reply_text("😔 Извините, произошла ошибка при обработке сообщения.")

def main():
    """Запуск бота"""
    # Получаем токены из переменных окружения
    telegram_token = os.getenv('TELEGRAM_TOKEN')
    if not telegram_token:
        logger.error("Не найден токен Telegram бота!")
        return
    
    if not os.getenv('OPENAI_API_KEY'):
        logger.error("Не найден токен OpenAI API!")
        return

    # Создаем приложение
    application = Application.builder().token(telegram_token).build()

    # Добавляем обработчики
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    
    # Обработка всех голосовых сообщений
    application.add_handler(MessageHandler(
        filters.VOICE,
        handle_voice,
        block=False
    ))

    # Запускаем бота
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
