from astrbot.api.event import filter
from astrbot.api.star import Context, Star
from astrbot.core.config.astrbot_config import AstrBotConfig
from astrbot.core.message.components import Reply
from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import (
    AiocqhttpMessageEvent,
)

from .core.config import PluginConfig
from .core.sender import HumanServiceSender
from .core.service import HumanServiceService
from .core.utils import get_ats, get_nickname, get_reply_user_id


class HumanServicePlugin(Star):
    """Adapt AstrBot events to the transport-neutral business service."""

    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.cfg = PluginConfig(config, context)
        self.sender = HumanServiceSender()
        self.service = HumanServiceService(self.cfg)

    @filter.command("转人工")
    async def transfer_to_human(self, event: AiocqhttpMessageEvent):
        """用户命令：请求转接人工客服"""
        result = self.service.request_human(
            event.get_sender_id(),
            await get_nickname(event, event.get_sender_id()),
            event.get_group_id() or "0",
        )
        await self.sender.send_result(event, result)
        if result.message:
            yield event.plain_result(result.message)

    @filter.command("转人机")
    async def transfer_to_bot(self, event: AiocqhttpMessageEvent):
        """用户命令：取消人工服务并转回机器人"""
        result = self.service.cancel_human(event.get_sender_id())
        await self.sender.send_result(event, result)
        if result.message:
            yield event.plain_result(result.message)

    @filter.command_group("客服")
    def customer_service(self) -> None:
        """客服的专用命令组，用户不可用"""

    @customer_service.command("拉黑")
    async def blacklist_user(self, event: AiocqhttpMessageEvent, target_id: str = ""):
        """客服 拉黑 <QQ号>, 将指定用户加入黑名单"""
        target_id = str(target_id or get_reply_user_id(event))
        if not target_id.isdigit():
            ats = get_ats(event, noself=True)
            target_id = ats[0] if ats else ""
        if not target_id.isdigit():
            yield event.plain_result("请提供正确的QQ号\n使用格式：客服 拉黑 QQ号")
            return

        result = self.service.blacklist_user(
            event.get_sender_id(), target_id, await get_nickname(event, target_id)
        )
        if result.code == "forbidden":
            return
        await self.sender.send_result(event, result)
        yield event.plain_result(result.message)

    @customer_service.command("取消拉黑")
    async def unblacklist_user(self, event: AiocqhttpMessageEvent, target_id: str = ""):
        """客服 取消拉黑 <QQ号>, 将指定用户移出黑名单"""
        target_id = str(target_id or get_reply_user_id(event))
        if not target_id.isdigit():
            ats = get_ats(event, noself=True)
            target_id = ats[0] if ats else ""
        if not target_id.isdigit():
            yield event.plain_result("请提供正确的QQ号\n使用格式：/客服 取消拉黑 QQ号")
            return

        result = self.service.unblacklist_user(
            event.get_sender_id(), target_id, await get_nickname(event, target_id)
        )
        if result.code != "forbidden":
            yield event.plain_result(result.message)

    @customer_service.command("黑名单")
    async def view_blacklist(self, event: AiocqhttpMessageEvent):
        """客服 黑名单, 查看被客服拉黑的用户名单"""
        result = self.service.get_blacklist(event.get_sender_id())
        if result.code == "forbidden":
            return
        blacklist = result.data["user_ids"]
        if not blacklist:
            yield event.plain_result("黑名单为空")
            return
        lines = [result.data["title"]]
        for index, user_id in enumerate(blacklist, 1):
            nickname = await get_nickname(event, user_id)
            lines.append(
                f"{index}. {nickname} ({user_id})"
                if nickname != user_id
                else f"{index}. {user_id}"
            )
        yield event.plain_result("\n".join(lines))

    @customer_service.command("接入")
    async def accept_conversation(
        self, event: AiocqhttpMessageEvent, target_id: str | int | None = None
    ):
        """(引用请求消息)客服 接入, 接入指定用户的人工会话"""
        target_id = str(target_id or get_reply_user_id(event))
        result = self.service.accept_conversation(
            event.get_sender_id(),
            await get_nickname(event, event.get_sender_id()),
            target_id,
        )
        if result.code == "forbidden":
            return
        await self.sender.send_result(event, result)
        if result.message:
            yield event.plain_result(result.message)
        if result.ok:
            event.stop_event()

    @customer_service.command("拒接")
    async def reject_conversation(
        self, event: AiocqhttpMessageEvent, target_id: str | int | None = None
    ):
        """(引用请求消息)客服 拒接, 拒绝指定用户的接入请求"""
        target_id = str(target_id or get_reply_user_id(event))
        result = self.service.reject_conversation(event.get_sender_id(), target_id)
        if result.code == "forbidden":
            return
        await self.sender.send_result(event, result)
        if result.message:
            yield event.plain_result(result.message)

    @customer_service.command("结束")
    async def end_conversation(self, event: AiocqhttpMessageEvent):
        """客服 结束，结束当前人工客服会话"""
        result = self.service.end_conversation(event.get_sender_id())
        if result.code == "forbidden":
            return
        await self.sender.send_result(event, result)
        if result.message:
            yield event.plain_result(result.message)

    @filter.event_message_type(filter.EventMessageType.ALL)
    async def handle_match(self, event: AiocqhttpMessageEvent):
        """监听并路由用户与客服的消息"""
        timeout_result = self.service.check_timeouts()
        await self.sender.send_result(event, timeout_result)

        chain = event.get_messages()
        if not chain or any(isinstance(segment, Reply) for segment in chain):
            return
        sender_id = event.get_sender_id()
        msg = event.message_str.strip()
        is_service_cmd = msg.startswith("客服 ")

        if event.is_private_chat() and not is_service_cmd:
            result = self.service.route_servicer_message(sender_id, msg)
            if result.ok:
                await self.sender.forward_event(
                    event,
                    identity_icon=result.data["identity_icon"],
                    group_id=result.data["group_id"],
                    user_id=result.data["user_id"],
                )
                event.stop_event()
                return

        result = self.service.route_user_message(sender_id, msg)
        if result.ok:
            await self.sender.forward_event(
                event,
                identity_icon=result.data["identity_icon"],
                user_id=result.data["user_id"],
            )
            event.stop_event()
