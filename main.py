
import asyncio
import csv
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

BASE_DIR = Path(__file__).resolve().parent
INPUT_FILE = BASE_DIR / "requiredsoftwares.csv"
OUTPUT_FILE = BASE_DIR / "software_versions_report.csv"

load_dotenv(BASE_DIR / ".env")

MODEL_NAME = os.getenv("OPENAI_MODEL", "gpt-4.1")
API_KEY = os.getenv("OPENAI_API_KEY")

DOWNLOADS_DIR = BASE_DIR / "downloads" / "downloads"

if not API_KEY:
    raise SystemExit("OPENAI_API_KEY is missing from .env")

client = OpenAI(api_key=API_KEY)


def approve_action(action: str) -> bool:
    """Ask the human before an action is performed."""
    print(f"\nAction requested: {action}")
    answer = input("Allow this action? (y/n): ").strip().lower()
    return answer == "y"


def parse_message(message):
    """Print a result in the terminal."""
    print(message)


async def find_latest_version(name, version, url):
    """Research a software release using OpenAI web search."""

    prompt = f"""
Find the latest stable release of this software using web search.

Software: {name}
Known version: {version or "Not provided"}
Suggested URL: {url or "Not provided"}

Rules:
1. Prefer official vendor websites or official release pages.
2. Exclude beta, alpha, and release-candidate releases.
3. Never invent a version or source URL.
4. If evidence is insufficient, mark the result NEEDS_REVIEW.
5. Return only a JSON object with these fields:
   latest_version, source_url, status, notes
6. status must be VERIFIED or NEEDS_REVIEW.
"""

    response = await asyncio.to_thread(
        client.responses.create,
        model=MODEL_NAME,
        tools=[{"type": "web_search"}],
        input=prompt,
    )

    text = response.output_text.strip()

    # Handle a JSON object inside a Markdown code fence.
    if text.startswith("```"):
        text = text.split("\n", 1)[1]
        text = text.rsplit("```", 1)[0].strip()

    result = json.loads(text)

    latest = str(result.get("latest_version") or "").strip()
    status = str(result.get("status") or "NEEDS_REVIEW").upper()

    if status != "VERIFIED" or not latest:
        status = "NEEDS_REVIEW"

    return {
        "latest_version": latest,
        "source_url": result.get("source_url", ""),
        "status": status,
        "notes": result.get("notes", ""),
    }


async def main():
    print("=== Software Latest-Version Finder Agent ===")
    print(f"Input file: {INPUT_FILE}")

    if not INPUT_FILE.exists():
        print("ERROR: requiredsoftwares.csv was not found.")
        return

    with INPUT_FILE.open(
        "r", newline="", encoding="utf-8-sig"
    ) as file:
        reader = csv.DictReader(file)

        required_columns = {"sno", "name", "version", "url"}
        actual_columns = set(reader.fieldnames or [])

        if not required_columns.issubset(actual_columns):
            print("ERROR: CSV must contain sno,name,version,url")
            return

        software_list = list(reader)

    if not software_list:
        print("No software entries found in the CSV.")
        return

    question = input(
        "\nEnter your instruction (e.g. find latest stable versions): "
    ).strip()

    if not question:
        question = "Find the latest stable versions of all listed software."

    print(f"\nInstruction: {question}")
    results = []

    for row in software_list:
        sno = (row.get("sno") or "").strip()
        name = (row.get("name") or "").strip()
        version = (row.get("version") or "").strip()
        url = (row.get("url") or "").strip()

        if not name:
            print(f"Skipping row {sno}: software name is empty.")
            continue

        print(f"\nSoftware: {name}")
        print(f"Current/reference version: {version or 'Not provided'}")

        if not approve_action(f"Search the web for {name}'s latest version"):
            print("Research rejected by user.")
            results.append({
                "sno": sno,
                "name": name,
                "input_version": version,
                "latest_version": "",
                "update_available": "UNKNOWN",
                "source_url": "",
                "checked_at": datetime.now(timezone.utc).isoformat(),
                "status": "SKIPPED",
                "notes": "User rejected web research.",
            })
            continue

        try:
            result = await find_latest_version(name, version, url)
            latest = result["latest_version"]

            parse_message(
                f"Latest version: {latest or 'Not verified'}"
            )
            parse_message(f"Status: {result['status']}")
            parse_message(f"Source: {result['source_url']}")

            # Avoid incorrect comparisons between different
            # software versioning schemes.
            comparison = (
                "COMPARE_MANUALLY" if version and latest else "UNKNOWN"
            )

            results.append({
                "sno": sno,
                "name": name,
                "input_version": version,
                "latest_version": latest,
                "update_available": comparison,
                "source_url": result["source_url"],
                "checked_at": datetime.now(timezone.utc).isoformat(),
                "status": result["status"],
                "notes": result["notes"],
            })

        except Exception as exc:
            print(f"Research failed: {type(exc).__name__}: {exc}")

            results.append({
                "sno": sno,
                "name": name,
                "input_version": version,
                "latest_version": "",
                "update_available": "UNKNOWN",
                "source_url": "",
                "checked_at": datetime.now(timezone.utc).isoformat(),
                "status": "ERROR",
                "notes": f"{type(exc).__name__}: {exc}",
            })

    if not results:
        print("\nNo results to write.")
        return

    if not approve_action(f"Write results to {OUTPUT_FILE}"):
        print("Report writing rejected. No report was written.")
        return

    columns = [
        "sno",
        "name",
        "input_version",
        "latest_version",
        "update_available",
        "source_url",
        "checked_at",
        "status",
        "notes",
    ]

    with OUTPUT_FILE.open(
        "w", newline="", encoding="utf-8"
    ) as file:
        writer = csv.DictWriter(file, fieldnames=columns)
        writer.writeheader()
        writer.writerows(results)

    print(f"\nReport saved: {OUTPUT_FILE}")
    print(f"Rows processed: {len(results)}")


if __name__ == "__main__":
    asyncio.run(main())


