#!/usr/bin/env python3
"""
S3 inventory limited to 2 levels (ideal for day-partitioned data).
Shows only folder names and aggregated sizes – no individual files.
Does NOT download any data.
"""

import os
from collections import defaultdict

import boto3
from botocore.exceptions import ClientError
from dotenv import load_dotenv
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

load_dotenv()

console = Console()

BUCKET = os.getenv("S3_BUCKET", "factored-datathon-2026-s3-157725502942-us-east-2-an")
REGION = os.getenv("AWS_DEFAULT_REGION", "us-east-2")


def get_s3_client():
    return boto3.client(
        "s3",
        aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
        region_name=REGION,
    )


def human_size(num_bytes: int) -> str:
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if abs(num_bytes) < 1024:
            return f"{num_bytes:.2f} {unit}"
        num_bytes /= 1024
    return f"{num_bytes:.2f} PB"


def main():
    s3 = get_s3_client()

    console.rule("[bold blue]Factored Datathon 2026 – 2-Level Inventory")
    console.print(f"Bucket : [cyan]{BUCKET}[/]")
    console.print(f"Region : [cyan]{REGION}[/]\n")

    # level1 → level2 → {size, count}
    stats = defaultdict(lambda: defaultdict(lambda: {"size": 0, "count": 0}))
    total_size = 0
    total_objects = 0

    console.print("[bold yellow]Scanning bucket (aggregating to 2 levels)...[/]\n")

    paginator = s3.get_paginator("list_objects_v2")

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("Listing objects...", total=None)

        try:
            for page in paginator.paginate(Bucket=BUCKET):
                for obj in page.get("Contents", []):
                    key = obj["Key"]
                    size = obj["Size"]

                    parts = key.split("/")

                    level1 = parts[0] if len(parts) > 0 else "(root)"
                    level2 = parts[1] if len(parts) > 1 else "(files)"

                    stats[level1][level2]["size"] += size
                    stats[level1][level2]["count"] += 1

                    total_size += size
                    total_objects += 1

                progress.update(task, description=f"Objects: {total_objects:,}")

        except ClientError as e:
            console.print(f"[red]AWS Error: {e}[/]")
            return

    # ------------------------------------------------------------------
    # Print results
    # ------------------------------------------------------------------
    console.print()

    for level1 in sorted(stats.keys(), key=lambda x: -sum(v["size"] for v in stats[x].values())):
        level1_size = sum(v["size"] for v in stats[level1].values())
        level1_count = sum(v["count"] for v in stats[level1].values())

        console.print(
            f"[bold cyan]📁 {level1}/[/]  "
            f"[dim]{human_size(level1_size)}  •  {level1_count:,} objects[/]"
        )

        # Second level, sorted by size
        sorted_level2 = sorted(stats[level1].items(), key=lambda x: -x[1]["size"])

        for level2, info in sorted_level2:
            console.print(
                f"   ├─ [green]{level2}[/]  "
                f"{human_size(info['size']):>10}  "
                f"({info['count']:,} files)"
            )

        console.print()

    # Final summary
    console.rule("[bold green]Total")
    console.print(f"Objects : [bold]{total_objects:,}[/]")
    console.print(f"Size    : [bold]{human_size(total_size)}[/]")


if __name__ == "__main__":
    main()
