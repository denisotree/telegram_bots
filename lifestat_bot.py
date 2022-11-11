import asyncio
import os
import pickle
from dataclasses import dataclass, field
from typing import Dict

import dotenv
from aiogram import Bot, types, Dispatcher
from aiogram.contrib.fsm_storage.redis import RedisStorage2
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import StatesGroup, State
from aiogram.utils import executor
from aiogram.utils.callback_data import CallbackData
from aioredis import Redis

from content.lifestat_bot import Messages


@dataclass
class Counter:
    name: str
    value: int


@dataclass
class UserState:
    id: int
    username: str = ''
    counters: Dict[str, Counter] = field(default_factory=dict)


class UserContext(StatesGroup):
    counter_name_create = State()
    counter_name_for_update = State()
    counter_name_update_new_name = State()
    counter_name_delete = State()


class AppData:

    def __init__(self, host: str, port: int, db: int, password: str):
        self.storage = Redis(
            host=host,
            port=port,
            db=db,
            password=password
        )
        self.storage_prefix = 'tg_bot_storage'

    def get_key(self, user_id: int) -> str:
        return f'{self.storage_prefix}:{user_id}'

    async def get_user_state(self, user_id: int) -> UserState:
        user_state = await self.storage.get(self.get_key(user_id))
        if not user_state:
            user_state = UserState(user_id)
        else:
            user_state = pickle.loads(user_state)
        return user_state

    async def set_user_state(self, user_id: int, state: UserState):
        await self.storage.set(self.get_key(user_id), pickle.dumps(state))


