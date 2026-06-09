import uuid
import logging
logger = logging.getLogger(__name__)
from typing import Optional
from zoneinfo import ZoneInfo
from aiogram import Router, F
from aiogram.types import Message, Document
from bot.adapters.manual import ManualAdapter
from bot.adapters.md_file import MdFileAdapter
from bot.keyboards.confirmation import confirm_keyboard
from bot.keyboards.task_list import done_list_keyboard
from bot.db.repository import TaskRepo, ChatMemberRepo
from bot.db.models import ChatMember
from bot.config import Config

# Pending RawTask objects awaiting user confirmation: {tmp_id: RawTask}
_pending: dict = {}

# Lazy-loaded Whisper model singleton to avoid reloading on every voice message
_whisper_model = None

def _get_whisper_model():
    global _whisper_model
    if _whisper_model is None:
        from faster_whisper import WhisperModel
        _whisper_model = WhisperModel("base", device="cpu", compute_type="int8")
    return _whisper_model

# Cached bot username for group mention check
_bot_username: Optional[str] = None

# Keywords that signal "I completed something" intent
_COMPLETION_WORDS = {
    "выполнил", "выполнила", "выполнено",
    "сделал", "сделала", "сделано",
    "готово", "готов", "готова",
    "завершил", "завершила", "завершено",
    "закончил", "закончила", "закончено",
    "done", "completed",
}


def _completion_query(text: str) -> Optional[str]:
    """If text looks like a completion message, return search query (title hint).
    Returns empty string if keyword found but no extra words.
    Returns None if not a completion message.
    """
    words = text.lower().split()
    for i, word in enumerate(words):
        clean = word.strip(".,!?")
        if clean in _COMPLETION_WORDS:
            remaining = " ".join(words[:i] + words[i + 1:]).strip()
            return remaining
    return None


def setup_messages_router(
    llm_client,
    config: Config,
    task_repo: TaskRepo = None,
    member_repo: ChatMemberRepo = None,
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

        adapter = MdFileAdapter(llm_client, tz_name=config.timezone)
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
                local_dt = raw.remind_at.astimezone(ZoneInfo(config.timezone))
                preview += f"\n📅 {local_dt.strftime('%d.%m.%Y %H:%M')}"
            if raw.recurrence:
                preview += "\n🔄 Повторяется"
            await message.answer(
                preview,
                parse_mode="HTML",
                reply_markup=confirm_keyboard(tmp_id),
            )

    @router.message(F.voice)
    async def handle_voice(message: Message) -> None:
        import tempfile, os

        await message.answer("🎙 Распознаю голос…")

        file = await message.bot.get_file(message.voice.file_id)
        ogg_bytes = await message.bot.download_file(file.file_path)

        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp_ogg:
            tmp_ogg.write(ogg_bytes.read())
            ogg_path = tmp_ogg.name

        wav_path = ogg_path.replace(".ogg", ".wav")
        os.system(f"ffmpeg -y -i {ogg_path} -ar 16000 -ac 1 -c:a pcm_s16le {wav_path} >/dev/null 2>&1")

        model = _get_whisper_model()
        segments, info = model.transcribe(wav_path, beam_size=5, language="ru")
        text = "".join([seg.text for seg in segments]).strip()

        os.unlink(ogg_path)
        os.unlink(wav_path)

        if not text:
            await message.answer("Не удалось распознать голос.")
            return

        # Echo recognized text so user can verify STT accuracy
        await message.answer(f"🗣 Услышал: <i>{text}</i>", parse_mode="HTML")
        logger.info("handle_voice: calling _process_text with text=%r", text)
        await _process_text(message, text)

    @router.message(F.text)
    async def handle_text(message: Message) -> None:
        await _process_text(message, message.text or "")

    async def _process_text(message: Message, text: str) -> None:
        if text.startswith("/"):
            return  # ignore commands — handled by commands router

        # In group chats only respond when bot is @mentioned
        is_group = message.chat.type in ("group", "supergroup")

        # Track group members (non-bot users)
        if is_group and member_repo and message.from_user and not message.from_user.is_bot:
            await member_repo.upsert(ChatMember(
                chat_id=message.chat.id,
                user_id=message.from_user.id,
                username=message.from_user.username,
                first_name=message.from_user.first_name or "",
            ))

        if is_group:
            global _bot_username
            if _bot_username is None:
                _bot_username = (await message.bot.get_me()).username
            # Use the ACTUAL text (transcribed for voice, message.text for text)
            # to check for @mention or "бот" trigger
            effective_text = text or message.text or ""
            has_mention = f"@{_bot_username}" in effective_text
            has_keyword = effective_text.lower().startswith("бот ")
            if not has_mention and not has_keyword:
                return
            # Strip trigger words from the text we actually have
            if has_mention:
                text = effective_text.replace(f"@{_bot_username}", "").strip()
            else:
                text = effective_text[4:].strip()
        else:
            text = message.text or ""

        # Check if user is reporting a completed task (variant В)
        query = _completion_query(text)
        if query is not None and task_repo is not None:
            active_tasks = await task_repo.list_active(chat_id=message.chat.id)
            if not active_tasks:
                await message.answer("Нет активных задач.")
                return
            # Filter by query if there's a hint, otherwise show all
            if query:
                matched = [t for t in active_tasks if query in t.title.lower()]
            else:
                matched = active_tasks
            tasks_to_show = matched if matched else active_tasks
            await message.answer(
                "Какую задачу отметить выполненной?",
                reply_markup=done_list_keyboard(tasks_to_show),
            )
            return

        # Extract assignee @mention from text (any @word that isn't the bot)
        import re
        assignee_username: Optional[str] = None
        mention_pattern = re.compile(r"@(\w+)")
        for match in mention_pattern.finditer(text):
            uname = match.group(1)
            if _bot_username and uname.lower() == _bot_username.lower():
                continue
            assignee_username = uname
            text = text[:match.start()].strip() + " " + text[match.end():].strip()
            text = text.strip()
            break

        # Otherwise treat as new task
        await message.answer("🔍 Понял, обрабатываю…")
        logger.info("_process_text: before adapter.extract text=%r", text)
        adapter = ManualAdapter(llm_client, tz_name=config.timezone)
        tasks = await adapter.extract(text)

        if not tasks:
            await message.answer(
                "Не понял задачу. Попробуй написать подробнее, например:\n"
                "«напомни купить молоко завтра в 10 утра»"
            )
            return

        for raw in tasks:
            raw.assignee_username = assignee_username
            tmp_id = str(uuid.uuid4())
            _pending[tmp_id] = raw
            preview = f"📋 <b>Создать задачу?</b>\n\n{raw.title}"
            if raw.assignee_username:
                preview += f"\n👤 @{raw.assignee_username}"
            if raw.remind_at:
                local_dt = raw.remind_at.astimezone(ZoneInfo(config.timezone))
                preview += f"\n📅 {local_dt.strftime('%d.%m.%Y %H:%M')}"
            await message.answer(
                preview,
                parse_mode="HTML",
                reply_markup=confirm_keyboard(tmp_id),
            )

    return router, _pending
