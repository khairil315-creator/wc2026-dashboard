#!/usr/bin/env python3
"""World Cup 2026 Dashboard — static standings + ESPN match schedule."""

import json
import os
import time
import threading
from flask import Flask, jsonify, send_from_directory
import requests

app = Flask(__name__, static_folder='static', static_url_path='')

# ── Security Headers ────────────────────────────────────────────────────────
@app.after_request
def add_security_headers(response):
    response.headers['Server'] = ''  # Don't advertise tech stack
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'SAMEORIGIN'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
    response.headers['Permissions-Policy'] = 'camera=(), microphone=(), geolocation=(), interest-cohort=()'
    # CSP: allow inline scripts/styles (single-file app), GA, flagcdn, wikimedia
    response.headers['Content-Security-Policy'] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' https://www.googletagmanager.com; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data: https://flagcdn.com https://upload.wikimedia.org; "
        "connect-src 'self' https://www.google-analytics.com; "
        "frame-ancestors 'none'; "
        "base-uri 'self'; "
        "form-action 'self'"
    )
    # Cache control for API routes
    if response.content_type == 'application/json':
        response.headers['Cache-Control'] = 'no-store'
    return response

# ── Rate Limiter ────────────────────────────────────────────────────────────
_rate_limits = {}
_rate_limit_lock = threading.Lock()

def rate_limit(max_requests=60, window=60):
    """Simple in-memory rate limiter (max_requests per window seconds)."""
    def decorator(f):
        from functools import wraps
        @wraps(f)
        def wrapper(*args, **kwargs):
            now = time.time()
            key = f.__name__
            with _rate_limit_lock:
                timestamps = _rate_limits.get(key, [])
                timestamps = [t for t in timestamps if now - t < window]
                if len(timestamps) >= max_requests:
                    return jsonify({'error': 'Too many requests', 'retry_after': window}), 429
                timestamps.append(now)
                _rate_limits[key] = timestamps
            return f(*args, **kwargs)
        return wrapper
    return decorator

# ── Error Handlers ──────────────────────────────────────────────────────────
@app.errorhandler(404)
def not_found(e):
    return jsonify({'error': 'Not found'}), 404

@app.errorhandler(500)
def server_error(e):
    return jsonify({'error': 'Internal server error'}), 500

# ── Static data from GitHub repo ────────────────────────────────────────────
DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')

def load_json(filename):
    with open(os.path.join(DATA_DIR, filename)) as f:
        return json.load(f)

STANDINGS_DATA = load_json('standings.json')

# ── Team name → country code mapping for flags ──────────────────────────────
TEAM_CODES = {
    'Algeria': 'dz', 'Argentina': 'ar', 'Australia': 'au', 'Austria': 'at',
    'Belgium': 'be', 'Bosnia-Herzegovina': 'ba', 'Brazil': 'br', 'Canada': 'ca',
    'Cape Verde': 'cv', 'Colombia': 'co', 'Congo DR': 'cd', 'Croatia': 'hr',
    'Curaçao': 'cw', 'Czechia': 'cz', 'Ecuador': 'ec', 'Egypt': 'eg',
    'England': 'gb-eng', 'France': 'fr', 'Germany': 'de', 'Ghana': 'gh',
    'Haiti': 'ht', 'Iran': 'ir', 'Iraq': 'iq', 'Ivory Coast': 'ci',
    'Japan': 'jp', 'Jordan': 'jo', 'Mexico': 'mx', 'Morocco': 'ma',
    'Netherlands': 'nl', 'New Zealand': 'nz', 'Norway': 'no', 'Panama': 'pa',
    'Paraguay': 'py', 'Portugal': 'pt', 'Qatar': 'qa', 'Saudi Arabia': 'sa',
    'Scotland': 'gb-sct', 'Senegal': 'sn', 'South Africa': 'za', 'South Korea': 'kr',
    'Spain': 'es', 'Sweden': 'se', 'Switzerland': 'ch', 'Tunisia': 'tn',
    'Türkiye': 'tr', 'United States': 'us', 'Uruguay': 'uy', 'Uzbekistan': 'uz',
}

