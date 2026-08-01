from __future__ import annotations

import csv
import html
from pathlib import Path
from typing import Sequence


def _format_change(value: int) -> str:
    return f"{value:+d}" if value else "+0"


def _format_rank(value: int, previous: int | None = None) -> str:
    if previous is not None and value == previous:
        return f"={value}"
    return str(value)


def _plain_table(headers: Sequence[str], rows: Sequence[Sequence[object]]) -> str:
    string_rows = [[str(value) for value in row] for row in rows]
    widths = [len(header) for header in headers]
    for row in string_rows:
        for index, value in enumerate(row):
            widths[index] = max(widths[index], len(value))
    rule = "+-" + "-+-".join("-" * width for width in widths) + "-+"
    header_line = "| " + " | ".join(header.ljust(widths[index]) for index, header in enumerate(headers)) + " |"
    lines = [rule, header_line, rule]
    for row in string_rows:
        lines.append("| " + " | ".join(value.ljust(widths[index]) for index, value in enumerate(row)) + " |")
    lines.append(rule)
    return "\n".join(lines)


def _html_table(headers: Sequence[str], rows: Sequence[Sequence[object]], css_class: str = "") -> str:
    heading = "".join(f"<th>{html.escape(str(value))}</th>" for value in headers)
    body = []
    for row in rows:
        body.append(
            "<tr>" + "".join(f"<td>{html.escape(str(value))}</td>" for value in row) + "</tr>"
        )
    return f'<table class="{html.escape(css_class)}"><thead><tr>{heading}</tr></thead><tbody>{"".join(body)}</tbody></table>'


def _podium_names(entries: Sequence[dict[str, object]]) -> str:
    if not entries:
        return ""
    return " / ".join(str(item["team"]) for item in entries)


def render_teams_text(payload: dict[str, object], graph_url: str) -> str:
    metadata = payload["metadata"]
    assert isinstance(metadata, dict)
    race = metadata["race"]
    round_number = metadata["round"]

    race_rows = [
        [entry["rank"], entry["team"], entry["manager"], entry["points"]]
        for entry in payload["race_top"]  # type: ignore[index]
    ]
    overall_rows = [
        [entry["rank"], entry["team"], entry["manager"], entry["points"]]
        for entry in payload["overall_top"]  # type: ignore[index]
    ]
    tally_rows = [
        [
            entry["team"],
            entry["manager"],
            f'{entry["first"]} ({_format_change(int(entry["first_change"]))})',
            f'{entry["second"]} ({_format_change(int(entry["second_change"]))})',
            f'{entry["third"]} ({_format_change(int(entry["third_change"]))})',
            f'{entry["total"]} ({_format_change(int(entry["total_change"]))})',
        ]
        for entry in payload["podium_tally"]  # type: ignore[index]
    ]
    podium_rows = [
        [
            f'{entry["race"]} - Race {int(entry["round"]):02d}',
            _podium_names(entry["first"]),
            _podium_names(entry["second"]),
            _podium_names(entry["third"]),
        ]
        for entry in payload["podium_by_race"]  # type: ignore[index]
    ]
    mover_rows = [
        [entry["team"], entry["manager"], _format_change(int(entry["movement"]))]
        for entry in payload["biggest_movers"]  # type: ignore[index]
    ]
    drop_rows = [
        [entry["team"], entry["manager"], _format_change(int(entry["movement"]))]
        for entry in payload["biggest_drops"]  # type: ignore[index]
    ]

    sections = [
        f"F1 SAVI LEAGUE / ROUND {round_number:02d} / {str(race).upper()}",
        "",
        f"{race} race top 10",
        _plain_table(["Pos", "Team", "Manager", "Pts"], race_rows),
        "",
        f"Overall top 10 after {race}",
        _plain_table(["Pos", "Team", "Manager", "Pts"], overall_rows),
        "",
        f"Podium tally after Race {round_number:02d}",
        _plain_table(["Team name", "Manager", "🥇 1st", "🥈 2nd", "🥉 3rd", "🏅 Total"], tally_rows),
        "",
        "Podium by race",
        _plain_table(["Race", "🥇 1st", "🥈 2nd", "🥉 3rd"], podium_rows),
        "",
        "Biggest movers",
        _plain_table(["Team", "Manager", "Movement"], mover_rows),
        "",
        "Biggest drops",
        _plain_table(["Team", "Manager", "Movement"], drop_rows),
        "",
        "Interactive graphs updated",
        graph_url,
    ]
    return "\n".join(sections).strip() + "\n"


