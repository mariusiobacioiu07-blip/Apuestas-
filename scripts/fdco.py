"""Baja los CSV de football-data.co.uk y genera:
 - data/fdco.json     córners y amarillas (últimos 5) por equipo y por árbitro
 - data/model.json    modelo Dixon-Coles (fuerza de ataque/defensa) para la app
 - data/backtest.json backtest honesto (walk-forward, sin mirar el futuro)

Reglas del backtest:
 * El modelo de cada partido se ajusta SOLO con partidos anteriores.
 * Las apuestas se eligen con cuotas de ANTES del cierre (Pinnacle pre vs mejor cuota pre).
 * El cierre de Pinnacle solo se usa DESPUÉS para medir CLV; nunca para decidir.
"""
import csv, io, json, math, os, sys, datetime as dt, urllib.request
import numpy as np

try:
    from scipy.optimize import minimize
except Exception:  # sin scipy no hay modelo, pero el resto sigue
    minimize = None

BASE = os.environ.get('FDCO_BASE', 'https://www.football-data.co.uk/mmz4281/{}/{}.csv')
OUT = os.environ.get('FDCO_OUT', 'data')
LIGAS = ['E0', 'SP1', 'D1', 'I1', 'F1', 'N1', 'P1']
EXTRA = ['B1', 'T1', 'G1', 'SC0', 'E1']          # ligas "blandas" para comparar en el backtest
NOMBRE = {'E0': 'Premier', 'SP1': 'La Liga', 'D1': 'Bundesliga', 'I1': 'Serie A', 'F1': 'Ligue 1', 'N1': 'Eredivisie',
          'P1': 'Liga Portugal', 'B1': 'Bélgica', 'T1': 'Turquía', 'G1': 'Grecia', 'SC0': 'Escocia', 'E1': 'Championship'}
FDCODE = {'E0': 'PL', 'SP1': 'PD', 'D1': 'BL1', 'I1': 'SA', 'F1': 'FL1', 'N1': 'DED', 'P1': 'PPL'}
ACTUAL, HIST = '2627', ['2122', '2223', '2324', '2425', '2526']
EVAL = {'2223', '2324', '2425', '2526'}
XI = 0.0025          # decaimiento por día (un partido de hace 1 año pesa ~40%)
BLOQUE = 28          # días entre reajustes en el walk-forward
VENTANA = 1100       # días máximos de historia para ajustar
UMBRAL_MIN = 100     # partidos mínimos para ajustar una liga

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


# ---------------------------------------------------------------- utilidades
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
    return None


def num(r, k):
    try:
        v = float(r[k])
        return v if v == v else None
    except Exception:
        return None


def avg(a):
    a = [x for x in a if x is not None]
    return round(sum(a) / len(a), 2) if a else None


def nov(odds):
    z = sum(1 / x for x in odds)
    return [1 / x / z for x in odds]


def nov_pot(odds):
    """Quita el margen por el método de la potencia: reparte más margen a los outsiders (corrige el sesgo favorito-longshot)."""
    q = [1 / x for x in odds]
    lo, hi = 1.0, 6.0
    for _ in range(60):
        mid = (lo + hi) / 2
        if sum(v ** mid for v in q) > 1:
            lo = mid
        else:
            hi = mid
    c = (lo + hi) / 2
    return [v ** c for v in q]


def trio(r, pref):
    v = [num(r, pref + s) for s in 'HDA']
    return v if all(x and x > 1 for x in v) else None


def mejor_pre(r):
    """Mejor cuota antes del cierre: columnas Max* o, si no existen, el máximo de las casas disponibles."""
    m = trio(r, 'Max')
    if m:
        return m
    out = []
    for s in 'HDA':
        c = [num(r, b + s) for b in ('B365', 'BW', 'IW', 'WH', 'VC', 'PS')]
        c = [x for x in c if x and x > 1]
        if not c:
            return None
        out.append(max(c))
    return out


def fila(r, temporada):
    d = fecha(r)
    if d is None:
        return None
    hg, ag = int(float(r['FTHG'])), int(float(r['FTAG']))
    return dict(d=d, s=temporada, h=r['HomeTeam'], a=r['AwayTeam'], hg=hg, ag=ag,
                ps=trio(r, 'PS'), pc=trio(r, 'PSC'), best=mejor_pre(r), b365=trio(r, 'B365'),
                libros=[x for x in (trio(r, b) for b in ('B365', 'BW', 'IW', 'WH', 'VC')) if x])


