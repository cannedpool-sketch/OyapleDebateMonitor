#!/usr/bin/env python3
# Copyright (c) 2026 CannedPool-sketch/TrueThugger
""" Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE."""

#YOUR SESSION TOKEN AND XSRF COOKIE IS NOT STORED OR SENT TO ANY EXTERNAL SOURCES, IT IS USED FOR AUTHENTICATION PURPOSES.



#you like that c++ syntax huh

import sys
import time
import threading
import json
import random
from collections import deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional, Set, Dict, List

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QObject, QUrl
from PyQt6.QtGui import QFont, QDesktopServices
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QScrollArea, QLabel, QFrame, QSplitter, QTextEdit,
    QSizePolicy, QTabWidget, QGroupBox
)

BASE = "https://oyaple.com"


#PUT YOUR STUFF HERE. ON FIREFOX, GO TO OYAPLE.COM, F12/DEVTOOLS, STORAGE, COOKIES, AND PASTE THE COOKIES. ON CHROME, GO TO APPLICATION INSTEAD OF STORAGE.
SESSION_ID = ""
XSRF_TOKEN = ""

THREAD_COUNT = 32
CURRENT_SEASON = 2

DEBATE_MIN_SECONDS = 180
DEBATE_MAX_SECONDS = 220
STALE_GRACE_SECONDS = 60
USER_DISCOVERY_INTERVAL = 300
ACTIVE_DEBATE_PRIORITY_INTERVAL = 2
BACKGROUND_SCAN_INTERVAL = 8
RECENT_HISTORY_WINDOW = 600

USER_CACHE_FILE = "oyaple_users_cache.json"
USER_CACHE_MAX_AGE = 86400
MAX_USERS_TO_SCAN = 5000

def make_session(session_id: str, xsrf_token: str) -> requests.Session:
    s = requests.Session()
    adapter = HTTPAdapter(
        pool_connections=THREAD_COUNT * 2,
        pool_maxsize=THREAD_COUNT * 2,
        max_retries=Retry(total=2, backoff_factor=0.3),
        pool_block=False
    )
    s.mount("https://", adapter)
    s.mount("http://", adapter)
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36",
        "Cookie": f"oyaple-session={session_id}; XSRF-TOKEN={xsrf_token}",
        "X-XSRF-TOKEN": xsrf_token,
        "Content-Type": "application/json",
        "Accept": "*/*",
        "Referer": "https://oyaple.com/lobby",
    })
    return s

def search_users(session: requests.Session, query: str) -> List[dict]:
    url = f"{BASE}/api/friends/search"
    try:
        resp = session.get(url, params={"q": query}, timeout=10)
        if resp.status_code == 429:
            time.sleep(0.5)
            return []
        resp.raise_for_status()
        data = resp.json()
        return data.get("users", [])
    except requests.RequestException:
        return []

def get_history(profile_id: str, session: requests.Session, season: int) -> dict:
    url = f"{BASE}/api/users/{profile_id}/history"
    try:
        resp = session.get(url, params={"season": season}, timeout=15)
        if resp.status_code == 429:
            time.sleep(0.3)
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException:
        return {}

def get_result(match_id: str, session: requests.Session) -> Optional[dict]:
    url = f"{BASE}/api/debates/{match_id}/result"
    try:
        resp = session.get(url, timeout=10)
        if resp.status_code == 404:
            return None
        if resp.status_code == 429:
            time.sleep(0.3)
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException:
        return None

def parse_date(debate: dict) -> Optional[datetime]:
    for key in ("created_at", "date", "started_at", "timestamp"):
        raw = debate.get(key)
        if not raw:
            continue
        try:
            if isinstance(raw, (int, float)):
                return datetime.fromtimestamp(raw, tz=timezone.utc)
            return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        except Exception:
            continue
    return None

