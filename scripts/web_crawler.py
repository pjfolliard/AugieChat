#!/usr/bin/env python3
"""Async web crawler for scraping sites into JSON shards.

This script uses Playwright to load pages (including JavaScript-driven
content), extracts visible text, splits the text into manageable chunks,
and writes the results to JSON files while respecting a token limit per
file. It can crawl a full site or scrape a single page.
"""

import asyncio
import datetime
import json
import os
import re
from urllib.parse import urljoin, urlparse

import tiktoken
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError


# ----------------------------------------------------------------------
# Default configuration values. These can be overridden via CLI options.
# ----------------------------------------------------------------------
DEFAULT_MODE = "crawl"  # 'crawl' for full site or 'single' for one URL
DEFAULT_TARGET_URL = "https://augie.edu"
DEFAULT_MAX_PAGES = 50
DEFAULT_MAX_CHARS_PER_CHUNK = 2000
DEFAULT_MAX_TOKENS_PER_SHARD = 1_200_000
DEFAULT_OUTPUT_DIR = "output_shards"
DEFAULT_ENCODING = "cl100k_base"
DEFAULT_BROWSER_TIMEOUT = 20_000  # milliseconds


# ----------------------------------------------------------------------
# Utility functions
# ----------------------------------------------------------------------

def split_into_chunks(text: str, max_chars: int) -> list[str]:
    """Split text into sentence-based chunks not exceeding ``max_chars``."""
    sentences = re.split(r"(?<=[.!?])\s+", text)
    chunks: list[str] = []
    current = ""

    for sentence in sentences:
        if len(current) + len(sentence) + 1 <= max_chars:
            current = f"{current} {sentence}".strip() if current else sentence
        else:
            if current:
                chunks.append(current)
            current = sentence

    if current:
        chunks.append(current)

    return chunks


async def scrape_page_content(page, url: str, max_chars: int) -> list[dict]:
    """Extract cleaned text from ``page`` and return chunk dictionaries."""
    try:
        html = await page.content()
        soup = BeautifulSoup(html, "html.parser")

        # Remove common non-content elements
        for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
            tag.decompose()

        body_text = soup.body.get_text(separator="\n") if soup.body else ""

        # Normalize whitespace
        lines = (line.strip() for line in body_text.splitlines())
        phrases = (p.strip() for line in lines for p in line.split("  "))
        cleaned = "\n".join(chunk for chunk in phrases if chunk)
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
        cleaned = re.sub(r"\s{2,}", " ", cleaned)

        if not cleaned.strip():
            print(f"No content found for {url}")
            return []

        chunks = split_into_chunks(cleaned, max_chars)
        return [{"url": url, "chunk": idx, "content": ch} for idx, ch in enumerate(chunks, 1)]

    except Exception as exc:  # pragma: no cover - best effort logging
        print(f"Error scraping {url}: {exc}")
        return []


def normalize_netloc(netloc: str) -> str:
    """Normalize network locations by removing a leading 'www.'"""
    return netloc.replace("www.", "")


async def crawl_website(p, start_url: str, max_pages: int, max_chars: int, timeout: int) -> list[dict]:
    """Crawl a site starting from ``start_url`` and return chunked data."""
    parsed = urlparse(start_url)
    base_netloc = normalize_netloc(parsed.netloc)

    to_visit = [start_url]
    seen: set[str] = {start_url}
    results: list[dict] = []

    browser = await p.chromium.launch(headless=True)
    context = await browser.new_context(
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/108.0 Safari/537.36"
        )
    )

    while to_visit and len(seen) <= max_pages:
        current = to_visit.pop(0)
        print(f"Crawling: {current}")
        page = await context.new_page()
        try:
            await page.goto(current, timeout=timeout, wait_until="domcontentloaded")
            page_data = await scrape_page_content(page, current, max_chars)
            results.extend(page_data)

            # Collect links
            links = await page.locator("a[href]").evaluate_all("els => els.map(el => el.href)")
            for link in links:
                link = link.split("#")[0]
                abs_url = urljoin(current, link)
                parsed_link = urlparse(abs_url)
                if normalize_netloc(parsed_link.netloc) == base_netloc and abs_url not in seen:
                    seen.add(abs_url)
                    if len(seen) <= max_pages:
                        to_visit.append(abs_url)
        except PlaywrightTimeoutError:
            print(f"Timeout loading {current}")
        except Exception as exc:
            print(f"Failed to process {current}: {exc}")
        finally:
            await page.close()

    await context.close()
    await browser.close()
    return results


