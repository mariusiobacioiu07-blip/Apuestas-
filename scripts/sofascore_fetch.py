import json, time, datetime as dt
from curl_cffi import requests

B = 'https://api.sofascore.com/api/v1'
LIGAS = {8, 17, 35, 23, 34, 37, 238}


def j(p):
    r = requests.get(B + p, impersonate='chrome', timeout=20)
    if r.status_code != 200:
        raise RuntimeError(f'{r.status_code} {p}')
    time.sleep(0.4)
    return r.json()


def avg(a):
    a = [x for x in a if x is not None]
    return round(sum(a) / len(a), 2) if a else None


def stats(ev, tid):
    loc = ev['homeTeam']['id'] == tid
    grupos = (j(f"/event/{ev['id']}/statistics").get('statistics') or [{}])[0].get('groups', [])
    items = [i for g in grupos for i in g['statisticsItems']]

    def v(k):
        it = next((i for i in items if i.get('key') == k), None)
        if not it:
            return (None, None)
        a = (it.get('homeValue'), it.get('awayValue'))
        return a if loc else (a[1], a[0])

    return v('expectedGoals'), v('cornerKicks'), v('yellowCards')


def equipo(tid):
    evs = [e for e in j(f'/team/{tid}/events/last/0').get('events', []) if e['status']['type'] == 'finished']
    rows = []
    for e in sorted(evs, key=lambda e: e['startTimestamp'])[-5:]:
        try:
            rows.append(stats(e, tid))
        except Exception:
            pass
    return {
        'xg': avg([r[0][0] for r in rows]), 'xga': avg([r[0][1] for r in rows]),
        'cf': avg([r[1][0] for r in rows]), 'ca': avg([r[1][1] for r in rows]),
        'cards': avg([r[2][0] for r in rows]), 'n': len(rows), 'bajas': [],
    }


teams = {}
hoy = dt.date.today()
for d in range(3):
    fecha = (hoy + dt.timedelta(d)).isoformat()
    try:
        evs = j(f'/sport/football/scheduled-events/{fecha}').get('events', [])
    except Exception as e:
        print('ERR', fecha, e)
        continue
    for ev in evs:
        if (ev.get('tournament', {}).get('uniqueTournament', {}).get('id')) not in LIGAS:
            continue
        try:
            lu = j(f"/event/{ev['id']}/lineups")
        except Exception:
            lu = {}
        for lado, key in (('homeTeam', 'home'), ('awayTeam', 'away')):
            t = ev[lado]
            if t['name'] in teams:
                continue
            try:
                dat = equipo(t['id'])
            except Exception as e:
                print('ERR', t['name'], e)
                continue
            dat['bajas'] = [
                {'n': m['player'].get('name'), 'pos': m['player'].get('position', '?')}
                for m in (lu.get(key) or {}).get('missingPlayers', []) if m.get('type') == 'missing'
            ]
            teams[t['name']] = dat
            print('OK', t['name'])

if not teams:
    raise SystemExit('Sin datos: Sofascore bloqueó la petición o no hay partidos.')
with open('data/sofascore.json', 'w', encoding='utf-8') as f:
    json.dump({'updated': dt.datetime.utcnow().isoformat() + 'Z', 'teams': teams}, f, ensure_ascii=False)
print(len(teams), 'equipos guardados')

