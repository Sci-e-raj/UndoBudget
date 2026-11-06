#!/usr/bin/env python3
"""Plot recorded UndoBudget CSV values as standalone SVG figures (stdlib only).

python3 experiments/plot.py /path/to/collector-output
Only PASS runs are graphed. Missing and failed runs are listed on each figure.
"""

import argparse
import csv
from collections import defaultdict
from pathlib import Path
from xml.sax.saxutils import escape


COLORS = {"fail:2": "#ca3e47", "block:3": "#2563a8",
          "shared:4": "#16866b", "race:5": "#aa6b11",
          "independent:6": "#7847a5", "independent:7": "#a35185"}
LABELS = {"fail:2": "FAIL plateau", "block:3": "BLOCK refill",
          "shared:4": "Shared fork", "race:5": "Concurrent",
          "independent:6": "Independent 6",
          "independent:7": "Independent 7"}
COUNTER_COLORS = {"allowed": "#16866b", "blocked": "#2563a8",
                  "refused": "#ca3e47"}


def read_data(directory):
    with (directory / "runs.csv").open(newline="") as stream:
        runs = list(csv.DictReader(stream))
    with (directory / "observations.csv").open(newline="") as stream:
        observations = list(csv.DictReader(stream))
    valid = {(int(run["cpus"]), run["scenario"]) for run in runs
             if run["status"] == "PASS"}
    series = defaultdict(list)
    for row in observations:
        cpu = int(row["cpus"])
        if (cpu, row["scenario"]) not in valid or not row["elapsed_ticks"]:
            continue
        key = f"{row['scenario']}:{row['gid']}"
        for field in ("elapsed_ticks", "completed", "remaining", "allowed",
                      "blocked", "refused"):
            row[field] = int(row[field])
        series[(cpu, key)].append(row)
    return runs, series


def missing_note(runs):
    missing = [f"CPU {run['cpus']} {run['scenario']}: {run['status']}"
               for run in runs if run["status"] != "PASS"]
    return "All selected experiments passed." if not missing else \
           "Missing from plots: " + "; ".join(missing)


def svg_start(width, height, title, subtitle):
    return [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}">',
            '<rect width="100%" height="100%" fill="#f8fafc"/>',
            '<style>text{font-family:Arial,Helvetica,sans-serif;fill:#182433}'
            '.title{font-size:25px;font-weight:bold}.sub{font-size:13px;fill:#475569}'
            '.panel{font-size:18px;font-weight:bold}.tick{font-size:12px;fill:#475569}'
            '.legend{font-size:13px}.note{font-size:12px;fill:#6b3b3b}'
            '</style>',
            f'<text x="60" y="42" class="title">{escape(title)}</text>',
            f'<text x="60" y="66" class="sub">{escape(subtitle)}</text>']


def text_at(out, x, y, value, css="tick", anchor=None):
    anchor_attr = f' text-anchor="{anchor}"' if anchor else ""
    out.append(f'<text x="{x:.1f}" y="{y:.1f}" class="{css}"'
               f'{anchor_attr}>{escape(str(value))}</text>')


def footer(out, runs, y, width):
    note = missing_note(runs)
    # Wrap long lists rather than clipping the right edge.
    words, lines, line = note.split(), [], ""
    for word in words:
        if len(line) + len(word) > 125:
            lines.append(line)
            line = word
        else:
            line = (line + " " + word).strip()
    if line:
        lines.append(line)
    for offset, part in enumerate(lines):
        text_at(out, 60, y + offset * 17, part, "note")


def axes(out, x, y, width, height, xmax, ymax, ylabel):
    for fraction in (0, .25, .5, .75, 1):
        gy = y + height * (1 - fraction)
        out.append(f'<line x1="{x}" y1="{gy:.1f}" x2="{x+width}" '
                   f'y2="{gy:.1f}" stroke="#dbe2e9"/>')
        text_at(out, x - 10, gy + 4, round(ymax * fraction), anchor="end")
        gx = x + width * fraction
        text_at(out, gx, y + height + 20, round(xmax * fraction), anchor="middle")
    out.append(f'<line x1="{x}" y1="{y}" x2="{x}" y2="{y+height}" '
               'stroke="#334155"/>')
    out.append(f'<line x1="{x}" y1="{y+height}" x2="{x+width}" '
               f'y2="{y+height}" stroke="#334155"/>')
    text_at(out, x + width / 2, y + height + 40, "Elapsed xv6 ticks",
            anchor="middle")
    text_at(out, x, y - 11, ylabel)


def step_path(rows, field, x, y, width, height, xmax, ymax):
    ordered = sorted(rows, key=lambda row: row["elapsed_ticks"])
    points = []
    for row in ordered:
        px = x + width * row["elapsed_ticks"] / xmax
        py = y + height * (1 - row[field] / ymax)
        if points:
            points.append((px, points[-1][1]))
        points.append((px, py))
    return " ".join(f"{px:.1f},{py:.1f}" for px, py in points)


