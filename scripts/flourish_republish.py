from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
from pathlib import Path

from playwright.async_api import Page, async_playwright


DEFAULT_VISUALISATIONS = (23536150, 23537908)
LOGIN_URL = "https://app.flourish.studio/login"


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        description="Republish existing Flourish visualisations through the normal editor UI."
    )
    result.add_argument(
        "--visualisation",
        action="append",
        dest="visualisations",
        type=int,
        help="Flourish visualisation ID. Can be supplied more than once.",
    )
    result.add_argument(
        "--diagnostics",
        type=Path,
        default=Path("build/flourish-republish/diagnostics"),
    )
    return result


async def first_visible(page: Page, selectors: list[str]) -> str | None:
    for selector in selectors:
        locator = page.locator(selector)
        try:
            if await locator.count() and await locator.first.is_visible():
                return selector
        except Exception:
            continue
    return None


async def capture(page: Page, directory: Path, label: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^a-zA-Z0-9._-]+", "-", label).strip("-") or "page"
    try:
        await page.screenshot(path=str(directory / f"{safe}.png"), full_page=True)
    except Exception:
        pass
    try:
        payload = {
            "url": page.url,
            "title": await page.title(),
            "body": (await page.locator("body").inner_text())[:6000],
        }
        (directory / f"{safe}.json").write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
    except Exception:
        pass


async def visible_login_fields(page: Page) -> tuple[str | None, str | None]:
    email_selector = await first_visible(
        page,
        [
            "input[type='email']",
            "input[name='email']",
            "input[name='username']",
            "input[autocomplete='username']",
        ],
    )
    password_selector = await first_visible(
        page,
        [
            "input[type='password']",
            "input[name='password']",
            "input[autocomplete='current-password']",
        ],
    )
    return email_selector, password_selector


async def login(page: Page, *, email: str, password: str, diagnostics: Path) -> None:
    await page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=90_000)

    # The Flourish login form is client-rendered. Wait explicitly for the email and
    # password controls instead of depending on an editor redirect settling in time.
    for _ in range(30):
        email_selector, password_selector = await visible_login_fields(page)
        if email_selector and password_selector:
            break
        if "/login" not in page.url:
            # An existing authenticated session may redirect away from /login.
            return
        await page.wait_for_timeout(1_000)
    else:
        await capture(page, diagnostics, "login-form-timeout")
        raise RuntimeError("Flourish login form did not become usable before timeout.")

    await page.locator(email_selector).first.fill(email)
    await page.locator(password_selector).first.fill(password)

    submit = await first_visible(
        page,
        [
            "button:has-text('Log in')",
            "button:has-text('Log In')",
            "button:has-text('Sign in')",
            "button:has-text('Sign In')",
            "button[type='submit']",
            "input[type='submit']",
        ],
    )
    if not submit:
        await capture(page, diagnostics, "login-submit-missing")
        raise RuntimeError("Flourish login form has no usable submit control.")

    await page.locator(submit).first.click()

    # Flourish can briefly visit a non-login route during authentication and then
    # return to /login. Require several consecutive seconds of authenticated state
    # before treating login as successful.
    stable_authenticated_seconds = 0
    for _ in range(45):
        await page.wait_for_timeout(1_000)
        body = (await page.locator("body").inner_text()).casefold()
        if any(term in body for term in ("verification code", "two-factor", "two factor", "authenticator")):
            await capture(page, diagnostics, "mfa-required")
            raise RuntimeError(
                "Flourish requires an interactive MFA step; browser republishing cannot continue unattended."
            )
        if any(
            term in body
            for term in (
                "invalid email",
                "invalid password",
                "incorrect password",
                "email or password is incorrect",
                "couldn't log in",
                "could not log in",
            )
        ):
            await capture(page, diagnostics, "login-rejected")
            raise RuntimeError("Flourish rejected the configured email/password login.")

        password_visible = bool(await page.locator("input[type='password']:visible").count())
        if "/login" not in page.url and not password_visible:
            stable_authenticated_seconds += 1
            if stable_authenticated_seconds >= 4:
                return
        else:
            stable_authenticated_seconds = 0

    await capture(page, diagnostics, "login-not-accepted")
    raise RuntimeError("Flourish did not establish a stable authenticated session with the configured credentials.")


