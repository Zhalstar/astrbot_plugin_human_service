"""Send human service outputs through OneBot."""

from astrbot.core.message.components import At, Plain
from astrbot.core.message.message_event_result import MessageChain
from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import (
    AiocqhttpMessageEvent,
)

from .models import ServiceResult


class HumanServiceSender:
    async def send_result(
        self, event: AiocqhttpMessageEvent, result: ServiceResult
    ) -> None:
        for notification in result.notifications:
            if notification.group_id and str(notification.group_id) != "0":
                await event.bot.send_group_msg(
                    group_id=int(notification.group_id),
                    message=notification.message,
                )
            elif notification.user_id:
                await event.bot.send_private_msg(
                    user_id=int(notification.user_id),
                    message=notification.message,
                )

        for export in result.history_exports:
            try:
                await event.bot.send_private_forward_msg(
                    user_id=int(export.servicer_id),
                    messages=[
                        {
                            "type": "node",
                            "data": {
                                "name": record.name,
                                "uin": record.sender_id,
                                "content": record.message,
                            },
                        }
                        for record in export.history
                    ],
                )
            except Exception:
                lines = [
                    f"📝 聊天记录（共 {len(export.history)} 条）",
                    "=" * 30,
                    "",
                ]
                for record in export.history:
                    lines.extend(
                        [
                            f"[{record.timestamp}] {record.name}:",
                            record.message,
                            "",
                        ]
                    )
                await event.bot.send_private_msg(
                    user_id=int(export.servicer_id),
                    message="\n".join(lines),
                )

    async def forward_event(
        self,
        event: AiocqhttpMessageEvent,
        identity_icon: str,
        group_id: int | str | None = None,
        user_id: int | str | None = None,
    ) -> None:
        if group_id and str(group_id) != "0":
            message = await event._parse_onebot_json(
                MessageChain(
                    chain=[Plain(f"{identity_icon}："), *event.message_obj.message]
                )
            )
            await event.bot.send_group_msg(group_id=int(group_id), message=message)
        elif user_id:
            chain = [Plain(f"{identity_icon}：")]
            for segment in event.message_obj.message:
                if not isinstance(segment, At):
                    chain.append(segment)  # type: ignore
                elif str(segment.qq) != event.get_self_id():
                    chain.append(Plain(f"@{segment.name or segment.qq}"))
            message = await event._parse_onebot_json(MessageChain(chain=chain))  # type: ignore
            await event.bot.send_private_msg(user_id=int(user_id), message=message)
