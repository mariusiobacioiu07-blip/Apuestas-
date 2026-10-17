"""Guarda la cuota de Pinnacle poco antes de cada partido (cuota de cierre aproximada) en data/closing.json.

Ahorra créditos de The Odds API: solo consulta una liga si football-data.org dice que
tiene un partido que empieza en los próximos 25 minutos, y pide solo Pinnacle.
Secrets necesarios en GitHub: FD_TOKEN (football-data.org) y ODDS_KEY (the-odds-api.com).
"""
import json, os, urllib.request, datetime as dt

FD, KEY = os.environ.get('FD_TOKEN', ''), os.environ.get('ODDS_KEY', '')
TOTALS = os.environ.get('CLOSING_TOTALS') == '1'      # +1 crédito por consulta: añade más/menos 2,5
DEPORTE = {'PL': 'soccer_epl', 'PD': 'soccer_spain_la_liga', 'BL1': 'soccer_germany_bundesliga', 'SA': 'soccer_italy_serie_a',
           'FL1': 'soccer_france_ligue_one', 'DED': 'soccer_netherlands_eredivisie', 'PPL': 'soccer_portugal_primeira_liga'}
VENTANA_MIN = 1440
RUTA = 'data/closing.json'


def get(url, headers=None):
    r = urllib.request.urlopen(urllib.request.Request(url, headers=headers or {}), timeout=30)
    return json.loads(r.read().decode()), r.headers


def utc(s):
    return dt.datetime.fromisoformat(s.replace('Z', '+00:00'))


def main():
    if not FD or not KEY:
        print('Faltan los secrets FD_TOKEN u ODDS_KEY; no hago nada.')
        return
    ahora = dt.datetime.now(dt.timezone.utc)
    d1, d2 = ahora.strftime('%Y-%m-%d'), (ahora + dt.timedelta(days=1)).strftime('%Y-%m-%d')
    fx, _ = get(f'https://api.football-data.org/v4/matches?dateFrom={d1}&dateTo={d2}', {'X-Auth-Token': FD})
    ligas = set()
    for m in fx.get('matches', []):
        mins = (utc(m['utcDate']) - ahora).total_seconds() / 60
        code = (m.get('competition') or {}).get('code')
        if m.get('status') in ('TIMED', 'SCHEDULED') and 0 < mins <= VENTANA_MIN and code in DEPORTE:
            ligas.add(code)
    if not ligas:
        print('Ningún partido de las ligas seguidas empieza en los próximos', VENTANA_MIN, 'min.')
        return

    try:
        datos = json.load(open(RUTA))
    except Exception:
        datos = {'matches': {}}
    M = datos.setdefault('matches', {})
    cambios = 0
    for code in sorted(ligas):
        mk = 'h2h,totals' if TOTALS else 'h2h'
        url = f'https://api.the-odds-api.com/v4/sports/{DEPORTE[code]}/odds?bookmakers=pinnacle&markets={mk}&oddsFormat=decimal&apiKey={KEY}'
        try:
            ev, hd = get(url)
        except Exception as e:
            print('Error The Odds API', code, e)
            continue
        datos['creditos_restantes'] = hd.get('x-requests-remaining')
        for e in ev:
            mins = (utc(e['commence_time']) - ahora).total_seconds() / 60
            if not (0 < mins <= VENTANA_MIN + 5):
                continue
            b = next((x for x in e.get('bookmakers', []) if x['key'] == 'pinnacle'), None)
            h2 = b and next((m for m in b['markets'] if m['key'] == 'h2h'), None)
            if not h2:
                continue
            g = lambda n: next((o['price'] for o in h2['outcomes'] if o['name'] == n), None)
            h, d, a = g(e['home_team']), g('Draw'), g(e['away_team'])
            if not (h and d and a):
                continue
            r = {'home': e['home_team'], 'away': e['away_team'], 'commence': e['commence_time'], 'liga': code,
                 'ts': ahora.isoformat(timespec='seconds'), 'h': h, 'd': d, 'a': a}
            t = next((m for m in b['markets'] if m['key'] == 'totals'), None)
            if t:
                o = next((x['price'] for x in t['outcomes'] if x['name'] == 'Over' and x.get('point') == 2.5), None)
                u = next((x['price'] for x in t['outcomes'] if x['name'] == 'Under' and x.get('point') == 2.5), None)
                if o and u:
                    r['o25'], r['u25'] = o, u
            M[f"{e['home_team']}|{e['away_team']}|{e['commence_time'][:10]}"] = r
            cambios += 1
    limite = ahora - dt.timedelta(days=45)
    for k in [k for k, v in M.items() if utc(v['commence']) < limite]:
        del M[k]
    if cambios:
        datos['updated'] = ahora.isoformat(timespec='seconds')
        os.makedirs('data', exist_ok=True)
        json.dump(datos, open(RUTA, 'w'), ensure_ascii=False)
    print(cambios, 'cuotas de cierre guardadas')


if __name__ == '__main__':
    main()
