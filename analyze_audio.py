#!/usr/bin/env python3
import os
import sys
import struct
import wave
import logging
import pprint
from rich import print
from rich.logging import RichHandler
import mutagen
from mutagen.oggvorbis import OggVorbis
from mutagen.ogg import OggFileType
import tempfile
import subprocess

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
    datefmt="[%X]",
    handlers=[RichHandler(rich_tracebacks=True)]
)
log = logging.getLogger("audio-analyzer")

def analyze_file_basic(file_path):
    """Базовый анализ файла: размер, тип и разрешение."""
    log.info(f"Анализирую файл: {file_path}")
    
    # Проверка существования файла
    if not os.path.exists(file_path):
        log.error(f"[red]Файл не существует: {file_path}[/red]")
        return False
    
    # Основная информация о файле
    file_size = os.path.getsize(file_path)
    file_extension = os.path.splitext(file_path)[1].lower()
    
    log.info(f"Размер файла: {file_size} байт ({file_size/1024:.2f} КБ)")
    log.info(f"Расширение файла: {file_extension}")
    
    # Проверка первых байтов для определения типа файла
    with open(file_path, 'rb') as f:
        header = f.read(16)  # Читаем первые 16 байтов для определения типа файла
        
    # Проверка сигнатуры OGG (начинается с "OggS")
    if header[:4] == b"OggS":
        log.info("[green]Файл имеет корректную сигнатуру OGG[/green]")
    else:
        log.warning(f"[yellow]Файл не имеет стандартной сигнатуры OGG. Первые байты: {header[:4]}[/yellow]")
    
    return True

def analyze_with_mutagen(file_path):
    """Анализ аудиофайла с помощью библиотеки mutagen."""
    log.info("Анализирую аудио метаданные с помощью mutagen...")
    
    try:
        # Пробуем открыть как OggVorbis
        try:
            audio = OggVorbis(file_path)
            audio_type = "OggVorbis"
            log.info("[green]Файл определен как OggVorbis[/green]")
        except:
            # Пробуем определить общий тип файла
            audio = mutagen.File(file_path)
            if isinstance(audio, OggFileType):
                audio_type = "Ogg (не Vorbis)"
                log.info("[yellow]Файл определен как Ogg (но не Vorbis)[/yellow]")
            else:
                audio_type = "Неизвестный формат" if audio else "Не распознан"
                log.warning(f"[yellow]Формат файла: {audio_type}[/yellow]")
        
        if audio:
            log.info("Метаданные аудио:")
            print(f"Тип аудио: {audio_type}")
            print(f"Информация: {audio.info}")
            print("Теги:")
            pprint.pprint(dict(audio))
            
            if hasattr(audio.info, 'length'):
                log.info(f"Длительность: {audio.info.length:.2f} секунд")
            if hasattr(audio.info, 'bitrate'):
                log.info(f"Битрейт: {audio.info.bitrate/1000:.1f} kbps")
            if hasattr(audio.info, 'sample_rate'):
                log.info(f"Частота дискретизации: {audio.info.sample_rate} Hz")
    except Exception as e:
        log.error(f"[red]Ошибка при анализе с mutagen: {e}[/red]")

def try_convert_to_wav(file_path):
    """Пробуем конвертировать файл в WAV и получить информацию."""
    log.info("Попытка конвертации в WAV для проверки...")
    
    temp_wav = tempfile.mktemp(suffix='.wav')
    try:
        # Используем ffmpeg для конвертации
        cmd = [
            'ffmpeg', 
            '-i', file_path, 
            '-acodec', 'pcm_s16le', 
            '-ar', '16000', 
            '-ac', '1', 
            '-y',  # Перезаписать файл, если он существует
            temp_wav
        ]
        
        log.info(f"Выполняю команду: {' '.join(cmd)}")
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode != 0:
            log.error(f"[red]Ошибка при конвертации: {result.stderr}[/red]")
            return
        
        log.info("[green]Конвертация успешна![/green]")
        
        # Анализируем полученный WAV
        try:
            with wave.open(temp_wav, 'rb') as wav_file:
                channels = wav_file.getnchannels()
                sample_width = wav_file.getsampwidth()
                frame_rate = wav_file.getframerate()
                frames = wav_file.getnframes()
                duration = frames / frame_rate
                
                log.info(f"WAV информация:")
                log.info(f"  Каналов: {channels}")
                log.info(f"  Разрядность: {sample_width * 8} бит")
                log.info(f"  Частота: {frame_rate} Hz")
                log.info(f"  Длительность: {duration:.2f} секунд")
                
                # Проверка совместимости с Google Speech-to-Text
                if channels == 1 and frame_rate == 16000 and sample_width == 2:
                    log.info("[green]Формат совместим с Google Speech-to-Text[/green]")
                else:
                    log.warning("[yellow]Формат может быть не оптимален для Google Speech-to-Text[/yellow]")
                    log.info("Рекомендуемый формат: моно, 16000 Hz, 16 бит")
        except Exception as e:
            log.error(f"[red]Ошибка при анализе WAV: {e}[/red]")
    except Exception as e:
        log.error(f"[red]Ошибка при конвертации: {e}[/red]")
    finally:
        # Удаляем временный файл
        if os.path.exists(temp_wav):
            os.remove(temp_wav)

def check_for_telegram_voice(file_path):
    """Проверка, является ли файл голосовым сообщением Telegram."""
    log.info("Проверка на форматы, используемые Telegram для голосовых сообщений...")
    
    # Telegram обычно использует OPUS в OGG контейнере для голосовых сообщений
    try:
        cmd = ['ffprobe', '-v', 'error', '-show_entries', 
               'stream=codec_name,codec_type', '-of', 'default=noprint_wrappers=1', 
               file_path]
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if 'codec_name=opus' in result.stdout:
            log.info("[green]Файл содержит аудио в формате OPUS (используется Telegram)[/green]")
            return True
        else:
            log.warning(f"[yellow]Файл не определён как OPUS. Информация FFprobe:[/yellow]\n{result.stdout}")
            return False
    except Exception as e:
        log.error(f"[red]Ошибка при проверке формата через ffprobe: {e}[/red]")
        return False

def analyze_for_telegram_bot(file_path):
    """Полный анализ файла для использования в Telegram боте."""
    if not analyze_file_basic(file_path):
        return
    
    analyze_with_mutagen(file_path)
    check_for_telegram_voice(file_path)
    try_convert_to_wav(file_path)
    
    log.info("\n[bold]Рекомендации для Telegram бота:[/bold]")
    log.info("1. Убедитесь, что бот корректно сохраняет полученные файлы")
    log.info("2. Для распознавания речи преобразуйте OGG/OPUS в WAV (16kHz, mono)")
    log.info("3. Используйте ffmpeg для конвертации: ffmpeg -i input.ogg -ar 16000 -ac 1 output.wav")
    log.info("4. Проверьте в коде обработку типов файлов 'voice' и 'audio' из Telegram")
    log.info("5. Файлы обычно имеют content_type='voice' для голосовых сообщений")

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Использование: python analyze_audio.py <путь_к_аудиофайлу>")
        sys.exit(1)
        
    file_path = sys.argv[1]
    analyze_for_telegram_bot(file_path)
