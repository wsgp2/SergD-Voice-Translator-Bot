import os
from openai import OpenAI
from dotenv import load_dotenv
from google.cloud import texttospeech

# Загружаем переменные окружения
load_dotenv()

# Инициализация клиентов
openai_client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))
google_client = texttospeech.TextToSpeechClient()

# Тестовые тексты
test_texts = {
    'id': """
    Selamat datang di dunia teknologi modern! Hari ini kita akan membahas tentang kecerdasan buatan dan dampaknya terhadap kehidupan sehari-hari. 
    
    Artificial Intelligence, atau AI, telah mengubah cara kita bekerja, berkomunikasi, dan bahkan berpikir. Dari asisten virtual seperti Siri dan Alexa, 
    hingga sistem rekomendasi di platform streaming dan e-commerce, AI ada di mana-mana.
    
    Di Indonesia, adopsi teknologi AI terus meningkat. Banyak startup dan perusahaan besar yang mulai mengintegrasikan AI ke dalam layanan mereka. 
    Ini membuka peluang baru untuk inovasi dan pertumbuhan ekonomi digital.
    
    Namun, kita juga harus mempertimbangkan tantangan dan risiko yang muncul. Privasi data, keamanan siber, dan dampak sosial adalah beberapa 
    hal yang perlu kita perhatikan. Mari bersama-sama membangun masa depan yang lebih baik dengan teknologi yang bertanggung jawab.
    """,
    
    'ru': """
    Добро пожаловать в мир современных технологий! Сегодня мы поговорим об искусственном интеллекте и его влиянии на нашу повседневную жизнь.

    Искусственный интеллект, или ИИ, изменил то, как мы работаем, общаемся и даже мыслим. От виртуальных помощников, таких как Siri и Alexa, 
    до рекомендательных систем на стриминговых платформах и в электронной коммерции - ИИ повсюду.

    В России развитие технологий ИИ идёт быстрыми темпами. Многие стартапы и крупные компании начинают интегрировать ИИ в свои сервисы. 
    Это открывает новые возможности для инноваций и роста цифровой экономики.

    Однако мы также должны учитывать возникающие проблемы и риски. Конфиденциальность данных, кибербезопасность и социальные последствия - 
    это лишь некоторые аспекты, на которые нам нужно обратить внимание. Давайте вместе строить лучшее будущее с помощью ответственных технологий.
    """
}

# Конфигурация голосов для Google TTS
GOOGLE_VOICES = {
    'id': {
        'name': 'id-ID-Standard-A',
        'language_code': 'id-ID'
    },
    'en': {
        'name': 'en-US-Standard-C',
        'language_code': 'en-US'
    },
    'ru': {
        'name': 'ru-RU-Standard-A',
        'language_code': 'ru-RU'
    }
}

def generate_google_tts(text, lang):
    """Генерирует аудио используя Google Cloud TTS"""
    input_text = texttospeech.SynthesisInput(text=text)
    
    voice = texttospeech.VoiceSelectionParams(
        language_code=GOOGLE_VOICES[lang]['language_code'],
        name=GOOGLE_VOICES[lang]['name']
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

def generate_openai_tts(text, voice='alloy'):
    """Генерирует аудио используя OpenAI TTS"""
    response = openai_client.audio.speech.create(
        model="tts-1",
        voice=voice,
        input=text
    )
    return response.content

def print_text_info(text):
    print(f"Текст: {text}")
    print(f"Длина текста: {len(text)}")
    print(f"Байты текста: {text.encode('utf-8')}")
    print(f"Символы: {[ord(c) for c in text]}")

# Тестируем Google TTS
for lang, text in test_texts.items():
    print('\n' + '=' * 50)
    print(f'Тестируем язык: {lang}')
    print(f'Текст:\n{text}')
    
    # Генерируем аудио с помощью Google Cloud TTS
    try:
        client = texttospeech.TextToSpeechClient()
        synthesis_input = texttospeech.SynthesisInput(text=text)
        
        voice = texttospeech.VoiceSelectionParams(
            language_code=GOOGLE_VOICES[lang]['language_code'],
            name=GOOGLE_VOICES[lang]['name']
        )
        
        audio_config = texttospeech.AudioConfig(
            audio_encoding=texttospeech.AudioEncoding.MP3,
            speaking_rate=1.0
        )
        
        response = client.synthesize_speech(
            input=synthesis_input,
            voice=voice,
            audio_config=audio_config
        )
        
        output_file = f'test_google_long_{lang}.mp3'
        with open(output_file, 'wb') as out:
            out.write(response.audio_content)
        print(f'✅ Google TTS успешно сгенерировано: {output_file}')
        
    except Exception as e:
        print(f'❌ Ошибка Google TTS: {e}')
