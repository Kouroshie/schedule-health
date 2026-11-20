# schedule-health

A small Python tool that turns a construction schedule export into an early-warning report.

It reads activities, durations and logic links, runs the Critical Path Method, and checks
whether each utility will be ready by the date the equipment team needs it. The results
are written as CSV files that a Power BI or Tableau dashboard can refresh from, plus a
short text health report for leadership.

## What it does

1. **Critical Path Method**: forward pass, backward pass, total float, free float and the
   critical path. Supports finish-to-start, start-to-start, finish-to-finish and
   start-to-finish links with lags or leads.
2. **Need-date alignment**: compares each "utility available" milestone with the date it is
   needed and labels the margin `CONFLICT` (late), `WATCH` (under 10 days) or `OK`.
3. **Baseline slip**: forecast finish vs. baseline finish for every activity.
4. **Schedule quality checks**: a simplified subset of the DCMA 14-point assessment
   (missing logic, leads, lags, relationship types, high float, high duration, negative float).

## Run it

```
pip install -r requirements.txt
python schedule_health.py sample_infra_schedule.csv need_dates.csv 2026-01-05
```

## Inputs

| File | Columns |
|---|---|
| `sample_infra_schedule.csv` | `id, name, area, duration, predecessors, baseline_finish` |
| `need_dates.csv` | `utility_milestone, need_date, needed_by` |

Link syntax in `predecessors` (separated by `;`): `A130` (finish-to-start), `A110SS+15`
(start-to-start, 15-day lag), `A420FS+2`, `A500FF-3` (3-day lead).

## Outputs

| File | Content |
|---|---|
| `out_activities.csv` | early and late dates, total and free float, critical flag, slip vs. baseline |
| `out_need_date_alignment.csv` | forecast ready date vs. need date, margin, status |
| `out_quality_checks.csv` | quality checks with targets |
| `out_health_report.txt` | short text report |

## Sample result

The sample is an invented industrial-facility utility schedule (cooling water, ultrapure
water, bulk gas, exhaust, electrical) feeding one equipment hook-up.

```
Critical path: A100 > A200 > A210 > A220 > A230 > A610 > A620 > A630

Utility readiness vs need dates (worst first):
  [CONFLICT] A230 UPW available to fab (milestone): ready 2026-04-01, needed 2026-03-25, margin -7 d
  [WATCH   ] A330 Bulk gas available to fab (milestone): ready 2026-03-03, needed 2026-03-05, margin +2 d
  [WATCH   ] A140 PCW available to fab (milestone): ready 2026-02-24, needed 2026-03-01, margin +5 d
  [WATCH   ] A510 Electrical available to fab (milestone): ready 2026-02-19, needed 2026-02-28, margin +9 d
  [OK      ] A420 Exhaust available to fab (milestone): ready 2026-03-06, needed 2026-03-20, margin +14 d
```

## Limits

- Durations are calendar days. Primavera P6 and MS Project use work calendars, which change
  the date math but not the logic.
- No resources or date constraints yet.
- Sample data is invented for illustration.

Planned next steps: read Primavera P6 XER exports directly, add work calendars, and track
float erosion between updates.

## License

MIT