# ---------------------------------------------------------------- Dixon-Coles
def ajustar(partidos, ref):
    """Ajusta ataque/defensa por equipo, ventaja local y rho con peso decreciente en el tiempo."""
    if minimize is None:
        return None
    P = [m for m in partidos if 0 <= (ref - m['d']).days <= VENTANA]
    if len(P) < UMBRAL_MIN:
        return None
    eq = sorted({m['h'] for m in P} | {m['a'] for m in P})
    ix = {t: i for i, t in enumerate(eq)}
    T = len(eq)
    hi = np.array([ix[m['h']] for m in P]); ai = np.array([ix[m['a']] for m in P])
    hg = np.array([m['hg'] for m in P], float); ag = np.array([m['ag'] for m in P], float)
    w = np.exp(-XI * np.array([(ref - m['d']).days for m in P], float))
    m00 = (hg == 0) & (ag == 0); m01 = (hg == 0) & (ag == 1); m10 = (hg == 1) & (ag == 0); m11 = (hg == 1) & (ag == 1)
    REG = 2.0

    def nll(p):
        att = p[:T] - p[:T].mean(); dfn = p[T:2 * T] - p[T:2 * T].mean()
        mu, hfa, rho = p[2 * T], p[2 * T + 1], p[2 * T + 2]
        lh = np.exp(mu + hfa + att[hi] + dfn[ai]); la = np.exp(mu + att[ai] + dfn[hi])
        tau = np.ones_like(lh)
        tau[m00] = 1 - lh[m00] * la[m00] * rho
        tau[m01] = 1 + lh[m01] * rho
        tau[m10] = 1 + la[m10] * rho
        tau[m11] = 1 - rho
        tau = np.maximum(tau, 1e-6)
        ll = np.log(tau) + hg * np.log(lh) - lh + ag * np.log(la) - la
        return -(w * ll).sum() + REG * (att @ att + dfn @ dfn)

    x0 = np.zeros(2 * T + 3); x0[2 * T] = 0.2; x0[2 * T + 1] = 0.25
    bnds = [(None, None)] * (2 * T + 2) + [(-0.3, 0.3)]
    r = minimize(nll, x0, method='L-BFGS-B', bounds=bnds, options={'maxiter': 300})
    p = r.x
    att = p[:T] - p[:T].mean(); dfn = p[T:2 * T] - p[T:2 * T].mean()
    return dict(mu=float(p[2 * T]), hfa=float(p[2 * T + 1]), rho=float(p[2 * T + 2]),
                eq={t: (float(att[i]), float(dfn[i])) for t, i in ix.items()})


FACT = [math.factorial(k) for k in range(12)]


def rejilla(lh, la, rho, N=10):
    ph = np.array([math.exp(-lh) * lh ** k / FACT[k] for k in range(N)])
    pa = np.array([math.exp(-la) * la ** k / FACT[k] for k in range(N)])
    G = np.outer(ph, pa)
    G[0, 0] *= max(1 - lh * la * rho, 1e-6); G[0, 1] *= max(1 + lh * rho, 1e-6)
    G[1, 0] *= max(1 + la * rho, 1e-6); G[1, 1] *= max(1 - rho, 1e-6)
    return G / G.sum()


def predecir(M, H, A):
    if not M or H not in M['eq'] or A not in M['eq']:
        return None
    ah, dh = M['eq'][H]; aa, da = M['eq'][A]
    lh = math.exp(M['mu'] + M['hfa'] + ah + da); la = math.exp(M['mu'] + aa + dh)
    G = rejilla(lh, la, M['rho'])
    return [float(np.tril(G, -1).sum()), float(np.trace(G)), float(np.triu(G, 1).sum())]


# ---------------------------------------------------------------- backtest
REGLA = 'Regla de la app: >5% y al menos 3 casas por encima de lo justo'


def regla_app(i, c, k='pps'):
    """Misma regla que la app: la mejor cuota de las casas conocidas paga >5% sobre Pinnacle (pre) y >=3 casas pagan más de lo justo."""
    ps = c[k][i]
    ok = [b[i] for b in c['libros'] if b[i] * ps - 1 > 0]
    if len(ok) >= 3 and max(ok) * ps - 1 > 0.05:
        return max(ok)
    return None