class LifeStatBot:

    def __init__(self):

        TELEGRAM_API_TOKEN = os.environ.get('TELEGRAM_API_TOKEN')
        REDIS_HOST = os.environ.get('REDIS_HOST')
        REDIS_PASSWORD = os.environ.get('REDIS_PASSWORD')

        self.loop = asyncio.get_event_loop()
        self.bot = Bot(token=TELEGRAM_API_TOKEN, loop=self.loop, parse_mode=types.ParseMode.HTML)
        storage = RedisStorage2(
            host=REDIS_HOST,
            port=6379,
            db=1,
            password=REDIS_PASSWORD,
            loop=self.loop
        )
        self.dp = Dispatcher(self.bot, storage=storage)
        self.counter_cb = CallbackData('counter', 'counter_name', 'action', 'value')
        self.app_data = AppData(host=REDIS_HOST, port=6379, db=1, password=REDIS_PASSWORD)

    def get_button(self, counter_name: str, button_text: str, action: str, value: int):
        return types.InlineKeyboardButton(
            button_text,
            callback_data=self.counter_cb.new(counter_name=counter_name, action=action, value=value)
        )

    def get_keyboard(self, counters: Dict[str, Counter]) -> types.InlineKeyboardMarkup:
        keyword_markup = types.InlineKeyboardMarkup()
        for counter in counters.values():
            keyword_markup.row(
                self.get_button(counter.name, counter.name, action='pass', value=counter.value),
                self.get_button(counter.name, '-', action='-', value=counter.value),
                self.get_button(counter.name, '+', action='+', value=counter.value),
                self.get_button(counter.name, 'x', action='reset', value=counter.value)
            )
        return keyword_markup

    @staticmethod
    def get_counters_review_message(counters: Dict[str, Counter]) -> str:
        return '\n'.join(
            f'Your {counter.name.lower()} counter value is {counter.value}' for counter in counters.values()
        )

    async def check_username(self, user_state: UserState, message: types.Message):
        if not user_state.username:
            user_state.username = message.from_user.username
            await self.app_data.set_user_state(message.from_user.id, user_state)

    async def start_handle(self, message: types.Message):
        user_state = await self.app_data.get_user_state(message.from_user.id)
        await self.check_username(user_state, message)
        if not user_state.counters:
            await message.answer(Messages.NO_COUNTERS)
            return
        message_text = self.get_counters_review_message(user_state.counters)
        await message.answer(message_text, reply_markup=self.get_keyboard(user_state.counters))

    @staticmethod
    async def create_handle_start(message: types.Message):
        await message.answer(Messages.CREATE_WELCOME)
        await UserContext.counter_name_create.set()

    async def create_handle_finish(self, message: types.Message, state: FSMContext):
        counter_name = message.text
        if counter_name.startswith('/'):
            if counter_name == '/cancel':
                await message.answer(Messages.CREATE_CANCEL)
                await state.finish()
                return
            await message.answer(Messages.INCORRECT_COUNTER_NAME)
            return
        user_state = await self.app_data.get_user_state(message.from_user.id)
        await self.check_username(user_state, message)
        user_state.counters[counter_name] = Counter(counter_name, 0)
        await self.app_data.set_user_state(user_state.id, user_state)
        await message.answer(Messages.CREATE_SUCCESS.format(counter_name=counter_name))
        await state.finish()
        await self.start_handle(message)

    async def update_handle_start(self, message: types.Message):
        user_state = await self.app_data.get_user_state(message.from_user.id)
        if not user_state.counters:
            await message.answer(Messages.NO_COUNTERS)
            return
        counters_list = '\n'.join(f'`{counter.name}`' for counter in user_state.counters.values())
        await message.answer(Messages.UPDATE_COUNTERS_LIST.format(counters_list=counters_list))
        await UserContext.counter_name_for_update.set()

    async def update_handle_new_name(self, message: types.Message, state: FSMContext):
        user_state = await self.app_data.get_user_state(message.from_user.id)
        counter_name_for_update = message.text
        if counter_name_for_update not in user_state.counters:
            await message.answer(Messages.COUNTER_NOT_FOUND.format(counter_name=counter_name_for_update))
            return
        async with state.proxy() as data:
            data['counter_name_for_update'] = message.text
        await message.answer(Messages.UPDATE_WELCOME.format(counter_name=message.text))
        await UserContext.counter_name_update_new_name.set()

    async def update_handle_finish(self, message: types.Message, state: FSMContext):
        new_counter_name = message.text
        async with state.proxy() as data:
            old_counter_name = data['counter_name_for_update']
        if new_counter_name.startswith('/'):
            if new_counter_name == '/cancel':
                await message.answer(Messages.UPDATE_CANCEL.format(counter_name=old_counter_name))
                await state.finish()
                return
            await message.answer(Messages.INCORRECT_COUNTER_NAME)
            return
        user_state = await self.app_data.get_user_state(message.from_user.id)
        await self.check_username(user_state, message)
        current_counter_state = user_state.counters[old_counter_name]
        current_counter_state.name = new_counter_name
        user_state.counters[new_counter_name] = current_counter_state
        del user_state.counters[old_counter_name]
        await self.app_data.set_user_state(user_state.id, user_state)
        await message.answer(Messages.UPDATE_SUCCESS.format(
            old_counter_name=old_counter_name,
            new_counter_name=new_counter_name
        ))
        await state.finish()
        await self.start_handle(message)

    async def delete_handle_start(self, message: types.Message):
        user_state = await self.app_data.get_user_state(message.from_user.id)
        if not user_state.counters:
            await message.answer(Messages.NO_COUNTERS)
            return
        counters_list = '\n'.join(f'`{counter.name}`' for counter in user_state.counters.values())
        await message.answer(Messages.DELETE_COUNTERS_LIST.format(counters_list=counters_list))
        await UserContext.counter_name_delete.set()

    async def delete_handle_finish(self, message: types.Message, state: FSMContext):
        counter_name = message.text
        user_state = await self.app_data.get_user_state(message.from_user.id)
        if counter_name not in user_state.counters:
            await message.answer(Messages.COUNTER_NOT_FOUND.format(counter_name=counter_name))
            return
        await self.check_username(user_state, message)
        user_state.counters.pop(counter_name)
        await self.app_data.set_user_state(user_state.id, user_state)
        await message.answer(Messages.DELETE_SUCCESS.format(counter_name=counter_name))
        await state.finish()
        await self.start_handle(message)

    async def counter_handler(self, query: types.CallbackQuery, callback_data: dict, operator: str):
        user_state = await self.app_data.get_user_state(query.from_user.id)
        if operator == '+':
            user_state.counters[callback_data['counter_name']].value += 1
        elif operator == '-':
            if user_state.counters[callback_data['counter_name']].value > 0:
                user_state.counters[callback_data['counter_name']].value -= 1
            else:
                return
        elif operator == 'reset':
            user_state.counters[callback_data['counter_name']].value = 0
        await self.app_data.set_user_state(user_state.id, user_state)
        message_text = self.get_counters_review_message(user_state.counters)
        await self.bot.edit_message_text(
            message_text,
            query.from_user.id,
            query.message.message_id,
            reply_markup=self.get_keyboard(user_state.counters)
        )

    async def increment_handler(self, query: types.CallbackQuery, callback_data: dict):
        await self.counter_handler(query, callback_data, '+')

    async def decrement_handler(self, query: types.CallbackQuery, callback_data: dict):
        await self.counter_handler(query, callback_data, '-')

    async def reset_handler(self, query: types.CallbackQuery, callback_data: dict):
        await self.counter_handler(query, callback_data, 'reset')

    async def default_handle(self, message: types.Message):
        await message.answer('Unknown command')
        await self.start_handle(message)

    def start(self):

        # Commands
        self.dp.register_message_handler(self.start_handle, commands='start')
        self.dp.register_message_handler(self.create_handle_start, commands='create')
        self.dp.register_message_handler(self.delete_handle_start, commands='delete')
        self.dp.register_message_handler(self.update_handle_start, commands='edit')

        # Context
        self.dp.register_message_handler(self.create_handle_finish, state=UserContext.counter_name_create)
        self.dp.register_message_handler(self.delete_handle_finish, state=UserContext.counter_name_delete)
        self.dp.register_message_handler(self.update_handle_new_name, state=UserContext.counter_name_for_update)
        self.dp.register_message_handler(self.update_handle_finish, state=UserContext.counter_name_update_new_name)

        # Callbacks
        self.dp.register_callback_query_handler(self.increment_handler, self.counter_cb.filter(action='+'))
        self.dp.register_callback_query_handler(self.decrement_handler, self.counter_cb.filter(action='-'))
        self.dp.register_callback_query_handler(self.reset_handler, self.counter_cb.filter(action='reset'))

        # Default
        self.dp.register_message_handler(self.default_handle, regexp='.')

        # Run bot
        executor.start_polling(self.dp, loop=self.loop, skip_updates=True)


if __name__ == '__main__':

    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

    dotenv.load_dotenv(
        os.path.join(BASE_DIR, '.env_lifestat_bot'),
        verbose=True
    )

    bot = LifeStatBot()

    bot.start()
