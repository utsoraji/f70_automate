def get_path(filename: str) -> str:
    """リソースファイルのパスを取得"""
    from importlib import resources
    return str(resources.as_file(resources.files("f70_automate.resources").joinpath(filename)).__enter__())
