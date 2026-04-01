from __future__ import annotations

from html import escape
from typing import ClassVar
import streamlit as st

from f70_automate._core.logging.models import LogEntry, LogLevel
from f70_automate._core.logging.protocols import LogSubscriber


class StreamlitConsoleSubscriber(LogSubscriber):
    """Streamlit UI のコンソール風出力にログを表示するサブスクライバー（シングルトン）

    インスタンスはプロセス内で1つだけ生成される。
    Streamlit のセッション再接続などによる多重登録を防ぐ。
    """

    _instance: ClassVar[StreamlitConsoleSubscriber | None] = None

    max_lines: int
    detailed: bool
    _lines: list[str]

    def __new__(cls, max_lines: int = 100, detailed: bool = False) -> StreamlitConsoleSubscriber:
        if cls._instance is None:
            instance = super().__new__(cls)
            instance.max_lines = max_lines
            instance.detailed = detailed
            instance._lines = []
            cls._instance = instance
        return cls._instance

    def __init__(self, max_lines: int = 100, detailed: bool = False) -> None:
        # 初期化は __new__ で一度だけ行われるため、ここでは何もしない
        pass

    @classmethod
    def _reset_singleton(cls) -> None:
        """シングルトンインスタンスをリセット（テスト専用）"""
        cls._instance = None

    def on_log_event(self, entry: LogEntry) -> None:
        """ログエントリを内部バッファに蓄積

        Args:
            entry: ログエントリ
        """
        
        formatted = entry.format_detailed() if self.detailed else entry.format_simple()
        self._lines.append(formatted)

        def icon_for_level(level: LogLevel) -> str:
            return {
                LogLevel.INFO: "ℹ️",
                LogLevel.WARNING: "⚠️",
                LogLevel.ERROR: "❌",
            }.get(level, "ℹ️")
        
        st.toast(formatted, icon=icon_for_level(entry.level))

        # バッファサイズを制限（古いログから削除)
        if len(self._lines) > self.max_lines:
            self._lines = self._lines[-self.max_lines :]

    def get_buffer(self) -> list[str]:
        """バッファ内のすべてのログを取得

        Returns:
            ログ行のリスト
        """
        return list(self._lines)

    def get_messages(self) -> list[str]:
        """バッファ内のメッセージのみを取得

        Returns:
            ログメッセージのリスト
        """
        return list(self._lines)

    def get_buffer_str(self) -> str:
        """バッファ内のログを改行区切りの文字列として取得

        Returns:
            ログを改行で結合した文字列
        """
        return "\n".join(self._lines)

    def render_to_streamlit(self, container = None, clear_button_key: str = "log_console_clear") -> None:
        """Streamlit コンテナにコンソール風で出力

        Args:
            container: 出力先の streamlit コンテナ。
                      Noneの場合は st モジュール直下に表示
        """
        if container is None:
            container = st

        if container.button("Clear", key=clear_button_key):
            self.clear_buffer()

        log_text = escape(self.get_buffer_str())
        container.markdown(
            f'<div style="'
            'background-color:#000;color:#fff;'
            'font-family:monospace,monospace;'
            'font-size:0.85rem;'
            'padding:0.6rem 0.8rem;'
            'border-radius:4px;'
            'overflow-y:auto;'
            'max-height:400px;'
            'white-space:pre-wrap;'
            'word-break:break-all;'
            f'">{log_text}</div>',
            unsafe_allow_html=True,
        )


    def clear_buffer(self) -> None:
        """バッファをクリア"""
        self._lines.clear()
