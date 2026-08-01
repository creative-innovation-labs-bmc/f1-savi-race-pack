from __future__ import annotations

import asyncio
from typing import Any

import fantasygp_update as update
from f1_savi.models import RacePackError


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


update.ajax = jquery_ajax


if __name__ == "__main__":
    raise SystemExit(asyncio.run(update.main()))
