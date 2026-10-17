// Subir a GitHub como: api/sofascore.js
// Datos de Sofascore (API no oficial, la misma que usa EasySoccerData): xG, córners, tarjetas y bajas.
// Puede fallar (403) desde Vercel si Sofascore bloquea la IP; la app lo ignora y sigue sin estos datos.
const B = 'https://api.sofascore.com/api/v1';
const HD = {
  'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36',
  Accept: 'application/json', 'Accept-Language': 'en', Referer: 'https://www.sofascore.com/', Origin: 'https://www.sofascore.com',
};
const j = async (p) => { const r = await fetch(B + p, { headers: HD }); if (!r.ok) throw new Error('Sofascore ' + r.status + ' en ' + p); return r.json(); };
const avg = (a) => { a = a.filter((x) => x != null && !isNaN(x)); return a.length ? +(a.reduce((s, x) => s + x, 0) / a.length).toFixed(2) : null; };
const limpia = (n) => n.replace(/\b(FC|CF|AFC|SC|AC|AS|RC|RCD|CD|UD|SSC|1899|1846)\b/g, '').replace(/\s+/g, ' ').trim();
const POS = { G: 'G', D: 'D', M: 'M', F: 'F' };

async function teamId(name) {
  const r = await j('/search/all?q=' + encodeURIComponent(limpia(name)));
  const t = (r.results || []).find((x) => x.type === 'team' && x.entity?.sport?.slug === 'football' && !x.entity?.national);
  if (!t) throw new Error('Equipo no encontrado: ' + name);
  return t.entity.id;
}

async function equipo(id, rivalId) {
  const ev = (await j(`/team/${id}/events/last/0`)).events || [];
  const ult = ev.filter((e) => e.status?.type === 'finished').sort((a, b) => a.startTimestamp - b.startTimestamp).slice(-5);
  const filas = await Promise.all(ult.map(async (e) => {
    try {
      const loc = e.homeTeam.id === id;
      const items = ((await j(`/event/${e.id}/statistics`)).statistics || [])[0]?.groups?.flatMap((g) => g.statisticsItems) || [];
      const v = (k) => { const it = items.find((x) => x.key === k); if (!it) return [null, null]; const a = [it.homeValue ?? parseFloat(it.home), it.awayValue ?? parseFloat(it.away)]; return loc ? a : [a[1], a[0]]; };
      return { xg: v('expectedGoals'), c: v('cornerKicks'), y: v('yellowCards') };
    } catch { return null; }
  }));
  const f = filas.filter(Boolean);
  const out = {
    xg: avg(f.map((x) => x.xg[0])), xga: avg(f.map((x) => x.xg[1])),
    cf: avg(f.map((x) => x.c[0])), ca: avg(f.map((x) => x.c[1])), cards: avg(f.map((x) => x.y[0])), n: f.length, bajas: [],
  };
  try {
    const prox = ((await j(`/team/${id}/events/next/0`)).events || []).find((e) => e.homeTeam.id === rivalId || e.awayTeam.id === rivalId);
    if (prox) {
      const lu = await j(`/event/${prox.id}/lineups`);
      const lado = prox.homeTeam.id === id ? lu.home : lu.away;
      out.bajas = (lado?.missingPlayers || []).filter((m) => m.type === 'missing').map((m) => ({ n: m.player?.name, pos: POS[m.player?.position] || '?' }));
    }
  } catch { /* alineaciones aún no publicadas */ }
  return out;
}

module.exports = async (req, res) => {
  try {
    const { home, away } = req.query;
    if (!home || !away) throw new Error('Faltan equipos');
    const [a, b] = await Promise.all([teamId(home), teamId(away)]);
    const [h, v] = await Promise.all([equipo(a, b), equipo(b, a)]);
    res.setHeader('Cache-Control', 's-maxage=3600, stale-while-revalidate=1800');
    res.json({ home: h, away: v });
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
};
