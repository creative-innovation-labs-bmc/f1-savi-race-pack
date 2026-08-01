from __future__ import annotations

import asyncio

import fantasygp_update_runner as base
from f1_savi.models import RacePackError


async def wait_for_auth_state(page, timeout: int = 45_000) -> None:
    await page.wait_for_function(
        """
        () => Boolean(
          document.querySelector('#raceselect2') ||
          document.querySelector('input[name="log"]') ||
          document.querySelector('input#user_login') ||
          document.querySelector('input[name="username"]') ||
          document.querySelector('input[type="email"]') ||
          document.querySelector('input[type="password"]')
        )
        """,
        timeout=timeout,
    )


async def authenticated_login(page, *, league_url: str, username: str, password: str) -> dict[str, object]:
    last_error = "FantasyGP login was not accepted."

    for attempt in range(1, 4):
        if attempt > 1:
            await page.context.clear_cookies()
            await page.wait_for_timeout(5_000 * attempt)

        await page.goto(league_url, wait_until="domcontentloaded", timeout=90_000)

        try:
            await wait_for_auth_state(page)
        except Exception:
            last_error = f"FantasyGP did not finish loading its login or league interface on attempt {attempt}."
            continue

        if await page.locator("#raceselect2").count():
            await page.wait_for_function(
                "() => window.MyAjax && window.MyAjax.ajaxurl && window.MyAjax.security && window.jQuery",
                timeout=30_000,
            )
            return {
                "login_attempted": attempt > 1,
                "login_attempts": attempt - 1,
                "final_url": page.url,
                "authenticated": True,
            }

        username_selector = await base.update.first_visible(
            page,
            [
                "input[name='log']",
                "input#user_login",
                "input[name='username']",
                "input[type='email']",
            ],
        )
        password_selector = await base.update.first_visible(
            page,
            [
                "input[name='pwd']",
                "input#user_pass",
                "input[name='password']",
                "input[type='password']",
            ],
        )
        if not username_selector or not password_selector:
            last_error = "FantasyGP loaded an unrecognised authentication interface."
            continue

        username_input = page.locator(username_selector).first
        password_input = page.locator(password_selector).first
        await username_input.fill(username)
        await password_input.fill(password)

        remember = page.locator("input[name='rememberme'], input#rememberme")
        if await remember.count() and await remember.first.is_visible():
            try:
                await remember.first.check()
            except Exception:
                pass

        submitted = await password_input.evaluate(
            """
            element => {
              if (!element.form) return false;
              if (typeof element.form.requestSubmit === 'function') element.form.requestSubmit();
              else element.form.submit();
              return true;
            }
            """
        )
        if not submitted:
            submit_selector = await base.update.first_visible(
                page,
                [
                    "button:has-text('Log In')",
                    "input[type='submit'][value='Log In']",
                    "button[type='submit']",
                    "input[type='submit']",
                ],
            )
            if not submit_selector:
                last_error = "FantasyGP login form had no usable submit control."
                continue
            await page.locator(submit_selector).first.click()

        await page.wait_for_timeout(8_000)
        await page.goto(league_url, wait_until="domcontentloaded", timeout=90_000)

        try:
            await wait_for_auth_state(page)
            await page.wait_for_selector("#raceselect2", state="attached", timeout=30_000)
            await page.wait_for_function(
                "() => window.MyAjax && window.MyAjax.ajaxurl && window.MyAjax.security && window.jQuery",
                timeout=30_000,
            )
            return {
                "login_attempted": True,
                "login_attempts": attempt,
                "final_url": page.url,
                "authenticated": True,
            }
        except Exception:
            body = (await page.locator("body").inner_text()).casefold()
            if "incorrect" in body or "invalid" in body or "unknown username" in body:
                last_error = "FantasyGP rejected the configured credentials."
                break
            last_error = f"FantasyGP login attempt {attempt} did not create an authenticated session."

    raise RacePackError(last_error)


base.update.login = authenticated_login


if __name__ == "__main__":
    raise SystemExit(asyncio.run(base.update.main()))