def _si(cond, price):
    return price if cond else None


ESTRAT = [
    (REGLA, regla_app),
    ('Regla de la app con margen quitado por potencia', lambda i, c: regla_app(i, c, 'ppw')),
    ('Mejor cuota (Max) vs Pinnacle (pre, potencia) >5%', lambda i, c: _si(c['best'][i] * c['ppw'][i] - 1 > 0.05, c['best'][i])),
    ('Regla de la app y el modelo coincide', lambda i, c: regla_app(i, c) if c['dc'] is not None and c['dc'][i] > c['pps'][i] else None),
    ('Mejor cuota (columna Max) vs Pinnacle (pre) >5%', lambda i, c: _si(c['best'][i] * c['pps'][i] - 1 > 0.05, c['best'][i])),
    ('Mejor cuota (columna Max) vs Pinnacle (pre) >2%', lambda i, c: _si(c['best'][i] * c['pps'][i] - 1 > 0.02, c['best'][i])),
    ('Solo Bet365 vs Pinnacle (pre) >3%', lambda i, c: _si(c['b365'] is not None and c['b365'][i] * c['pps'][i] - 1 > 0.03, c['b365'][i] if c['b365'] else None)),
    ('Solo el modelo (EV>5% vs mejor cuota)', lambda i, c: _si(c['dc'] is not None and c['dc'][i] * c['best'][i] - 1 > 0.05, c['best'][i])),
]


def nuevo():
    return {n: [0, 0.0, 0.0, 0.0, 0.0] for n, _ in ESTRAT}   # n, sum ret, sum ret², sum clv, sum clv²


def acumular(S, c):
    for nom, f in ESTRAT:
        for i in range(3):
            price = f(i, c)
            if price:
                ret = price - 1 if c['out'][i] else -1.0
                clv = price * c['pc'][i] - 1
                a = S[nom]; a[0] += 1; a[1] += ret; a[2] += ret * ret; a[3] += clv; a[4] += clv * clv


def resumen(a):
    n, sr, sr2, sc, sc2 = a
    if not n:
        return dict(n=0, roi=None, roi_ic=None, clv=None, clv_ic=None)
    mr, mc = sr / n, sc / n
    vr = max(sr2 / n - mr * mr, 0); vc = max(sc2 / n - mc * mc, 0)
    return dict(n=n, roi=round(mr * 100, 2), roi_ic=round(1.96 * math.sqrt(vr / n) * 100, 2),
                clv=round(mc * 100, 2), clv_ic=round(1.96 * math.sqrt(vc / n) * 100, 2))


def backtest(datos):
    S = nuevo(); porliga = {}
    B = dict(n=0, bm=0.0, bp=0.0, bc=0.0, lm=0.0, lp=0.0, lc=0.0)
    for l, todos in datos.items():
        todos = sorted(todos, key=lambda m: m['d'])
        ev = [m for m in todos if m['s'] in EVAL]
        if not ev:
            continue
        inicio = ev[0]['d']; SL = nuevo(); modelo = None; bl = -1
        for m in ev:
            blq = (m['d'] - inicio).days // BLOQUE
            if blq != bl:
                bl = blq; ref = m['d']
                modelo = ajustar([x for x in todos if x['d'] < ref], ref)
            if not (m['ps'] and m['pc'] and m['best']):
                continue
            out = [1, 0, 0] if m['hg'] > m['ag'] else [0, 1, 0] if m['hg'] == m['ag'] else [0, 0, 1]
            c = dict(best=m['best'], b365=m['b365'], libros=m['libros'], pps=nov(m['ps']), ppw=nov_pot(m['ps']), pc=nov(m['pc']), out=out, dc=predecir(modelo, m['h'], m['a']))
            if c['dc'] is not None:
                B['n'] += 1
                for k, pr in (('m', c['dc']), ('p', c['pps']), ('c', c['pc'])):
                    B['b' + k] += sum((p - o) ** 2 for p, o in zip(pr, out))
                    B['l' + k] += -math.log(max(sum(p * o for p, o in zip(pr, out)), 1e-9))
            acumular(S, c); acumular(SL, c)
        porliga[l] = SL
        print('  liga', l, 'hecha', flush=True)
    return S, porliga, B