def flag_url(name):
    code = TEAM_CODES.get(name, 'xx').lower()
    return f"https://flagcdn.com/w80/{code}.png"

# ── ESPN API for match schedule ─────────────────────────────────────────────
ESPN_BASE = "https://site.api.espn.com/apis/site/v2/sports/soccer/fifa.world"
cache = {}
cache_lock = threading.Lock()

def fetch_espn(path, ttl=30):
    now = time.time()
    with cache_lock:
        if path in cache and (now - cache[path]['ts']) < ttl:
            return cache[path]['data']
    url = f"{ESPN_BASE}/{path}"
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        with cache_lock:
            cache[path] = {'data': data, 'ts': now}
        return data
    except Exception as e:
        with cache_lock:
            if path in cache:
                return cache[path]['data']
        return {"error": str(e)}

# ── API Endpoints ──────────────────────────────────────────────────────────

@app.route('/api/matches')
@rate_limit(120, 60)
def api_matches():
    """Matches from ESPN, grouped by date."""
    import re
    placeholder_re = re.compile(
        r'(Group\s+[A-Z]\s+(Winner|2nd\s+Place)|'
        r'Round\s+of\s+(16|32)\s+\d+\s+Winner|'
        r'Third\s+Place\s+Group)', re.IGNORECASE
    )

    data = fetch_espn("scoreboard?dates=20260601-20260801")
    events = data.get('events', [])
    matches = []
    for event in events:
        comps = event.get('competitions', [])
        if not comps:
            continue
        comp = comps[0]
        competitors = comp.get('competitors', [])
        home = competitors[0] if len(competitors) > 0 else {}
        away = competitors[1] if len(competitors) > 1 else {}

        h_name = home.get('team', {}).get('displayName', home.get('team', {}).get('name', '?'))
        a_name = away.get('team', {}).get('displayName', away.get('team', {}).get('name', '?'))
        if placeholder_re.search(h_name) or placeholder_re.search(a_name):
            continue

        status = event.get('status', {}).get('type', {})

        # Build team ID → name mapping for detail events
        team_id_map = {
            home.get('id', ''): h_name,
            away.get('id', ''): a_name,
        }

        # Extract key events (goals, cards)
        key_events = []
        for detail in comp.get('details', []):
            evt_type = detail.get('type', {}).get('text', '')
            is_goal = detail.get('scoringPlay', False)
            is_yellow = detail.get('yellowCard', False)
            is_red = detail.get('redCard', False)
            if not (is_goal or is_yellow or is_red):
                continue
            icon = '⚽' if is_goal else ('🟥' if is_red else '🟨')
            athlete = detail.get('athletesInvolved', [{}])[0] if detail.get('athletesInvolved') else {}
            key_events.append({
                'icon': icon,
                'type': evt_type,
                'minute': detail.get('clock', {}).get('displayValue', ''),
                'player': athlete.get('shortName') or athlete.get('displayName', ''),
                'playerId': athlete.get('id', ''),
                'headshot': athlete.get('headshot', ''),
                'team': team_id_map.get(detail.get('team', {}).get('id', ''), ''),
                'ownGoal': detail.get('ownGoal', False),
                'penalty': detail.get('penaltyKick', False),
            })

        matches.append({
            'id': event.get('id'),
            'name': event.get('name', ''),
            'shortName': event.get('shortName', ''),
            'date': event.get('date', ''),
            'status': status.get('name', ''),
            'statusDetail': status.get('detail', ''),
            'statusCompleted': status.get('completed', False),
            'period': event.get('status', {}).get('period', 0),
            'clock': event.get('status', {}).get('displayClock', ''),
            'venue': comp.get('venue', {}).get('fullName', ''),
            'home': {
                'name': h_name,
                'abbrev': h_name[:3].upper(),
                'score': home.get('score', '0'),
                'logo': flag_url(h_name),
                'color': f"#{home.get('team', {}).get('color', '333333')}",
                'altColor': f"#{home.get('team', {}).get('alternateColor', 'ffffff')}",
            },
            'away': {
                'name': a_name,
                'abbrev': a_name[:3].upper(),
                'score': away.get('score', '0'),
                'logo': flag_url(a_name),
                'color': f"#{away.get('team', {}).get('color', '333333')}",
                'altColor': f"#{away.get('team', {}).get('alternateColor', 'ffffff')}",
            },
            'keyEvents': key_events,
        })

    by_date = {}
    for m in matches:
        day = m['date'][:10]
        by_date.setdefault(day, []).append(m)

    return jsonify({'matches': matches, 'byDate': by_date, 'count': len(matches)})


