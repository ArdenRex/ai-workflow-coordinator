"""Gmail connector (read-only): list and read messages of the mailbox that owns the OAuth grant.

Uses OAuth refresh-token credentials (see app/connectors/oauth.py) and refuses a grant broader than gmail.readonly.
Only GET requests are made, only to the users/me profile, messages.list and messages.get endpoints. The list is one
messages.list call plus one metadata call per message (at most `limit` <= 25). Shapes follow Gmail API v1 as I know it;
verify against a real account before relying on it in production.
"""
import base64
import binascii
import re
from email.message import EmailMessage
from html import unescape
from typing import Any, Dict, List, Optional

from pydantic import ValidationError

from app.connectors.base import Capability, ConnectionStatus
from app.connectors.email.base import (CURSOR_PATTERN, ComposeEmailInput, DraftEmailOutput, EmailWriter, SendEmailOutput, MESSAGE_ID_PATTERN, EmailConnector, GetMessageInput,
                                       GetMessageOutput, ListMessagesInput, ListMessagesOutput, MessageDetail,
                                       MessageSummary, email_tool_definitions)
from app.connectors.errors import ConnectorBadResponseError, ConnectorError, ConnectorNotFoundError
from app.connectors.kit import clean_text
from app.connectors.oauth import OAuthConnector
from app.kernel.registry import ToolDefinition

GMAIL_SCOPES = frozenset({"https://www.googleapis.com/auth/gmail.readonly"})
GMAIL_WRITE_SCOPES = frozenset({"https://www.googleapis.com/auth/gmail.compose", "https://www.googleapis.com/auth/gmail.send"})
_CURSOR = re.compile(CURSOR_PATTERN)
_ID = re.compile(MESSAGE_ID_PATTERN)
_META = ["From", "Subject", "Date"]
_FULL_META = ["From", "To", "Cc", "Subject", "Date"]
_MAX_PARTS, _MAX_DEPTH, _MAX_BODY_BYTES = 50, 6, 200_000
_BODY_CHARS = 4000
_TAGS = re.compile(r"<(script|style)\b.*?</\1\s*>|<[^>]*>", re.I | re.S)
_bad = lambda: ConnectorBadResponseError("External system returned an unexpected shape")  # noqa: E731


