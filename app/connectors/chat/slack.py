"""Slack connector (read-only): public channels and their recent messages, via a bot token.

Only GET requests are made, and only to conversations.list, conversations.info, conversations.history and auth.test.
Slack answers most failures with HTTP 200 and {"ok": false, "error": "<code>"}; the code is mapped to a fixed connector
error and the remote text is never echoed. Before history is read, the channel is checked to be a public channel, so a
private channel, DM or group DM id can never be read through this tool even if the bot token could reach it.
Shapes follow Slack's Web API as I know it; verify against a real workspace before relying on it in production.
"""
import re
from typing import Any, List, Optional

from pydantic import ValidationError

from app.connectors.base import Capability, ConnectionStatus
from app.connectors.chat.base import (CURSOR_PATTERN, Channel, ChatConnector, ChatWriter, PostMessageInput, PostMessageOutput, ListChannelsInput, ListChannelsOutput,
                                      ListMessagesInput, ListMessagesOutput, Message, chat_tool_definitions)
from app.connectors.errors import (ConnectorAuthError, ConnectorBadResponseError, ConnectorError,
                                   ConnectorNotFoundError, ConnectorRateLimitedError)
from app.connectors.kit import KitConnector
from app.connectors.writes import WriteGate
from app.kernel.registry import ToolDefinition

_CURSOR = re.compile(CURSOR_PATTERN)
_AUTH = {"invalid_auth", "not_authed", "account_inactive", "token_revoked", "token_expired", "missing_scope",
         "no_permission", "access_denied"}
_NOT_FOUND = {"channel_not_found", "not_in_channel", "is_archived"}
_SKIP_SUBTYPES_EXCEPT = {None, "bot_message", "thread_broadcast"}
_bad = lambda: ConnectorBadResponseError("External system returned an unexpected shape")  # noqa: E731


class SlackConnector(KitConnector, ChatConnector, ChatWriter, WriteGate):
    name = "slack"
    auth_kind = "bearer"

    def __init__(self, config, *, allow_write: bool = False, **kw):
        self.allow_write = allow_write
        super().__init__(config, **kw)

    def capabilities(self) -> List[Capability]:
        caps = [Capability("channel.list", "List public channels"), Capability("message.list", "Read public channel messages")]
        if self.allow_write:
            caps.append(Capability("message.post", "Post to a public channel", write=True))
        return caps

    def tools(self) -> List[ToolDefinition]:
        return chat_tool_definitions(lambda workspace_id: self)

    def validate_connection(self) -> ConnectionStatus:
        try:
            self._slack("/auth.test")
            return ConnectionStatus(True, "Connected")
        except ConnectorError as exc:
            return ConnectionStatus(False, exc.code)
        except Exception:
            return ConnectionStatus(False, "connector_error")

    # -- transport ---------------------------------------------------------------
    def _slack(self, path: str, params: Optional[dict] = None, *, method: str = "GET", body: Optional[dict] = None) -> dict:
        raw = self._request(method, path, params=params, json_body=body)
        if not isinstance(raw, dict) or not isinstance(raw.get("ok"), bool):
            raise _bad()
        if raw["ok"]:
            return raw
        code = raw.get("error")
        if code in _AUTH:
            raise ConnectorAuthError("External system rejected the credentials")
        if code in _NOT_FOUND:
            raise ConnectorNotFoundError("Resource not found in external system")
        if code == "ratelimited":
            raise ConnectorRateLimitedError()
        raise _bad()                                   # the remote's error text is never echoed

    @staticmethod
    def _next(raw: dict) -> Optional[str]:
        meta = raw.get("response_metadata")
        if meta is None:
            return None
        if not isinstance(meta, dict):
            raise _bad()
        cursor = meta.get("next_cursor")
        if cursor in (None, ""):
            return None
        if not isinstance(cursor, str) or not _CURSOR.match(cursor):
            raise _bad()
        return cursor

    @staticmethod
    def _is_public_channel(info: Any) -> bool:
        return (isinstance(info, dict) and info.get("is_channel") is True and info.get("is_private") is not True
                and info.get("is_im") is not True and info.get("is_mpim") is not True and info.get("is_group") is not True)

    # -- reads -------------------------------------------------------------------
    def list_channels(self, data: ListChannelsInput) -> ListChannelsOutput:
        params = {"types": "public_channel", "exclude_archived": "true", "limit": data.limit}
        if data.cursor:
            params["cursor"] = data.cursor
        raw = self._slack("/conversations.list", params)
        if not isinstance(raw.get("channels"), list):
            raise _bad()
        channels = []
        for c in raw["channels"]:
            if not isinstance(c, dict):
                raise _bad()
            if not self._is_public_channel(c) or c.get("is_archived") is True:
                continue                                   # defence in depth: never surface non-public channels
            try:
                channels.append(Channel(id=c.get("id"), name=c.get("name"), member_count=c.get("num_members"),
                                        topic=(c.get("topic") or {}).get("value"),
                                        purpose=(c.get("purpose") or {}).get("value")))
            except (ValidationError, AttributeError):
                raise _bad() from None
        return ListChannelsOutput(channels=channels[:data.limit], next_cursor=self._next(raw))

    def list_messages(self, data: ListMessagesInput) -> ListMessagesOutput:
        info = self._slack("/conversations.info", {"channel": data.channel_id}).get("channel")
        if not self._is_public_channel(info):
            raise ConnectorNotFoundError("Resource not found in external system")   # private/DM ids look like missing ones
        params = {"channel": data.channel_id, "limit": data.limit}
        if data.cursor:
            params["cursor"] = data.cursor
        raw = self._slack("/conversations.history", params)
        if not isinstance(raw.get("messages"), list):
            raise _bad()
        out = []
        for m in raw["messages"]:
            if not isinstance(m, dict):
                raise _bad()
            if m.get("type") != "message" or m.get("subtype") not in _SKIP_SUBTYPES_EXCEPT or not isinstance(m.get("text"), str):
                continue
            try:
                out.append(Message(ts=m.get("ts"), author_id=m.get("user"), text=m.get("text"), thread_ts=m.get("thread_ts")))
            except ValidationError:
                raise _bad() from None
        return ListMessagesOutput(messages=out[:data.limit], next_cursor=self._next(raw))

    # -- writes (10.5): only when the connection has allow_write; never retried -------------------------------------
    def post_message(self, data: PostMessageInput) -> PostMessageOutput:
        self._require_write()
        info = self._slack("/conversations.info", {"channel": data.channel_id}).get("channel")
        if not self._is_public_channel(info):
            raise ConnectorNotFoundError("Resource not found in external system")   # never post to private channels or DMs
        raw = self._slack("/chat.postMessage", method="POST",
                          body={"channel": data.channel_id, "text": data.text, "parse": "none", "link_names": False,
                                "unfurl_links": False, "unfurl_media": False})
        if raw.get("channel") != data.channel_id:
            raise _bad()
        try:
            return PostMessageOutput(channel_id=data.channel_id, ts=raw.get("ts"))
        except ValidationError:
            raise _bad() from None