@app.route('/api/standings')
@rate_limit(60, 60)
def api_standings():
    """Group standings — team lists only, zeroed stats (tournament not started)."""
    groups = []
    for g in STANDINGS_DATA.get('standings', []):
        entries = []
        for i, e in enumerate(g.get('table', [])):
            team_name = e['team']['name']
            entries.append({
                'team': team_name,
                'abbrev': team_name[:3].upper(),
                'logo': flag_url(team_name),
                'gp': 0, 'w': 0, 'd': 0, 'l': 0,
                'gf': 0, 'ga': 0, 'gd': 0, 'pts': 0,
                'form': '',
            })
        group_name = g['group'].replace('GROUP_', 'Group ')
        groups.append({'name': group_name, 'standings': entries})

    return jsonify({'groups': groups})


@app.route('/api/teams')
@rate_limit(60, 60)
def api_teams():
    """All teams from standings data."""
    teams = {}
    for g in STANDINGS_DATA.get('standings', []):
        for e in g.get('table', []):
            name = e['team']['name']
            if name not in teams:
                teams[name] = {
                    'id': e['team']['id'],
                    'name': name,
                    'abbrev': name[:3].upper(),
                    'logo': flag_url(name),
                    'color': '1a1a2e',
                    'altColor': 'e2e8f0',
                }
    team_list = sorted(teams.values(), key=lambda t: t['name'])
    return jsonify({'teams': team_list, 'count': len(team_list)})


@app.route('/api/live')
@rate_limit(120, 60)
def api_live():
    """Live/upcoming matches from ESPN."""
    data = fetch_espn("scoreboard")
    events = data.get('events', [])
    live = []
    for e in events:
        status = e.get('status', {}).get('type', {})
        if status.get('name') in ('STATUS_IN_PROGRESS', 'STATUS_HALFTIME', 'STATUS_SCHEDULED'):
            live.append({
                'id': e.get('id'),
                'name': e.get('name', ''),
                'shortName': e.get('shortName', ''),
                'date': e.get('date', ''),
                'status': status.get('name', ''),
                'clock': e.get('status', {}).get('displayClock', ''),
                'period': e.get('status', {}).get('period', 0),
            })
    return jsonify({'live': live})