async def scrape_single_url(p, url: str, max_chars: int, timeout: int) -> list[dict]:
    """Scrape a single page using Playwright."""
    browser = await p.chromium.launch(headless=True)
    page = await browser.new_page()
    data: list[dict] = []
    try:
        await page.goto(url, timeout=timeout, wait_until="domcontentloaded")
        data = await scrape_page_content(page, url, max_chars)
    except PlaywrightTimeoutError:
        print(f"Timeout loading {url}")
    except Exception as exc:
        print(f"Failed to scrape {url}: {exc}")
    finally:
        await browser.close()
    return data


def output_prefix(url: str, mode_prefix: str) -> str:
    """Generate a filename prefix using the domain and date."""
    domain = urlparse(url).netloc
    clean = re.sub(r"^(www\.)|(\.(com|edu|org|co\.uk))", "", domain)
    clean = clean.replace(".", "_").replace("-", "_")
    date = datetime.datetime.now().strftime("%Y-%m-%d")
    return f"{mode_prefix}_{clean}_{date}"


def save_to_json_shards(data: list[dict], prefix: str, out_dir: str, max_tokens: int, encoding: str) -> None:
    """Write ``data`` to JSON files under ``out_dir`` respecting ``max_tokens``."""
    if not data:
        print("No data to save.")
        return

    os.makedirs(out_dir, exist_ok=True)
    enc = tiktoken.get_encoding(encoding)

    shard: list[dict] = []
    tokens = 0
    idx = 1

    for record in data:
        content = record.get("content", "").strip()
        if not content:
            continue
        tcount = len(enc.encode(content))
        if shard and tokens + tcount > max_tokens:
            path = os.path.join(out_dir, f"{prefix}_{str(idx).zfill(3)}.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(shard, f, ensure_ascii=False, indent=2)
            print(f"Saved shard {path} ({tokens} tokens, {len(shard)} records)")
            shard, tokens = [], 0
            idx += 1
        shard.append(record)
        tokens += tcount

    if shard:
        path = os.path.join(out_dir, f"{prefix}_{str(idx).zfill(3)}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(shard, f, ensure_ascii=False, indent=2)
        print(f"Saved shard {path} ({tokens} tokens, {len(shard)} records)")


# ----------------------------------------------------------------------
# Command line interface
# ----------------------------------------------------------------------

def parse_args():
    import argparse

    parser = argparse.ArgumentParser(description="Async web crawler using Playwright")
    parser.add_argument("url", nargs="?", default=DEFAULT_TARGET_URL, help="Target URL")
    parser.add_argument("--mode", choices=["crawl", "single"], default=DEFAULT_MODE, help="crawl entire site or scrape single page")
    parser.add_argument("--max-pages", type=int, default=DEFAULT_MAX_PAGES, help="Maximum pages to crawl")
    parser.add_argument("--max-chars", type=int, default=DEFAULT_MAX_CHARS_PER_CHUNK, help="Maximum characters per chunk")
    parser.add_argument("--max-tokens", type=int, default=DEFAULT_MAX_TOKENS_PER_SHARD, help="Maximum tokens per output shard")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR, help="Directory to save JSON shards")
    parser.add_argument("--encoding", default=DEFAULT_ENCODING, help="tiktoken encoding to use")
    parser.add_argument("--timeout", type=int, default=DEFAULT_BROWSER_TIMEOUT, help="Navigation timeout in ms")
    return parser.parse_args()


async def run(opts) -> None:
    async with async_playwright() as p:
        if opts.mode == "single":
            mode_prefix = "single_page"
            data = await scrape_single_url(p, opts.url, opts.max_chars, opts.timeout)
        else:
            mode_prefix = "crawled_site"
            data = await crawl_website(p, opts.url, opts.max_pages, opts.max_chars, opts.timeout)
        prefix = output_prefix(opts.url, mode_prefix)
        save_to_json_shards(data, prefix, opts.output_dir, opts.max_tokens, opts.encoding)


def main() -> None:
    opts = parse_args()
    asyncio.run(run(opts))


if __name__ == "__main__":  # pragma: no cover - script entry point
    main()