class UserDiscovery:
    def __init__(self, session: requests.Session):
        self.session = session
        self.known_users: Dict[str, dict] = {}
        self.user_cache_file = USER_CACHE_FILE
        self._load_cache()

    def _load_cache(self):
        try:
            with open(self.user_cache_file, 'r') as f:
                cache = json.load(f)
                if time.time() - cache.get('timestamp', 0) < USER_CACHE_MAX_AGE:
                    self.known_users = cache.get('users', {})
                    print(f"Loaded {len(self.known_users)} users from cache")
        except (FileNotFoundError, json.JSONDecodeError):
            pass

    def _save_cache(self):
        try:
            cache = {
                'timestamp': time.time(),
                'users': self.known_users
            }
            with open(self.user_cache_file, 'w') as f:
                json.dump(cache, f)
        except Exception:
            pass

    def find_users(self, max_workers: int = 16) -> Set[str]:
        queries = self._search_queries()
        user_ids = set()

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(search_users, self.session, q): q for q in queries}

            for future in as_completed(futures):
                try:
                    users = future.result()
                    for user in users:
                        user_id = user.get('id')
                        if user_id:
                            user_ids.add(user_id)
                            self.known_users[user_id] = user
                except Exception:
                    continue

        self._save_cache()
        return user_ids

    def _search_queries(self) -> List[str]:
        queries = []
        chars = 'abcdefghijklmnopqrstuvwxyz0123456789_-'

        for c in chars:
            queries.append(c)

        for c1 in chars:
            for c2 in chars:
                queries.append(f"{c1}{c2}")

        common_names = ['alex', 'sam', 'max', 'leo', 'ben', 'dan', 'tom', 'joe', 'kim', 'ann',
                       'bob', 'ted', 'ian', 'eva', 'mia', 'zoe', 'amy', 'jay', 'ray', 'ken']
        for name in common_names:
            queries.append(name)
            for suffix in ['', '1', '2', '3', '12', '23', '123', 'x', 'xx', 'pro', 'gamer']:
                queries.append(f"{name}{suffix}")

        return queries

@dataclass
class TrackedDebate:
    match_id: str
    first_seen: float = field(default_factory=time.time)
    last_updated: float = field(default_factory=time.time)
    status: str = "active"
    result: Optional[dict] = None
    motion: str = ""
    user_a_name: str = ""
    user_b_name: str = ""
    user_a_id: str = ""
    user_b_id: str = ""
    priority: int = 0

    def elapsed(self) -> float:
        return time.time() - self.first_seen