@app.route('/api/bracket')
@rate_limit(30, 60)
def api_bracket():
    """Knockout bracket from ESPN."""
    import re
    data = fetch_espn("scoreboard?dates=20260601-20260801", ttl=3600)
    stages = {}
    for e in data.get('events', []):
        slug = e.get('season', {}).get('slug', '?')
        if slug == 'group-stage':
            continue
        comps = e.get('competitions', [])
        if not comps:
            continue
        comp = comps[0]
        competitors = comp.get('competitors', [])
        h = competitors[0] if len(competitors) > 0 else {}
        a = competitors[1] if len(competitors) > 1 else {}
        h_name = h.get('team', {}).get('displayName', h.get('team', {}).get('name', 'TBD'))
        a_name = a.get('team', {}).get('displayName', a.get('team', {}).get('name', 'TBD'))
        stages.setdefault(slug, []).append({
            'id': e.get('id'),
            'home': h_name, 'away': a_name,
            'homeScore': h.get('score', None),
            'awayScore': a.get('score', None),
            'date': e.get('date', ''),
            'status': e.get('status', {}).get('type', {}).get('name', ''),
        })
    # Order stages
    stage_order = ['round-of-32', 'round-of-16', 'quarterfinals', 'semifinals', 'third-place', 'final']
    bracket = {}
    for s in stage_order:
        if s in stages:
            bracket[s] = stages[s]

    # Hardcoded later rounds that ESPN hasn't published yet
    if 'semifinals' not in bracket:
        bracket['semifinals'] = [
            {'id': 'sf1', 'home': 'QF 1 Winner', 'away': 'QF 2 Winner', 'homeScore': None, 'awayScore': None, 'date': '2026-07-14T19:00:00Z', 'status': 'STATUS_SCHEDULED'},
            {'id': 'sf2', 'home': 'QF 3 Winner', 'away': 'QF 4 Winner', 'homeScore': None, 'awayScore': None, 'date': '2026-07-15T19:00:00Z', 'status': 'STATUS_SCHEDULED'},
        ]
    if 'third-place' not in bracket:
        bracket['third-place'] = [
            {'id': 'tp1', 'home': 'SF 1 Loser', 'away': 'SF 2 Loser', 'homeScore': None, 'awayScore': None, 'date': '2026-07-18T19:00:00Z', 'status': 'STATUS_SCHEDULED'},
        ]
    if 'final' not in bracket:
        bracket['final'] = [
            {'id': 'f1', 'home': 'SF 1 Winner', 'away': 'SF 2 Winner', 'homeScore': None, 'awayScore': None, 'date': '2026-07-19T19:00:00Z', 'status': 'STATUS_SCHEDULED'},
        ]

    return jsonify({'bracket': bracket, 'stages': list(bracket.keys())})


@app.route('/api/news')
@rate_limit(10, 60)
def api_news():
    """World Cup 2026 news from Google News RSS."""
    import xml.etree.ElementTree as ET
    news = fetch_espn("news", ttl=900)  # dummy — will replace with RSS
    try:
        resp = requests.get(
            'https://news.google.com/rss/search?q=World+Cup+2026+football&hl=en-US&gl=US&ceid=US:en',
            timeout=10
        )
        resp.raise_for_status()
        tree = ET.fromstring(resp.text)
        items = []
        for item in tree.findall('.//item')[:15]:
            title = item.find('title').text if item.find('title') is not None else ''
            link = item.find('link').text if item.find('link') is not None else ''
            source = item.find('source').text if item.find('source') is not None else ''
            pubdate = item.find('pubDate').text if item.find('pubDate') is not None else ''
            if title and link:
                items.append({
                    'title': title,
                    'url': link,
                    'source': source,
                    'time': pubdate,
                })
        return jsonify({'news': items, 'count': len(items)})
    except Exception as e:
        return jsonify({'error': str(e), 'news': []}), 502


