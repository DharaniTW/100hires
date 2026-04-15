#!/usr/bin/env python3
"""Fetch YouTube transcripts from Supadata and save them as text files."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import unicodedata
from pathlib import Path
from typing import Any
from urllib import error, parse, request


BASE_URL = "https://api.supadata.ai/v1"
DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parent / "youtube-transcripts"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Fetch transcripts for one or more YouTube URLs using the Supadata API "
            "and save them as text files."
        )
    )
    parser.add_argument(
        "urls",
        nargs="*",
        help="One or more YouTube video URLs.",
    )
    parser.add_argument(
        "--input-file",
        type=Path,
        help="Optional text file with one YouTube URL per line.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"Output directory for transcript files. Default: {DEFAULT_OUTPUT_DIR}",
    )
    parser.add_argument(
        "--lang",
        help="Preferred transcript language, for example 'en'.",
    )
    parser.add_argument(
        "--mode",
        choices=("native", "auto", "generate"),
        default="auto",
        help="Supadata transcript mode. Default: auto",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=1.0,
        help="Seconds between async job status checks. Default: 1.0",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=300,
        help="Maximum seconds to wait for an async transcript job. Default: 300",
    )
    return parser.parse_args()


def load_urls(args: argparse.Namespace) -> list[str]:
    urls = list(args.urls)
    if args.input_file:
        lines = args.input_file.read_text(encoding="utf-8").splitlines()
        urls.extend(line.strip() for line in lines if line.strip() and not line.strip().startswith("#"))
    unique_urls: list[str] = []
    seen: set[str] = set()
    for url in urls:
        if url not in seen:
            seen.add(url)
            unique_urls.append(url)
    return unique_urls


def api_get(path: str, api_key: str, params: dict[str, Any] | None = None) -> tuple[int, dict[str, Any]]:
    query = ""
    if params:
        filtered = {key: value for key, value in params.items() if value is not None}
        query = "?" + parse.urlencode(filtered)

    req = request.Request(
        f"{BASE_URL}{path}{query}",
        headers={
            "x-api-key": api_key,
            "Accept": "application/json",
        },
        method="GET",
    )

    try:
        with request.urlopen(req) as response:
            body = response.read().decode("utf-8")
            data = json.loads(body) if body else {}
            return response.status, data
    except error.HTTPError as exc:
        raw_body = exc.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(raw_body)
        except json.JSONDecodeError:
            payload = {"message": raw_body or exc.reason}
        message = payload.get("details") or payload.get("message") or exc.reason
        raise RuntimeError(f"Supadata API error ({exc.code}) for {path}: {message}") from exc
    except error.URLError as exc:
        raise RuntimeError(f"Network error calling Supadata API: {exc.reason}") from exc


def fetch_metadata(video_url: str, api_key: str) -> dict[str, Any]:
    _, data = api_get("/metadata", api_key, params={"url": video_url})
    return data


def fetch_transcript(
    video_url: str,
    api_key: str,
    *,
    lang: str | None,
    mode: str,
    poll_interval: float,
    timeout: int,
) -> dict[str, Any]:
    status, data = api_get(
        "/transcript",
        api_key,
        params={
            "url": video_url,
            "text": "true",
            "mode": mode,
            "lang": lang,
        },
    )

    if status == 200 and "jobId" not in data:
        return data

    job_id = data.get("jobId")
    if not job_id:
        raise RuntimeError(f"Unexpected transcript response for {video_url}: {data}")

    deadline = time.time() + timeout
    while time.time() < deadline:
        _, job_data = api_get(f"/transcript/{job_id}", api_key)
        job_status = job_data.get("status")
        if job_status == "completed":
            return job_data
        if job_status == "failed":
            error_info = job_data.get("error") or {}
            message = error_info.get("details") or error_info.get("message") or "Unknown error"
            raise RuntimeError(f"Transcript job failed for {video_url}: {message}")
        time.sleep(poll_interval)

    raise TimeoutError(f"Timed out waiting for transcript job {job_id} for {video_url}")


def slugify(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    ascii_text = ascii_text.lower()
    ascii_text = re.sub(r"[^a-z0-9]+", "-", ascii_text)
    ascii_text = re.sub(r"-{2,}", "-", ascii_text).strip("-")
    return ascii_text or "untitled"


def choose_filename(metadata: dict[str, Any], output_dir: Path) -> Path:
    author = (
        metadata.get("author", {}).get("displayName")
        or metadata.get("channel", {}).get("name")
        or "unknown-author"
    )
    title = metadata.get("title") or "untitled-video"
    base_name = f"{slugify(author)}-{slugify(title)}"
    candidate = output_dir / f"{base_name}.txt"
    suffix = 2
    while candidate.exists():
        candidate = output_dir / f"{base_name}-{suffix}.txt"
        suffix += 1
    return candidate


def save_transcript(file_path: Path, transcript: dict[str, Any], source_url: str) -> None:
    content = transcript.get("content")
    if not isinstance(content, str) or not content.strip():
        raise RuntimeError(f"No plain-text transcript content returned for {source_url}")

    file_path.write_text(content.strip() + "\n", encoding="utf-8")


def main() -> int:
    args = parse_args()
    api_key = os.getenv("SUPADATA_API_KEY")
    if not api_key:
        print("Missing SUPADATA_API_KEY environment variable.", file=sys.stderr)
        return 1

    urls = load_urls(args)
    if not urls:
        print("No YouTube URLs provided. Pass URLs as arguments or via --input-file.", file=sys.stderr)
        return 1

    args.output_dir.mkdir(parents=True, exist_ok=True)

    failures = 0
    for video_url in urls:
        try:
            metadata = fetch_metadata(video_url, api_key)
            transcript = fetch_transcript(
                video_url,
                api_key,
                lang=args.lang,
                mode=args.mode,
                poll_interval=args.poll_interval,
                timeout=args.timeout,
            )
            file_path = choose_filename(metadata, args.output_dir)
            save_transcript(file_path, transcript, video_url)
            print(f"Saved {video_url} -> {file_path}")
        except Exception as exc:  # noqa: BLE001
            failures += 1
            print(f"Failed {video_url}: {exc}", file=sys.stderr)

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
