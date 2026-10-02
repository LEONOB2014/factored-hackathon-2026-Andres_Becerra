#!/usr/bin/env python3
"""
Download the entire S3 bucket into ./data/raw (preserving key structure).

- Parallel downloads (thread pool)
- Resumable: files already present with the same size are skipped
- Optional --prefix to download only a subset, --dry-run to just list

Usage:
    uv run scripts/download_s3.py
    uv run scripts/download_s3.py --prefix some_folder/ --workers 32
    uv run scripts/download_s3.py --dry-run
"""

import argparse
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
from dotenv import load_dotenv
from rich.console import Console
from rich.progress import (
    BarColumn,
    DownloadColumn,
    Progress,
    TextColumn,
    TimeRemainingColumn,
    TransferSpeedColumn,
)

load_dotenv()

console = Console()

BUCKET = os.getenv("S3_BUCKET", "factored-datathon-2026-s3-157725502942-us-east-2-an")
REGION = os.getenv("AWS_DEFAULT_REGION", "us-east-2")
ROOT = Path(__file__).resolve().parent.parent
DATA = Path(os.getenv("LATAM_EDA_DATA", ROOT / "data")).expanduser().resolve()
DEFAULT_DEST = DATA / "raw"


def get_s3_client(workers: int):
    return boto3.client(
        "s3",
        aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
        region_name=REGION,
        config=Config(max_pool_connections=max(workers, 10), retries={"max_attempts": 5}),
    )


def human_size(num_bytes: float) -> str:
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if abs(num_bytes) < 1024:
            return f"{num_bytes:.2f} {unit}"
        num_bytes /= 1024
    return f"{num_bytes:.2f} PB"


def list_objects(s3, prefix: str):
    """Return [(key, size)] for all real files (skips folder placeholder keys)."""
    objects = []
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=BUCKET, Prefix=prefix):
        for obj in page.get("Contents", []):
            if obj["Key"].endswith("/"):
                continue
            objects.append((obj["Key"], obj["Size"]))
    return objects


def download_one(s3, key: str, size: int, dest: Path, progress, task):
    """Download a single object. Returns 'downloaded' or 'skipped'."""
    target = dest / key
    if target.exists() and target.stat().st_size == size:
        progress.update(task, advance=size)
        return "skipped"

    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".part")
    s3.download_file(BUCKET, key, str(tmp), Callback=lambda n: progress.update(task, advance=n))
    tmp.replace(target)  # atomic: no half-written files under the final name
    return "downloaded"


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    parser.add_argument("--dest", type=Path, default=DEFAULT_DEST, help=f"default: {DEFAULT_DEST}")
    parser.add_argument("--prefix", default="", help="only download keys under this prefix")
    parser.add_argument("--workers", type=int, default=16)
    parser.add_argument("--dry-run", action="store_true", help="list what would be downloaded")
    args = parser.parse_args()

    s3 = get_s3_client(args.workers)

    console.rule("[bold blue]Factored Datathon 2026 – S3 Download")
    console.print(f"Bucket : [cyan]{BUCKET}[/]")
    console.print(f"Prefix : [cyan]{args.prefix or '(all)'}[/]")
    console.print(f"Dest   : [cyan]{args.dest}[/]\n")

    try:
        with console.status("Listing objects..."):
            objects = list_objects(s3, args.prefix)
    except ClientError as e:
        console.print(f"[red]AWS Error: {e}[/]")
        return

    total_size = sum(size for _, size in objects)
    console.print(f"Found [bold]{len(objects):,}[/] files, [bold]{human_size(total_size)}[/]\n")

    if args.dry_run or not objects:
        return

    # Fail early if the disk can't hold the data
    args.dest.mkdir(parents=True, exist_ok=True)
    free = os.statvfs(args.dest).f_bavail * os.statvfs(args.dest).f_frsize
    if total_size > free:
        console.print(
            f"[red]Not enough disk space: need {human_size(total_size)}, have {human_size(free)}[/]"
        )
        return

    counts = {"downloaded": 0, "skipped": 0}
    failures = []

    with Progress(
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        DownloadColumn(),
        TransferSpeedColumn(),
        TimeRemainingColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Downloading", total=total_size)

        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures = {
                pool.submit(download_one, s3, key, size, args.dest, progress, task): key
                for key, size in objects
            }
            for future in as_completed(futures):
                key = futures[future]
                try:
                    counts[future.result()] += 1
                except Exception as e:  # keep going; report at the end
                    failures.append((key, e))

    console.rule("[bold green]Done")
    console.print(f"Downloaded : [bold]{counts['downloaded']:,}[/]")
    console.print(f"Skipped    : [bold]{counts['skipped']:,}[/] (already present)")
    if failures:
        console.print(f"[red]Failed     : {len(failures):,}[/] (re-run to retry)")
        for key, e in failures[:20]:
            console.print(f"  [red]✗[/] {key}: {e}")


if __name__ == "__main__":
    main()
