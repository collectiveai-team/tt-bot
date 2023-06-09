from tt_bot.qa import DocQA
from tt_bot.meta import BotHandler
from tt_bot.logger import get_logger
from tt_bot.retrieval import Retrieval

from telegram import Update
from telegram.ext import (
    MessageHandler,
    ContextTypes,
    filters,
)


logger = get_logger(__name__)


doc_qa = DocQA()
retrieval = Retrieval()


class QAHandler(BotHandler):
    def __init__(self, bot_name: str):
        super().__init__(bot_name=bot_name)

    def parse_query_text(self, text: str, bot_name: str) -> str:
        text = text.replace(bot_name, "")
        text = " ".join(text.split())
        text = text.strip()

        return text

    def get_ref_text(self, refs: list[dict]) -> str:
        ref_text = "\n\n".join(
            "\n".join(f"{k}: {v}" for k, v in ref.items()) for ref in refs
        )

        return ref_text

    async def callback(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ):
        mentions = update.effective_message.parse_entities(["mention"])
        mentions = set(mentions.values())
        logger.info(f"mentions => {mentions}")

        if self.bot_name not in mentions:
            return

        message = update.message
        self.dsp.stop_all()
        self.dsp.start_rand_inv()

        query_text = self.parse_query_text(message.text, self.bot_name)
        if not query_text:
            logger.warning("No query text")
            return

        logger.info(f"query_text => {query_text}")

        sim_chunks = await retrieval.retrieve(query_text)
        if not sim_chunks:
            await message.reply_text("I don't know")
            self.dsp.stop_all()
            return

        self.dsp.stop_rand_inv()
        self.dsp.start_intermittent()

        response = doc_qa.get_answer(
            sim_chunks=sim_chunks,
            query_text=query_text,
        )

        ref_text = self.get_ref_text(response["ref"])
        await message.reply_text(
            f"{response['answer']}\n\n{ref_text}",
            disable_web_page_preview=True,
        )

        self.dsp.stop_all()

    def get_handler(self) -> MessageHandler:
        handler = MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            self.apply_callback,
        )

        return handler
