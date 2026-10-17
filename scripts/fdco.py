"""Baja los CSV de football-data.co.uk y genera:
 - data/fdco.json: córners y amarillas (últimos 5) por equipo y por árbitro
 - data/backtest.json + informe en el log: ¿el modelo Poisson mejora a Pinnacle?"""
import csv, io, json, math, datetime as dt, urllib.request

BASE = 'https://www.football-data.co.uk/mmz4281/{}/{}.csv'
LIGAS = ['E0', 'SP1', 'D1', 'I1', 'F1', 'N1', 'P1']
ACTUAL, BACK = '2627', ['2425', '2526']
ALIAS = {
    'Man United': 'Manchester United', 'Man City': 'Manchester City', "Nott'm Forest": 'Nottingham Forest',
    'Newcastle': 'Newcastle United', 'Tottenham': 'Tottenham Hotspur', 'West Ham': 'West Ham United',
    'Wolves': 'Wolverhampton Wanderers', 'Leeds': 'Leeds United', 'Brighton': 'Brighton and Hove Albion',
    'Ath Madrid': 'Atletico Madrid', 'Ath Bilbao': 'Athletic Bilbao', 'Betis': 'Real Betis',
    'Espanol': 'Espanyol', 'Vallecano': 'Rayo Vallecano', 'Sociedad': 'Real Sociedad', 'Celta': 'Celta Vigo',
    'Leverkusen': 'Bayer Leverkusen', "M'gladbach": 'Borussia Monchengladbach', 'Dortmund': 'Borussia Dortmund',
    'Ein Frankfurt': 'Eintracht Frankfurt', 'Mainz': 'Mainz 05', 'FC Koln': 'Cologne', 'Paris SG': 'Paris Saint-Germain',
    'St Etienne': 'Saint-Etienne', 'Sp Lisbon': 'Sporting CP', 'Sp Braga': 'Braga', 'Inter': 'Internazionale',
    'Milan': 'AC Milan', 'Verona': 'Hellas Verona', 'Spal': 'SPAL', 'Hoffenheim': 'TSG Hoffenheim',
    'Heidenheim': 'Heidenheim', 'Union Berlin': 'Union Berlin', 'Bayern Munich': 'Bayern Munchen',
    'Lyon': 'Olympique Lyonnais', 'Marseille': 'Olympique Marseille', 'Monaco': 'AS Monaco',
}


def bajar(s, l):
    try:
        rq = urllib.request.Request(BASE.format(s, l), headers={'User-Agent': 'Mozilla/5.0'})
        txt = urllib.request.urlopen(rq, timeout=30).read().decode('utf-8-sig', 'replace')
        return [r for r in csv.DictReader(io.StringIO(txt)) if r.get('HomeTeam') and r.get('FTHG') not in (None, '')]
    except Exception as e:
        print('ERR', s, l, e)
        return []


def fecha(r):
    for f in ('%d/%m/%Y', '%d/%m/%y'):
        try:
            return dt.datetime.strptime(r['Date'], f)
        except Exception:
            pass
    return dt.datetime(1970, 1, 1)


def num(r, k):
    try:
        return float(r[k])
    except Exception:
        return None


def avg(a):
    a = [x for x in a if x is not None]
    return round(sum(a) / len(a), 2) if a else None


def pois(l, k):
    return math.exp(-l) * l ** k / math.factorial(k)


def probs(lh, la):
    h = d = a = 0
    for i in range(9):
        for j in range(9):
            p = pois(lh, i) * pois(la, j)
            if i > j: h += p
            elif i < j: a += p
            else: d += p
    t = h + d + a
    return [h / t, d / t, a / t]


