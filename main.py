import collections

import telegram
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters
import argparse
import re
from datetime import datetime
import logging


class Bot:
    def __init__(self):

        self._args = self._parse_args()

        self._time_pattern = re.compile(r'\b(1[1-4])[:|-]?([0-5]\d)\b')

        self.updater = Updater(token=self._args.token, use_context=True)
        self.dispatcher = self.updater.dispatcher

        self._chat_id_to_was_declared = collections.defaultdict(bool)
        self._chat_id_to_repeating_job = {}

        start_handler = CommandHandler('start', self._start_callback)
        self.dispatcher.add_handler(start_handler)

        start_handler = MessageHandler(Filters.text, self._read_message_from_group_callback)
        self.dispatcher.add_handler(start_handler)

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

    def _read_message_from_group_callback(self, update, context):

        text = update.message.text

        match = self._time_pattern.findall(text)

        if len(match) > 0:
            hours, minutes = match[0]

            self._chat_id_to_was_declared[update.message.chat_id] = True
            context.bot.send_message(chat_id=update.message.chat_id, text=f"{hours}:{minutes}")

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

        context.bot.send_message(chat_id=chat_id, text="bot started")

        self._schedule_declaration_job_if_not_exist(update, context)

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


def main():
    logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                        level=logging.INFO)

    bot = Bot()

    bot.updater.start_polling()
    bot.updater.idle()


if __name__ == "__main__":
    main()