class DebateScanner(QObject):
    debate_updated = pyqtSignal(str)
    debate_finished = pyqtSignal(str)
    debate_stale = pyqtSignal(str)
    status_message = pyqtSignal(str)
    error_message = pyqtSignal(str)

    def __init__(self, session: requests.Session):
        super().__init__()
        self.session = session
        self.tracked: Dict[str, TrackedDebate] = {}
        self.lock = threading.Lock()
        self._running = False
        self._threads: List[threading.Thread] = []
        self.user_discovery = UserDiscovery(session)
        self.user_ids: Set[str] = set(self.user_discovery.known_users.keys())
        self.last_user_discovery = 0.0
        self.last_background_scan = 0.0
        self._scan_complete = False

    def start(self):
        self._running = True

        self._threads.append(threading.Thread(target=self._priority, daemon=True))
        self._threads.append(threading.Thread(target=self._background, daemon=True))
        self._threads.append(threading.Thread(target=self._user_loop, daemon=True))

        for thread in self._threads:
            thread.start()

        self.status_message.emit(f"Loaded {len(self.user_ids)} users, starting fast scan...")

    def stop(self):
        self._running = False

    def get_tracked_snapshot(self) -> list:
        with self.lock:
            return list(self.tracked.values())

    def _user_loop(self):
        while self._running:
            try:
                if time.time() - self.last_user_discovery > USER_DISCOVERY_INTERVAL:
                    self.status_message.emit("Discovering new users...")
                    users = self.user_discovery.find_users(max_workers=16)
                    self.user_ids.update(users)
                    self.last_user_discovery = time.time()
                    self.status_message.emit(f"Total users: {len(self.user_ids)}")
            except Exception as exc:
                self.error_message.emit(f"discovery error: {exc}")

            time.sleep(30)

    def _priority(self):
        while self._running:
            try:
                with self.lock:
                    active = [mid for mid, td in self.tracked.items()
                                 if td.status == "active" and td.priority > 0]

                if active:
                    active.sort(key=lambda x: self.tracked[x].priority, reverse=True)

                    with ThreadPoolExecutor(max_workers=min(16, len(active))) as executor:
                        futures = {executor.submit(get_result, mid, self.session): mid
                                  for mid in active[:50]}

                        for future in as_completed(futures):
                            mid = futures[future]
                            try:
                                result = future.result()
                                self._update_debate(mid, result)
                            except Exception:
                                continue

                self._expire_stale()

            except Exception as exc:
                self.error_message.emit(f"priority scan error: {exc}")

            time.sleep(ACTIVE_DEBATE_PRIORITY_INTERVAL)

    def _background(self):
        while self._running:
            try:
                if time.time() - self.last_background_scan > BACKGROUND_SCAN_INTERVAL:
                    if not self._scan_complete:
                        self._initial_scan()
                    else:
                        self._scan_recent()
                    self.last_background_scan = time.time()
            except Exception as exc:
                self.error_message.emit(f"background scan error: {exc}")

            time.sleep(2)

    def _initial_scan(self):
        if not self.user_ids:
            self._scan_complete = True
            return

        user_ids = list(self.user_ids)[:MAX_USERS_TO_SCAN]
        self.status_message.emit(f"Fast scanning {len(user_ids)} users...")

        with ThreadPoolExecutor(max_workers=THREAD_COUNT) as executor:
            futures = {executor.submit(self._scan_history, uid): uid for uid in user_ids}

            completed = 0
            total = len(futures)

            for future in as_completed(futures):
                try:
                    match_ids = future.result()
                    if match_ids:
                        self._check_debates(match_ids)
                    completed += 1
                    if completed % 500 == 0:
                        self.status_message.emit(f"Scanned {completed}/{total} users")
                except Exception:
                    continue

        self._scan_complete = True
        self.status_message.emit("Initial scan complete!")

    def _scan_recent(self):
        if not self.user_ids:
            return

        user_ids = list(self.user_ids)[:MAX_USERS_TO_SCAN]

        with ThreadPoolExecutor(max_workers=THREAD_COUNT) as executor:
            futures = {executor.submit(self._scan_history, uid): uid for uid in user_ids}

            for future in as_completed(futures):
                try:
                    match_ids = future.result()
                    if match_ids:
                        self._check_debates(match_ids)
                except Exception:
                    continue

    def _scan_history(self, profile_id: str) -> Set[str]:
        found = set()
        try:
            history = get_history(profile_id, self.session, CURRENT_SEASON)
        except requests.RequestException:
            return found

        debates = history.get("debates", [])
        now = time.time()

        for debate in debates:
            mid = debate.get("id") or debate.get("match_id")
            if not mid:
                continue

            dt = parse_date(debate)
            if dt is not None:
                age = now - dt.timestamp()
                if age <= RECENT_HISTORY_WINDOW:
                    found.add(mid)
            else:
                if mid not in self.tracked:
                    found.add(mid)

        return found

    def _check_debates(self, match_ids: Set[str]):
        with self.lock:
            new_ids = [mid for mid in match_ids if mid not in self.tracked]

        if not new_ids:
            return

        with ThreadPoolExecutor(max_workers=THREAD_COUNT) as executor:
            futures = {executor.submit(get_result, mid, self.session): mid
                      for mid in new_ids[:100]}

            for future in as_completed(futures):
                mid = futures[future]
                try:
                    result = future.result()
                    self._update_debate(mid, result)
                except Exception:
                    continue

    def _update_debate(self, match_id: str, result: Optional[dict]):
        with self.lock:
            td = self.tracked.get(match_id)
            if td is None:
                td = TrackedDebate(match_id=match_id)
                self.tracked[match_id] = td

            if result is None:
                td.last_updated = time.time()
                if td.status != "finished":
                    td.status = "active"
                    td.priority += 1
                self.debate_updated.emit(match_id)
                return

            motion = result.get("motion", {}) or {}
            td.motion = motion.get("text", td.motion or "Unknown motion")
            user_a = result.get("user_a", {}) or {}
            user_b = result.get("user_b", {}) or {}
            td.user_a_name = user_a.get("display_name", td.user_a_name)
            td.user_b_name = user_b.get("display_name", td.user_b_name)
            td.user_a_id = user_a.get("id", td.user_a_id)
            td.user_b_id = user_b.get("id", td.user_b_id)
            td.result = result
            td.last_updated = time.time()

            is_resolved = (
                result.get("status") == "results"
                or (result.get("has_transcripts") and result.get("winner_id"))
            )

            if is_resolved:
                if td.status != "finished":
                    td.status = "finished"
                    td.priority = 0
                    self.debate_finished.emit(match_id)
                else:
                    self.debate_updated.emit(match_id)
            else:
                td.status = "active"
                td.priority += 1
                self.debate_updated.emit(match_id)

    def _expire_stale(self):
        cutoff = DEBATE_MAX_SECONDS + STALE_GRACE_SECONDS
        with self.lock:
            for mid, td in self.tracked.items():
                if td.status == "active" and td.elapsed() > cutoff:
                    td.status = "stale"
                    td.priority = 0
                    self.debate_stale.emit(mid)

