from __future__ import annotations

import asyncio
import json
import sys

import fantasygp_probe as probe


async def first_visible_selector(page, selectors: list[str]) -> str | None:
    for selector in selectors:
        if await probe.visible(page, selector):
            return selector
    return None


async def corrected_perform_login(page):
    username_selector = await first_visible_selector(
        page,
        [
            "input[name='log']",
            "input#user_login",
            "input[name='username']",
            "input[type='email']",
        ],
    )
    password_selector = await first_visible_selector(
        page,
        [
            "input[name='pwd']",
            "input#user_pass",
            "input[name='password']",
            "input[type='password']",
        ],
    )
    if not username_selector or not password_selector:
        return {"login_form_detected": False, "login_attempted": False}

    await page.locator(username_selector).first.fill(probe.USERNAME)
    await page.locator(password_selector).first.fill(probe.PASSWORD)

    remember = page.locator("input[name='rememberme'], input#rememberme")
    if await remember.count() and await remember.first.is_visible():
        try:
            await remember.first.check()
        except Exception:
            pass

    submit_selector = await first_visible_selector(
        page,
        [
            "button[type='submit']",
            "input[type='submit']",
            "button:has-text('Log In')",
            "button:has-text('Login')",
        ],
    )
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


probe.perform_login = corrected_perform_login


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(probe.main()))
    except Exception as error:
        probe.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        failure = {"status": "fail", "error": f"{type(error).__name__}: {error}"}
        (probe.OUTPUT_DIR / "probe-summary.json").write_text(
            json.dumps(failure, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        print(json.dumps(failure, ensure_ascii=False), file=sys.stderr)
        raise
