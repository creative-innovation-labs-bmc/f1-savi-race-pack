from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

from playwright.async_api import Page, async_playwright

from f1_savi.fantasygp import (
    FantasyGPRow,
    combine_league_pages,
    parse_integer,
    update_season_datasets,
)
from f1_savi.models import RacePackError

DEFAULT_LEAGUE_URL = "https://fantasygp.com/league/?lid=10527"


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        description="Authenticate to FantasyGP, fetch league scores and prepare validated season CSVs."
    )
    result.add_argument("--individual", required=True, type=Path)
    result.add_argument("--cumulative", required=True, type=Path)
    result.add_argument("--output", required=True, type=Path)
    result.add_argument("--league-url", default=DEFAULT_LEAGUE_URL)
    result.add_argument("--league-id", default="10527")
    result.add_argument("--expected-competitors", type=int, default=46)
    result.add_argument("--expected-round", type=int)
    result.add_argument("--expected-race")
    return result


def json_response(text: str, *, action: str) -> dict[str, Any]:
    try:
        value = json.loads(text)
    except json.JSONDecodeError as error:
        raise RacePackError(
            f"FantasyGP action {action!r} did not return valid JSON: {text[:300]!r}"
        ) from error
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as error:
            raise RacePackError(
                f"FantasyGP action {action!r} returned a JSON string that was not an object."
            ) from error
    if not isinstance(value, dict):
        raise RacePackError(
            f"FantasyGP action {action!r} returned {type(value).__name__}; expected an object."
        )
    return value


async def first_visible(page: Page, selectors: list[str]) -> str | None:
    for selector in selectors:
        locator = page.locator(selector)
        try:
            if await locator.count() and await locator.first.is_visible():
                return selector
        except Exception:
            continue
    return None


