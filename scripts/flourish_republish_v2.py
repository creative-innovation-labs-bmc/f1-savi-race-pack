from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
from pathlib import Path

from playwright.async_api import Page, async_playwright


PROJECTS = {
    23536150: "F1 SAVI League - Races",
    23537908: "F1 SAVI League - Leaderboard",
}
LOGIN_URL = "https://app.flourish.studio/login"
PROJECTS_URL = "https://app.flourish.studio/projects"


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser()
    p.add_argument("--visualisation", action="append", type=int, dest="visualisations")
    p.add_argument(
        "--diagnostics",
        type=Path,
        default=Path("build/flourish-republish/diagnostics"),
    )
    return p


async def snapshot(page: Page, directory: Path, name: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^a-zA-Z0-9._-]+", "-", name).strip("-") or "page"
    try:
        await page.screenshot(path=str(directory / f"{safe}.png"), full_page=True)
    except Exception:
        pass
    try:
        buttons = []
        for button in await page.locator("button:visible").all():
            text = (await button.inner_text()).strip()
            if text and text not in buttons:
                buttons.append(text)
        payload = {
            "url": page.url,
            "title": await page.title(),
            "visible_buttons": buttons[:80],
            "body_excerpt": (await page.locator("body").inner_text())[:5000],
        }
        (directory / f"{safe}.json").write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
    except Exception:
        pass


async def login(page: Page, email: str, password: str, diagnostics: Path) -> None:
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

    await page.wait_for_url(re.compile(r"/projects(?:$|[?#])"), timeout=45_000)
    # Do not immediately leave /projects. Flourish performs additional client-side
    # session setup after the initial 302. Wait until the known projects themselves
    # are visible before opening an editor.
    await page.get_by_text(PROJECTS[23536150], exact=True).wait_for(state="visible", timeout=45_000)
    await page.get_by_text(PROJECTS[23537908], exact=True).wait_for(state="visible", timeout=45_000)
    await page.wait_for_timeout(5_000)


async def exact_control(page: Page, names: list[str]):
    for name in names:
        pattern = re.compile(rf"^{re.escape(name)}$", re.I)
        for locator in (
            page.get_by_role("button", name=pattern),
            page.get_by_text(pattern, exact=True),
        ):
            try:
                if await locator.count() and await locator.first.is_visible():
                    return locator.first
            except Exception:
                continue
    return None


async def republish_one(page: Page, visualisation_id: int, diagnostics: Path) -> None:
    expected_name = PROJECTS[visualisation_id]
    edit_url = f"https://app.flourish.studio/visualisation/{visualisation_id}/edit"
    await page.goto(edit_url, wait_until="domcontentloaded", timeout=90_000)

    # Wait for the editor title and then give its toolbar a little time to hydrate.
    for _ in range(60):
        if "/login" in page.url:
            await snapshot(page, diagnostics, f"{visualisation_id}-unexpected-login")
            raise RuntimeError(f"Flourish session was lost while opening {visualisation_id}.")
        title = await page.title()
        if expected_name in title:
            break
        await page.wait_for_timeout(500)
    else:
        await snapshot(page, diagnostics, f"{visualisation_id}-editor-title-timeout")
        raise RuntimeError(f"Flourish editor title did not load for {visualisation_id}.")

    await page.wait_for_timeout(8_000)
    await snapshot(page, diagnostics, f"{visualisation_id}-before-republish")

    # Flourish may expose Republish directly when there are unpublished changes.
    control = await exact_control(page, ["Republish", "Publish changes"])
    if control is None:
        export_control = await exact_control(page, ["Export & publish", "Export and publish"])
        if export_control is None:
            await snapshot(page, diagnostics, f"{visualisation_id}-no-export-control")
            raise RuntimeError(f"No Export & publish control was visible for {visualisation_id}.")
        await export_control.click()
        await page.wait_for_timeout(2_000)
        control = await exact_control(page, ["Republish", "Publish changes"])

    if control is None:
        await snapshot(page, diagnostics, f"{visualisation_id}-no-republish-control")
        raise RuntimeError(
            f"No exact Republish/Publish changes control was visible for {visualisation_id}."
        )

    await control.click()
    await page.wait_for_timeout(5_000)

    # A confirmation dialog may appear. Only accept an exact republish-labelled
    # confirmation, never a broad or ambiguous publish button.
    confirmation = await exact_control(page, ["Republish", "Publish changes"])
    if confirmation is not None:
        try:
            await confirmation.click()
            await page.wait_for_timeout(5_000)
        except Exception:
            pass

    await snapshot(page, diagnostics, f"{visualisation_id}-after-republish")
    if "/login" in page.url:
        raise RuntimeError(f"Flourish session was lost while republishing {visualisation_id}.")


async def run() -> int:
    args = parser().parse_args()
    ids = args.visualisations or list(PROJECTS)
    unknown = [value for value in ids if value not in PROJECTS]
    if unknown:
        raise RuntimeError(f"Unsupported Flourish visualisation IDs: {unknown}")

    email = os.environ.get("FLOURISH_EMAIL", "").strip()
    password = os.environ.get("FLOURISH_PASSWORD", "")
    if not email or not password:
        raise RuntimeError("FLOURISH_EMAIL and FLOURISH_PASSWORD must be configured.")

    args.diagnostics.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        context = await browser.new_context(
            locale="en-AU",
            timezone_id="Australia/Melbourne",
            viewport={"width": 1600, "height": 1200},
        )
        page = await context.new_page()
        await login(page, email, password, args.diagnostics)

        completed = []
        for visualisation_id in ids:
            await republish_one(page, visualisation_id, args.diagnostics)
            completed.append(visualisation_id)

        await context.close()
        await browser.close()

    print(json.dumps({"status": "pass", "republished": completed}))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run()))