INK = "#11151c"
PANEL = "#171c26"
PANEL_RAISED = "#1c222e"
RULE = "#2a3140"
PAPER = "#e8e3d5"
PAPER_DIM = "#8b93a3"
LIVE = "#c98a3d"
CLOSED = "#5b8c6e"
LAPSED = "#8a5a5a"

SERIF = "Georgia, 'Noto Serif', serif"
MONO = "'JetBrains Mono', 'DejaVu Sans Mono', 'Cascadia Mono', monospace"

STATUS_STYLES = {
    "active":   {"tag": "LIVE",    "color": LIVE},
    "finished": {"tag": "CLOSED",  "color": CLOSED},
    "stale":    {"tag": "LAPSED",  "color": LAPSED},
}

class ClickableLabel(QLabel):
    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self._url = ""
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def set_url(self, url):
        self._url = url
        if url:
            self.setToolTip(f"Open: {url}")

    def mousePressEvent(self, event):
        if self._url:
            QDesktopServices.openUrl(QUrl(self._url))
        super().mousePressEvent(event)

class DebateCard(QFrame):
    def __init__(self, match_id: str, parent=None):
        super().__init__(parent)
        self.match_id = match_id
        self.setObjectName("DebateCard")
        self._status_key = "active"

        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(14, 10, 14, 11)
        self.layout.setSpacing(3)

        top_row = QHBoxLayout()
        top_row.setSpacing(8)
        self.status_label = QLabel("LIVE")
        status_font = QFont()
        status_font.setFamily(MONO)
        status_font.setPointSize(9)
        status_font.setBold(True)
        status_font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.2)
        self.status_label.setFont(status_font)

        self.docket_label = ClickableLabel(f"#{match_id[:8]}")
        docket_font = QFont()
        docket_font.setFamily(MONO)
        docket_font.setPointSize(9)
        self.docket_label.setFont(docket_font)
        self.docket_label.setStyleSheet(f"color: {PAPER_DIM}; text-decoration: underline;")
        self.docket_label.set_url(f"{BASE}/api/debates/{match_id}/result")

        self.timer_label = QLabel("0:00")
        self.timer_label.setFont(docket_font)
        self.timer_label.setStyleSheet(f"color: {PAPER_DIM};")

        top_row.addWidget(self.status_label)
        top_row.addStretch()
        top_row.addWidget(self.docket_label)
        top_row.addWidget(self.timer_label)
        self.layout.addLayout(top_row)

        self.motion_label = QLabel("Loading motion…")
        self.motion_label.setWordWrap(True)
        motion_font = QFont()
        motion_font.setFamily(SERIF)
        motion_font.setPointSize(12)
        self.motion_label.setFont(motion_font)
        self.motion_label.setStyleSheet(f"color: {PAPER};")
        self.layout.addWidget(self.motion_label)

        self.matchup_label = ClickableLabel("")
        matchup_font = QFont()
        matchup_font.setFamily(MONO)
        matchup_font.setPointSize(9)
        self.matchup_label.setFont(matchup_font)
        self.matchup_label.setStyleSheet(f"color: {PAPER_DIM};")
        self.layout.addWidget(self.matchup_label)

        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._apply_style()

    def _apply_style(self):
        color = STATUS_STYLES[self._status_key]["color"]
        self.setStyleSheet(f"""
            QFrame#DebateCard {{
                background-color: {PANEL};
                border: none;
                border-left: 3px solid {color};
            }}
            QFrame#DebateCard:hover {{
                background-color: {PANEL_RAISED};
            }}
        """)

    def update_from(self, td: TrackedDebate):
        elapsed = int(td.elapsed())
        mins, secs = divmod(elapsed, 60)
        self.timer_label.setText(f"{mins}:{secs:02d}")

        self._status_key = td.status if td.status in STATUS_STYLES else "active"
        style = STATUS_STYLES[self._status_key]
        self.status_label.setText(style["tag"])
        self.status_label.setStyleSheet(f"color: {style['color']};")
        self._apply_style()

        self.motion_label.setText(td.motion or "Motion pending…")

        if td.user_a_name and td.user_b_name:
            user_a_text = f"<a href='{BASE}/profile/{td.user_a_id}' style='color: {LIVE};'>{td.user_a_name.upper()}</a>"
            user_b_text = f"<a href='{BASE}/profile/{td.user_b_id}' style='color: {CLOSED};'>{td.user_b_name.upper()}</a>"
            self.matchup_label.setText(f"{user_a_text}  vs.  {user_b_text}")
            self.matchup_label.setTextFormat(Qt.TextFormat.RichText)
            self.matchup_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
            self.matchup_label.setOpenExternalLinks(True)

class TranscriptPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"background-color: {PANEL_RAISED};")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(10)

        self.eyebrow = QLabel("SELECTED CASE")
        eyebrow_font = QFont()
        eyebrow_font.setFamily(MONO)
        eyebrow_font.setPointSize(9)
        eyebrow_font.setBold(True)
        eyebrow_font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.5)
        self.eyebrow.setFont(eyebrow_font)
        self.eyebrow.setStyleSheet(f"color: {LIVE};")
        layout.addWidget(self.eyebrow)

        self.header = QLabel("Select a debate from the docket to follow it live.")
        header_font = QFont()
        header_font.setFamily(SERIF)
        header_font.setPointSize(18)
        self.header.setFont(header_font)
        self.header.setWordWrap(True)
        self.header.setStyleSheet(f"color: {PAPER};")
        layout.addWidget(self.header)

        self.meta = QLabel("")
        meta_font = QFont()
        meta_font.setFamily(MONO)
        meta_font.setPointSize(9)
        self.meta.setFont(meta_font)
        self.meta.setStyleSheet(f"color: {PAPER_DIM};")
        self.meta.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        self.meta.setOpenExternalLinks(True)
        layout.addWidget(self.meta)

        # Tabs
        self.tabs = QTabWidget()
        self.tabs.setStyleSheet(f"""
            QTabWidget::pane {{ border: 1px solid {RULE}; background: {INK}; }}
            QTabBar::tab {{ background: {PANEL}; color: {PAPER_DIM}; padding: 8px 16px; border: 1px solid {RULE}; border-bottom: none; }}
            QTabBar::tab:selected {{ background: {INK}; color: {PAPER}; }}
        """)

        # Transcripts tab
        self.transcripts_widget = QWidget()
        transcripts_layout = QVBoxLayout(self.transcripts_widget)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setStyleSheet(f"QSplitter::handle {{ background-color: {RULE}; }}")
        self.side_a_box = self._side_box("SIDE A")
        self.side_b_box = self._side_box("SIDE B")
        splitter.addWidget(self.side_a_box["container"])
        splitter.addWidget(self.side_b_box["container"])
        transcripts_layout.addWidget(splitter)
        self.tabs.addTab(self.transcripts_widget, "Transcripts")

        # Analysis tab
        self.analysis_widget = QWidget()
        analysis_layout = QVBoxLayout(self.analysis_widget)
        self.analysis_scroll = QScrollArea()
        self.analysis_scroll.setWidgetResizable(True)
        self.analysis_content = QWidget()
        self.analysis_layout = QVBoxLayout(self.analysis_content)
        self.analysis_scroll.setWidget(self.analysis_content)
        analysis_layout.addWidget(self.analysis_scroll)
        self.tabs.addTab(self.analysis_widget, "Analysis")

        # Stats tab
        self.stats_widget = QWidget()
        stats_layout = QVBoxLayout(self.stats_widget)
        self.stats_text = QTextEdit()
        self.stats_text.setReadOnly(True)
        self.stats_text.setStyleSheet(f"background-color: {INK}; color: {PAPER}; border: 1px solid {RULE};")
        stats_layout.addWidget(self.stats_text)
        self.tabs.addTab(self.stats_widget, "Stats")

        layout.addWidget(self.tabs, stretch=1)

        # Summary
        summary_label = QLabel("RULING")
        label_font = QFont()
        label_font.setFamily(MONO)
        label_font.setPointSize(9)
        label_font.setBold(True)
        label_font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.2)
        summary_label.setFont(label_font)
        summary_label.setStyleSheet(f"color: {PAPER_DIM}; margin-top: 6px;")
        layout.addWidget(summary_label)

        self.summary_box = QTextEdit()
        self.summary_box.setReadOnly(True)
        self.summary_box.setMaximumHeight(130)
        body_font = QFont()
        body_font.setFamily(SERIF)
        body_font.setPointSize(10)
        self.summary_box.setFont(body_font)
        self.summary_box.setStyleSheet(f"""
            QTextEdit {{ background-color: {INK}; color: {PAPER}; border: 1px solid {RULE}; padding: 8px; }}
        """)
        layout.addWidget(self.summary_box)

    def _side_box(self, label_text: str) -> dict:
        container = QWidget()
        vbox = QVBoxLayout(container)
        vbox.setContentsMargins(0, 4, 12, 4)
        vbox.setSpacing(6)

        name_label = QLabel(label_text)
        label_font = QFont()
        label_font.setFamily(MONO)
        label_font.setPointSize(9)
        label_font.setBold(True)
        label_font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.2)
        name_label.setFont(label_font)
        name_label.setStyleSheet(f"color: {PAPER_DIM};")
        name_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        name_label.setOpenExternalLinks(True)
        vbox.addWidget(name_label)

        text = QTextEdit()
        text.setReadOnly(True)
        body_font = QFont()
        body_font.setFamily(SERIF)
        body_font.setPointSize(10)
        text.setFont(body_font)
        text.setStyleSheet(f"""
            QTextEdit {{ background-color: {INK}; color: {PAPER}; border: 1px solid {RULE}; padding: 10px; }}
        """)
        vbox.addWidget(text)
        return {"container": container, "name_label": name_label, "text": text}

    def show_debate(self, td: TrackedDebate):
        self.eyebrow.setText(STATUS_STYLES[td.status if td.status in STATUS_STYLES else "active"]["tag"])
        self.eyebrow.setStyleSheet(
            f"color: {STATUS_STYLES[td.status if td.status in STATUS_STYLES else 'active']['color']};"
        )
        self.header.setText(td.motion or "Motion pending…")
        elapsed = int(td.elapsed())
        mins, secs = divmod(elapsed, 60)

        result = td.result or {}
        user_a = result.get("user_a", {}) or {}
        user_b = result.get("user_b", {}) or {}

        meta_text = f"{mins}:{secs:02d} elapsed · "
        meta_text += f"<a href='{BASE}/api/debates/{td.match_id}/result' style='color: {PAPER_DIM};'>docket #{td.match_id}</a>"

        if user_a.get("display_name"):
            meta_text += f" · <a href='{BASE}/profile/{user_a.get('id')}' style='color: {LIVE};'>{user_a['display_name']}</a>"
        if user_b.get("display_name"):
            meta_text += f" vs <a href='{BASE}/profile/{user_b.get('id')}' style='color: {CLOSED};'>{user_b['display_name']}</a>"

        self.meta.setText(meta_text)

        self.side_a_box["name_label"].setText(
            f"<a href='{BASE}/profile/{user_a.get('id')}' style='color: {LIVE};'>{user_a.get('display_name', 'SIDE A').upper()}</a>"
        )
        self.side_b_box["name_label"].setText(
            f"<a href='{BASE}/profile/{user_b.get('id')}' style='color: {CLOSED};'>{user_b.get('display_name', 'SIDE B').upper()}</a>"
        )

        rounds = result.get("rounds", {}) or {}

        a_text = self._format_transcript(rounds.get("user_a", []))
        b_text = self._format_transcript(rounds.get("user_b", []))

        if not a_text and result.get("transcripts", {}).get("user_a"):
            a_text = result["transcripts"]["user_a"]
        if not b_text and result.get("transcripts", {}).get("user_b"):
            b_text = result["transcripts"]["user_b"]

        self.side_a_box["text"].setPlainText(a_text or "No transcript yet.")
        self.side_b_box["text"].setPlainText(b_text or "No transcript yet.")

        self._show_analysis(result)
        self._show_stats(result)

        summary = result.get("summary", "")
        reasoning = result.get("reasoning", "")
        combined = ""
        if summary:
            combined += f"{summary}\n\n"
        if reasoning:
            combined += reasoning
        self.summary_box.setPlainText(combined or "Not yet judged.")

    def _show_analysis(self, result: dict):
        while self.analysis_layout.count():
            item = self.analysis_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if result.get('axis_comparisons'):
            axis_group = QGroupBox("Axis Comparisons")
            axis_group.setStyleSheet(f"QGroupBox {{ color: {PAPER}; font-weight: bold; }}")
            axis_layout = QVBoxLayout(axis_group)
            for axis, comparison in result['axis_comparisons'].items():
                label = QLabel(f"<b>{axis.replace('_', ' ').title()}:</b> {comparison}")
                label.setWordWrap(True)
                label.setStyleSheet(f"color: {PAPER_DIM};")
                axis_layout.addWidget(label)
            self.analysis_layout.addWidget(axis_group)

        if result.get('decisive_clashes'):
            clashes_group = QGroupBox("Decisive Clashes")
            clashes_group.setStyleSheet(f"QGroupBox {{ color: {PAPER}; font-weight: bold; }}")
            clashes_layout = QVBoxLayout(clashes_group)
            for clash in result['decisive_clashes']:
                clash_text = f"<b>{clash.get('title', 'Clash')}</b><br>"
                clash_text += f"Winner: {clash.get('winner', 'Unknown')}<br>"
                clash_text += f"Ruling: {clash.get('ruling', '')}"
                label = QLabel(clash_text)
                label.setWordWrap(True)
                label.setStyleSheet(f"color: {PAPER_DIM}; padding: 5px;")
                clashes_layout.addWidget(label)
            self.analysis_layout.addWidget(clashes_group)

        self.analysis_layout.addStretch()

    def _show_stats(self, result: dict):
        stats_text = ""
        if result.get('user_a_score') is not None:
            stats_text += f"SCORES:\n  Side A: {result['user_a_score']}\n  Side B: {result['user_b_score']}\n\n"

        for side in ['user_a', 'user_b']:
            user = result.get(side, {})
            if user:
                stats_text += f"{user.get('display_name', side).upper()}:\n"
                stats_text += f"  W/L: {user.get('wins', 0)}/{user.get('losses', 0)}\n"
                stats_text += f"  Matches: {user.get('matches_played', 0)}\n"
                if user.get('elo_before') is not None and user.get('elo_after') is not None:
                    stats_text += f"  Elo: {user['elo_before']} → {user['elo_after']} ({user.get('elo_delta', 0):+d})\n"
                if user.get('is_pro'):
                    stats_text += "  ★ PRO Player\n"
                stats_text += "\n"

        self.stats_text.setPlainText(stats_text)

    def _format_transcript(self, rounds: list) -> str:
        parts = []
        for r in rounds:
            label = (r.get("label") or "").upper()
            round_num = r.get("round", "")
            text = r.get("text", "")
            if text:
                parts.append(f"ROUND {round_num} — {label}\n{text}")
        return "\n\n".join(parts)

