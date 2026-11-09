from __future__ import annotations

import argparse
import asyncio
import csv
import json
import os
import re
from pathlib import Path

from playwright.async_api import Page, async_playwright


LOGIN_URL = "https://app.flourish.studio/login"
PROJECTS = {
    23536150: "F1 SAVI League - Races",
    23537908: "F1 SAVI League - Leaderboard",
}


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Upload canonical SAVI CSVs into Flourish and republish the two charts."
    )
    p.add_argument("--races", type=Path, required=True)
    p.add_argument("--leaderboard", type=Path, required=True)
    p.add_argument("--expected-competitors", type=int, default=46)
    p.add_argument(
        "--diagnostics",
        type=Path,
        default=Path("build/flourish-sync/diagnostics"),
    )
    return p


def inspect_csv(path: Path, expected_competitors: int) -> dict[str, object]:
    if not path.exists():
        raise RuntimeError(f"Missing CSV: {path}")
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.reader(handle))
    if not rows:
        raise RuntimeError(f"CSV is empty: {path}")
    header = rows[0]
    data = rows[1:]
    if len(data) != expected_competitors:
        raise RuntimeError(
            f"{path} has {len(data)} competitors; expected {expected_competitors}."
        )
    if not header or header[0] != "Team | Manager":
        raise RuntimeError(f"{path} has an unexpected first column.")
    if len(header) < 2:
        raise RuntimeError(f"{path} has no race columns.")
    if any(len(row) != len(header) for row in data):
        raise RuntimeError(f"{path} contains rows with a different column count.")
    return {
        "path": str(path),
        "rows": len(data),
        "columns": len(header),
        "latest_header": header[-1],
        "header": header,
    }


async def snapshot(page: Page, directory: Path, label: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^a-zA-Z0-9._-]+", "-", label).strip("-") or "page"
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
            "visible_buttons": buttons[:100],
            "body_excerpt": (await page.locator("body").inner_text())[:10000],
        }
        (directory / f"{safe}.json").write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
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
    await page.get_by_text(PROJECTS[23536150], exact=True).wait_for(state="visible", timeout=45_000)
    await page.get_by_text(PROJECTS[23537908], exact=True).wait_for(state="visible", timeout=45_000)
    await page.wait_for_timeout(5_000)


async def exact_control(page: Page, names: list[str]):
    for name in names:
        pattern = re.compile(rf"^{re.escape(name)}$", re.I)
        for locator in (
            page.get_by_role("button", name=pattern),
            page.get_by_role("tab", name=pattern),
            page.get_by_text(pattern, exact=True),
        ):
            try:
                if await locator.count() and await locator.first.is_visible():
                    return locator.first
            except Exception:
                continue
    return None


async def open_editor(page: Page, visualisation_id: int, diagnostics: Path) -> None:
    expected_name = PROJECTS[visualisation_id]
    await page.goto(
        f"https://app.flourish.studio/visualisation/{visualisation_id}/edit",
        wait_until="domcontentloaded",
        timeout=90_000,
    )
    for _ in range(90):
        if "/login" in page.url:
            await snapshot(page, diagnostics, f"{visualisation_id}-session-lost")
            raise RuntimeError(f"Flourish session was lost opening {visualisation_id}.")
        if expected_name.casefold() in (await page.title()).casefold():
            await page.wait_for_timeout(3000)
            return
        await page.wait_for_timeout(500)
    await snapshot(page, diagnostics, f"{visualisation_id}-editor-timeout")
    raise RuntimeError(f"Flourish editor did not load for {visualisation_id}.")


async def open_data_tab(page: Page, visualisation_id: int, diagnostics: Path) -> None:
    tab = await exact_control(page, ["Data"])
    if tab is None:
        await snapshot(page, diagnostics, f"{visualisation_id}-data-tab-missing")
        raise RuntimeError(f"Could not find the Flourish Data tab for {visualisation_id}.")
    await tab.click()
    await page.wait_for_timeout(2500)