# ---------------------------------------------------------------- main
def main():
    os.makedirs(OUT, exist_ok=True)
    teams, refs, datos, finales = {}, {}, {}, {}
    for l in LIGAS + EXTRA:
        hist = []
        for s in HIST:
            hist += [f for f in (fila(r, s) for r in bajar(s, l)) if f]
        if l in LIGAS:
            rows = sorted([r for r in bajar(ACTUAL, l) if fecha(r)], key=fecha)
            por = {}
            for r in rows:
                for t, c, cc, y in ((r['HomeTeam'], 'HC', 'AC', 'HY'), (r['AwayTeam'], 'AC', 'HC', 'AY')):
                    por.setdefault(t, []).append((num(r, c), num(r, cc), num(r, y)))
                if r.get('Referee'):
                    refs.setdefault(r['Referee'], []).append((num(r, 'HY'), num(r, 'AY'), num(r, 'HC'), num(r, 'AC')))
            for t, v in por.items():
                v = v[-5:]
                teams[ALIAS.get(t, t)] = {'cf': avg([x[0] for x in v]), 'ca': avg([x[1] for x in v]), 'cards': avg([x[2] for x in v]), 'n': len(v)}
            actual = [f for f in (fila(r, ACTUAL) for r in rows) if f]
            M = ajustar(hist + actual, dt.datetime.now())
            if M:
                finales[FDCODE[l]] = dict(mu=round(M['mu'], 4), hfa=round(M['hfa'], 4), rho=round(M['rho'], 4),
                                          teams={ALIAS.get(t, t): {'a': round(a, 4), 'd': round(d, 4)} for t, (a, d) in M['eq'].items()})
        datos[l] = hist
        print(l, len(hist), 'partidos históricos', flush=True)

    refs = {k: {'cards': avg([(a or 0) + (b or 0) for a, b, _, _ in v]), 'corners': avg([(c or 0) + (d or 0) for _, _, c, d in v]), 'n': len(v)} for k, v in refs.items()}
    ahora = dt.datetime.now(dt.timezone.utc).isoformat()

    S, PL, B = backtest(datos)
    if B['n'] or any(a[0] for a in S.values()):
        n = max(B['n'], 1)
        rep = dict(generado=ahora, partidos_modelo=B['n'],
                   brier={'modelo': round(B['bm'] / n, 4), 'pinnacle_pre': round(B['bp'] / n, 4), 'pinnacle_cierre': round(B['bc'] / n, 4)},
                   logloss={'modelo': round(B['lm'] / n, 4), 'pinnacle_pre': round(B['lp'] / n, 4), 'pinnacle_cierre': round(B['lc'] / n, 4)},
                   estrategias=[dict(nombre=k, **resumen(v)) for k, v in S.items()],
                   por_liga=[dict(liga=NOMBRE.get(l, l), **resumen(SL[REGLA])) for l, SL in PL.items()])
        json.dump(rep, open(os.path.join(OUT, 'backtest.json'), 'w'), ensure_ascii=False)
        print(f"BACKTEST walk-forward. Brier (menor=mejor): modelo {rep['brier']['modelo']} | Pinnacle pre {rep['brier']['pinnacle_pre']} | Pinnacle cierre {rep['brier']['pinnacle_cierre']}")
        for e in rep['estrategias']:
            print(f"  {e['nombre']}: n={e['n']} ROI={e['roi']}% ±{e['roi_ic']} CLV={e['clv']}% ±{e['clv_ic']}")
        for e in rep['por_liga']:
            print(f"  liga {e['liga']}: n={e['n']} ROI={e['roi']}% ±{e['roi_ic']} CLV={e['clv']}%")
    if finales:
        json.dump(dict(updated=ahora, ligas=finales), open(os.path.join(OUT, 'model.json'), 'w'), ensure_ascii=False)
        print('modelo Dixon-Coles guardado para', ', '.join(finales))
    if not teams:
        sys.exit('Sin datos de football-data.co.uk')
    json.dump({'updated': ahora, 'teams': teams, 'refs': refs}, open(os.path.join(OUT, 'fdco.json'), 'w'), ensure_ascii=False)
    print(len(teams), 'equipos guardados')


if __name__ == '__main__':
    main()