def _headers(payload: Any, wanted: List[str]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    hs = payload.get("headers") if isinstance(payload, dict) else None
    if hs is None:
        return out
    if not isinstance(hs, list):
        raise _bad()
    for h in hs:
        if not isinstance(h, dict) or not isinstance(h.get("name"), str) or not isinstance(h.get("value"), str):
            raise _bad()
        for w in wanted:
            if h["name"].lower() == w.lower() and w not in out:
                out[w] = h["value"].replace("\r", " ").replace("\n", " ")
    return out


class GmailConnector(OAuthConnector, EmailConnector, EmailWriter):
    name = "gmail"
    allowed_scopes = GMAIL_SCOPES
    write_scopes = GMAIL_WRITE_SCOPES
    probe_path = "/gmail/v1/users/me/profile"

    def capabilities(self) -> List[Capability]:
        caps = [Capability("message.list", "List email messages"), Capability("message.get", "Read one email message")]
        if self.allow_write:
            caps += [Capability("draft", "Save an email draft", write=True), Capability("send", "Send an email", write=True)]
        return caps

    def tools(self) -> List[ToolDefinition]:
        return email_tool_definitions(lambda workspace_id: self)

    def validate_connection(self) -> ConnectionStatus:
        try:
            self._request("GET", self.probe_path)
            return ConnectionStatus(True, "Connected")
        except ConnectorError as exc:
            return ConnectionStatus(False, exc.code)
        except Exception:
            return ConnectionStatus(False, "connector_error")

    # -- reads -------------------------------------------------------------------
    def list_messages(self, data: ListMessagesInput) -> ListMessagesOutput:
        q = ["is:unread"] if data.unread_only else []
        if data.query:
            q.append(data.query)
        params: Dict[str, Any] = {"labelIds": data.label, "maxResults": data.limit}
        if q:
            params["q"] = " ".join(q)
        if data.cursor:
            params["pageToken"] = data.cursor
        raw = self._request("GET", "/gmail/v1/users/me/messages", params=params)
        if not isinstance(raw, dict):
            raise _bad()
        refs = raw.get("messages", [])
        if refs is None:
            refs = []
        if not isinstance(refs, list):
            raise _bad()
        out = []
        for ref in refs[:data.limit]:
            mid = ref.get("id") if isinstance(ref, dict) else None
            if not isinstance(mid, str) or not _ID.match(mid):
                raise _bad()
            meta = self._request("GET", f"/gmail/v1/users/me/messages/{mid}",
                                 params={"format": "metadata", "metadataHeaders": _META})
            out.append(self._summary(meta, mid))
        nxt = raw.get("nextPageToken")
        if nxt is not None and (not isinstance(nxt, str) or not _CURSOR.match(nxt)):
            raise _bad()
        return ListMessagesOutput(messages=out, next_cursor=nxt or None)

    def get_message(self, data: GetMessageInput) -> GetMessageOutput:
        raw = self._request("GET", f"/gmail/v1/users/me/messages/{data.message_id}", params={"format": "full"})
        if not isinstance(raw, dict):
            raise _bad()
        if raw.get("id") != data.message_id:
            raise ConnectorNotFoundError("Resource not found in external system")   # an answer for another id is refused
        base = self._summary(raw, data.message_id)
        payload = raw.get("payload")
        if not isinstance(payload, dict):
            raise _bad()
        hs = _headers(payload, _FULL_META)
        body, truncated, attachments = self._body(payload)
        try:
            return GetMessageOutput(message=MessageDetail(**base.model_dump(), to=hs.get("To"), cc=hs.get("Cc"),
                                                          body=body, body_truncated=truncated,
                                                          has_attachments=attachments))
        except ValidationError:
            raise _bad() from None

    # -- helpers -----------------------------------------------------------------
    def _summary(self, raw: Any, expected_id: str) -> MessageSummary:
        if not isinstance(raw, dict) or raw.get("id") != expected_id:
            raise _bad()
        labels = raw.get("labelIds")
        if labels is not None and not (isinstance(labels, list) and all(isinstance(x, str) for x in labels)):
            raise _bad()
        hs = _headers(raw.get("payload"), _META)
        try:
            return MessageSummary(id=expected_id, thread_id=raw.get("threadId"), sender=hs.get("From"),
                                  subject=hs.get("Subject"), date=hs.get("Date"), snippet=unescape(raw["snippet"])
                                  if isinstance(raw.get("snippet"), str) else raw.get("snippet"),
                                  unread=None if labels is None else "UNREAD" in labels)
        except ValidationError:
            raise _bad() from None

    @staticmethod
    def _decode(data: Any) -> str:
        if not isinstance(data, str) or len(data) > _MAX_BODY_BYTES:
            raise _bad()
        try:
            return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode("utf-8", errors="replace")
        except (binascii.Error, ValueError):
            raise _bad() from None

    def _body(self, payload: dict):
        """Plain text preferred, HTML stripped as a fallback. Attachments are never read, only noticed."""
        plain: Optional[str] = None
        html: Optional[str] = None
        attachments, seen = False, 0
        stack = [(payload, 0)]
        while stack:
            part, depth = stack.pop()
            seen += 1
            if seen > _MAX_PARTS or depth > _MAX_DEPTH or not isinstance(part, dict):
                raise _bad()
            if part.get("filename"):
                attachments = True
                continue
            mime, body = part.get("mimeType"), part.get("body")
            if isinstance(body, dict) and body.get("data") is not None:
                if mime == "text/plain" and plain is None:
                    plain = self._decode(body["data"])
                elif mime == "text/html" and html is None:
                    html = self._decode(body["data"])
            subparts = part.get("parts")
            if subparts is not None:
                if not isinstance(subparts, list):
                    raise _bad()
                stack.extend((p, depth + 1) for p in reversed(subparts))
        text = plain if plain is not None else (unescape(_TAGS.sub(" ", html)) if html is not None else None)
        if text is None:
            return None, False, attachments
        text = re.sub(r"[ \t]+", " ", clean_text(text, 20_000) or "").strip()
        return text[:_BODY_CHARS], len(text) > _BODY_CHARS, attachments


    # -- writes (10.5): only when the connection has allow_write; never retried (see HttpConnector._request) ----------
    @staticmethod
    def _raw(data: ComposeEmailInput) -> str:
        msg = EmailMessage()
        msg["To"] = ", ".join(data.to)
        if data.cc:
            msg["Cc"] = ", ".join(data.cc)
        msg["Subject"] = data.subject
        msg.set_content(data.body)
        return base64.urlsafe_b64encode(msg.as_bytes()).decode("ascii")

    def create_draft(self, data: ComposeEmailInput) -> DraftEmailOutput:
        self._require_write()
        raw = self._request("POST", "/gmail/v1/users/me/drafts", json_body={"message": {"raw": self._raw(data)}})
        if not isinstance(raw, dict) or not isinstance(raw.get("id"), str):
            raise _bad()
        message = raw.get("message")
        if message is not None and not isinstance(message, dict):
            raise _bad()
        try:
            return DraftEmailOutput(draft_id=raw["id"], message_id=(message or {}).get("id"))
        except ValidationError:
            raise _bad() from None

    def send_message(self, data: ComposeEmailInput) -> SendEmailOutput:
        self._require_write()
        raw = self._request("POST", "/gmail/v1/users/me/messages/send", json_body={"raw": self._raw(data)})
        if not isinstance(raw, dict):
            raise _bad()
        try:
            return SendEmailOutput(message_id=raw.get("id"), thread_id=raw.get("threadId"))
        except ValidationError:
            raise _bad() from None