def line_figure(path, runs, series, title, field, selected=None):
    width, height = 1280, 810
    out = svg_start(width, height, title,
                    "Observed guest ticks and kernel budgetstat snapshots; "
                    "lines connect discrete observations.")
    for panel, cpu in enumerate((1, 3)):
        chosen = [(key, rows) for (count, key), rows in series.items()
                  if count == cpu and (selected is None or key in selected)]
        chosen.sort(key=lambda pair: list(COLORS).index(pair[0]))
        top = 110 + panel * 320
        text_at(out, 80, top, f"CPUS={cpu}", "panel")
        if not chosen:
            text_at(out, 110, top + 110, "MISSING — no verified measurements",
                    "note")
            continue
        xmax = max(1, max(row["elapsed_ticks"] for _, rows in chosen
                          for row in rows))
        ymax = max(1, max(row[field] for _, rows in chosen for row in rows))
        x, y, plot_width, plot_height = 100, top + 35, 780, 205
        axes(out, x, y, plot_width, plot_height, xmax, ymax,
             "Completed deletions" if field == "completed" else
             "Remaining budget units")
        for index, (key, rows) in enumerate(chosen):
            color = COLORS[key]
            path_data = step_path(rows, field, x, y, plot_width, plot_height,
                                  xmax, ymax)
            out.append(f'<polyline points="{path_data}" fill="none" '
                       f'stroke="{color}" stroke-width="2.5"/>')
            legend_y = y + 12 + index * 28
            out.append(f'<line x1="925" y1="{legend_y-4}" x2="950" '
                       f'y2="{legend_y-4}" stroke="{color}" stroke-width="3"/>')
            text_at(out, 960, legend_y, LABELS[key], "legend")
    footer(out, runs, 757, width)
    path.write_text("\n".join(out + ["</svg>"]) + "\n")


def counter_figure(path, runs, series):
    width, height = 1280, 810
    out = svg_start(width, height, "Final budget counter breakdown",
                    "ALLOWED=successful deductions; BLOCKED=wait registrations; "
                    "REFUSED=terminal charge refusals.")
    for panel, cpu in enumerate((1, 3)):
        chosen = [(key, next(row for row in rows if row["event"] == "end"))
                  for (count, key), rows in series.items() if count == cpu]
        chosen.sort(key=lambda pair: list(COLORS).index(pair[0]))
        top = 115 + panel * 315
        text_at(out, 80, top, f"CPUS={cpu}", "panel")
        if not chosen:
            text_at(out, 100, top + 90, "MISSING — no verified measurements",
                    "note")
            continue
        ymax = max(1, max(row[counter] for _, row in chosen
                          for counter in COUNTER_COLORS))
        x, y, w, h = 100, top + 35, 900, 190
        for fraction in (0, .5, 1):
            gy = y + h * (1 - fraction)
            out.append(f'<line x1="{x}" y1="{gy:.1f}" x2="{x+w}" '
                       f'y2="{gy:.1f}" stroke="#dbe2e9"/>')
            text_at(out, x - 10, gy + 4, round(ymax * fraction), anchor="end")
        slot = w / len(chosen)
        for index, (key, row) in enumerate(chosen):
            for offset, (counter, color) in enumerate(COUNTER_COLORS.items()):
                value = row[counter]
                bh = h * value / ymax
                bx = x + index * slot + slot * (.13 + offset * .25)
                out.append(f'<rect x="{bx:.1f}" y="{y+h-bh:.1f}" '
                           f'width="{slot*.18:.1f}" height="{bh:.1f}" '
                           f'fill="{color}"/>')
                text_at(out, bx + slot * .09,
                        max(y + 12, y + h - bh - 5), value, anchor="middle")
            text_at(out, x + (index + .5) * slot, y + h + 19,
                    LABELS[key], anchor="middle")
    for index, (counter, color) in enumerate(COUNTER_COLORS.items()):
        out.append(f'<rect x="1030" y="{165 + index*27}" width="13" '
                   f'height="13" fill="{color}"/>')
        text_at(out, 1050, 177 + index * 27, counter.upper(), "legend")
    footer(out, runs, 754, width)
    path.write_text("\n".join(out + ["</svg>"]) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("data_dir", type=Path)
    parser.add_argument("--output", type=Path,
                        help="figure directory (default: DATA_DIR/figures)")
    args = parser.parse_args()
    runs, series = read_data(args.data_dir)
    output = args.output or args.data_dir / "figures"
    output.mkdir(parents=True, exist_ok=True)
    line_figure(output / "completed_vs_time.svg", runs, series,
                "Completed deletions vs time", "completed")
    line_figure(output / "remaining_budget.svg", runs, series,
                "Remaining group budget vs time", "remaining")
    counter_figure(output / "counter_breakdown.svg", runs, series)
    line_figure(output / "fail_block_comparison.svg", runs, series,
                "FAIL deletion plateau vs BLOCK refill staircase", "completed",
                selected={"fail:2", "block:3"})
    print(f"Saved 4 SVG figures in {output}")


if __name__ == "__main__":
    main()
