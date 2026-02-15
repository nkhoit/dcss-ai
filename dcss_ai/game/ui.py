"""UIHandler mixin: menu and popup interaction."""
import time
import logging

from .utils import _strip_formatting

logger = logging.getLogger(__name__)


class UIHandler:
    """Mixin providing UI interaction methods (menus, popups)."""

    def read_ui(self) -> str:
        if self._current_menu:
            return self.read_menu()
        if self._current_popup:
            return self.read_popup()
        return "No menu or popup is currently open."

    def dismiss(self) -> str:
        if self._current_menu:
            return self.close_menu()
        if self._current_popup:
            return self.dismiss_popup()
        self._ws.send_key("key_esc")
        return "Escape pressed."

    def read_menu(self) -> str:
        if not self._current_menu:
            return "No menu is currently open."
        m = self._current_menu
        lines = []
        tag = m.get("tag", "unknown")
        title = m.get("title", {})
        if isinstance(title, dict):
            title_text = title.get("text", "Menu")
        elif isinstance(title, str):
            title_text = title
        else:
            title_text = "Menu"
        title_text = _strip_formatting(title_text)
        lines.append(f"=== {title_text} (type: {tag}) ===")
        more = m.get("more", "")
        if isinstance(more, dict):
            more = more.get("text", "")
        more = _strip_formatting(more)
        if more:
            lines.append(more)
        for item in self._menu_items:
            text = item.get("text", "")
            text = _strip_formatting(text)
            if not text.strip():
                continue
            level = item.get("level", 2)
            hotkeys = item.get("hotkeys", [])
            if level < 2:
                lines.append(f"\n  {text}")
            elif hotkeys:
                key = chr(hotkeys[0]) if isinstance(hotkeys[0], int) else hotkeys[0]
                lines.append(f"  [{key}] {text}")
            else:
                lines.append(f"      {text}")
        return "\n".join(lines)

    def select_menu_item(self, key: str) -> str:
        if not self._current_menu:
            return "No menu is currently open."
        self._ws.send_key(key)
        time.sleep(0.3)
        msgs = self._ws.recv_messages(timeout=1.0)
        menu_closed = False
        for msg in msgs:
            self._process_msg(msg)
            mt = msg.get("msg")
            if mt == "close_menu":
                menu_closed = True
                self._current_menu = None
                self._menu_items = []
            elif mt in ("menu", "update_menu", "update_menu_items"):
                self._handle_menu_msg(msg)
        if menu_closed:
            return f"Menu closed after pressing '{key}'."
        elif self._current_menu:
            return f"Pressed '{key}'. Menu still open. Use read_menu() to see updated state."
        return f"Pressed '{key}'."

    def close_menu(self) -> str:
        if not self._current_menu:
            return "No menu is currently open."
        self._ws.send_key("key_esc")
        time.sleep(0.3)
        msgs = self._ws.recv_messages(timeout=1.0)
        for msg in msgs:
            self._process_msg(msg)
            if msg.get("msg") == "close_menu":
                self._current_menu = None
                self._menu_items = []
        self._current_menu = None
        self._menu_items = []
        return "Menu closed."

    def _handle_menu_msg(self, msg: dict):
        mt = msg.get("msg")
        if mt == "menu":
            self._current_menu = msg
            self._menu_items = msg.get("items", [])
        elif mt == "update_menu":
            if self._current_menu:
                for k, v in msg.items():
                    if k != "msg":
                        self._current_menu[k] = v
                if "items" in msg:
                    self._menu_items = msg["items"]
        elif mt == "update_menu_items":
            chunk_start = msg.get("chunk_start", 0)
            new_items = msg.get("items", [])
            for i, item in enumerate(new_items):
                idx = chunk_start + i
                if idx < len(self._menu_items):
                    self._menu_items[idx] = item
                else:
                    self._menu_items.append(item)

    def _handle_ui_msg(self, msg: dict):
        mt = msg.get("msg")
        if mt == "ui-push":
            self._current_popup = msg
        elif mt == "ui-state" and self._current_popup:
            for k, v in msg.items():
                if k != "msg":
                    self._current_popup[k] = v

    def read_popup(self) -> str:
        if not self._current_popup:
            return "No popup is currently open."
        p = self._current_popup
        ui_type = p.get("type", "unknown")
        lines = [f"=== Popup: {ui_type} ==="]
        body = p.get("body", "")
        if body:
            if isinstance(body, str):
                lines.append(_strip_formatting(body))
            elif isinstance(body, dict):
                lines.append(_strip_formatting(body.get("text", str(body))))
        title = p.get("title", "")
        if title:
            if isinstance(title, str):
                lines.insert(1, _strip_formatting(title))
            elif isinstance(title, dict):
                lines.insert(1, _strip_formatting(title.get("text", "")))
        prompt = p.get("prompt", "")
        if prompt:
            lines.append(_strip_formatting(prompt if isinstance(prompt, str) else str(prompt)))
        for field in ("description", "quote", "spells_description", "stats"):
            val = p.get(field, "")
            if val:
                text = val if isinstance(val, str) else str(val)
                lines.append(_strip_formatting(text))
        if len(lines) == 1:
            data_keys = [k for k in p.keys() if k not in ("msg", "type", "generation_id")]
            lines.append(f"Data keys: {', '.join(data_keys)}")
        return "\n".join(lines)

    def dismiss_popup(self) -> str:
        if not self._current_popup:
            return "No popup is currently open."
        self._ws.send_key("key_esc")
        time.sleep(0.3)
        msgs = self._ws.recv_messages(timeout=1.0)
        for msg in msgs:
            self._process_msg(msg)
            if msg.get("msg") == "ui-pop":
                self._current_popup = None
        self._current_popup = None
        return "Popup dismissed."