def render_teams_html(payload: dict[str, object], graph_url: str) -> str:
    metadata = payload["metadata"]
    assert isinstance(metadata, dict)
    race = str(metadata["race"])
    round_number = int(metadata["round"])

    def ranked_rows(key: str) -> list[list[object]]:
        return [
            [entry["rank"], entry["team"], entry["manager"], entry["points"]]
            for entry in payload[key]  # type: ignore[index]
        ]

    tally_rows = [
        [
            entry["team"],
            entry["manager"],
            f'{entry["first"]} ({_format_change(int(entry["first_change"]))})',
            f'{entry["second"]} ({_format_change(int(entry["second_change"]))})',
            f'{entry["third"]} ({_format_change(int(entry["third_change"]))})',
            f'{entry["total"]} ({_format_change(int(entry["total_change"]))})',
        ]
        for entry in payload["podium_tally"]  # type: ignore[index]
    ]
    podium_rows = [
        [
            f'{entry["race"]} - Race {int(entry["round"]):02d}',
            _podium_names(entry["first"]),
            _podium_names(entry["second"]),
            _podium_names(entry["third"]),
        ]
        for entry in payload["podium_by_race"]  # type: ignore[index]
    ]
    mover_rows = [
        [entry["team"], entry["manager"], _format_change(int(entry["movement"]))]
        for entry in payload["biggest_movers"]  # type: ignore[index]
    ]
    drop_rows = [
        [entry["team"], entry["manager"], _format_change(int(entry["movement"]))]
        for entry in payload["biggest_drops"]  # type: ignore[index]
    ]

    sections = [
        ("race", f"{race} race top 10", _html_table(["Pos", "Team", "Manager", "Pts"], ranked_rows("race_top"))),
        ("overall", f"Overall top 10 after {race}", _html_table(["Pos", "Team", "Manager", "Pts"], ranked_rows("overall_top"))),
        ("tally", f"Podium tally after Race {round_number:02d}", _html_table(["Team name", "Manager", "🥇 1st", "🥈 2nd", "🥉 3rd", "🏅 Total"], tally_rows)),
        ("podiums", "Podium by race", _html_table(["Race", "🥇 1st", "🥈 2nd", "🥉 3rd"], podium_rows)),
        ("movers", "Biggest movers", _html_table(["Team", "Manager", "Movement"], mover_rows)),
        ("drops", "Biggest drops", _html_table(["Team", "Manager", "Movement"], drop_rows)),
    ]
    section_html = []
    for identifier, title, table in sections:
        section_html.append(
            f'''<section id="{identifier}" class="copy-block">
<div class="section-heading"><h2>{html.escape(title)}</h2><button type="button" data-copy-target="{identifier}">Copy section</button></div>
{table}
</section>'''
        )
    all_sections = "\n".join(section_html)
    escaped_graph_url = html.escape(graph_url, quote=True)

    return f'''<!doctype html>
<html lang="en-AU">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow, noarchive">
<title>F1 SAVI League / Round {round_number:02d} / {html.escape(race)}</title>
<style>
:root{{--green:#89c925;--grey:#373a36;--ink:#1c1b1c;--paper:#fff;--soft:#f0f2f0}}
*{{box-sizing:border-box}} body{{margin:0;background:var(--soft);color:var(--ink);font-family:Arial,Helvetica,sans-serif;line-height:1.35}}
main{{width:min(1100px,calc(100% - 32px));margin:28px auto 64px}} header{{background:var(--grey);color:#fff;padding:28px;border-top:8px solid var(--green)}}
h1{{margin:0;font-size:clamp(1.8rem,4vw,3rem)}} .eyebrow{{color:var(--green);font-weight:800;letter-spacing:.08em;text-transform:uppercase}}
.toolbar{{display:flex;gap:10px;flex-wrap:wrap;margin:16px 0}} button,.button{{appearance:none;border:0;background:var(--green);color:var(--ink);font-weight:800;padding:10px 14px;cursor:pointer;text-decoration:none;display:inline-block}}
button:hover,.button:hover{{filter:brightness(.94)}} section{{background:var(--paper);padding:18px;margin:14px 0;border:1px solid #d3d7d3}}
.section-heading{{display:flex;justify-content:space-between;gap:12px;align-items:center}} h2{{font-size:1.05rem;margin:0 0 10px}}
table{{border-collapse:collapse;width:100%;font-size:.9rem}} th,td{{border:1px solid #bfc4bf;padding:6px 8px;text-align:left;vertical-align:top}} th{{background:#e9ece9;font-weight:800}} td:first-child,th:first-child{{white-space:nowrap}}
.status{{min-height:1.4em;font-weight:700}} .note{{background:#e8f5d6;border-left:5px solid var(--green);padding:12px 14px}} @media(max-width:700px){{section{{overflow:auto}}table{{min-width:680px}}}}
</style>
</head>
<body>
<main>
<header id="all-content">
<div class="eyebrow">F1 SAVI League</div>
<h1>Round {round_number:02d} / {html.escape(race)}</h1>
<p>Validated race pack prepared for Microsoft Teams and Flourish.</p>
</header>
<div class="toolbar">
<button type="button" data-copy-target="teams-content">Copy complete Teams update</button>
<a class="button" href="Teams_Update.txt" download>Download plain text</a>
<a class="button" href="race_data.json" download>Download race data</a>
</div>
<p id="copy-status" class="status" aria-live="polite"></p>
<div id="teams-content">
{all_sections}
<section id="graphs" class="copy-block"><h2>Interactive graphs updated</h2><p><a href="{escaped_graph_url}">{escaped_graph_url}</a></p></section>
</div>
<p class="note">Paste into Teams using standard paste. The copy action includes both formatted HTML and plain text.</p>
</main>
<script>
const statusEl=document.getElementById('copy-status');
function plainText(node){{return node.innerText.replace(/\n{{3,}}/g,'\n\n').trim();}}
async function copyNode(node){{
 const text=plainText(node); const rich=node.innerHTML;
 if(navigator.clipboard && window.ClipboardItem){{
  const item=new ClipboardItem({{'text/html':new Blob([rich],{{type:'text/html'}}),'text/plain':new Blob([text],{{type:'text/plain'}})}});
  await navigator.clipboard.write([item]);
 }} else if(navigator.clipboard){{await navigator.clipboard.writeText(text);}}
 else{{const area=document.createElement('textarea');area.value=text;document.body.appendChild(area);area.select();document.execCommand('copy');area.remove();}}
}}
document.querySelectorAll('[data-copy-target]').forEach(button=>button.addEventListener('click',async()=>{{
 const target=document.getElementById(button.dataset.copyTarget);
 try{{await copyNode(target);statusEl.textContent='Copied. Paste directly into Teams.';}}
 catch(error){{statusEl.textContent='Copy failed. Open Teams_Update.txt and copy from there.';console.error(error);}}
}}));
</script>
</body>
</html>
'''


def write_csv_table(path: Path, headers: Sequence[str], rows: Sequence[Sequence[object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(headers)
        writer.writerows(rows)