class MainWindow(QMainWindow):
    def __init__(self, scanner: DebateScanner):
        super().__init__()
        self.scanner = scanner
        self.setWindowTitle("The Docket — live debate wire")
        self.resize(1440, 860)
        self.setStyleSheet(f"background-color: {INK};")

        self.cards: dict[str, DebateCard] = {}
        self.selected_match_id: Optional[str] = None

        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QHBoxLayout(central)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        left_panel = QWidget()
        left_panel.setFixedWidth(430)
        left_panel.setStyleSheet(f"background-color: {INK}; border-right: 1px solid {RULE};")
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(18, 18, 18, 12)
        left_layout.setSpacing(4)

        title = QLabel("THE DOCKET")
        title_font = QFont()
        title_font.setFamily(MONO)
        title_font.setBold(True)
        title_font.setPointSize(14)
        title_font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 2.0)
        title.setFont(title_font)
        title.setStyleSheet(f"color: {PAPER};")
        left_layout.addWidget(title)

        self.status_line = QLabel("connecting…")
        status_font = QFont()
        status_font.setFamily(MONO)
        status_font.setPointSize(8)
        self.status_line.setFont(status_font)
        self.status_line.setStyleSheet(f"color: {PAPER_DIM}; margin-bottom: 10px;")
        left_layout.addWidget(self.status_line)

        left_layout.addWidget(self._section("LIVE", LIVE))
        self.active_scroll, self.active_container = self._scroll_area()
        left_layout.addWidget(self.active_scroll, stretch=2)

        left_layout.addWidget(self._section("LAPSED", LAPSED))
        self.stale_scroll, self.stale_container = self._scroll_area()
        left_layout.addWidget(self.stale_scroll, stretch=1)

        left_layout.addWidget(self._section("CLOSED", CLOSED))
        self.finished_scroll, self.finished_container = self._scroll_area()
        left_layout.addWidget(self.finished_scroll, stretch=2)

        root_layout.addWidget(left_panel)

        self.transcript_panel = TranscriptPanel()
        root_layout.addWidget(self.transcript_panel, stretch=1)

        self.ui_timer = QTimer()
        self.ui_timer.timeout.connect(self.refresh_ui)
        self.ui_timer.start(1000)

        self.scanner.status_message.connect(self.on_status_message)
        self.scanner.error_message.connect(self.on_error_message)

    def _section(self, text: str, color: str) -> QLabel:
        lbl = QLabel(text)
        font = QFont()
        font.setFamily(MONO)
        font.setBold(True)
        font.setPointSize(9)
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.3)
        lbl.setFont(font)
        lbl.setStyleSheet(f"color: {color}; margin-top: 10px; margin-bottom: 2px;")
        return lbl

    def _scroll_area(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("border: none; background: transparent;")
        container = QWidget()
        container.setStyleSheet("background: transparent;")
        vbox = QVBoxLayout(container)
        vbox.setAlignment(Qt.AlignmentFlag.AlignTop)
        vbox.setSpacing(1)
        vbox.setContentsMargins(0, 0, 0, 0)
        scroll.setWidget(container)
        return scroll, container

    def on_status_message(self, msg: str):
        self.status_line.setText(msg)

    def on_error_message(self, msg: str):
        self.status_line.setText(f"⚠ {msg}")
        self.status_line.setStyleSheet(f"color: {LAPSED}; margin-bottom: 10px;")

    def refresh_ui(self):
        snapshot = self.scanner.get_tracked_snapshot()
        snapshot.sort(key=lambda td: td.first_seen, reverse=True)

        active = [td for td in snapshot if td.status == "active"]
        stale = [td for td in snapshot if td.status == "stale"]
        finished = [td for td in snapshot if td.status == "finished"]

        self._render_section(self.active_container, active)
        self._render_section(self.stale_container, stale)
        self._render_section(self.finished_container, finished[:50])

        if self.selected_match_id:
            for td in snapshot:
                if td.match_id == self.selected_match_id:
                    self.transcript_panel.show_debate(td)
                    break

    def _render_section(self, container: QWidget, debates: list):
        layout = container.layout()
        existing_ids = set()

        for td in debates:
            existing_ids.add(td.match_id)
            card = self.cards.get(td.match_id)
            if card is None:
                card = DebateCard(td.match_id)
                card.mousePressEvent = self._click_handler(td.match_id)
                self.cards[td.match_id] = card
            card.update_from(td)

            idx = layout.indexOf(card)
            if idx == -1:
                layout.addWidget(card)
            if card.parent() is not container:
                card.setParent(container)
                layout.addWidget(card)

        for i in reversed(range(layout.count())):
            item = layout.itemAt(i)
            widget = item.widget() if item else None
            if widget is not None and isinstance(widget, DebateCard):
                if widget.match_id not in existing_ids:
                    layout.removeWidget(widget)
                    widget.setParent(None)

    def _click_handler(self, match_id: str):
        def handler(event):
            self.selected_match_id = match_id
            for td in self.scanner.get_tracked_snapshot():
                if td.match_id == match_id:
                    self.transcript_panel.show_debate(td)
                    break
        return handler

def main():
    if not SESSION_ID or not XSRF_TOKEN:
        print("Fill in SESSION_ID and XSRF_TOKEN at the top of this file before running.")
        sys.exit(1)

    session = make_session(SESSION_ID, XSRF_TOKEN)
    scanner = DebateScanner(session)
    scanner.start()

    app = QApplication(sys.argv)
    window = MainWindow(scanner)
    window.show()

    exit_code = app.exec()
    scanner.stop()
    sys.exit(exit_code)

if __name__ == "__main__":
    main()