async def wait_for_editor_or_login(page: Page, *, visualisation_id: int, timeout_seconds: int = 45) -> str:
    publish_candidates = [
        "button:has-text('Export & publish')",
        "button:has-text('Export and publish')",
        "[role='button']:has-text('Export & publish')",
        "[role='button']:has-text('Export and publish')",
    ]
    for _ in range(timeout_seconds):
        if "/login" in page.url:
            return "login"
        if await first_visible(page, publish_candidates):
            return "editor"
        await page.wait_for_timeout(1_000)
    return "timeout"


async def ensure_editor_access(
    page: Page,
    *,
    visualisation_id: int,
    email: str,
    password: str,
    diagnostics: Path,
) -> None:
    edit_url = f"https://app.flourish.studio/visualisation/{visualisation_id}/edit"

    for attempt in range(2):
        await page.goto(edit_url, wait_until="domcontentloaded", timeout=90_000)
        state = await wait_for_editor_or_login(page, visualisation_id=visualisation_id)
        if state == "editor":
            return
        if state == "login" and attempt == 0:
            await login(page, email=email, password=password, diagnostics=diagnostics)
            continue
        break

    await capture(page, diagnostics, f"{visualisation_id}-editor-access-failed")
    raise RuntimeError(
        f"Could not establish authenticated editor access for Flourish visualisation {visualisation_id}."
    )


async def open_publish_panel(page: Page, diagnostics: Path, visualisation_id: int) -> None:
    candidates = [
        "button:has-text('Export & publish')",
        "button:has-text('Export and publish')",
        "[role='button']:has-text('Export & publish')",
        "[role='button']:has-text('Export and publish')",
    ]
    selector = await first_visible(page, candidates)
    if not selector:
        await capture(page, diagnostics, f"{visualisation_id}-editor-no-publish-control")
        raise RuntimeError(
            f"Flourish editor {visualisation_id} loaded without a visible Export & publish control."
        )
    await page.locator(selector).first.click()
    await page.wait_for_timeout(1_500)


async def click_exact_republish(page: Page) -> bool:
    exact_candidates = [
        page.get_by_role("button", name=re.compile(r"^Republish$", re.I)),
        page.get_by_role("button", name=re.compile(r"^Publish changes$", re.I)),
        page.get_by_text(re.compile(r"^Republish$", re.I), exact=True),
        page.get_by_text(re.compile(r"^Publish changes$", re.I), exact=True),
    ]
    for locator in exact_candidates:
        try:
            if await locator.count() and await locator.first.is_visible():
                await locator.first.click()
                return True
        except Exception:
            continue
    return False


async def republish(page: Page, *, visualisation_id: int, email: str, password: str, diagnostics: Path) -> None:
    await ensure_editor_access(
        page,
        visualisation_id=visualisation_id,
        email=email,
        password=password,
        diagnostics=diagnostics,
    )

    await open_publish_panel(page, diagnostics, visualisation_id)
    if not await click_exact_republish(page):
        await capture(page, diagnostics, f"{visualisation_id}-republish-control-missing")
        raise RuntimeError(
            f"Flourish visualisation {visualisation_id} did not expose an exact Republish control. "
            "No broader Publish button was clicked for safety."
        )

    await page.wait_for_timeout(2_000)
    # Some Flourish publish flows use a second confirmation dialog with the same label.
    await click_exact_republish(page)

    try:
        await page.wait_for_load_state("networkidle", timeout=30_000)
    except Exception:
        pass
    await page.wait_for_timeout(3_000)
    await capture(page, diagnostics, f"{visualisation_id}-after-republish")


async def run() -> int:
    args = parser().parse_args()
    visualisations = tuple(args.visualisations or DEFAULT_VISUALISATIONS)
    email = os.environ.get("FLOURISH_EMAIL", "").strip()
    password = os.environ.get("FLOURISH_PASSWORD", "")
    if not email or not password:
        raise RuntimeError("FLOURISH_EMAIL and FLOURISH_PASSWORD must be configured as secrets.")

    args.diagnostics.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        context = await browser.new_context(
            locale="en-AU",
            timezone_id="Australia/Melbourne",
            viewport={"width": 1600, "height": 1200},
        )
        page = await context.new_page()

        # Authenticate once at the start of a fresh GitHub runner session, then reuse
        # that browser context for both visualisations.
        await login(page, email=email, password=password, diagnostics=args.diagnostics)

        completed: list[int] = []
        for visualisation_id in visualisations:
            await republish(
                page,
                visualisation_id=visualisation_id,
                email=email,
                password=password,
                diagnostics=args.diagnostics,
            )
            completed.append(visualisation_id)
        await context.close()
        await browser.close()

    print(json.dumps({"status": "pass", "republished": completed}))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run()))
