from __future__ import annotations

import asyncio
from typing import Any
from urllib.parse import parse_qs

import fantasygp_update as update
from f1_savi.fantasygp import FantasyGPRow, combine_league_pages, parse_integer
from f1_savi.models import RacePackError


def request_matches(response, *, race: int, offset: int) -> bool:
    if "admin-ajax.php" not in response.url or response.request.method != "POST":
        return False
    parameters = parse_qs(response.request.post_data or "", keep_blank_values=True)
    return (
        parameters.get("action") == ["fetchLeague"]
        and parameters.get("leaguerace") == [str(race)]
        and parameters.get("leagueoffset") == [str(offset)]
    )


async def jquery_ajax(
    page,
    action: str,
    params: dict[str, object],
    *,
    method: str = "POST",
) -> dict[str, Any]:
    result = await page.evaluate(
        """
        ({action, params, method}) => new Promise((resolve) => {
          const config = window.MyAjax;
          if (!config || !config.ajaxurl || !config.security || !window.jQuery) {
            resolve({status: 0, ok: false, text: 'FantasyGP AJAX configuration is unavailable'});
            return;
          }
          const data = {action, security: config.security, ...params};
          window.jQuery.ajax({
            url: config.ajaxurl,
            method,
            data,
            dataType: 'text',
            success: (payload, _textStatus, xhr) => resolve({
              status: xhr.status,
              ok: true,
              text: typeof payload === 'string' ? payload : JSON.stringify(payload)
            }),
            error: (xhr, textStatus, errorThrown) => resolve({
              status: xhr.status,
              ok: false,
              text: xhr.responseText || errorThrown || textStatus
            })
          });
        })
        """,
        {"action": action, "params": params, "method": method},
    )
    if not result.get("ok"):
        raise RacePackError(
            f"FantasyGP action {action!r} returned HTTP {result.get('status')}: "
            f"{str(result.get('text'))[:300]}"
        )
    return update.json_response(str(result.get("text", "")), action=action)


async def capture_site_page(page, *, league_id: str, race: int, offset: int) -> dict[str, Any]:
    async with page.expect_response(
        lambda response: request_matches(response, race=race, offset=offset),
        timeout=60_000,
    ) as pending:
        if offset == 0:
            await page.evaluate(
                """
                ({leagueId, race}) => {
                  const select = window.jQuery('#raceselect2');
                  if (!select.length) throw new Error('FantasyGP race selector is missing');
                  if (!select.find(`option[value="${race}"]`).length) {
                    select.append(window.jQuery('<option>', {value: String(race), text: String(race)}));
                  }
                  select.attr('data-league', String(leagueId));
                  select.val(String(race));
                  select.trigger('change');
                }
                """,
                {"leagueId": league_id, "race": race},
            )
        else:
            await page.evaluate(
                """
                ({leagueId, race, offset}) => {
                  const candidates = [...document.querySelectorAll('.pageitnext')];
                  const control = candidates.find(element =>
                    String(element.dataset.league) === String(leagueId) &&
                    String(element.dataset.race) === String(race) &&
                    String(element.dataset.offset) === String(offset)
                  );
                  if (!control) throw new Error(`FantasyGP next-page control is missing for offset ${offset}`);
                  window.jQuery(control).trigger('click');
                }
                """,
                {"leagueId": league_id, "race": race, "offset": offset},
            )

    response = await pending.value
    text = await response.text()
    if response.status != 200:
        raise RacePackError(
            f"FantasyGP site-generated fetchLeague request returned HTTP {response.status}: {text[:300]}"
        )
    return update.json_response(text, action="fetchLeague")


async def site_fetch_pages(
    page,
    *,
    league_id: str,
    race: int,
    expected_competitors: int,
) -> tuple[list[dict[str, Any]], tuple[FantasyGPRow, ...]]:
    await page.wait_for_function(
        "() => window.jQuery && document.querySelector('#raceselect2')",
        timeout=60_000,
    )

    pages: list[dict[str, Any]] = []
    offset = 0
    seen_offsets: set[int] = set()
    while True:
        if offset in seen_offsets:
            raise RacePackError(f"FantasyGP pagination repeated offset {offset}.")
        seen_offsets.add(offset)

        payload = await capture_site_page(
            page,
            league_id=league_id,
            race=race,
            offset=offset,
        )
        pages.append(payload)

        howmany = parse_integer(payload.get("howmany", 0), field="howmany")
        total = parse_integer(payload.get("total", 0), field="total")
        collected = sum(parse_integer(item.get("howmany", 0), field="howmany") for item in pages)
        if collected >= total:
            break
        if howmany <= 0:
            raise RacePackError(
                f"FantasyGP pagination stopped after {collected} of {total} competitors."
            )

        next_offset = parse_integer(payload.get("newoffset", offset + howmany), field="newoffset")
        if next_offset <= offset:
            next_offset = offset + howmany

        await page.wait_for_function(
            """
            ({leagueId, race, offset}) => [...document.querySelectorAll('.pageitnext')].some(element =>
              String(element.dataset.league) === String(leagueId) &&
              String(element.dataset.race) === String(race) &&
              String(element.dataset.offset) === String(offset)
            )
            """,
            arg={"leagueId": league_id, "race": race, "offset": next_offset},
            timeout=30_000,
        )
        offset = next_offset
        if len(pages) > 20:
            raise RacePackError("FantasyGP pagination exceeded 20 pages.")

    rows = combine_league_pages(pages, expected_competitors=expected_competitors)
    return pages, rows


update.ajax = jquery_ajax
update.fetch_pages = site_fetch_pages


if __name__ == "__main__":
    raise SystemExit(asyncio.run(update.main()))
