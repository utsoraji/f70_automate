"""Resource management utilities."""
from importlib import resources

def get_path(filename: str) -> str:
    """リソースファイルのパスを取得"""
    return str(resources.as_file(resources.files("f70_automate.apps.internal.resources").joinpath(filename)).__enter__())
