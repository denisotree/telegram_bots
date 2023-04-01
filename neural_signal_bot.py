import os
import logging
import dotenv
from typing import List, Optional, Tuple
from io import StringIO
from gtts import gTTS
import email
import quopri
import re
from time import sleep
import subprocess
import asyncio
import pickle

from tqdm import tqdm
from telegram import Bot
import dbm

from content.neural_signal_bot import DISCLAIMER
from lib.gmail_client import GmailClient

os.environ.setdefault('PYDEVD_WARN_EVALUATION_TIMEOUT', str(60 * 2))

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger('telegram_bot.neural_signal_bot')


class NeuralSignalBot:
    def __init__(self, telegram_api_token: str, mail_username: str, mail_password: str, channel_name: str):
        self.telegram_api_token = telegram_api_token
        self.mail_username = mail_username
        self.mail_password = mail_password
        self.channel_name = channel_name

        self.sender_address = 'daily@meduza.io'
        self.directory_name = 'data'

    def get_unread_messages(self) -> List[list]:
        mail_client = GmailClient(
            username=self.mail_username,
            password=self.mail_password
        )
        mails = mail_client.get_unseen_from_sender(sender=self.sender_address)
        return mails

    def get_filename(self, subject: str) -> str:
        filename = f"signal_{subject}.mp3"
        filename = os.path.join(self.directory_name, filename)
        return filename

    def process_message(self, message: list) -> Optional[Tuple[str, str]]:
        message = email.message_from_bytes(message[0][1])
        subject = quopri.decodestring(
            message['subject'].split('?')[3]).decode()
        if '\xa0' in subject:
            subject = subject.replace('\xa0', ' ')
        filename = self.get_filename(subject)
        print(f'Start upload episode - {subject}')
        body = message.get_payload()[0].get_payload(decode=True).decode()
        body = body.replace('*', '')
        body = body.replace('\n', '')
        body = body.replace('\r', '')
        body = re.sub(
            r'\(?https?:\/\/(?:www\.)?[-a-zA-Z0-9@:\';∂%._\+~#=〈≷,!]{1,256}\.[a-zA-Z0-9()\';∂〈≷,!]{1,6}(?:[-a-zA-Z0-9()@:\';∂%_\+.~#?&\/=〈≷,!]*)', '', body)
        body = re.sub(
            r'\(mailto[-a-zA-Z0-9()@:\';∂%_\+.~#?&\/=〈≷,]*', '', body)
        end_phrase = 'Будущее — это вы.'
        end_phrase_position = body.find(end_phrase)
        if end_phrase_position > 0:
            body = body[:end_phrase_position+len(end_phrase)]
        else:
            alter_end_phrase = 'Отписаться можно тут'
            alter_end_phrase_position = body.find(alter_end_phrase)
            if alter_end_phrase_position > 0:
                body = body[:alter_end_phrase_position + len(alter_end_phrase)]

        return body, subject

    def generate_audio(self, text: str, subject: str) -> str:
        sio = StringIO(text)
        audios = []
        chunk = sio.read(5000)
        while True:
            if chunk == '':
                break
            audio = gTTS(text=chunk, lang="ru")
            audios.append(audio)
            chunk = sio.read(5000)

        filename = self.get_filename(subject)
        with open(filename, 'wb') as af:
            for part in tqdm(audios):
                part.write_to_fp(af)
        return filename

    def speed_up_audio(self, filename: str, tempo: float = 1.5) -> str:
        compressed_filename = f"{filename[:-4]}_compressed.mp3"
        command = f'ffmpeg -y -i "{filename}" -af "atempo={tempo}" -hide_banner -loglevel error "{compressed_filename}"'
        try:
            subprocess.run(command, shell=True, check=True, timeout=120)
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Error: {e.output.decode()}") from e
        os.remove(filename)
        return compressed_filename
    
    async def get_channel_id(self, channel_name: str) -> Optional[int]:
        bot = Bot(token=self.telegram_api_token)
        async with bot:
            updates = await bot.get_updates()
            comparable_channel_names = [u.channel_post.chat for u in updates if u.channel_post]
            comparable_channel_ids = [c.id for c in comparable_channel_names if c.username == channel_name]
            if comparable_channel_ids:
                channel_id = next(iter(comparable_channel_ids))
                return channel_id
            return 

    async def send_telegram_message(self, message: str, audiofile_name: str):
        
        bot = Bot(token=self.telegram_api_token)
        async with bot:
            with dbm.open('data/data.db', 'c') as db:
                channel_id = db.get('channel_id')
            if not channel_id:
                channel_id = await self.get_channel_id(self.channel_name)
                with dbm.open('data/data.db', 'c') as db:
                    db['channel_id'] = pickle.dumps(channel_id)
            else:
                channel_id = pickle.loads(channel_id)
            audio_title_expression = re.compile(r'signal_#\d+. (?P<title>[A-Za-zА-Яа-я «»!?0-9]+).')
            audio_title = audio_title_expression.search(audiofile_name).group('title')
            with open(audiofile_name, 'rb') as af:
                await bot.send_audio(
                    chat_id=channel_id,
                    title=audio_title,
                    audio=af,
                    caption=message
                )
            os.remove(audiofile_name)

    def start(self):
        logger.info(f"Starting bot")
        if not os.path.exists(self.directory_name):
            os.mkdir(self.directory_name)
        
        while True:
            unreed_messages = self.get_unread_messages()
            if unreed_messages:
                for raw_message in unreed_messages:
                    result = self.process_message(raw_message)
                    if result is None:
                        logging.exception(f"Error while processing message")
                        continue
                    prepared_message, subject = result
                    audiofile_name = self.generate_audio(prepared_message, subject)
                    compressed_audiofile_name = self.speed_up_audio(
                        audiofile_name)
                    asyncio.run(self.send_telegram_message(DISCLAIMER, compressed_audiofile_name))
            logger.info(f"Sleeping for 1 hour")
            sleep(3600)


def main():

    TELEGRAM_API_TOKEN = os.environ.get('NEURAL_SIGNAL_BOT_TOKEN')
    TELEGRAM_CHANNEL_NAME = os.environ.get('NEURAL_SIGNAL_CHANNEL')
    MAIL_USERNAME = os.environ.get('MAIL_USERNAME')
    MAIL_PASSWORD = os.environ.get('MAIL_PASSWORD')

    # Create an instance of the bot
    bot = NeuralSignalBot(
        telegram_api_token=TELEGRAM_API_TOKEN,
        mail_username=MAIL_USERNAME,
        mail_password=MAIL_PASSWORD,
        channel_name=TELEGRAM_CHANNEL_NAME
    )

    # Start the bot
    bot.start()


if __name__ == '__main__':
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

    dotenv.load_dotenv(
        os.path.join(BASE_DIR, '.env'),
        verbose=True
    )
    main()
