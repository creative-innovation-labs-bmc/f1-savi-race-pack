from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from playwright.async_api import BrowserContext, Page, Response, async_playwright

LEAGUE_URL = os.environ.get("FANTASYGP_LEAGUE_URL", "https://fantasygp.com/league/?lid=10527")
OUTPUT_DIR = Path(os.environ.get("FANTASYGP_PROBE_OUTPUT", "build/fantasygp-probe"))
USERNAME = os.environ.get("FANTASYGP_USERNAME", "")
PASSWORD = os.environ.get("FANTASYGP_PASSWORD", "")
MAX_RESPONSE_BYTES = 1_500_000

SENSITIVE_KEYS = {
    "password",
    "pass",
    "pwd",
    "log",
    "username",
    "user",
    "email",
    "security",
    "nonce",
    "_ajax_nonce",
    "token",
}


def clean_text(value: str, limit: int = 200_000) -> str:
    value = value.replace("\x00", "")
    return value[:limit]


def safe_url(url: str) -> str:
    parts = urlsplit(url)
    safe_query: list[tuple[str, str]] = []
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        safe_query.append((key, "[redacted]" if key.casefold() in SENSITIVE_KEYS else value))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(safe_query), ""))


def safe_post_data(post_data: str | None) -> str | None:
    if not post_data:
        return None
    try:
        pairs = parse_qsl(post_data, keep_blank_values=True)
    except ValueError:
        return "[unparseable request body omitted]"
    return urlencode(
        (key, "[redacted]" if key.casefold() in SENSITIVE_KEYS else value)
        for key, value in pairs
    )[:20_000]


def response_filename(index: int, response: Response) -> str:
    digest = hashlib.sha256(response.url.encode("utf-8")).hexdigest()[:10]
    return f"{index:03d}_{response.status}_{digest}.txt"


async def visible(page: Page, selector: str) -> bool:
    locator = page.locator(selector)
    try:
        return await locator.count() > 0 and await locator.first.is_visible()
    except Exception:
        return False


async def perform_login(page: Page) -> dict[str, Any]:
    username_selectors = [
        "input[name='log']",
        "input#user_login",
        "input[name='username']",
        "input[type='email']",
    ]
    password_selectors = [
        "input[name='pwd']",
        "input#user_pass",
        "input[name='password']",
        "input[type='password']",
    ]

    username_selector = next((item for item in username_selectors if await visible(page, item)), None)
    password_selector = next((item for item in password_selectors if await visible(page, item)), None)
    if not username_selector or not password_selector:
        return {"login_form_detected": False, "login_attempted": False}

    await page.locator(username_selector).first.fill(USERNAME)
    await page.locator(password_selector).first.fill(PASSWORD)

    remember = page.locator("input[name='rememberme'], input#rememberme")
    if await remember.count() and await remember.first.is_visible():
        try:
            await remember.first.check()
        except Exception:
            pass

    submit_selectors = [
        "button[type='submit']",
        "input[type='submit']",
        "button:has-text('Log In')",
        "button:has-text('Login')",
    ]
    submit_selector = next((item for item in submit_selectors if await visible(page, item)), None)
    if not submit_selector:
        raise RuntimeError("FantasyGP login form was detected but no visible submit control was found.")

    await page.locator(submit_selector).first.click()
    try:
        await page.wait_for_load_state("networkidle", timeout=60_000)
    except Exception:
        await page.wait_for_timeout(8_000)

    return {
        "login_form_detected": True,
        "login_attempted": True,
        "username_selector": username_selector,
        "password_selector": password_selector,
        "submit_selector": submit_selector,
    }


async def sanitised_html(page: Page) -> str:
    return await page.evaluate(
        """
        () => {
          const clone = document.documentElement.cloneNode(true);
          clone.querySelectorAll('script, style, noscript').forEach(node => node.remove());
          clone.querySelectorAll('input, textarea').forEach(node => {
            node.removeAttribute('value');
            node.textContent = '';
          });
          clone.querySelectorAll('[nonce]').forEach(node => node.removeAttribute('nonce'));
          return '<!doctype html>\n' + clone.outerHTML;
        }
        """
    )


async def collect_dom_inventory(page: Page) -> dict[str, Any]:
    return await page.evaluate(
        """
        () => {
          const text = node => (node?.innerText || node?.textContent || '').replace(/\s+/g, ' ').trim();
          const nearestHeading = node => {
            let current = node;
            for (let depth = 0; depth < 6 && current; depth += 1, current = current.parentElement) {
              const headings = [...current.querySelectorAll(':scope > h1, :scope > h2, :scope > h3, :scope > h4, :scope > h5, :scope > h6, :scope > .title, :scope > .heading')];
              const found = headings.map(text).find(Boolean);
              if (found) return found;
              let sibling = current.previousElementSibling;
              for (let steps = 0; steps < 4 && sibling; steps += 1, sibling = sibling.previousElementSibling) {
                if (/^H[1-6]$/.test(sibling.tagName) || sibling.matches('.title, .heading')) {
                  const value = text(sibling);
                  if (value) return value;
                }
              }
            }
            return '';
          };
          const rowsFor = table => [...table.querySelectorAll('tr')].map(row =>
            [...row.querySelectorAll(':scope > th, :scope > td')].map(text)
          ).filter(row => row.some(Boolean));

          return {
            title: document.title,
            url: location.href,
            body_text: text(document.body).slice(0, 200000),
            headings: [...document.querySelectorAll('h1,h2,h3,h4,h5,h6')]
              .map(node => ({tag: node.tagName, text: text(node)})).filter(item => item.text),
            tables: [...document.querySelectorAll('table')].map((table, index) => ({
              index,
              id: table.id || '',
              class_name: table.className || '',
              heading: nearestHeading(table),
              rows: rowsFor(table),
            })),
            selects: [...document.querySelectorAll('select')].map((select, index) => ({
              index,
              id: select.id || '',
              name: select.name || '',
              aria_label: select.getAttribute('aria-label') || '',
              selected_value: select.value,
              options: [...select.options].map(option => ({
                text: text(option),
                value: option.value,
                selected: option.selected,
              })),
            })),
            buttons: [...document.querySelectorAll('button, input[type=submit], a.button, [role=button]')]
              .map((node, index) => ({
                index,
                tag: node.tagName,
                id: node.id || '',
                class_name: node.className || '',
                text: text(node),
                aria_label: node.getAttribute('aria-label') || '',
              })).filter(item => item.text || item.aria_label),
            forms: [...document.querySelectorAll('form')].map((form, index) => ({
              index,
              id: form.id || '',
              class_name: form.className || '',
              action: form.action || '',
              method: form.method || '',
              fields: [...form.querySelectorAll('input, select, textarea')].map(node => ({
                tag: node.tagName,
                type: node.type || '',
                id: node.id || '',
                name: node.name || '',
              })),
            })),
            role_tables: [...document.querySelectorAll('[role=table], [role=grid]')].map((node, index) => ({
              index,
              role: node.getAttribute('role'),
              id: node.id || '',
              class_name: node.className || '',
              heading: nearestHeading(node),
              text: text(node).slice(0, 50000),
            })),
            scripts: [...document.scripts].map(script => script.src).filter(Boolean),
          };
        }
        """
    )


