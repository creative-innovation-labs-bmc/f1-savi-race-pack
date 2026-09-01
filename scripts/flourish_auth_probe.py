from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from urllib.parse import urlsplit

from playwright.async_api import async_playwright


OUTPUT = Path("build/flourish-republish/diagnostics/auth-probe.json")
LOGIN_URL = "https://app.flourish.studio/login"


def safe_url(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}{parts.path}"


async def run() -> int:
    email = os.environ.get("FLOURISH_EMAIL", "").strip()
    password = os.environ.get("FLOURISH_PASSWORD", "")
    if not email or not password:
        raise RuntimeError("Flourish secrets are missing.")

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    events: list[dict[str, object]] = []

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        context = await browser.new_context(locale="en-AU", timezone_id="Australia/Melbourne")
        page = await context.new_page()

        def on_response(response) -> None:
            try:
                request = response.request
                if request.method != "GET" and "flourish.studio" in response.url:
                    events.append(
                        {
                            "kind": "response",
                            "method": request.method,
                            "url": safe_url(response.url),
                            "status": response.status,
                        }
                    )
            except Exception:
                pass

        page.on("response", on_response)
        await page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=90_000)
        email_box = page.locator("input[type='email'], input[name='email']").first
        password_box = page.locator("input[type='password'], input[name='password']").first
        await email_box.wait_for(state="visible", timeout=30_000)
        await password_box.wait_for(state="visible", timeout=30_000)
        await email_box.fill(email)
        await password_box.fill(password)
        submit = page.get_by_role("button", name="Log in", exact=True)
        if not await submit.count():
            submit = page.locator("button[type='submit']").first
        await submit.click()

        previous: tuple[str, bool] | None = None
        for tick in range(40):
            await page.wait_for_timeout(500)
            state = (safe_url(page.url), bool(await page.locator("input[type='password']:visible").count()))
            if state != previous:
                events.append(
                    {
                        "kind": "state",
                        "ms_after_submit": (tick + 1) * 500,
                        "url": state[0],
                        "password_visible": state[1],
                    }
                )
                previous = state

        events.append(
            {
                "kind": "final",
                "url": safe_url(page.url),
                "title": await page.title(),
                "password_visible": bool(await page.locator("input[type='password']:visible").count()),
            }
        )
        await context.close()
        await browser.close()

    OUTPUT.write_text(json.dumps(events, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote safe Flourish auth trace to {OUTPUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run()))
