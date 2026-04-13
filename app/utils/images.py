"""画像ダウンロードユーティリティ（リトライ付き）"""

import logging
from pathlib import Path
from typing import List

import requests

from app.utils.retry import retry

logger = logging.getLogger(__name__)

_DEFAULT_OUTPUT_DIR = "temp_images"


@retry(max_retries=3, delay=2, backoff=2.0)
def download_image(url: str, output_dir: str = _DEFAULT_OUTPUT_DIR) -> str:
    """
    URL から画像をダウンロードしてローカルに保存する。
    最大 3 回リトライ（初回失敗後 2 秒、4 秒、8 秒待機）。

    Args:
        url: ダウンロード対象の画像 URL
        output_dir: 保存先ディレクトリ

    Returns:
        保存したローカルファイルパス

    Raises:
        requests.HTTPError: HTTP エラー時（リトライ上限後）
    """
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    response = requests.get(url, timeout=10)
    response.raise_for_status()

    # URL からファイル名を抽出
    filename = url.split("/")[-1].split("?")[0]
    if not filename or "." not in filename:
        filename = "image.jpg"

    filepath = Path(output_dir) / filename
    with open(filepath, "wb") as f:
        f.write(response.content)

    logger.info("Downloaded image: %s", filepath)
    return str(filepath)


def download_images(
    urls: List[str],
    output_dir: str = _DEFAULT_OUTPUT_DIR,
) -> List[str]:
    """
    複数の画像を順番にダウンロードする。
    個々の失敗はスキップして続行する。

    Args:
        urls: ダウンロード対象 URL リスト
        output_dir: 保存先ディレクトリ

    Returns:
        ダウンロードに成功したファイルパスのリスト
    """
    paths: List[str] = []
    for url in urls:
        try:
            path = download_image(url, output_dir)
            paths.append(path)
        except Exception as exc:
            logger.warning("Skipped image %s: %s", url, exc)
    return paths
