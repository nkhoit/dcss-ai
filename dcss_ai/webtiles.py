"""Pure Python WebSocket client for DCSS webtiles with proper timeout support.

Replaces the dcss_api Rust library to avoid GIL-blocking issues with read_until().
"""

import json
import zlib
import time
import re
import threading
from typing import List, Dict, Any, Tuple, Optional
from collections import deque
import websockets.sync.client


class WebTilesConnection:
    """Pure Python WebSocket connection to DCSS webtiles."""
    
    SPECIAL_KEYS = {
        "key_tab": {"msg": "key", "keycode": 9},
        "key_esc": {"msg": "key", "keycode": 27},
        "key_enter": {"msg": "input", "text": "\r"},
        "key_dir_n": {"msg": "input", "text": "8"},
        "key_dir_ne": {"msg": "input", "text": "9"},
        "key_dir_e": {"msg": "input", "text": "6"},
        "key_dir_se": {"msg": "input", "text": "3"},
        "key_dir_s": {"msg": "input", "text": "2"},
        "key_dir_sw": {"msg": "input", "text": "1"},
        "key_dir_w": {"msg": "input", "text": "4"},
        "key_dir_nw": {"msg": "input", "text": "7"},
    }
    
    def __init__(self, url: str):
        self.url = url
        self._ws = websockets.sync.client.connect(url)
        self._decompressor = zlib.decompressobj(-15)  # Raw deflate, stateful
        self._queue: deque = deque()
        self._last_msg_time = time.time()
        self._ping_stop = threading.Event()
        self._ping_thread = threading.Thread(target=self._ping_loop, daemon=True)
        self._ping_thread.start()
    
    def _ping_loop(self):
        """Background thread that sends keepalive pings every 30s of inactivity.
        Also drains incoming messages to catch and respond to server pings."""
        while not self._ping_stop.wait(10):
            try:
                # Drain any pending messages (this auto-responds to server pings via _decode)
                if self._ws:
                    try:
                        raw = self._ws.recv(timeout=0)
                        msgs = self._decode(raw)
                        # Queue any non-ping messages for later processing
                        for msg in msgs:
                            if msg.get("msg") != "ping":
                                self._queue.append(msg)
                    except (TimeoutError, Exception):
                        pass
                # Also send proactive pong if idle
                if time.time() - self._last_msg_time > 30:
                    self.ping()
            except Exception:
                break

    def ping(self) -> None:
        """Send a keepalive ping to prevent server timeout."""
        self._send({"msg": "pong"})
        self._last_msg_time = time.time()
    
    def send_key(self, key: str) -> None:
        """Send a key. Supports key_dir_n, key_tab, key_esc, key_ctrl_X, or plain chars."""
        if key in self.SPECIAL_KEYS:
            self._send(self.SPECIAL_KEYS[key])
        elif key.startswith("key_ctrl_") and len(key) == 10:
            ch = key[9].lower()
            self._send({"msg": "key", "keycode": ord(ch) - ord('a') + 1})
        elif len(key) == 1:
            self._send({"msg": "input", "text": key})
        else:
            # Try sending as raw text (multi-char like "yes", "quit")
            self._send({"msg": "input", "text": key})
    
    def _send(self, data: dict) -> None:
        if not self._ws:
            raise RuntimeError("Not connected")
        self._ws.send(json.dumps(data))
        self._last_msg_time = time.time()
    
    def recv_messages(self, timeout: float = 0.1) -> List[dict]:
        """Receive and return all available messages, waiting up to timeout seconds.
        Returns empty list on timeout.
        """
        result = []
        # Drain queue first
        while self._queue:
            result.append(self._queue.popleft())
        
        # Try receiving from WebSocket
        deadline = time.time() + timeout
        while True:
            remaining = deadline - time.time()
            if remaining <= 0 and result:
                break
            try:
                raw = self._ws.recv(timeout=max(0.01, remaining))
            except TimeoutError:
                break
            except websockets.exceptions.ConnectionClosed:
                break
            
            msgs = self._decode(raw)
            result.extend(msgs)
            
            # If we got messages and still have time, try to get more non-blocking
            if msgs:
                try:
                    while True:
                        raw2 = self._ws.recv(timeout=0)
                        result.extend(self._decode(raw2))
                except (TimeoutError, websockets.exceptions.ConnectionClosed):
                    pass
                break
        
        return result
    
    def wait_for(self, msg_type: str, key: str = None, value: Any = None,
                 timeout: float = 30.0) -> Tuple[bool, List[dict]]:
        """Wait for a specific message type. Returns (found, all_messages).
        Never blocks indefinitely.
        """
        all_msgs = []
        deadline = time.time() + timeout
        
        while time.time() < deadline:
            remaining = deadline - time.time()
            msgs = self.recv_messages(timeout=min(1.0, remaining))
            all_msgs.extend(msgs)
            
            for msg in msgs:
                if msg.get("msg") == msg_type:
                    if key is None or msg.get(key) == value:
                        return True, all_msgs
        
        return False, all_msgs
    
    def _decode(self, raw) -> List[dict]:
        """Decode a WebSocket frame into message dicts.
        Automatically responds to server ping messages."""
        if isinstance(raw, bytes):
            # Binary: deflate-compressed
            data = raw + b'\x00\x00\xff\xff'
            try:
                text = self._decompressor.decompress(data).decode('utf-8')
            except Exception:
                return []
            try:
                msgs = json.loads(text).get("msgs", [])
            except (json.JSONDecodeError, AttributeError):
                return []
        elif isinstance(raw, str):
            try:
                msgs = json.loads(raw).get("msgs", [])
            except (json.JSONDecodeError, AttributeError):
                return []
        else:
            return []
        
        # Auto-respond to server pings to prevent connection timeout
        for msg in msgs:
            if msg.get("msg") == "ping":
                try:
                    self._send({"msg": "pong"})
                except Exception:
                    pass
        
        return msgs
    
    # --- High-level protocol ---
    
    def register(self, username: str, password: str) -> None:
        """Register account. Silently succeeds if user already exists."""
        self._send({"msg": "register", "username": username, "password": password, "email": ""})
        found, msgs = self.wait_for("login_success", timeout=10.0)
        if not found:
            # User probably exists — will login separately
            pass
    
    def login(self, username: str, password: str) -> List[str]:
        """Login and return list of game IDs."""
        self._send({"msg": "login", "username": username, "password": password})
        found, login_msgs = self.wait_for("login_success", timeout=10.0)
        if not found:
            raise RuntimeError("Login failed")
        
        self._send({"msg": "go_lobby"})
        found, lobby_msgs = self.wait_for("go_lobby", timeout=10.0)
        
        # Extract game IDs from all messages
        all_msgs = login_msgs + lobby_msgs
        game_ids = []
        for msg in all_msgs:
            if msg.get("msg") == "set_game_links":
                content = msg.get("content", "")
                game_ids = re.findall(r'#play-([^"]+)"', content)
                if game_ids:
                    break
        return game_ids
    
    def start_game(self, game_id: str, species: str, background: str, weapon: str) -> List[dict]:
        """Start a new game. Handles character creation prompts.
        Returns all messages received during startup.
        """
        self._send({"msg": "play", "game_id": game_id})
        
        choices = [species, background, weapon]
        choice_idx = 0
        all_msgs = []
        
        # Loop: wait for either "map" (game started) or need to send a choice
        deadline = time.time() + 30.0
        while time.time() < deadline:
            msgs = self.recv_messages(timeout=2.0)
            all_msgs.extend(msgs)
            
            got_map = False
            for msg in msgs:
                mt = msg.get("msg")
                if mt == "map":
                    got_map = True
                elif mt == "ui-state" and msg.get("type") == "newgame-choice" and choice_idx < len(choices):
                    # Character creation menu — send next choice
                    self.send_key(choices[choice_idx])
                    choice_idx += 1
            
            if got_map:
                return all_msgs
        
        raise RuntimeError("Timeout starting game")
    
    def quit_game(self) -> None:
        """Abandon current game (Ctrl-Q + 'yes' to confirm). Deletes save."""
        # Escape any open menus/prompts first
        for _ in range(3):
            self.send_key("key_esc")
            time.sleep(0.1)
        self.recv_messages(timeout=0.5)  # drain
        
        # Send Ctrl+Q to trigger "Really quit?" prompt
        self.send_key("key_ctrl_q")
        time.sleep(0.5)
        self.recv_messages(timeout=0.5)  # drain prompt
        
        # Type "yes" as individual characters then Enter
        for ch in "yes":
            self.send_key(ch)
            time.sleep(0.05)
        self.send_key("key_enter")
        time.sleep(0.5)
        
        # Wait for lobby
        for _ in range(10):
            msgs = self.recv_messages(timeout=0.5)
            for msg in msgs:
                if msg.get("msg") == "go_lobby":
                    return
            if not msgs:
                break
    
    def save_game(self) -> None:
        """Save and exit to lobby (Ctrl-S)."""
        self.send_key("key_ctrl_s")
        self.wait_for("go_lobby", timeout=10.0)
    
    def disconnect(self) -> None:
        """Close connection."""
        self._ping_stop.set()
        if self._ws:
            try:
                self._ws.close()
            except Exception:
                pass
            self._ws = None
