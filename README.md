# WC2026 Dashboard

Live World Cup 2026 dashboard at **https://wc2026.bilbofort.site/**

## Stack

- **Backend**: Flask (Python) — `/home/bilbo/wc2026/server.py`
- **Frontend**: Single-page HTML/CSS/JS — `/home/bilbo/wc2026/static/index.html`
- **Data**: ESPN public API (`site.api.espn.com`) + Google News RSS
- **Tunnel**: Cloudflare Tunnel → `monitor.bilbofort.site` config

## Features

| Tab | Description |
|---|---|
| Matches | Live scores, schedule, team filter (click any team name) |
| Bracket | Knockout stage tree (round of 32 → final) |
| Standings | Group tables (A–L) |
| Teams | All 48 teams with flags |
| Stats | Tournament stats + top scorers/assists/cards |

### Special features
- **News ticker** — auto-scrolling Google News headlines, touch-drag enabled
- **Team filter** — click any team name in a match card or standings table to filter schedule
- **Live polling** — matches refresh every 30 min, news every 15 min
- **Goal animations** — confetti on new goals
- **PWA-ready** — responsive, mobile-friendly

## API Endpoints

All rate-limited, ESPN data cached server-side:

| Endpoint | Rate Limit | Source |
|---|---|---|
| `/api/matches` | 120/min | ESPN scoreboard |
| `/api/live` | 120/min | ESPN scoreboard (live only) |
| `/api/standings` | 60/min | Static JSON |
| `/api/teams` | 60/min | Static JSON |
| `/api/bracket` | 30/min | ESPN + hardcoded later rounds |
| `/api/stats` | 60/min | Computed from match data |
| `/api/news` | 10/min | Google News RSS |

## Running

```bash
# Start
cd /home/bilbo/wc2026
/home/bilbo/.hermes/hermes-agent/venv/bin/python3 server.py

# Server listens on localhost:8895
# Cloudflare Tunnel exposes it publicly
```

## Security

- CSP, HSTS, X-Frame-Options, XSS protection
- Rate limiting on all API endpoints
- Cloudflare hides origin server headers
- No sensitive files exposed

## Cron Jobs

| Job | Schedule | Purpose |
|---|---|---|
| WC2026 Health Watchdog | Every 10 min | Checks server + API + tunnel; silent when healthy |

## Notes

- ESPN API is unofficial/public — personal use only
- Tournament: June 11 – July 19, 2026
- Match times displayed in MYT (UTC+8)
- SSL via Cloudflare, no cert management needed
