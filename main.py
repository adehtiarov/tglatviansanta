#!/usr/bin/env python
# pylint: disable=unused-argument
# This program is dedicated to the public domain under the CC0 license.

"""
Simple Bot to reply to Telegram messages.

First, a few handler functions are defined. Then, those functions are passed to
the Application and registered at their respective places.
Then, the bot is started and runs until we press Ctrl-C on the command line.

Usage:
Basic Echobot example, repeats messages.
Press Ctrl-C on the command line or send a signal to the process to stop the
bot.
"""
from dotenv import load_dotenv
load_dotenv()

import logging
import os
import tempfile
import asyncio

from openai import AsyncOpenAI 
openai_client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"), organization=os.getenv("OPENAI_ORGANIZATION_ID"))
assistant_id = os.getenv("OPENAI_ASSISTANT_ID")

from telegram import ForceReply, Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from pydub import AudioSegment
import requests
from io import BytesIO

# Enable logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
# set higher logging level for httpx to avoid all GET and POST requests being logged
logging.getLogger("httpx").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

threads = {}

# Define a few command handlers. These usually take the two arguments update and
# context.
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a message when the command /start is issued."""
    user = update.effective_user
    threads[user.id] = await openai_client.beta.threads.create()
    await update.message.reply_html(
        rf"""Sveiki {user.mention_html()}! Добро пожаловать в увлекательное путешествие изучения латышского языка!
Я могу помочь вам с тренировкой на основании материалов подготовки к экзамену, которые я уже узнаю.
Практикуйте разговоры на латышском со мной.
Если отправите текст, то я отвечу текстом. Если отправите голосовое сообщение, то я отвечу и голосовым сообщением, и текстом.
Для сброса текущей беседы, отправьте /start""",
        reply_markup=ForceReply(selective=True),
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a message when the command /help is issued."""
    await update.message.reply_text("Help!")

async def generate_response(user_id, text):
    if user_id not in threads:
        threads[user_id] = await openai_client.beta.threads.create()
    thread = threads[user_id]
    message = await openai_client.beta.threads.messages.create(
        thread_id=thread.id,
        role="user",
        content=text
    )
    run = await openai_client.beta.threads.runs.create(
        thread_id=thread.id,
        assistant_id=assistant_id
    )
    await asyncio.sleep(1)
    while run.status == "queued" or run.status == "in_progress":
        run = await openai_client.beta.threads.runs.retrieve(
            thread_id=thread.id,
            run_id=run.id
        )
        await asyncio.sleep(1)

    response = ""
    if run.status == "completed":
        messages = await openai_client.beta.threads.messages.list(thread_id=thread.id)
        response = messages.data[0].content[0].text.value
    else:
        response = "Something went wrong. Please try again. Assistant run status: " + run.status
    return response

async def echo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Echo the user message."""
    user = update.effective_user
    response = await generate_response(user.id, update.message.text)
    await update.message.reply_text(response)

async def transcribe_audio(audio_stream):
    transcript = await openai_client.audio.transcriptions.create(
        model="whisper-1", 
        file=audio_stream,
        response_format="text",
        temperature=0.0,
        language="lv",
    )
    return transcript

async def get_tts_audio(text):
    response = await openai_client.audio.speech.create(
        model="tts-1",
        voice="echo",
        input=text,
    )
    return response.content

async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle voice messages."""
    print("Voice received")
    voice = update.message.voice
    file = await context.bot.get_file(voice.file_id)
    file_path = file.file_path

    # Download the voice file
    response = requests.get(file_path)
    print(f"Downloaded: {file_path}")
    voice_file = BytesIO(response.content)

    # Convert from OGG to MP3
    audio = AudioSegment.from_file(voice_file, format="ogg", codec="opus")

    audio_prompt = ""
    with tempfile.NamedTemporaryFile(suffix=".mp3") as temp_mp3:
        audio.export(temp_mp3.name, format="mp3")
        temp_mp3.seek(0)
        print(f"Converted: {temp_mp3.name}")
        with open(temp_mp3.name, "rb") as audio_stream:
            audio_prompt = await transcribe_audio(audio_stream)
            print(f"Transcribed: {audio_prompt}")

    assistant_response = await generate_response(update.effective_user.id, audio_prompt)
    print(f"Assistant response: {assistant_response}")
    await update.message.reply_text(assistant_response)
    with BytesIO(await get_tts_audio(assistant_response)) as audio_file:
        audio_file.seek(0)
        # Send the MP3 file back to the user
        await update.message.reply_audio(audio_file, filename="voice_message.mp3")
        print("Sent audio response")

def main() -> None:
    """Start the bot."""
    print(os.getenv("OPENAI_API_KEY"))
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        logger.error("No token provided")
        return
    # Create the Application and pass it your bot's token.
    application = Application.builder().token(token).build()

    # on different commands - answer in Telegram
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))

    # on non command i.e message - echo the message on Telegram
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, echo))
    application.add_handler(MessageHandler(filters.VOICE, handle_voice))

    # Run the bot until the user presses Ctrl-C
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
