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

def extract_penalty_misses(home_name, away_name, known_scorers, match_id=None):
    """Return full shootout sequence for known matches: [(team, player, scored), ...]
    Returns None if no data available for this match."""
    import re
    
    # Full shootout sequence overrides for known matches
    # (team, player, scored) — ordered by actual shootout order
    sequences = {
        # Germany vs Paraguay (760489): 6 rounds, 3 GER misses, 2 PAR misses
        # R1: PAR✅(Maurício) GER❌(Havertz)
        # R2: PAR✅(Gómez)    GER✅(Kimmich)
        # R3: PAR✅(Galarza)  GER❌(Woltemade)
        # R4: PAR❌(—)        GER✅(Musiala)
        # R5: PAR❌(—)        GER❌(Tah)
        # R6: PAR✅(Canale)   (game ends, GER's 6th taker not needed)
        760489: [
            ('Paraguay', 'Maurício', True), ('Germany', 'K. Havertz', False),
            ('Paraguay', 'G. Gómez', True), ('Germany', 'J. Kimmich', True),
            ('Paraguay', 'M. Galarza', True), ('Germany', 'N. Woltemade', False),
            ('Paraguay', '—', False), ('Germany', 'J. Musiala', True),
            ('Paraguay', '—', False), ('Germany', 'J. Tah', False),
            ('Paraguay', 'J. Canale', True),
        ],
        # Netherlands vs Morocco (760488): 10 kicks, NED 2-3 MAR
        # R1: NED✅(Koopmeiners)   MAR❌(El Aynaoui - bar)
        # R2: NED❌(Kluivert - post) MAR✅(Rahimi)
        # R3: NED✅(Weghorst)       MAR✅(Talbi)
        # R4: NED❌(Timber - miss)  MAR❌(Hakimi - post)
        # SD: NED❌(Summerville - saved) MAR✅(Saibari - winner)
        760488: [
            ('Netherlands', 'T. Koopmeiners', True), ('Morocco', 'N. El Aynaoui', False),
            ('Netherlands', 'J. Kluivert', False), ('Morocco', 'S. Rahimi', True),
            ('Netherlands', 'W. Weghorst', True), ('Morocco', 'C. Talbi', True),
            ('Netherlands', 'Q. Timber', False), ('Morocco', 'A. Hakimi', False),
            ('Netherlands', 'C. Summerville', False), ('Morocco', 'I. Saibari', True),
        ],
    }
    
    if match_id and int(match_id) in sequences:
        return sequences[int(match_id)]
    return None

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
            is_shootout = detail.get('shootout', False)
            # Include goals, cards, and all shootout events (including misses)
            if not (is_goal or is_yellow or is_red or is_shootout):
                continue
            if is_shootout:
                icon = '✅' if is_goal else '❌'
            else:
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
                'shootout': is_shootout,
                'scored': is_goal,
                })
        
        # ── Reconstruct full shootout sequence (ESPN only provides scored penalties) ──
        shootout_events = [e for e in key_events if e['shootout']]
        if shootout_events:
            first_shooter_team = shootout_events[0]['team']
            other_team = a_name if first_shooter_team == h_name else h_name
            team_order = [first_shooter_team, other_team]
            team_map = {team: [] for team in team_order}
            for e in shootout_events:
                team_map[e['team']].append(e)

            full_sequence = []
            # Try to get full shootout sequence from match reports (overrides round logic)
            known_scorers = set(e['player'] for e in shootout_events if e['scored'] and e['player'])
            reported_sequence = extract_penalty_misses(h_name, a_name, known_scorers, match_id=event.get('id'))
            
            if reported_sequence:
                # Use the exact sequence from match report
                for team, player, scored in reported_sequence:
                    full_sequence.append({
                        'icon': '✅' if scored else '❌',
                        'type': 'Penalty - Scored' if scored else 'Penalty - Missed',
                        'minute': "120'", 'player': player, 'playerId': '', 'headshot': '',
                        'team': team, 'ownGoal': False, 'penalty': True,
                        'shootout': True, 'scored': scored,
                    })
            else:
                # Fallback: ESPN-only round-based logic
                r = 0
                while True:
                    t1_done = len(team_map[team_order[0]]) > r
                    t2_done = len(team_map[team_order[1]]) > r
                    if not t1_done and not t2_done:
                        break
                    for team in team_order:
                        if len(team_map[team]) > r:
                            full_sequence.append(team_map[team][r])
                        else:
                            full_sequence.append({
                                'icon': '❌', 'type': 'Penalty - Missed', 'minute': "120'",
                                'player': '—', 'playerId': '', 'headshot': '',
                                'team': team, 'ownGoal': False, 'penalty': True,
                                'shootout': True, 'scored': False,
                            })
                    r += 1
            key_events = [e for e in key_events if not e['shootout']] + full_sequence

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
            'stage': event.get('season', {}).get('slug', 'group-stage'),
            'home': {
                'name': h_name,
                'abbrev': h_name[:3].upper(),
                'score': home.get('score', '0'),
                'logo': flag_url(h_name),
                'color': f"#{home.get('team', {}).get('color', '333333')}",
                'altColor': f"#{home.get('team', {}).get('alternateColor', 'ffffff')}",
                'winner': home.get('winner', False),
                'shootoutScore': home.get('shootoutScore', None),
            },
            'away': {
                'name': a_name,
                'abbrev': a_name[:3].upper(),
                'score': away.get('score', '0'),
                'logo': flag_url(a_name),
                'color': f"#{away.get('team', {}).get('color', '333333')}",
                'altColor': f"#{away.get('team', {}).get('alternateColor', 'ffffff')}",
                'winner': away.get('winner', False),
                'shootoutScore': away.get('shootoutScore', None),
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
    """Group standings — computed from actual match results."""
    import re
    placeholder_re = re.compile(
        r'(Group\s+[A-Z]\s+(Winner|2nd\s+Place)|'
        r'Round\s+of\s+(16|32)\s+\d+\s+Winner|'
        r'Third\s+Place\s+Group)', re.IGNORECASE
    )

    # Fetch all matches
    data = fetch_espn("scoreboard?dates=20260601-20260801")
    events = data.get('events', [])

    # Build a map: team_name -> {gp, w, d, l, gf, ga, form_list}
    team_stats = {}
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
        status_name = status.get('name', '')
        if status_name not in ('STATUS_FINAL', 'STATUS_FULL_TIME'):
            continue

        try:
            h_score = int(home.get('score', '0') or '0')
            a_score = int(away.get('score', '0') or '0')
        except (ValueError, TypeError):
            continue

        for name in (h_name, a_name):
            if name not in team_stats:
                team_stats[name] = {'gp': 0, 'w': 0, 'd': 0, 'l': 0,
                                     'gf': 0, 'ga': 0, 'form': []}

        # Home team
        team_stats[h_name]['gp'] += 1
        team_stats[h_name]['gf'] += h_score
        team_stats[h_name]['ga'] += a_score
        if h_score > a_score:
            team_stats[h_name]['w'] += 1
            team_stats[h_name]['form'].append('W')
        elif h_score < a_score:
            team_stats[h_name]['l'] += 1
            team_stats[h_name]['form'].append('L')
        else:
            team_stats[h_name]['d'] += 1
            team_stats[h_name]['form'].append('D')

        # Away team
        team_stats[a_name]['gp'] += 1
        team_stats[a_name]['gf'] += a_score
        team_stats[a_name]['ga'] += h_score
        if a_score > h_score:
            team_stats[a_name]['w'] += 1
            team_stats[a_name]['form'].append('W')
        elif a_score < h_score:
            team_stats[a_name]['l'] += 1
            team_stats[a_name]['form'].append('L')
        else:
            team_stats[a_name]['d'] += 1
            team_stats[a_name]['form'].append('D')

    groups = []
    for g in STANDINGS_DATA.get('standings', []):
        group_name = g['group'].replace('GROUP_', 'Group ')
        entries = []
        for e in g.get('table', []):
            team_name = e['team']['name']
            stats = team_stats.get(team_name, {'gp': 0, 'w': 0, 'd': 0, 'l': 0,
                                                'gf': 0, 'ga': 0, 'form': []})
            form_str = ''.join(stats.get('form', [])[-5:])
            entries.append({
                'team': team_name,
                'abbrev': team_name[:3].upper(),
                'logo': flag_url(team_name),
                'gp': stats['gp'],
                'w': stats['w'],
                'd': stats['d'],
                'l': stats['l'],
                'gf': stats['gf'],
                'ga': stats['ga'],
                'gd': stats['gf'] - stats['ga'],
                'pts': stats['w'] * 3 + stats['d'],
                'form': form_str,
            })
        # Sort by points desc, GD desc, GF desc
        entries.sort(key=lambda x: (-x['pts'], -x['gd'], -x['gf']))
        groups.append({'name': group_name, 'standings': entries})

    return jsonify({'groups': groups})


@app.route('/api/best-thirds')
@rate_limit(60, 60)
def api_best_thirds():
    """Best third-place teams across all groups — sorted by points, GD, GF."""
    # Reuse the same standings computation
    import re
    placeholder_re = re.compile(
        r'(Group\s+[A-Z]\s+(Winner|2nd\s+Place)|'
        r'Round\s+of\s+(16|32)\s+\d+\s+Winner|'
        r'Third\s+Place\s+Group)', re.IGNORECASE
    )

    data = fetch_espn("scoreboard?dates=20260601-20260801")
    events = data.get('events', [])

    team_stats = {}
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
        status_name = status.get('name', '')
        if status_name not in ('STATUS_FINAL', 'STATUS_FULL_TIME'):
            continue

        try:
            h_score = int(home.get('score', '0') or '0')
            a_score = int(away.get('score', '0') or '0')
        except (ValueError, TypeError):
            continue

        for name in (h_name, a_name):
            if name not in team_stats:
                team_stats[name] = {'gp': 0, 'w': 0, 'd': 0, 'l': 0,
                                     'gf': 0, 'ga': 0, 'form': []}

        team_stats[h_name]['gp'] += 1
        team_stats[h_name]['gf'] += h_score
        team_stats[h_name]['ga'] += a_score
        if h_score > a_score:
            team_stats[h_name]['w'] += 1
            team_stats[h_name]['form'].append('W')
        elif h_score < a_score:
            team_stats[h_name]['l'] += 1
            team_stats[h_name]['form'].append('L')
        else:
            team_stats[h_name]['d'] += 1
            team_stats[h_name]['form'].append('D')

        team_stats[a_name]['gp'] += 1
        team_stats[a_name]['gf'] += a_score
        team_stats[a_name]['ga'] += h_score
        if a_score > h_score:
            team_stats[a_name]['w'] += 1
            team_stats[a_name]['form'].append('W')
        elif a_score < h_score:
            team_stats[a_name]['l'] += 1
            team_stats[a_name]['form'].append('L')
        else:
            team_stats[a_name]['d'] += 1
            team_stats[a_name]['form'].append('D')

    # Extract 3rd place from each group
    thirds = []
    for g in STANDINGS_DATA.get('standings', []):
        group_name = g['group'].replace('GROUP_', 'Group ')
        entries = []
        for e in g.get('table', []):
            team_name = e['team']['name']
            stats = team_stats.get(team_name, {'gp': 0, 'w': 0, 'd': 0, 'l': 0,
                                                'gf': 0, 'ga': 0, 'form': []})
            form_str = ''.join(stats.get('form', [])[-5:])
            entries.append({
                'team': team_name,
                'abbrev': team_name[:3].upper(),
                'logo': flag_url(team_name),
                'gp': stats['gp'],
                'w': stats['w'],
                'd': stats['d'],
                'l': stats['l'],
                'gf': stats['gf'],
                'ga': stats['ga'],
                'gd': stats['gf'] - stats['ga'],
                'pts': stats['w'] * 3 + stats['d'],
                'form': form_str,
            })
        entries.sort(key=lambda x: (-x['pts'], -x['gd'], -x['gf']))
        if len(entries) >= 3:
            third = entries[2]
            third['group'] = group_name
            thirds.append(third)

    # Sort all 3rd place teams: pts desc, gd desc, gf desc
    thirds.sort(key=lambda x: (-x['pts'], -x['gd'], -x['gf']))

    # Mark top 8 as qualifying
    for i, t in enumerate(thirds):
        t['rank'] = i + 1
        t['qualifies'] = i < 8

    return jsonify({'thirds': thirds, 'qualifying_spots': 8})


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
    """Knockout bracket from ESPN, reordered into correct bracket tree."""
    import re
    data = fetch_espn("scoreboard?dates=20260601-20260801", ttl=30)

    # Parse all events, skip group stage
    raw = {}
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
        raw.setdefault(slug, []).append({
            'id': e.get('id'),
            'home': h_name, 'away': a_name,
            'homeScore': h.get('score', None),
            'awayScore': a.get('score', None),
            'homeWinner': h.get('winner', False),
            'awayWinner': a.get('winner', False),
            'homeShootoutScore': h.get('shootoutScore', None),
            'awayShootoutScore': a.get('shootoutScore', None),
            'date': e.get('date', ''),
            'status': e.get('status', {}).get('type', {}).get('name', ''),
        })

    # ── Correct bracket slot order (left side top→bottom, then right side top→bottom) ──
    BRACKET_ORDER = [
        # Left side (slots 1-8)
        ('Germany', 'Paraguay'),       # 1
        ('France', 'Sweden'),          # 2
        ('South Africa', 'Canada'),    # 3
        ('Netherlands', 'Morocco'),    # 4
        ('Spain', 'Austria'),          # 5
        ('Portugal', 'Croatia'),       # 6
        ('United States', 'Bosnia-Herzegovina'),  # 7
        ('Belgium', 'Senegal'),        # 8
        # Right side (slots 9-16)
        ('Brazil', 'Japan'),           # 9
        ('Mexico', 'Ecuador'),         # 10
        ('Ivory Coast', 'Norway'),     # 11
        ('England', 'Congo DR'),       # 12
        ('Argentina', 'Cape Verde'),   # 13
        ('Australia', 'Egypt'),        # 14
        ('Switzerland', 'Algeria'),    # 15
        ('Colombia', 'Ghana'),         # 16
    ]

    def normalize(s):
        return s.lower().replace('-', ' ').replace('&', 'and').replace('.', '').strip()

    def matches_slot(m, slot_home, slot_away):
        mh = normalize(m['home'])
        ma = normalize(m['away'])
        sh = normalize(slot_home)
        sa = normalize(slot_away)
        return (mh == sh and ma == sa) or (mh == sa and ma == sh)

    # ── Reorder R32 ──
    r32_raw = raw.get('round-of-32', [])
    r32_ordered = []
    for slot_home, slot_away in BRACKET_ORDER:
        found = None
        for m in r32_raw:
            if matches_slot(m, slot_home, slot_away):
                found = m
                break
        if found:
            r32_ordered.append(found)
        else:
            r32_ordered.append({
                'id': f'r32-{len(r32_ordered)+1}',
                'home': slot_home, 'away': slot_away,
                'homeScore': None, 'awayScore': None,
                'date': '', 'status': 'STATUS_SCHEDULED',
            })

    def winner_label(match):
        """Return the winning team name, checking winner flag for penalty shootouts."""
        if match.get('status') in ('STATUS_FINAL', 'STATUS_FULL_TIME', 'STATUS_FINAL_PEN'):
            # First check the explicit winner flag (handles penalty wins with tied scores)
            if match.get('homeWinner'):
                return match['home']
            if match.get('awayWinner'):
                return match['away']
            # Fallback to score comparison
            hs = match.get('homeScore')
            aws = match.get('awayScore')
            if hs is not None and aws is not None:
                try:
                    if int(hs) > int(aws):
                        return match['home']
                    elif int(aws) > int(hs):
                        return match['away']
                except (ValueError, TypeError):
                    pass
        return None

    # ── Build R16 with correct pairings ──
    r16_pairings = [
        (0, 1),   # R16-1: R32-1 vs R32-2
        (2, 3),   # R16-2: R32-3 vs R32-4
        (4, 5),   # R16-3: R32-5 vs R32-6
        (6, 7),   # R16-4: R32-7 vs R32-8
        (8, 9),   # R16-5: R32-9 vs R32-10
        (10, 11), # R16-6: R32-11 vs R32-12
        (12, 13), # R16-7: R32-13 vs R32-14
        (14, 15), # R16-8: R32-15 vs R32-16
    ]

    r16_raw = raw.get('round-of-16', [])
    r16_ordered = []
    for pair_idx, (idx_a, idx_b) in enumerate(r16_pairings):
        a_winner = winner_label(r32_ordered[idx_a])
        b_winner = winner_label(r32_ordered[idx_b])
        home = a_winner or f'Round of 32 {idx_a+1} Winner'
        away = b_winner or f'Round of 32 {idx_b+1} Winner'
        # Use ESPN R16 data in order to preserve dates/scores (or placeholder)
        espn = r16_raw[pair_idx] if pair_idx < len(r16_raw) else None
        r16_ordered.append({
            'id': espn['id'] if espn else f'r16-{pair_idx+1}',
            'home': home, 'away': away,
            'homeScore': espn.get('homeScore') if espn else None,
            'awayScore': espn.get('awayScore') if espn else None,
            'date': espn.get('date', '') if espn else '',
            'status': espn.get('status', 'STATUS_SCHEDULED') if espn else 'STATUS_SCHEDULED',
        })

    # ── Build QF ──
    qf_pairings = [
        (0, 1),   # QF-1: R16-1 vs R16-2 (left top)
        (2, 3),   # QF-2: R16-3 vs R16-4 (left bottom)
        (4, 5),   # QF-3: R16-5 vs R16-6 (right top)
        (6, 7),   # QF-4: R16-7 vs R16-8 (right bottom)
    ]

    def r16_winner_label(idx):
        m = r16_ordered[idx]
        if m.get('status') in ('STATUS_FINAL', 'STATUS_FULL_TIME', 'STATUS_FINAL_PEN'):
            if m.get('homeWinner'):
                return m['home']
            if m.get('awayWinner'):
                return m['away']
            hs = m.get('homeScore')
            aws = m.get('awayScore')
            if hs is not None and aws is not None:
                try:
                    if int(hs) > int(aws):
                        return m['home']
                    elif int(aws) > int(hs):
                        return m['away']
                except (ValueError, TypeError):
                    pass
        return None

    qf_raw = raw.get('quarterfinals', [])
    qf_ordered = []
    for pair_idx, (idx_a, idx_b) in enumerate(qf_pairings):
        a_winner = r16_winner_label(idx_a)
        b_winner = r16_winner_label(idx_b)
        home = a_winner or f'Round of 16 {idx_a+1} Winner'
        away = b_winner or f'Round of 16 {idx_b+1} Winner'
        espn = qf_raw[pair_idx] if pair_idx < len(qf_raw) else None
        qf_ordered.append({
            'id': espn['id'] if espn else f'qf-{pair_idx+1}',
            'home': home, 'away': away,
            'homeScore': espn.get('homeScore') if espn else None,
            'awayScore': espn.get('awayScore') if espn else None,
            'date': espn.get('date', '') if espn else '',
            'status': espn.get('status', 'STATUS_SCHEDULED') if espn else 'STATUS_SCHEDULED',
        })

    # ── Build SF ──
    def qf_winner_label(idx):
        m = qf_ordered[idx]
        if m.get('status') in ('STATUS_FINAL', 'STATUS_FULL_TIME', 'STATUS_FINAL_PEN'):
            if m.get('homeWinner'):
                return m['home']
            if m.get('awayWinner'):
                return m['away']
            hs = m.get('homeScore')
            aws = m.get('awayScore')
            if hs is not None and aws is not None:
                try:
                    if int(hs) > int(aws):
                        return m['home']
                    elif int(aws) > int(hs):
                        return m['away']
                except (ValueError, TypeError):
                    pass
        return None

    sf1_home = qf_winner_label(0) or 'QF 1 Winner'
    sf1_away = qf_winner_label(1) or 'QF 2 Winner'
    sf2_home = qf_winner_label(2) or 'QF 3 Winner'
    sf2_away = qf_winner_label(3) or 'QF 4 Winner'

    sf_raw = raw.get('semifinals', [])
    sf_ordered = []
    for sf_idx, (home_label, away_label) in enumerate([(sf1_home, sf1_away), (sf2_home, sf2_away)]):
        espn = sf_raw[sf_idx] if sf_idx < len(sf_raw) else None
        sf_ordered.append({
            'id': espn['id'] if espn else f'sf-{sf_idx+1}',
            'home': home_label, 'away': away_label,
            'homeScore': espn.get('homeScore') if espn else None,
            'awayScore': espn.get('awayScore') if espn else None,
            'date': espn.get('date', '') if espn else '',
            'status': espn.get('status', 'STATUS_SCHEDULED') if espn else 'STATUS_SCHEDULED',
        })

    # ── Final & Third Place ──
    def sf_winner_label(idx):
        m = sf_ordered[idx]
        if m.get('status') in ('STATUS_FINAL', 'STATUS_FULL_TIME', 'STATUS_FINAL_PEN'):
            if m.get('homeWinner'):
                return m['home']
            if m.get('awayWinner'):
                return m['away']
            hs = m.get('homeScore')
            aws = m.get('awayScore')
            if hs is not None and aws is not None:
                try:
                    if int(hs) > int(aws):
                        return m['home']
                    elif int(aws) > int(hs):
                        return m['away']
                except (ValueError, TypeError):
                    pass
        return None

    sf1_w = sf_winner_label(0)
    sf2_w = sf_winner_label(1)

    final_raw = raw.get('final', [{}])[0] if raw.get('final') else {}
    third_raw = raw.get('third-place', [{}])[0] if raw.get('third-place') else {}

    final_match = {
        'id': final_raw.get('id', 'f1'),
        'home': sf1_w or 'SF 1 Winner',
        'away': sf2_w or 'SF 2 Winner',
        'homeScore': final_raw.get('homeScore'),
        'awayScore': final_raw.get('awayScore'),
        'date': final_raw.get('date', '2026-07-19T19:00:00Z'),
        'status': final_raw.get('status', 'STATUS_SCHEDULED'),
    }
    third_match = {
        'id': third_raw.get('id', 'tp1'),
        'home': 'SF 1 Loser',
        'away': 'SF 2 Loser',
        'homeScore': third_raw.get('homeScore'),
        'awayScore': third_raw.get('awayScore'),
        'date': third_raw.get('date', '2026-07-18T19:00:00Z'),
        'status': third_raw.get('status', 'STATUS_SCHEDULED'),
    }

    bracket = {
        'round-of-32': r32_ordered,
        'round-of-16': r16_ordered,
        'quarterfinals': qf_ordered,
        'semifinals': sf_ordered,
        'third-place': [third_match],
        'final': [final_match],
    }

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
    player_team = {}  # player shortName → team name

    # Known player→team mappings for players not captured in match details
    _known_players = {
        'B. Guimarães': 'Brazil',
        'M. Olise': 'France',
        'H. Mejbri': 'Tunisia',
        'D. Dumfries': 'Netherlands',
        'C. Wood': 'New Zealand',
        'J. Enciso': 'Paraguay',
        'V. Gyökeres': 'Sweden',
        'K. Mbappé': 'France',
        'B. Embolo': 'Switzerland',
    }
    player_team.update(_known_players)

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

            if team_name:
                player_team[player_name] = team_name

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

    # Rank players — now includes team
    def rank_dict(d, limit=10):
        result = []
        for name, count in sorted(d.items(), key=lambda x: (-x[1], x[0]))[:limit]:
            entry = {'name': name, 'count': count}
            team = player_team.get(name, '')
            if team:
                entry['team'] = team
            result.append(entry)
        return result

    # Fetch assists from ESPN statistics API (scoring details only have 1 athlete)
    assist_leaders = []
    try:
        stats_data = fetch_espn("statistics")
        for stat_group in stats_data.get('stats', []):
            if stat_group.get('name') == 'assistsLeaders':
                for leader in stat_group.get('leaders', []):
                    athlete = leader.get('athlete', {})
                    name = athlete.get('shortName') or athlete.get('displayName', '')
                    value = int(leader.get('value', 0))
                    if name and value > 0:
                        entry = {'name': name, 'count': value}
                        team = player_team.get(name, '')
                        if team:
                            entry['team'] = team
                        assist_leaders.append(entry)
                break
    except Exception:
        pass  # fall back to empty if stats API fails

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
            'topScorers': rank_dict(player_goals, 10),
            'topAssists': assist_leaders[:10],
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