def backtest(rows, R):
    hist = {}
    for r in sorted(rows, key=fecha):
        H, A, hg, ag = r['HomeTeam'], r['AwayTeam'], int(r['FTHG']), int(r['FTAG'])
        hh, ha = hist.get(H, []), hist.get(A, [])
        hom, awa = [x for x in hh if x[2]], [x for x in ha if not x[2]]
        ps = [num(r, k) for k in ('PSCH', 'PSCD', 'PSCA')]
        if len(hom) >= 3 and len(awa) >= 3 and all(ps):
            m = lambda L, i: sum(x[i] for x in L) / len(L)
            lh = ((m(hom, 0) + m(hh[-5:], 0)) / 2 + (m(awa, 1) + m(ha[-5:], 1)) / 2) / 2
            la = ((m(awa, 0) + m(ha[-5:], 0)) / 2 + (m(hom, 1) + m(hh[-5:], 1)) / 2) / 2
            ph = probs(lh, la)
            z = sum(1 / x for x in ps)
            pin = [1 / x / z for x in ps]
            out = [1, 0, 0] if hg > ag else [0, 1, 0] if hg == ag else [0, 0, 1]
            R['n'] += 1
            R['bm'] += sum((p - o) ** 2 for p, o in zip(ph, out))
            R['bp'] += sum((p - o) ** 2 for p, o in zip(pin, out))
            for i, s in enumerate('HDA'):
                cu = [num(r, c + s) for c in ('B365', 'BW', 'IW', 'WH', 'VC', 'PS')]
                best = max([x for x in cu if x] or [0])
                if not best:
                    continue
                for nom, ok in (('mezcla>5%', (0.4 * ph[i] + 0.6 * pin[i]) * best - 1 > 0.05 and ph[i] > pin[i]),
                                ('linea>2%', pin[i] * best - 1 > 0.02), ('linea>5%', pin[i] * best - 1 > 0.05)):
                    if ok:
                        S = R['s'].setdefault(nom, [0, 0, 0])
                        S[0] += 1
                        S[1] += (best - 1) if out[i] else -1
                        S[2] += best / ps[i] - 1
        hist.setdefault(H, []).append((hg, ag, True))
        hist.setdefault(A, []).append((ag, hg, False))


teams, refs, R = {}, {}, dict(n=0, bm=0, bp=0, bets=0, pf=0, clv=0)
for l in LIGAS:
    rows = sorted(bajar(ACTUAL, l), key=fecha)
    por = {}
    for r in rows:
        for t, c, cc, y in ((r['HomeTeam'], 'HC', 'AC', 'HY'), (r['AwayTeam'], 'AC', 'HC', 'AY')):
            por.setdefault(t, []).append((num(r, c), num(r, cc), num(r, y)))
        if r.get('Referee'):
            refs.setdefault(r['Referee'], []).append((num(r, 'HY'), num(r, 'AY'), num(r, 'HC'), num(r, 'AC')))
    for t, v in por.items():
        v = v[-5:]
        teams[ALIAS.get(t, t)] = {'cf': avg([x[0] for x in v]), 'ca': avg([x[1] for x in v]), 'cards': avg([x[2] for x in v]), 'n': len(v)}
    for s in BACK:
        backtest(bajar(s, l), R)

refs = {k: {'cards': avg([(a or 0) + (b or 0) for a, b, _, _ in v]), 'corners': avg([(c or 0) + (d or 0) for _, _, c, d in v]), 'n': len(v)} for k, v in refs.items()}
if R['n']:
    print(f"BACKTEST {R['n']} partidos (2 temporadas, 7 ligas)")
    print(f"Brier modelo: {R['bm'] / R['n']:.4f} | Brier Pinnacle cierre: {R['bp'] / R['n']:.4f} (menor = mejor)")
    print('Estrategia | apuestas | ROI | CLV medio')
    for k, (n, pf, clv) in R['s'].items():
        print(f"{k} | {n} | {pf / n * 100:.1f}% | {clv / n * 100:.1f}%")
    json.dump(R, open('data/backtest.json', 'w'))
if not teams:
    raise SystemExit('Sin datos de football-data.co.uk')
json.dump({'updated': dt.datetime.now(dt.timezone.utc).isoformat(), 'teams': teams, 'refs': refs}, open('data/fdco.json', 'w'), ensure_ascii=False)
print(len(teams), 'equipos guardados')