async def write_auth_diagnostics(page: Page, diagnostics: Path, error: Exception) -> None:
    diagnostics.mkdir(parents=True, exist_ok=True)
    try:
        await page.screenshot(path=str(diagnostics / "auth-failure.png"), full_page=True)
    except Exception:
        pass

    try:
        details = await page.evaluate(
            """
            () => {
              const visible = element => {
                const style = window.getComputedStyle(element);
                const rect = element.getBoundingClientRect();
                return style.visibility !== 'hidden' &&
                  style.display !== 'none' &&
                  rect.width > 0 &&
                  rect.height > 0;
              };
              return {
                title: document.title,
                visibleInputs: [...document.querySelectorAll('input')]
                  .filter(visible)
                  .map(element => ({
                    type: element.type || '',
                    name: element.name || '',
                    id: element.id || '',
                    autocomplete: element.autocomplete || ''
                  })),
                visibleButtons: [...document.querySelectorAll('button, input[type="submit"]')]
                  .filter(visible)
                  .map(element => (element.innerText || element.value || '').trim())
                  .filter(Boolean),
                bodyExcerpt: (document.body?.innerText || '').slice(0, 1500)
              };
            }
            """
        )
    except Exception as diagnostic_error:
        details = {"diagnostic_error": f"{type(diagnostic_error).__name__}: {diagnostic_error}"}

    payload = {
        "error": f"{type(error).__name__}: {error}",
        "url": page.url,
        **details,
    }
    (diagnostics / "auth-failure.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


async def login(page: Page, *, league_url: str, username: str, password: str) -> dict[str, object]:
    await page.goto(league_url, wait_until="domcontentloaded", timeout=90_000)
    username_selector = await first_visible(
        page,
        ["input[name='log']", "input#user_login", "input[name='username']", "input[type='email']"],
    )
    password_selector = await first_visible(
        page,
        ["input[name='pwd']", "input#user_pass", "input[name='password']", "input[type='password']"],
    )

    login_attempted = bool(username_selector and password_selector)
    if login_attempted:
        assert username_selector and password_selector
        await page.locator(username_selector).first.fill(username)
        await page.locator(password_selector).first.fill(password)
        remember = page.locator("input[name='rememberme'], input#rememberme")
        if await remember.count() and await remember.first.is_visible():
            try:
                await remember.first.check()
            except Exception:
                pass
        submit_selector = await first_visible(
            page,
            [
                "button[type='submit']",
                "input[type='submit']",
                "button:has-text('Log In')",
                "button:has-text('Login')",
            ],
        )
        if not submit_selector:
            raise RacePackError("FantasyGP login form has no visible submit control.")
        await page.locator(submit_selector).first.click()
        try:
            await page.wait_for_load_state("networkidle", timeout=60_000)
        except Exception:
            await page.wait_for_timeout(8_000)
        await page.goto(league_url, wait_until="domcontentloaded", timeout=90_000)

    try:
        await page.wait_for_function(
            "() => window.MyAjax && window.MyAjax.ajaxurl && window.MyAjax.security",
            timeout=60_000,
        )
    except Exception as error:
        body = (await page.locator("body").inner_text()).casefold()
        if "please login to continue" in body or await page.locator("input[type='password']").count():
            raise RacePackError("FantasyGP login was not accepted.") from error
        raise RacePackError("FantasyGP loaded without its authenticated AJAX configuration.") from error

    return {
        "login_attempted": login_attempted,
        "final_url": page.url,
    }


async def ajax(page: Page, action: str, params: dict[str, object], *, method: str = "POST") -> dict[str, Any]:
    result = await page.evaluate(
        """
        async ({action, params, method}) => {
          const config = window.MyAjax;
          if (!config || !config.ajaxurl || !config.security) {
            throw new Error('MyAjax configuration is unavailable');
          }
          const form = new URLSearchParams();
          form.set('action', action);
          form.set('security', config.security);
          for (const [key, value] of Object.entries(params)) form.set(key, String(value));
          const options = {
            method,
            credentials: 'same-origin',
            headers: {'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8'}
          };
          let url = config.ajaxurl;
          if (method === 'GET') url += '?' + form.toString();
          else options.body = form.toString();
          const response = await fetch(url, options);
          return {status: response.status, ok: response.ok, text: await response.text()};
        }
        """,
        {"action": action, "params": params, "method": method},
    )
    if not result.get("ok"):
        raise RacePackError(
            f"FantasyGP action {action!r} returned HTTP {result.get('status')}: {str(result.get('text'))[:300]}"
        )
    return json_response(str(result.get("text", "")), action=action)


async def fetch_pages(
    page: Page,
    *,
    league_id: str,
    race: int,
    expected_competitors: int,
) -> tuple[list[dict[str, Any]], tuple[FantasyGPRow, ...]]:
    pages: list[dict[str, Any]] = []
    offset = 0
    seen_offsets: set[int] = set()
    while True:
        if offset in seen_offsets:
            raise RacePackError(f"FantasyGP pagination repeated offset {offset}.")
        seen_offsets.add(offset)
        response = await ajax(
            page,
            "fetchLeague",
            {"leagueid": league_id, "leagueoffset": offset, "leaguerace": race},
        )
        pages.append(response)
        howmany = parse_integer(response.get("howmany", 0), field="howmany")
        total = parse_integer(response.get("total", 0), field="total")
        collected = sum(parse_integer(item.get("howmany", 0), field="howmany") for item in pages)
        if collected >= total:
            break
        if howmany <= 0:
            raise RacePackError(
                f"FantasyGP pagination stopped after {collected} of {total} competitors."
            )
        candidate = response.get("newoffset", offset + howmany)
        next_offset = parse_integer(candidate, field="newoffset")
        if next_offset <= offset:
            next_offset = offset + howmany
        offset = next_offset
        if len(pages) > 20:
            raise RacePackError("FantasyGP pagination exceeded 20 pages.")

    rows = combine_league_pages(pages, expected_competitors=expected_competitors)
    return pages, rows


def sanitise_page(page: dict[str, Any]) -> dict[str, Any]:
    excluded = {"leaguecode", "presidentlist", "profilelinks", "teamuids", "rowtag"}
    return {key: value for key, value in page.items() if key not in excluded}


async def run(args: argparse.Namespace) -> dict[str, object]:
    username = os.environ.get("FANTASYGP_USERNAME", "")
    password = os.environ.get("FANTASYGP_PASSWORD", "")
    if not username or not password:
        raise RacePackError("FANTASYGP_USERNAME and FANTASYGP_PASSWORD must be configured.")

    args.output.mkdir(parents=True, exist_ok=True)
    diagnostics = args.output / "diagnostics"
    diagnostics.mkdir(exist_ok=True)

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        context = await browser.new_context(
            locale="en-AU",
            timezone_id="Australia/Melbourne",
            viewport={"width": 1440, "height": 1400},
        )
        page = await context.new_page()
        try:
            login_summary = await login(
                page, league_url=args.league_url, username=username, password=password
            )
        except Exception as error:
            await write_auth_diagnostics(page, diagnostics, error)
            await context.close()
            await browser.close()
            raise

        try:
            await page.wait_for_load_state("networkidle", timeout=45_000)
        except Exception:
            pass
        await page.wait_for_timeout(4_000)
        await page.screenshot(path=str(diagnostics / "league-page.png"), full_page=True)

        race_select = await ajax(page, "fetchRaceSelect", {}, method="GET")
        active_race = parse_integer(race_select.get("activerace"), field="activerace")
        latest_round = active_race - 1
        if latest_round < 1:
            raise RacePackError("FantasyGP does not report a completed race yet.")
        names = race_select.get("gp")
        if not isinstance(names, list) or latest_round >= len(names):
            raise RacePackError(
                f"FantasyGP race selector has no name for completed Round {latest_round:02d}."
            )
        race_name = str(names[latest_round]).strip()
        if not race_name:
            raise RacePackError(f"FantasyGP returned a blank name for Round {latest_round:02d}.")
        if args.expected_round is not None and latest_round != args.expected_round:
            raise RacePackError(
                f"FantasyGP latest completed round is {latest_round}; expected {args.expected_round}."
            )
        if args.expected_race and race_name.casefold() != args.expected_race.strip().casefold():
            raise RacePackError(
                f"FantasyGP latest race is {race_name!r}; expected {args.expected_race!r}."
            )

        standings_pages, standings_rows = await fetch_pages(
            page,
            league_id=args.league_id,
            race=0,
            expected_competitors=args.expected_competitors,
        )
        race_pages, race_rows = await fetch_pages(
            page,
            league_id=args.league_id,
            race=latest_round,
            expected_competitors=args.expected_competitors,
        )

        snapshot = {
            "league_id": args.league_id,
            "latest_completed_round": latest_round,
            "latest_completed_race": race_name,
            "active_race": active_race,
            "race_selector": {
                "gp": race_select.get("gp"),
                "gpid": race_select.get("gpid"),
                "gpdate": race_select.get("gpdate"),
            },
            "standings": [row.to_dict() for row in standings_rows],
            "race_results": [row.to_dict() for row in race_rows],
            "standings_pages": [sanitise_page(item) for item in standings_pages],
            "race_pages": [sanitise_page(item) for item in race_pages],
        }
        (diagnostics / "fantasygp-snapshot.json").write_text(
            json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )

        updated_individual = args.output / "updated_individual.csv"
        updated_cumulative = args.output / "updated_cumulative.csv"
        update_summary = update_season_datasets(
            args.individual,
            args.cumulative,
            race_name=race_name,
            round_number=latest_round,
            race_rows=race_rows,
            standings_rows=standings_rows,
            output_individual_path=updated_individual,
            output_cumulative_path=updated_cumulative,
            expected_competitors=args.expected_competitors,
        )
        summary: dict[str, object] = {
            "status": "pass",
            "login": login_summary,
            "update": update_summary,
            "individual_csv": str(updated_individual),
            "cumulative_csv": str(updated_cumulative),
        }
        (args.output / "update-summary.json").write_text(
            json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        await context.close()
        await browser.close()
        return summary


async def main() -> int:
    args = parser().parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    try:
        summary = await run(args)
        print(json.dumps(summary, ensure_ascii=False))
        return 0
    except Exception as error:
        failure = {"status": "fail", "error": f"{type(error).__name__}: {error}"}
        (args.output / "update-summary.json").write_text(
            json.dumps(failure, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        print(json.dumps(failure, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
