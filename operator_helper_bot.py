import asyncio
import os
from typing import Any, List, Dict

import dotenv
from aiogram import Bot, types, Dispatcher
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher.filters.state import StatesGroup, State
from aiogram.utils import executor
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from tabulate import tabulate

from content.operator_helper_bot import Messages


class Context(StatesGroup):
    payment_method_id = State()


class OperatorHelperBot:

    def __init__(self):
        TELEGRAM_API_TOKEN = os.environ.get('OPERATOR_HELPER_BOT_TOKEN')
        TELEGRAM_CHANNEL_ID = os.environ.get('OPERATOR_HELPER_CHANNEL_ID')

        self.loop = asyncio.get_event_loop()
        self.bot = Bot(token=TELEGRAM_API_TOKEN, loop=self.loop, parse_mode=types.ParseMode.HTML)
        self.channel_id = TELEGRAM_CHANNEL_ID
        self.dp = Dispatcher(self.bot, storage=MemoryStorage())

        self.payment_methods_map = {
            'monetix': [145, 275, 276, 277, 278, 282, 283, 284, 285, 286, 287, 288, 289, 292, 297, 301, 302, 303, 305,
                        306, 307, 308, 309, 310, 311, 318, 319, 332, 333, 334, 335, 340, 341, 342, 343, 348, 349, 350,
                        351, 352, 353, 354, 363, 369, 370, 371, 372, 373, 374, 375, 376, 377, 381, 387, 388, 389, 393,
                        394, 395, 397, 399, 401, 443, 457, 467],
            'expay': [465, 466]
        }

    async def check_channel_id(self, message: types.Message):
        if message.chat.id != int(self.channel_id):
            await message.answer(Messages.NOT_IN_CHANNEL)
            return False
        return True

    async def get_data(self, query: str) -> List[Dict[str, Any]]:
        mysql_username = os.environ.get('MYSQL_USERNAME')
        mysql_password = os.environ.get('MYSQL_PASSWORD')
        mysql_host = os.environ.get('MYSQL_HOST')
        mysql_port = os.environ.get('MYSQL_PORT')
        mysql_db = os.environ.get('MYSQL_DB')
        engine = create_async_engine(
            f"mysql+aiomysql://{mysql_username}:{mysql_password}@{mysql_host}:{mysql_port}/{mysql_db}")
        query = text(query)
        async with engine.begin() as conn:
            result = await conn.execute(query)
            result = result.fetchall()
            result = [row._mapping for row in result]

        return result

    async def show_cancels(self, message: types.Message):
        if not await self.check_channel_id(message):
            return
        message_parts = message.text.split(' ')
        if len(message_parts) == 1 or not message_parts[1].isdigit():
            await message.answer(Messages.AWAITED_VARS.format(awaited_vars=f'payment_method_id (int)'))
        else:
            payment_method_id = int(message_parts[1])
            pid_extract_schema = ''
            if payment_method_id in self.payment_methods_map['monetix']:
                pid_extract_schema = '$.operation.id'
            elif payment_method_id in self.payment_methods_map['expay']:
                pid_extract_schema = '$.refer'
            query = f'''
            SELECT id, 
                   cancel_reason_code,
                   JSON_EXTRACT(response, '{pid_extract_schema}') pid 
            FROM rdv6088.z_gotobill 
            WHERE pay_method_id = {payment_method_id} 
            AND status = 'cancel' 
            AND dt >= now() - INTERVAL 48 HOUR 
            ORDER BY dt DESC 
            LIMIT 10
            '''
            result = await self.get_data(query)
            result_message = tabulate(
                [(row["id"], row["pid"], row["cancel_reason_code"]) for row in result],
                headers=['inner id', 'outer id', 'cancel code'],
                tablefmt="github"
            )
            result_message = f'Last 10 cancel transactions for payment_method {payment_method_id}\n<pre>{result_message}</pre>'
            await message.answer(result_message)

    async def show_last_success_time(self, message: types.Message):
        if not await self.check_channel_id(message):
            return
        message_parts = message.text.split(' ')
        if len(message_parts) == 1 or not message_parts[1].isdigit():
            await message.answer(Messages.AWAITED_VARS.format(awaited_vars=f'payment_method_id (int)'))
        else:
            payment_method_id = int(message_parts[1])
            query = f"SELECT dt FROM rdv6088.z_gotobill WHERE pay_method_id = {payment_method_id} AND status = 'success' ORDER BY dt DESC LIMIT 1"
            result = await self.get_data(query)
            if len(result):
                await message.answer(f'Last success time of payment method {payment_method_id}: <code>{result[0]["dt"]} UTC</code>')
            else:
                await message.answer(f'Not found success transactions for {payment_method_id}')

    async def default_handle(self, message: types.Message):
        ...

    def start(self):

        # Commands
        self.dp.register_message_handler(self.show_cancels, commands=['show_cancels'])
        self.dp.register_message_handler(self.show_last_success_time, commands=['show_last_success'])

        # Default
        self.dp.register_message_handler(self.default_handle, regexp='.')

        # Run bot
        executor.start_polling(self.dp, loop=self.loop, skip_updates=True)


if __name__ == '__main__':
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

    dotenv.load_dotenv(
        os.path.join(BASE_DIR, '.env'),
        verbose=True
    )

    bot = OperatorHelperBot()

    bot.start()