async def upload_csv(
    page: Page,
    visualisation_id: int,
    csv_path: Path,
    latest_header: str,
    diagnostics: Path,
) -> None:
    await open_data_tab(page, visualisation_id, diagnostics)
    await snapshot(page, diagnostics, f"{visualisation_id}-data-before-import")

    # Current Flourish exposes a blue split-button labelled exactly "Upload data".
    # Use that control rather than assigning an arbitrary hidden file input.
    upload = None
    # Flourish currently renders "Upload data" as a styled non-button element.
    # Text-engine lookup is therefore more reliable than ARIA/button lookup.
    candidates = page.locator("text=Upload data")
    for i in range(await candidates.count()):
        candidate = candidates.nth(i)
        try:
            if await candidate.is_visible():
                upload = candidate
                break
        except Exception:
            continue

    if upload is None:
        await snapshot(page, diagnostics, f"{visualisation_id}-upload-data-missing")
        raise RuntimeError(
            f"Could not find the Flourish Upload data control for visualisation {visualisation_id}."
        )

    chooser_used = False
    try:
        async with page.expect_file_chooser(timeout=8000) as chooser_info:
            await upload.click()
        chooser = await chooser_info.value
        await chooser.set_files(str(csv_path.resolve()))
        chooser_used = True
    except Exception:
        # Some UI variants open an upload menu/modal before exposing the file input.
        await page.wait_for_timeout(1200)
        file_inputs = page.locator("input[type='file']")
        if await file_inputs.count():
            await file_inputs.first.set_input_files(str(csv_path.resolve()))
            chooser_used = True
        else:
            # Try the split-button menu for an explicit file-upload entry.
            menu_button = page.locator(
                "button:visible"
            ).filter(has=page.locator("svg")).filter(has_text="")
            # Prefer menu text if the main Upload data button opened a menu.
            for label in ("Upload CSV", "Upload file", "Choose file", "Import data"):
                candidate = page.get_by_text(re.compile(rf"^{re.escape(label)}$", re.I), exact=True)
                if await candidate.count() and await candidate.first.is_visible():
                    try:
                        async with page.expect_file_chooser(timeout=5000) as chooser_info:
                            await candidate.first.click()
                        chooser = await chooser_info.value
                        await chooser.set_files(str(csv_path.resolve()))
                        chooser_used = True
                        break
                    except Exception:
                        await page.wait_for_timeout(500)
                        file_inputs = page.locator("input[type='file']")
                        if await file_inputs.count():
                            await file_inputs.first.set_input_files(str(csv_path.resolve()))
                            chooser_used = True
                            break

    if not chooser_used:
        await snapshot(page, diagnostics, f"{visualisation_id}-file-chooser-missing")
        raise RuntimeError(
            f"Flourish upload UI for {visualisation_id} did not accept a CSV file."
        )

    await page.wait_for_timeout(3000)

    # Confirm only explicit import/replace actions when Flourish presents them.
    for names in (
        ["Import", "Import data", "Replace", "Replace data"],
        ["Continue", "Next"],
        ["Import", "Replace data", "Confirm"],
    ):
        control = await exact_control(page, names)
        if control is not None:
            try:
                await control.click()
                await page.wait_for_timeout(1800)
            except Exception:
                pass

    # Flourish virtualises wide data grids, so columns outside the viewport are not
    # present in the DOM until horizontally scrolled into view. Scroll every
    # horizontally-overflowing grid container to its far right before verifying.
    for _ in range(6):
        await page.evaluate(
            """
            () => {
              for (const el of document.querySelectorAll('*')) {
                if (el.scrollWidth > el.clientWidth + 80) {
                  el.scrollLeft = el.scrollWidth;
                }
              }
            }
            """
        )
        await page.wait_for_timeout(700)
        body = await page.locator("body").inner_text()
        if latest_header in body:
            await snapshot(page, diagnostics, f"{visualisation_id}-data-after-import")
            return

    await snapshot(page, diagnostics, f"{visualisation_id}-latest-header-not-visible")
    raise RuntimeError(
        f"Flourish visualisation {visualisation_id} did not show latest column '{latest_header}' after import."
    )


async def unpublished_changes_button(page: Page):
    status = page.get_by_text("Unpublished changes", exact=True)
    try:
        if not await status.count() or not await status.first.is_visible():
            return None
        row = status.first.locator("xpath=ancestor::*[.//button][1]")
        buttons = row.locator("button:visible")
        if await buttons.count() == 1:
            return buttons.first
    except Exception:
        pass
    return None


async def is_already_published(page: Page) -> bool:
    unpublished = page.get_by_text("Unpublished changes", exact=True)
    published = page.get_by_text("Published", exact=True)
    try:
        return bool(
            await published.count()
            and await published.first.is_visible()
            and not (await unpublished.count() and await unpublished.first.is_visible())
        )
    except Exception:
        return False


