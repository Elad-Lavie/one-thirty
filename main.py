import collections
import argparse
import datetime
import logging
import requests
import re
from time import time
import json
import pathlib
import csv

import telegram
from telegram import ChatAction
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, jobqueue
from bs4 import BeautifulSoup


class Bot:
    def __init__(self):

        self._args = self._parse_args()

        self._time_pattern = re.compile(r'(?:\b|[^0-9])(1[1-4])[:|-]?([0-5]\d)(?:\b|[^0-9])')

        self.updater = Updater(token=self._args.token, use_context=True)

        self.dispatcher = self.updater.dispatcher

        self._chat_id_to_should_announce = collections.defaultdict(bool)

        self._add_handlers()

        self._start_declaration_job()

        self._non_working_days = self.get_non_working_dates()

    @staticmethod
    def _parse_args():
        parser = argparse.ArgumentParser(description="script to notify the lunch time")
        parser.add_argument('token', type=str, help='your bot token')

        parser.add_argument("--time_to_declare", default="13:30")

        parser.add_argument("--declare_at", default='13:20')

        args = parser.parse_args()

        for time_pattern in (args.time_to_declare, args.declare_at):
            datetime.datetime.strptime(time_pattern, '%H:%M')  # raises if time format is illegal

        return args

    def get_non_working_dates(self):
        path_to_dates_files = pathlib.Path(__file__).parent / "non_working_days.csv"

        with open(path_to_dates_files, "r") as fd:
            reader = csv.reader(fd)
            non_working_days = {datetime.datetime.strptime(date[0], "%Y-%m-%d").date() for date in reader}

        return non_working_days

    def _add_handlers(self):
        self.dispatcher.add_handler(MessageHandler(Filters.text | Filters.command,
                                                   self._before_each_command_and_message_callback), group=-1)

        self.dispatcher.add_handler(CommandHandler('start', self._start_callback))

        self.dispatcher.add_handler(CommandHandler('gute', self._gute_callback))

        self.dispatcher.add_handler(CommandHandler('zozobra', self._zozobra_callback))

        self.dispatcher.add_handler(CommandHandler('pilaf', self._pilaf_callback))

        self.dispatcher.add_handler(MessageHandler(Filters.text, self._handle_non_command_message))

    def _before_each_command_and_message_callback(self, update, context):
        message = update.message
        print(f"{message.from_user.first_name or ''}  {message.from_user.id or ''}:\n"
              f"{message.text or ''}\n")

        chat_id = update.message.chat_id
        if chat_id not in self._chat_id_to_should_announce:
            print("new chat " + str(chat_id))

            self._chat_id_to_should_announce[chat_id] = True

    def _start_declaration_job(self):
        def declaration_job(context):
            if datetime.date.today() not in self._non_working_days:
                for chat_id, should_announce in self._chat_id_to_should_announce.items():
                    if should_announce is True:
                        context.bot.send_message(chat_id=chat_id, text=self._args.time_to_declare)

        announcement_hour, announcement_minute = map(int, self._args.declare_at.split(":"))
        declaration_time = datetime.time(announcement_hour, announcement_minute)

        d = jobqueue.Days
        self.dispatcher.job_queue.run_daily(declaration_job,
                                            days=(d.SUN, d.MON, d.TUE, d.WED, d.THU),
                                            time=declaration_time)

        def reset_job(context):
            for chat_id in self._chat_id_to_should_announce:
                self._chat_id_to_should_announce[chat_id] = True

        # noinspection PyCallByClass
        midnight_time = datetime.time(0, 0)
        self.dispatcher.job_queue.run_daily(reset_job, time=midnight_time)

    def _handle_non_command_message(self, update, context):
        text = update.message.text

        match = self._time_pattern.findall(text)

        if len(match) > 0:
            self._chat_id_to_should_announce[update.message.chat_id] = False

            hours, minutes = match[0]
            context.bot.send_message(chat_id=update.message.chat_id, text=f"{hours}:{minutes}")

        elif "rm -rf" in text.lower():
            context.bot.send_animation(chat_id=update.message.chat_id,
                                       animation="https://media.giphy.com/media/lruCgPNh4Bo3K/giphy.gif")

    def _start_callback(self, update, context: telegram.ext.callbackcontext.CallbackContext):
        chat_id = update.message.chat_id
        self._chat_id_to_should_announce[chat_id] = True

        update.message.reply_text("bot started")

    @staticmethod
    def _zozobra_callback(update, context: telegram.ext.callbackcontext.CallbackContext):
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

    @staticmethod
    def _gute_callback(update, context):
        GuteSpecial.gute_callback(update, context)

    @staticmethod
    def _pilaf_callback(update, context):
        PILAF_API = f'http://api.beteabon.co.il/website/api.php?action=get&guid=4B04EDAE-BE13-D698-9F7D-61EBB1192BDF&time={int(time())}'
        response = requests.get(PILAF_API)
        json_data = json.loads(response.content)
        for item in json_data['rest']['menu']:
            if "ספיישל היום" in item['name']:
                specials = [special['name'] for special in item['items']]
                update.message.reply_text("\n".join(specials))


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
