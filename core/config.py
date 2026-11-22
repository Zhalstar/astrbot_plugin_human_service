"""Typed configuration for the human service plugin."""

from astrbot.api import AstrBotConfig
from astrbot.api.star import Context


class PluginConfig:
    servicer_icon = "👤"
    user_icon = "🧑"

    servicers_id: list[str]
    blacklist: list[str]
    conversation_idle_timeout: int
    queue_timeout: int

    def __init__(self, config: AstrBotConfig, context: Context):
        self._config = config
        self.servicers_id = self._init_servicers_id(context)
        self.blacklist = config["blacklist"]
        self.conversation_idle_timeout = config["conversation_idle_timeout"]
        self.queue_timeout = config["queue_timeout"]

    def _init_servicers_id(self, context: Context) -> list[str]:
        if servicers_id := self._config["servicers_id"]:
            return [str(user_id) for user_id in servicers_id]

        servicers_id = [
            str(user_id)
            for user_id in context.get_config().get("admins_id", [])
            if str(user_id).isdigit()
        ]
        self._config["servicers_id"] = servicers_id
        self._config.save_config()
        return servicers_id

    def is_servicer(self, user_id: str) -> bool:
        return user_id in self.servicers_id

    def is_blacklisted(self, user_id: str) -> bool:
        return user_id in self.blacklist

    def add_to_blacklist(self, user_id: str) -> None:
        if user_id in self.blacklist:
            return
        self.blacklist.append(user_id)
        self._config["blacklist"] = self.blacklist
        self._config.save_config()

    def remove_from_blacklist(self, user_id: str) -> bool:
        if user_id not in self.blacklist:
            return False
        self.blacklist.remove(user_id)
        self._config["blacklist"] = self.blacklist
        self._config.save_config()
        return True