async def confirm_publish_dialog(page: Page, visualisation_id: int, diagnostics: Path) -> None:
    prompt = page.get_by_text("Publish this visualization?", exact=True)
    try:
        await prompt.first.wait_for(state="visible", timeout=8000)
    except Exception:
        return
    dialog = prompt.first.locator("xpath=ancestor::*[@role='dialog'][1]")
    if not await dialog.count():
        dialog = prompt.first.locator("xpath=ancestor::*[.//button][1]")
    publish = dialog.get_by_role("button", name=re.compile(r"^Publish$", re.I))
    if await publish.count() != 1:
        await snapshot(page, diagnostics, f"{visualisation_id}-publish-dialog-ambiguous")
        raise RuntimeError(f"Could not safely confirm publish for {visualisation_id}.")
    await publish.first.click()


async def republish(page: Page, visualisation_id: int, diagnostics: Path) -> str:
    control = await exact_control(page, ["Republish", "Publish changes"])
    if control is not None:
        await control.click()
        await page.wait_for_timeout(1500)
    else:
        export_control = await exact_control(page, ["Export & publish", "Export and publish"])
        if export_control is None:
            await snapshot(page, diagnostics, f"{visualisation_id}-publish-control-missing")
            raise RuntimeError(f"No Export & publish control for {visualisation_id}.")
        await export_control.click()
        await page.wait_for_timeout(1500)

        if await is_already_published(page):
            return "already_published"

        control = await exact_control(page, ["Republish", "Publish changes"])
        if control is not None:
            await control.click()
        else:
            icon = await unpublished_changes_button(page)
            if icon is None:
                await snapshot(page, diagnostics, f"{visualisation_id}-republish-control-missing")
                raise RuntimeError(f"No safe Republish control for {visualisation_id}.")
            await icon.click()

    await confirm_publish_dialog(page, visualisation_id, diagnostics)

    for _ in range(60):
        await page.wait_for_timeout(500)
        status = page.get_by_text("Unpublished changes", exact=True)
        try:
            if not await status.count() or not await status.first.is_visible():
                await snapshot(page, diagnostics, f"{visualisation_id}-after-publish")
                return "republished"
        except Exception:
            return "republished"

    await snapshot(page, diagnostics, f"{visualisation_id}-publish-timeout")
    raise RuntimeError(f"Flourish still reports unpublished changes for {visualisation_id}.")


async def run() -> int:
    args = parser().parse_args()
    races = inspect_csv(args.races, args.expected_competitors)
    leaderboard = inspect_csv(args.leaderboard, args.expected_competitors)

    if races["header"] != leaderboard["header"]:
        raise RuntimeError("Race and cumulative CSV headers do not match.")
    if races["latest_header"] != leaderboard["latest_header"]:
        raise RuntimeError("Race and cumulative CSV latest round labels do not match.")

    email = os.environ.get("FLOURISH_EMAIL", "").strip()
    password = os.environ.get("FLOURISH_PASSWORD", "")
    if not email or not password:
        raise RuntimeError("FLOURISH_EMAIL and FLOURISH_PASSWORD must be configured.")

    args.diagnostics.mkdir(parents=True, exist_ok=True)
    summary: dict[str, object] = {
        "status": "started",
        "latest_header": races["latest_header"],
        "expected_competitors": args.expected_competitors,
        "projects": {},
    }

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        context = await browser.new_context(
            locale="en-AU",
            timezone_id="Australia/Melbourne",
            viewport={"width": 1600, "height": 1200},
        )
        page = await context.new_page()
        await login(page, email, password, args.diagnostics)

        for visualisation_id, path in (
            (23536150, args.races),
            (23537908, args.leaderboard),
        ):
            await open_editor(page, visualisation_id, args.diagnostics)
            await upload_csv(
                page,
                visualisation_id,
                path,
                str(races["latest_header"]),
                args.diagnostics,
            )
            publish_status = await republish(page, visualisation_id, args.diagnostics)
            summary["projects"][str(visualisation_id)] = {
                "name": PROJECTS[visualisation_id],
                "csv": str(path),
                "rows": args.expected_competitors,
                "latest_header": races["latest_header"],
                "publish_status": publish_status,
            }

        await context.close()
        await browser.close()

    summary["status"] = "pass"
    out = Path("build/flourish-sync/sync-summary.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run()))
