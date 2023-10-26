import asyncio
import os
from sqlite3 import OperationalError
from typing import Any, List, Dict

import dotenv
from aiogram import Bot, types, Dispatcher
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher.filters.state import StatesGroup, State
from aiogram.utils import executor
from async_lru import alru_cache
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

        self.payment_methods_map = {}

    # @alru_cache(ttl=60 * 60 * 24)
    async def get_payment_methods_map(self):
        query = """
        SELECT billing, GROUP_CONCAT(distinct id) as payment_methods
        FROM PaymentMethods
        GROUP BY billing
        """

        result = await self.get_data(query)
        result = {row['billing'].lower(): list(map(int, row['payment_methods'].split(','))) for row in result}
        return result

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

    async def get_last_transaction_time(self, payment_method_id: int, transaction_type: str = '') -> str:
        status_str = f"AND status = '{transaction_type}'" if transaction_type else ''
        last_transaction_time_query = f'''
        SELECT dt
        FROM z_gotobill
        WHERE pay_method_id = {payment_method_id}
        {status_str}
        ORDER BY dt DESC
        LIMIT 1
        '''
        last_transaction_time = await self.get_data(last_transaction_time_query)
        return last_transaction_time[0]['dt']

    async def get_period_transactions(self, payment_method_id: int, period: str) -> List[Dict[str, Any]]:
        period_transactions_query = f'''
        SELECT id, dt, status
        FROM z_gotobill
        WHERE pay_method_id = {payment_method_id}
        AND dt >= now() - INTERVAL {period}
        '''
        period_transactions = await self.get_data(period_transactions_query)
        return period_transactions

    async def show_cancels(self, message: types.Message):
        if not await self.check_channel_id(message):
            return
        if not self.payment_methods_map:
            self.payment_methods_map = await self.get_payment_methods_map()
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
            elif payment_method_id in self.payment_methods_map['octopays']:
                pid_extract_schema = '$.data.internal_id'
            elif payment_method_id in self.payment_methods_map['swiffy']:
                pid_extract_schema = '$.callpay_transaction_id'
            query = f'''
            SELECT id,
                   dt,
                   cancel_reason_code,
                   JSON_EXTRACT(response, '{pid_extract_schema}') pid 
            FROM z_gotobill 
            WHERE pay_method_id = {payment_method_id} 
            AND status = 'cancel' 
            AND dt >= now() - INTERVAL 48 HOUR 
            ORDER BY dt DESC 
            LIMIT 10
            '''
            try:
                result = await self.get_data(query)
                result_message = tabulate(
                    [(row['dt'], row["id"], row["pid"], row["cancel_reason_code"]) for row in result],
                    headers=['bill datetime', 'inner id', 'outer id', 'cancel code'],
                    tablefmt="github"
                )
                result_message = f'Last 10 cancel transactions for payment_method {payment_method_id}\n<pre>{result_message}</pre>'
                await message.answer(result_message)
            except OperationalError:
                await message.answer('Database error - look at the logs for more information')
            except Exception as e:
                await message.answer(f'Unexpected error - {e}')

    async def show_pendings(self, message: types.Message):
        if not await self.check_channel_id(message):
            return
        if not self.payment_methods_map:
            self.payment_methods_map = await self.get_payment_methods_map()
        message_parts = message.text.split(' ')
        if len(message_parts) == 1 or not message_parts[1].isdigit():
            await message.answer(Messages.AWAITED_VARS.format(awaited_vars=f'payment_method_id (int)'))
        else:
            payment_method_id = int(message_parts[1])

            query = f'''
            SELECT id, dt
            FROM z_gotobill 
            WHERE pay_method_id = {payment_method_id} 
            AND status = 'pending' 
            AND dt >= now() - INTERVAL 48 HOUR 
            ORDER BY dt DESC 
            LIMIT 20, 10
            '''
            try:
                result = await self.get_data(query)
                result_message = tabulate(
                    [(row["dt"], row["id"]) for row in result],
                    headers=['bill datetime', 'inner id'],
                    tablefmt="github"
                )
                result_message = f'10 example pending transactions for payment_method {payment_method_id}\n<pre>{result_message}</pre>'
                await message.answer(result_message)
            except OperationalError:
                await message.answer('Database error - look at the logs for more information')
            except Exception as e:
                await message.answer(f'Unexpected error - {e}')

    async def show_last_success_time(self, message: types.Message):
        if not await self.check_channel_id(message):
            return
        message_parts = message.text.split(' ')
        if len(message_parts) == 1 or not message_parts[1].isdigit():
            await message.answer(Messages.AWAITED_VARS.format(awaited_vars=f'payment_method_id (int)'))
        else:
            payment_method_id = int(message_parts[1])
            result = await self.get_last_transaction_time(payment_method_id, 'success')
            if len(result):
                await message.answer(f'Last success time of payment method {payment_method_id}: <code>{result[0]["dt"]} UTC</code>')
            else:
                await message.answer(f'Not found success transactions for {payment_method_id}')

    async def get_method_info(self, message: types.Message):
        if not await self.check_channel_id(message):
            return
        message_parts = message.text.split(' ')
        if len(message_parts) == 1 or not message_parts[1].isdigit():
            await message.answer(Messages.AWAITED_VARS.format(awaited_vars=f'payment_method_id (int)'))
        else:
            payment_method_id = int(message_parts[1])
            status_query = f"SELECT name, active FROM PaymentMethods WHERE id = {payment_method_id}"
            status_result = await self.get_data(status_query)
            if len(status_result):
                method_name = status_result[0]['name']
                method_status = status_result[0]['active']
            else:
                await message.answer(f'Not found payment method {payment_method_id}')
                return
            last_try_time = await self.get_last_transaction_time(payment_method_id)
            last_success_time = await self.get_last_transaction_time(payment_method_id, 'success')
            last_hour_transactions = await self.get_period_transactions(payment_method_id, '1 HOUR')
            last_hour_success = len(filter(lambda x: x['status'] == 'success', last_hour_transactions))
            last_hour_cancels = len(filter(lambda x: x['status'] == 'cancel', last_hour_transactions))
            last_hour_pendings = len(filter(lambda x: x['status'] == 'pending', last_hour_transactions))

            await message.answer(f'''
            <b>Payment method:</b> <code>{method_name}[{payment_method_id}]</code>
            <b>Status:</b> <code>{'enabled' if method_status else 'disabled'}</code>
            <b>Last try:</b> <code>{last_try_time} UTC</code>
            <b>Last success:</b> <code>{last_success_time} UTC</code>
            <b>Last hour success count:</b> <code>{last_hour_success}</code>
            <b>Last hour cancel count:</b> <code>{last_hour_cancels}</code>
            <b>Last hour pending count:</b> <code>{last_hour_pendings}</code>
            ''')

    async def default_handle(self, message: types.Message):
        ...

    def start(self):

        # Commands
        self.dp.register_message_handler(self.show_cancels, commands=['show_cancels'])
        self.dp.register_message_handler(self.show_pendings, commands=['show_pendings'])
        self.dp.register_message_handler(self.show_last_success_time, commands=['show_last_success'])
        self.dp.register_message_handler(self.get_method_info, commands=['get_info'])

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
