import uuid
from aiogram import Router, F
from aiogram.types import Message, Document
from bot.adapters.manual import ManualAdapter
from bot.adapters.md_file import MdFileAdapter
from bot.keyboards.confirmation import confirm_keyboard
from bot.config import Config
import anthropic

# Pending RawTask objects awaiting user confirmation: {tmp_id: RawTask}
_pending: dict = {}


def setup_messages_router(
    llm_client: anthropic.AsyncAnthropic,
    config: Config,
) -> tuple[Router, dict]:
    router = Router()

    @router.message(F.document)
    async def handle_document(message: Message) -> None:
        doc: Document = message.document
        if not doc.file_name or not doc.file_name.endswith(".md"):
            await message.answer("Поддерживаются только .md файлы.")
            return

        await message.answer("📄 Читаю файл…")
        file = await message.bot.get_file(doc.file_id)
        content_bytes = await message.bot.download_file(file.file_path)
        content = content_bytes.read().decode("utf-8")

        adapter = MdFileAdapter(llm_client)
        tasks = await adapter.extract(content, filename=doc.file_name)

        if not tasks:
            await message.answer("Не нашёл задач в документе.")
            return

        for raw in tasks:
            tmp_id = str(uuid.uuid4())
            _pending[tmp_id] = raw
            preview = f"📋 <b>Предлагаемая задача:</b>\n\n{raw.title}"
            if raw.notes:
                preview += f"\n<i>{raw.notes}</i>"
            if raw.remind_at:
                preview += f"\n📅 {raw.remind_at.strftime('%d.%m.%Y %H:%M')}"
            if raw.recurrence:
                preview += "\n🔄 Повторяется"
            await message.answer(
                preview,
                parse_mode="HTML",
                reply_markup=confirm_keyboard(tmp_id),
            )

    @router.message(F.text)
    async def handle_text(message: Message) -> None:
        if message.text and message.text.startswith("/"):
            return  # ignore commands — handled by commands router

        await message.answer("🔍 Понял, обрабатываю…")
        adapter = ManualAdapter(llm_client)
        tasks = await adapter.extract(message.text or "")

        if not tasks:
            await message.answer(
                "Не понял задачу. Попробуй написать подробнее, например:\n"
                "«напомни купить молоко завтра в 10 утра»"
            )
            return

        for raw in tasks:
            tmp_id = str(uuid.uuid4())
            _pending[tmp_id] = raw
            preview = f"📋 <b>Создать задачу?</b>\n\n{raw.title}"
            if raw.remind_at:
                preview += f"\n📅 {raw.remind_at.strftime('%d.%m.%Y %H:%M')}"
            await message.answer(
                preview,
                parse_mode="HTML",
                reply_markup=confirm_keyboard(tmp_id),
            )

    return router, _pending
