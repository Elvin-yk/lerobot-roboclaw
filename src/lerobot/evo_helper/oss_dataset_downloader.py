#!/usr/bin/env python3
"""Download OSS datasets with lightweight progress tracking."""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


DEFAULT_ENDPOINT = "https://oss-cn-hangzhou.aliyuncs.com"
DEFAULT_OSS_URI_TEMPLATE = "oss://evo-data/all_usr_dataset/%s/%s/"
DEFAULT_TARGET_DIR_TEMPLATE = "/root/autodl-tmp/%s/datasets"
DEFAULT_PROGRESS_FILE = "/root/evohelper/download.json"


class OSSDatasetDownloader:
    def __init__(
        self,
        endpoint: str,
        access_key_id: str | None = None,
        access_key_secret: str | None = None,
        progress_file: str = DEFAULT_PROGRESS_FILE,
    ) -> None:
        try:
            import oss2
        except ModuleNotFoundError as exc:
            raise RuntimeError("oss2 is required to download OSS datasets.") from exc

        self.oss2 = oss2
        self.endpoint = endpoint
        self.access_key_id = access_key_id or os.environ.get("ALIBABA_CLOUD_ACCESS_KEY_ID", "")
        self.access_key_secret = access_key_secret or os.environ.get("ALIBABA_CLOUD_ACCESS_KEY_SECRET", "")
        if not self.access_key_id or not self.access_key_secret:
            raise RuntimeError("OSS access key id/secret is empty.")

        self.total_files = 0
        self.downloaded_files = 0
        self.total_bytes = 0
        self.downloaded_bytes = 0
        self._started_at = 0.0
        self.progress_file = Path(progress_file).expanduser()

    def download_data(self, oss_uri: str, target_dir: str) -> dict[str, Any]:
        parsed = urlparse(oss_uri)
        if parsed.scheme != "oss" or not parsed.netloc:
            raise ValueError(f"invalid OSS uri: {oss_uri}")

        bucket = self.oss2.Bucket(
            self.oss2.Auth(self.access_key_id, self.access_key_secret),
            self.endpoint,
            parsed.netloc,
        )
        prefix = parsed.path.lstrip("/")
        if prefix and not prefix.endswith("/"):
            prefix = f"{prefix}/"
        target_root = Path(target_dir).expanduser()
        target_root.mkdir(parents=True, exist_ok=True)
        objects = [obj for obj in self.oss2.ObjectIterator(bucket, prefix=prefix) if not obj.key.endswith("/")]

        self.total_files = len(objects)
        self.downloaded_files = 0
        self.total_bytes = sum(int(obj.size or 0) for obj in objects)
        self.downloaded_bytes = 0
        self._started_at = time.monotonic()
        self._write_progress("downloading")

        downloaded_bytes_base = 0
        for obj in objects:
            relative_key = obj.key[len(prefix) :].lstrip("/") if prefix else obj.key
            local_path = target_root / relative_key
            local_path.parent.mkdir(parents=True, exist_ok=True)

            def progress_callback(consumed_bytes: int, total_bytes: int) -> None:
                self.downloaded_bytes = downloaded_bytes_base + consumed_bytes
                self._write_progress("downloading")

            bucket.get_object_to_file(obj.key, str(local_path), progress_callback=progress_callback)
            downloaded_bytes_base += int(obj.size or 0)
            self.downloaded_files += 1
            self.downloaded_bytes = downloaded_bytes_base
            self._write_progress("downloading")

        self._write_progress("success")
        return self.get_download_progress()

    def get_download_progress(self) -> dict[str, Any]:
        elapsed_seconds = time.monotonic() - self._started_at if self._started_at else 0.0
        total_bytes = self.total_bytes
        downloaded_bytes = self.downloaded_bytes
        speed_bytes_per_second = downloaded_bytes / elapsed_seconds if elapsed_seconds > 0 else 0.0
        percent = downloaded_bytes * 100 / total_bytes if total_bytes else 0.0
        return {
            "total_files": self.total_files,
            "downloaded_files": self.downloaded_files,
            "total_bytes": total_bytes,
            "downloaded_bytes": downloaded_bytes,
            "speed_bytes_per_second": round(speed_bytes_per_second, 2),
            "percent": round(percent, 2),
        }

    def _write_progress(self, status: str) -> None:
        progress = self.get_download_progress()
        progress["status"] = status
        progress["updated_at"] = time.time()
        self.progress_file.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.progress_file.with_suffix(f"{self.progress_file.suffix}.tmp")
        tmp_path.write_text(json.dumps(progress, ensure_ascii=False), encoding="utf-8")
        tmp_path.replace(self.progress_file)


def _dataset_oss_uri(username: str, dataset: str) -> str:
    template = os.environ.get("EVO_DATASET_OSS_URI_TEMPLATE", DEFAULT_OSS_URI_TEMPLATE)
    return template % (username, dataset)


def _dataset_target_dir(username: str) -> str:
    template = os.environ.get("EVO_DATASET_TARGET_DIR_TEMPLATE", DEFAULT_TARGET_DIR_TEMPLATE)
    return template % username


def _read_progress(progress_file: str) -> dict[str, Any]:
    path = Path(progress_file).expanduser()
    if not path.exists():
        return {"status": "missing", "error": f"progress file not found: {path}"}
    return json.loads(path.read_text(encoding="utf-8"))


def _write_failed_progress(progress_file: str, progress: dict[str, Any], error: Exception) -> None:
    progress["status"] = "failed"
    progress["error"] = str(error)
    path = Path(progress_file).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(progress, ensure_ascii=False), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="evohelper")
    subparsers = parser.add_subparsers(dest="command", required=True)

    download_parser = subparsers.add_parser("download")
    download_parser.add_argument("download_action", nargs="?", choices=["check"])
    download_parser.add_argument("--usrname", required=True)
    download_parser.add_argument("--dataset", required=True)

    args = parser.parse_args(argv)

    if args.command == "download" and args.download_action == "check":
        print(json.dumps(_read_progress(DEFAULT_PROGRESS_FILE), ensure_ascii=False))
        return 0

    if args.command == "download":
        downloader = OSSDatasetDownloader(DEFAULT_ENDPOINT)
        try:
            progress = downloader.download_data(
                _dataset_oss_uri(args.usrname, args.dataset),
                _dataset_target_dir(args.usrname),
            )
        except Exception as exc:
            _write_failed_progress(DEFAULT_PROGRESS_FILE, downloader.get_download_progress(), exc)
            raise
        print(json.dumps(progress, ensure_ascii=False))
        return 0

    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