@app.route('/api/stats')
@rate_limit(60, 60)
def api_stats():
    """Tournament + player stats computed from match data."""
    import re
    placeholder_re = re.compile(
        r'(Group\s+[A-Z]\s+(Winner|2nd\s+Place)|'
        r'Round\s+of\s+(16|32)\s+\d+\s+Winner|'
        r'Third\s+Place\s+Group)', re.IGNORECASE
    )

    data = fetch_espn("scoreboard?dates=20260601-20260801")
    events = data.get('events', [])

    # Tournament counters
    total_goals = 0
    matches_played = 0
    matches_with_results = 0
    yellow_cards = 0
    red_cards = 0
    clean_sheets = {}
    biggest_win = {'margin': 0, 'match': '', 'score': ''}
    total_attendance = 0
    attendance_count = 0

    # Player stats
    player_goals = {}
    player_assists = {}
    player_yellows = {}
    player_reds = {}

    for event in events:
        comps = event.get('competitions', [])
        if not comps:
            continue
        comp = comps[0]
        competitors = comp.get('competitors', [])
        home = competitors[0] if len(competitors) > 0 else {}
        away = competitors[1] if len(competitors) > 1 else {}

        h_name = home.get('team', {}).get('displayName', home.get('team', {}).get('name', '?'))
        a_name = away.get('team', {}).get('displayName', away.get('team', {}).get('name', '?'))
        if placeholder_re.search(h_name) or placeholder_re.search(a_name):
            continue

        status = event.get('status', {}).get('type', {})
        is_completed = status.get('completed', False)
        is_live = status.get('name') in ('STATUS_IN_PROGRESS', 'STATUS_HALFTIME')

        if not (is_completed or is_live):
            continue  # skip scheduled matches

        h_score = int(home.get('score', 0) or 0)
        a_score = int(away.get('score', 0) or 0)

        total_goals += h_score + a_score
        matches_played += 1
        if is_completed:
            matches_with_results += 1

        # Clean sheets
        if h_score == 0:
            clean_sheets[a_name] = clean_sheets.get(a_name, 0) + 1
        if a_score == 0:
            clean_sheets[h_name] = clean_sheets.get(h_name, 0) + 1

        # Biggest win
        margin = abs(h_score - a_score)
        if margin > biggest_win['margin']:
            winner = h_name if h_score > a_score else a_name
            biggest_win = {
                'margin': margin,
                'match': f"{h_name} vs {a_name}",
                'score': f"{max(h_score, a_score)}-{min(h_score, a_score)}",
                'winner': winner,
            }

        # Attendance
        attendance = comp.get('attendance', 0)
        if attendance:
            total_attendance += attendance
            attendance_count += 1

        # Process details for player stats
        team_id_map = {
            str(home.get('id', '')): h_name,
            str(away.get('id', '')): a_name,
        }
        for detail in comp.get('details', []):
            evt_type = detail.get('type', {}).get('text', '')
            is_goal = detail.get('scoringPlay', False)
            is_yellow = detail.get('yellowCard', False)
            is_red = detail.get('redCard', False)
            if not (is_goal or is_yellow or is_red):
                continue

            athlete = detail.get('athletesInvolved', [{}])[0] if detail.get('athletesInvolved') else {}
            player_name = athlete.get('shortName') or athlete.get('displayName', '')
            team_id = str(detail.get('team', {}).get('id', ''))
            team_name = team_id_map.get(team_id, '')

            if not player_name:
                continue

            if is_goal:
                player_goals[player_name] = player_goals.get(player_name, 0) + 1
                # Assist
                if len(detail.get('athletesInvolved', [])) > 1:
                    assister = detail['athletesInvolved'][1]
                    a_name_p = assister.get('shortName') or assister.get('displayName', '')
                    if a_name_p:
                        player_assists[a_name_p] = player_assists.get(a_name_p, 0) + 1
            if is_yellow:
                player_yellows[player_name] = player_yellows.get(player_name, 0) + 1
                yellow_cards += 1
            if is_red:
                player_reds[player_name] = player_reds.get(player_name, 0) + 1
                red_cards += 1

    # Rank players
    def rank_dict(d, limit=10):
        return [{'name': k, 'count': v} for k, v in
                sorted(d.items(), key=lambda x: (-x[1], x[0]))[:limit]]

    return jsonify({
        'tournament': {
            'totalGoals': total_goals,
            'matchesPlayed': matches_played,
            'matchesCompleted': matches_with_results,
            'goalsPerMatch': round(total_goals / matches_played, 2) if matches_played else 0,
            'yellowCards': yellow_cards,
            'redCards': red_cards,
            'cleanSheets': rank_dict(clean_sheets, 5),
            'biggestWin': biggest_win,
            'avgAttendance': round(total_attendance / attendance_count) if attendance_count else 0,
            'totalAttendance': total_attendance,
        },
        'players': {
            'topScorers': rank_dict(player_goals, 15),
            'topAssists': rank_dict(player_assists, 15),
            'mostYellows': rank_dict(player_yellows, 10),
            'mostReds': rank_dict(player_reds, 10),
        }
    })


@app.route('/')
def index():
    return send_from_directory('static', 'index.html')


@app.route('/robots.txt')
def robots():
    return send_from_directory('static', 'robots.txt')


@app.route('/sitemap.xml')
def sitemap():
    return send_from_directory('static', 'sitemap.xml')


if __name__ == '__main__':
    app.run(host='127.0.0.1', port=8895, debug=False)
