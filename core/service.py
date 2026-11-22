"""Business service for human customer support workflows."""

from .config import PluginConfig
from .models import (
    ChatRecord,
    HistoryExport,
    Notification,
    ServiceResult,
    ServiceSession,
    SessionStatus,
)
from .queue import QueueManager
from .session import SessionManager


class HumanServiceService:
    def __init__(self, config: PluginConfig):
        self.cfg = config
        self.queue_mgr = QueueManager(self.cfg.servicers_id, self.cfg.queue_timeout)
        self.session_mgr = SessionManager(self.cfg.conversation_idle_timeout)
        self.chat_history: dict[str, list[ChatRecord]] = {}

    def request_human(
        self, user_id: str, user_name: str, group_id: str
    ) -> ServiceResult:
        if self.cfg.is_blacklisted(user_id):
            return ServiceResult("blacklisted", "您已被拉黑，无法转人工", False)
        if self.session_mgr.has_session(user_id):
            return ServiceResult("session_exists", "您已在等待接入或正在对话", False)
        for servicer_id in self.queue_mgr.servicer_queue:
            position = self.queue_mgr.get_position(servicer_id, user_id)
            if position > 0:
                return ServiceResult(
                    "already_queued",
                    f"您已在排队中，当前排在第 {position} 位",
                    False,
                )

        available_servicers = self.cfg.servicers_id
        if not available_servicers:
            return ServiceResult("no_servicer", "当前没有可用的客服", False)

        # Prefer direct idle assignment; otherwise join the shortest queue.
        idle_servicers = [
            servicer_id
            for servicer_id in available_servicers
            if not self.session_mgr.is_servicer_occupied(servicer_id)
        ]
        if idle_servicers:
            servicer_id = min(
                idle_servicers,
                key=self.queue_mgr.get_size,
            )
            self.session_mgr.create_session(
                ServiceSession(
                    user_id=user_id,
                    group_id=group_id,
                    user_name=user_name,
                    assigned_servicer_id=servicer_id,
                )
            )
            return ServiceResult(
                "waiting",
                "正在等待客服👤接入...",
                data={"servicer_id": servicer_id},
                notifications=[
                    Notification(
                        f"【{user_name}】({user_id}) 请求转人工",
                        user_id=servicer_id,
                    )
                ],
            )

        servicer_id = min(
            available_servicers,
            key=self.queue_mgr.get_size,
        )
        self.queue_mgr.add(servicer_id, user_id, user_name, group_id)
        position = self.queue_mgr.get_position(servicer_id, user_id)
        queue_count = self.queue_mgr.get_size(servicer_id)
        return ServiceResult(
            "queued",
            (f"🔴客服正在服务中，您已加入排队，当前排在第 {position} 位"),
            data={
                "servicer_id": servicer_id,
                "position": position,
                "queue_count": queue_count,
            },
            notifications=[
                Notification(
                    f"【{user_name}】({user_id}) 已加入排队，当前队列：{queue_count} 人",
                    user_id=servicer_id,
                )
            ],
        )

    def cancel_human(self, user_id: str) -> ServiceResult:
        if self.queue_mgr.remove(user_id):
            return ServiceResult("queue_cancelled", "已退出排队，我现在是人机啦！")

        session = self.session_mgr.get_session(user_id)
        if not session:
            return ServiceResult("request_missing", "您当前没有转人工请求", False)

        notifications = []
        if session.status is SessionStatus.WAITING:
            servicer_ids = (
                [session.assigned_servicer_id]
                if session.assigned_servicer_id
                else self.cfg.servicers_id
            )
            notifications = [
                Notification(
                    f"❗【{session.user_name}】({session.user_id}) 已取消人工请求",
                    user_id=servicer_id,
                )
                for servicer_id in servicer_ids
            ]
            message = "已取消人工客服请求"
        else:
            notifications.append(
                Notification(
                    f"❗【{session.user_name}】({session.user_id}) 已结束对话",
                    user_id=session.servicer_id,
                )
            )
            message = "已退出人工服务"

        history_export = self._close_session(user_id)
        return ServiceResult(
            "request_cancelled",
            message,
            notifications=notifications,
            history_exports=[history_export] if history_export else [],
        )

    def blacklist_user(
        self, servicer_id: str, user_id: str, user_name: str
    ) -> ServiceResult:
        if not self.cfg.is_servicer(servicer_id):
            return ServiceResult("forbidden", ok=False)

        self.cfg.add_to_blacklist(user_id)
        notifications = []
        session = self.session_mgr.get_session(user_id)
        if session:
            user_name = session.user_name
        history_export = None
        if session:
            notifications.append(
                Notification(
                    "您已被客服拉黑，对话已结束",
                    group_id=session.group_id,
                    user_id=user_id,
                )
            )
            history_export = self._close_session(user_id)
        self.queue_mgr.remove(user_id)
        user_label = f"【{user_name}】({user_id})" if user_name != user_id else user_id
        return ServiceResult(
            "blacklisted",
            f"已将{user_label} 加入黑名单",
            notifications=notifications,
            history_exports=[history_export] if history_export else [],
        )

    def get_blacklist(self, servicer_id: str) -> ServiceResult:
        if not self.cfg.is_servicer(servicer_id):
            return ServiceResult("forbidden", ok=False)
        return ServiceResult(
            "blacklist",
            data={
                "user_ids": sorted(self.cfg.blacklist),
                "title": "【黑名单列表】",
            },
        )

    def unblacklist_user(
        self, servicer_id: str, user_id: str, user_name: str
    ) -> ServiceResult:
        if not self.cfg.is_servicer(servicer_id):
            return ServiceResult("forbidden", ok=False)
        user_label = f"【{user_name}】({user_id})" if user_name != user_id else user_id
        if not self.cfg.remove_from_blacklist(user_id):
            return ServiceResult("not_blacklisted", f"{user_label} 不在黑名单中", False)
        return ServiceResult("unblacklisted", f"已将{user_label} 从黑名单移除")

    def accept_conversation(
        self, servicer_id: str, servicer_name: str, user_id: str
    ) -> ServiceResult:
        if not self.cfg.is_servicer(servicer_id):
            return ServiceResult("forbidden", ok=False)
        session = self.session_mgr.get_session(user_id)
        if not session or session.status is not SessionStatus.WAITING:
            return ServiceResult("request_missing", "该用户未请求人工", False)
        if session.assigned_servicer_id and session.assigned_servicer_id != servicer_id:
            return ServiceResult(
                "assigned_to_other",
                "该请求已自动分配给其他客服",
                False,
            )

        session.status = SessionStatus.CONNECTED
        session.servicer_id = servicer_id
        session.servicer_name = servicer_name
        session.assigned_servicer_id = None
        self.session_mgr.touch(user_id)
        self.chat_history[user_id] = []

        tips = (
            f"已接入【{session.user_name}】({session.user_id})，"
            "接下来我将转发你的消息给对方，请开始对话："
        )
        return ServiceResult(
            "connected",
            tips,
            notifications=[
                Notification(
                    f"客服【{session.servicer_name}】已接入",
                    group_id=session.group_id,
                    user_id=user_id,
                )
            ],
        )

    def reject_conversation(self, servicer_id: str, user_id: str) -> ServiceResult:
        if not self.cfg.is_servicer(servicer_id):
            return ServiceResult("forbidden", ok=False)
        session = self.session_mgr.get_session(user_id)
        if not session or session.status is not SessionStatus.WAITING:
            return ServiceResult("request_missing", "该用户未请求人工或已被接入", False)
        if session.assigned_servicer_id and session.assigned_servicer_id != servicer_id:
            return ServiceResult(
                "assigned_to_other",
                "该请求已自动分配给其他客服",
                False,
            )
        self.session_mgr.delete_session(user_id)
        return ServiceResult(
            "rejected",
            f"已拒绝【{session.user_name}】({session.user_id}) 的接入请求",
            notifications=[
                Notification(
                    "抱歉，客服暂时无法接入，请稍后再试或联系其他客服",
                    group_id=session.group_id,
                    user_id=user_id,
                )
            ],
        )

    def end_conversation(self, servicer_id: str) -> ServiceResult:
        if not self.cfg.is_servicer(servicer_id):
            return ServiceResult("forbidden", ok=False)
        user_id = self.session_mgr.get_user_by_servicer(servicer_id)
        if not user_id:
            return ServiceResult("conversation_missing", "当前无对话需要结束", False)
        session = self.session_mgr.get_session(user_id)
        if not session:
            return ServiceResult("conversation_missing", "当前无对话需要结束", False)
        notifications = [
            Notification(
                f"客服【{session.servicer_name}】已结束对话",
                group_id=session.group_id,
                user_id=user_id,
            )
        ]
        history_export = self._close_session(user_id)
        next_result = self.prepare_next_user(
            servicer_id,
            f"已结束与【{session.user_name}】({session.user_id}) 的对话",
        )
        notifications.extend(next_result.notifications)
        message = (
            ""
            if next_result.code == "next_user"
            else (
                f"已结束与【{session.user_name}】({session.user_id}) 的对话，"
                "当前队列为空"
            )
        )
        return ServiceResult(
            "conversation_ended",
            message,
            data={"user_id": user_id, **next_result.data},
            notifications=notifications,
            history_exports=[history_export] if history_export else [],
        )

    def prepare_next_user(
        self, servicer_id: str, context_message: str = ""
    ) -> ServiceResult:
        next_user = self.queue_mgr.pop_next(servicer_id)
        if not next_user:
            return ServiceResult("queue_empty")

        user_id = next_user.user_id
        self.session_mgr.create_session(
            ServiceSession(
                user_id=user_id,
                group_id=next_user.group_id,
                user_name=next_user.user_name,
                assigned_servicer_id=servicer_id,
            )
        )
        remaining = self.queue_mgr.get_size(servicer_id)
        queue_info = f"（队列剩余 {remaining} 人）" if remaining else "（队列已清空）"
        context_info = f"{context_message}\n" if context_message else ""
        return ServiceResult(
            "next_user",
            data={"user_id": user_id, "remaining_queue": remaining},
            notifications=[
                Notification(
                    "⏰ 轮到您了！客服正在准备接入您的对话...\n"
                    "客服可以使用 /客服 接入 命令开始服务",
                    group_id=next_user.group_id,
                    user_id=user_id,
                ),
                Notification(
                    f"{context_info}"
                    "📋 队列中的下一位用户已准备就绪：\n"
                    f"用户：【{next_user.user_name}】({user_id})\n"
                    "请使用 /客服 接入 命令（回复用户消息）开始服务\n"
                    f"{queue_info}",
                    user_id=servicer_id,
                ),
            ],
        )

    def check_timeouts(self) -> ServiceResult:
        notifications = []
        for user_id in self.session_mgr.get_idle_user_ids():
            session = self.session_mgr.get_session(user_id)
            if not session:
                continue
            servicer_id = session.servicer_id
            notifications.append(
                Notification(
                    "⏰ 对话因长时间无人参与已自动结束。如需继续咨询，请重新转人工",
                    group_id=session.group_id,
                    user_id=user_id,
                )
            )
            self._close_session(user_id)
            next_result = self.prepare_next_user(
                servicer_id,
                f"⏰ 与【{session.user_name}】({session.user_id}) 的对话"
                "因长时间无人参与已自动结束",
            )
            notifications.extend(next_result.notifications)
            if next_result.code == "queue_empty":
                notifications.append(
                    Notification(
                        f"⏰ 与【{session.user_name}】({session.user_id}) 的对话"
                        "因长时间无人参与已自动结束\n"
                        "📋 当前队列为空",
                        user_id=servicer_id,
                    )
                )

        for item in self.queue_mgr.pop_expired():
            notifications.append(
                Notification(
                    f"⏰ 排队时间已超过 {self.cfg.queue_timeout} 秒，已自动退出队列\n"
                    "如需继续咨询，请重新转人工",
                    group_id=item.group_id,
                    user_id=item.user_id,
                )
            )
        return ServiceResult("timeouts_checked", notifications=notifications)

    def route_servicer_message(self, servicer_id: str, message: str) -> ServiceResult:
        if not self.cfg.is_servicer(servicer_id):
            return ServiceResult("not_routed", ok=False)
        user_id = self.session_mgr.get_user_by_servicer(servicer_id)
        if not user_id:
            return ServiceResult("not_routed", ok=False)
        session = self.session_mgr.get_session(user_id)
        if not session:
            return ServiceResult("not_routed", ok=False)
        if user_id in self.chat_history:
            self.chat_history[user_id].append(
                ChatRecord.create(
                    sender_id=servicer_id,
                    name=f"客服【{session.servicer_name}】",
                    message=message,
                )
            )
        self.session_mgr.touch(user_id)
        return ServiceResult(
            "route_message",
            data={
                "group_id": session.group_id,
                "user_id": user_id,
                "identity_icon": self.cfg.servicer_icon,
            },
        )

    def route_user_message(self, user_id: str, message: str) -> ServiceResult:
        session = self.session_mgr.get_session(user_id)
        if not session or session.status is not SessionStatus.CONNECTED:
            return ServiceResult("not_routed", ok=False)
        if user_id in self.chat_history:
            self.chat_history[user_id].append(
                ChatRecord.create(
                    sender_id=user_id,
                    name=session.user_name,
                    message=message,
                )
            )
        self.session_mgr.touch(user_id)
        return ServiceResult(
            "route_message",
            data={
                "user_id": session.servicer_id,
                "identity_icon": self.cfg.user_icon,
            },
        )

    def _close_session(self, user_id: str) -> HistoryExport | None:
        session = self.session_mgr.get_session(user_id)
        history = self.chat_history.pop(user_id, [])
        self.session_mgr.delete_session(user_id)
        if not session or not session.servicer_id or not history:
            return None
        return HistoryExport(session.servicer_id, history)
