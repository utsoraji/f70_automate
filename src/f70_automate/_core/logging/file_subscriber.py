from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from f70_automate._core.logging.models import LogEntry
from f70_automate._core.logging.protocols import LogSubscriber


@dataclass
class FileLogSubscriber(LogSubscriber):
    """ファイルにログを出力するサブスクライバー"""

    file_path: Path | str
    detailed: bool = False

    def __post_init__(self) -> None:
        """初期化: ファイルパスをPathに正規化"""
        if isinstance(self.file_path, str):
            self.file_path = Path(self.file_path)

    def on_log_event(self, entry: LogEntry) -> None:
        """ログエントリをファイルに書き込む

        Args:
            entry: ログエントリ

        Raises:
            IOError: ファイル書き込み失敗時
        """
        formatted = entry.format_detailed() if self.detailed else entry.format_simple()

        # 親ディレクトリが存在しない場合は作成
        self.file_path.parent.mkdir(parents=True, exist_ok=True)

        # ファイルに追記
        with open(self.file_path, "a", encoding="utf-8") as f:
            f.write(formatted + "\n")