async def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    network_dir = OUTPUT_DIR / "network"
    network_dir.mkdir(exist_ok=True)

    if not USERNAME or not PASSWORD:
        raise RuntimeError("FANTASYGP_USERNAME and FANTASYGP_PASSWORD must both be configured.")

    captured: list[dict[str, Any]] = []
    response_tasks: list[asyncio.Task[None]] = []

    async def capture_response(response: Response) -> None:
        url = response.url
        if "fantasygp.com" not in url:
            return
        content_type = (response.headers.get("content-type") or "").casefold()
        is_candidate = (
            "json" in content_type
            or "admin-ajax" in url.casefold()
            or "league" in url.casefold()
            or "stand" in url.casefold()
            or "result" in url.casefold()
        )
        entry: dict[str, Any] = {
            "url": safe_url(url),
            "status": response.status,
            "content_type": content_type,
            "request_method": response.request.method,
            "request_post_data": safe_post_data(response.request.post_data),
            "body_file": None,
        }
        if is_candidate:
            try:
                body = await response.body()
                if len(body) <= MAX_RESPONSE_BYTES:
                    filename = response_filename(len(captured), response)
                    (network_dir / filename).write_bytes(body)
                    entry["body_file"] = f"network/{filename}"
                    entry["body_bytes"] = len(body)
                else:
                    entry["body_bytes"] = len(body)
                    entry["body_omitted"] = "over size limit"
            except Exception as error:
                entry["body_error"] = type(error).__name__
        captured.append(entry)

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        context: BrowserContext = await browser.new_context(
            locale="en-AU",
            timezone_id="Australia/Melbourne",
            viewport={"width": 1440, "height": 1400},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36"
            ),
        )
        page = await context.new_page()
        page.on("response", lambda response: response_tasks.append(asyncio.create_task(capture_response(response))))

        await page.goto(LEAGUE_URL, wait_until="domcontentloaded", timeout=90_000)
        login_result = await perform_login(page)
        if login_result["login_attempted"]:
            await page.goto(LEAGUE_URL, wait_until="domcontentloaded", timeout=90_000)

        try:
            await page.wait_for_load_state("networkidle", timeout=60_000)
        except Exception:
            pass
        await page.wait_for_timeout(10_000)

        password_visible = await visible(page, "input[type='password']")
        body_text = (await page.locator("body").inner_text()).casefold()
        login_error = any(
            phrase in body_text
            for phrase in (
                "incorrect password",
                "unknown username",
                "invalid username",
                "login failed",
                "please login to continue",
            )
        )
        logged_in = not password_visible and not login_error

        await page.screenshot(path=str(OUTPUT_DIR / "league-page.png"), full_page=True)
        inventory = await collect_dom_inventory(page)
        html = await sanitised_html(page)
        (OUTPUT_DIR / "league-page.sanitised.html").write_text(clean_text(html), encoding="utf-8")
        (OUTPUT_DIR / "dom-inventory.json").write_text(
            json.dumps(inventory, indent=2, ensure_ascii=False), encoding="utf-8"
        )

        if response_tasks:
            await asyncio.gather(*response_tasks, return_exceptions=True)

        summary = {
            "status": "pass" if logged_in else "fail",
            "league_url": safe_url(LEAGUE_URL),
            "final_url": safe_url(page.url),
            "logged_in": logged_in,
            "login": login_result,
            "table_count": len(inventory.get("tables", [])),
            "select_count": len(inventory.get("selects", [])),
            "role_table_count": len(inventory.get("role_tables", [])),
            "captured_response_count": len(captured),
            "captured_body_count": sum(1 for item in captured if item.get("body_file")),
        }
        (OUTPUT_DIR / "network-index.json").write_text(
            json.dumps(captured, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        (OUTPUT_DIR / "probe-summary.json").write_text(
            json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        print(json.dumps(summary, ensure_ascii=False))

        await context.close()
        await browser.close()

    return 0 if logged_in else 1


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except Exception as error:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        failure = {"status": "fail", "error": f"{type(error).__name__}: {error}"}
        (OUTPUT_DIR / "probe-summary.json").write_text(
            json.dumps(failure, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        print(json.dumps(failure, ensure_ascii=False), file=sys.stderr)
        raise
