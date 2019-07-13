import collections
import argparse
from datetime import datetime
import logging
import requests
import re
from time import time
import json

import telegram
from telegram import ChatAction
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters
from bs4 import BeautifulSoup


class Bot:
    def __init__(self):

        self._args = self._parse_args()

        self._time_pattern = re.compile(r'\b(1[1-4])[:|-]?([0-5]\d)\b')

        self.updater = Updater(token=self._args.token, use_context=True)
        self.dispatcher = self.updater.dispatcher

        self._chat_id_to_was_declared = collections.defaultdict(bool)
        self._chat_id_to_repeating_job = {}

        self._add_handlers()

    @staticmethod
    def _parse_args():
        parser = argparse.ArgumentParser(description="script to notify the lunch time")
        parser.add_argument('token', type=str, help='your bot token')

        parser.add_argument("--time_to_declare", default="13:30")

        parser.add_argument("--declare_at", default='13:20')

        args = parser.parse_args()

        for time_pattern in (args.time_to_declare, args.declare_at):
            datetime.strptime(time_pattern, '%H:%M')  # raises if time format is illegal

        return args

    def _add_handlers(self):
        self.dispatcher.add_handler(CommandHandler('start', self._start_callback))

        self.dispatcher.add_handler(CommandHandler('gute', self._gute_callback))

        self.dispatcher.add_handler(CommandHandler('zozobra', self._zozobra_callback))

        self.dispatcher.add_handler(CommandHandler('pilaf', self._pilaf_callback))

        regular_message = MessageHandler(Filters.text, self._read_message_from_group_callback)
        self.dispatcher.add_handler(regular_message)

    def _read_message_from_group_callback(self, update, context):
        text = update.message.text

        match = self._time_pattern.findall(text)

        if len(match) > 0:
            hours, minutes = match[0]

            self._chat_id_to_was_declared[update.message.chat_id] = True
            context.bot.send_message(chat_id=update.message.chat_id, text=f"{hours}:{minutes}")

        elif "rm -rf" in text.lower():
            context.bot.send_animation(chat_id=update.message.chat_id,
                                       animation="https://media.giphy.com/media/lruCgPNh4Bo3K/giphy.gif")

        self._schedule_declaration_job_if_not_exist(update, context)

    def _declare_time_if_necassary_callback(self, context):
        FRIDAY = 4
        SATURDAY = 5

        if datetime.today().weekday() in (FRIDAY, SATURDAY):
            return

        chat_id = context.job.context

        if self._chat_id_to_was_declared[chat_id] is False:
            context.bot.send_message(chat_id=chat_id, text=self._args.time_to_declare)

        else:
            self._chat_id_to_was_declared[chat_id] = False

    def _schedule_declaration_job_if_not_exist(self, update, context):
        chat_id = update.message.chat_id
        if chat_id not in self._chat_id_to_repeating_job:
            next_declaration_time = self._calculate_next_declaration_time(self._args.declare_at)

            DAY_IN_SECONDS = 60 * 60 * 24

            declare_callback_handle = context.job_queue.run_repeating(self._declare_time_if_necassary_callback,
                                                                      first=next_declaration_time,
                                                                      interval=DAY_IN_SECONDS,
                                                                      context=update.message.chat_id)

            self._chat_id_to_repeating_job[chat_id] = declare_callback_handle

    def _start_callback(self, update, context: telegram.ext.callbackcontext.CallbackContext):
        chat_id = update.message.chat_id
        self._chat_id_to_was_declared[chat_id] = False

        update.message.reply_text("bot started")

        self._schedule_declaration_job_if_not_exist(update, context)

    def _zozobra_callback(self, update, context: telegram.ext.callbackcontext.CallbackContext):
        print(str(update.message.from_user.username) + " zozobra")
        context.bot.send_chat_action(chat_id=update.effective_message.chat_id, action=ChatAction.TYPING)
        response = requests.get('https://www.10bis.co.il/next/Restaurants/Menu/Delivery/562/זוזוברה')
        message_to_user = "couldn't get special"

        if response.status_code == 200:
            bs = BeautifulSoup(response.content, "html.parser")
            special_list = bs.findAll("div", string=re.compile("ספיישל השבוע"))
            filtered_list = list(filter(lambda item: item.parent['class'][0].startswith("Menu"), special_list))
            if len(filtered_list) != 0:
                message_to_user = filtered_list[0].parent.text

        update.message.reply_text(message_to_user)
        self._schedule_declaration_job_if_not_exist(update, context)

    def _gute_callback(self, update, context):
        print(str(update.message.from_user.username) + " gute")
        GuteSpecial.gute_callback(update, context)

        self._schedule_declaration_job_if_not_exist(update, context)

    def _pilaf_callback(self, update, context):
        PILAF_API = f'http://api.beteabon.co.il/website/api.php?action=get&guid=4B04EDAE-BE13-D698-9F7D-61EBB1192BDF&time={int(time())}'
        response = requests.get(PILAF_API)
        json_data = json.loads(response.content)
        for item in json_data['rest']['menu']:
            if "ספיישל היום" in item['name']:
                specials = [special['name'] for special in item['items']]
                update.message.reply_text("\n".join(specials))

    @staticmethod
    def _calculate_next_declaration_time(declare_at: str):
        announcement_hour, announcement_minute = map(int, declare_at.split(":"))
        current_time = datetime.now()
        current_hour = current_time.hour
        current_minute = current_time.minute

        next_time = current_time.replace(hour=announcement_hour, minute=announcement_minute, second=0, microsecond=0)
        if (announcement_hour, announcement_minute) <= (current_hour, current_minute):
            next_time = next_time.replace(day=current_time.day + 1)

        return next_time


class GuteSpecial:
    url_to_parse = 'https://www.mishloha.co.il/r/גוטה%20בריא%20ומהיר%20הרצליה#!/rest/3190/menu'
    search_regex = re.compile(">(.*?ספיישל היום.*?)<")

    @classmethod
    def gute_callback(cls, update, context: telegram.ext.callbackcontext.CallbackContext):
        context.bot.send_chat_action(chat_id=update.effective_message.chat_id, action=ChatAction.TYPING)
        special = None

        response = requests.get(cls.url_to_parse)
        if response.status_code == 200:
            dishes = cls.search_regex.findall(response.text)
            if len(dishes) != 0:
                special = dishes[0]

        if special is None:
            message_to_user = "couldn't get special"
        else:
            message_to_user = special

        update.message.reply_text(message_to_user)


def main():
    logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                        level=logging.INFO)

    bot = Bot()

    bot.updater.start_polling()
    bot.updater.idle()


if __name__ == "__main__":
    main()
