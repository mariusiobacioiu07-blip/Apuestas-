// Subir a GitHub como: api/understat.js  (sustituye al anterior)
// Understat ya no incluye los datos en el HTML: ahora los sirve por un endpoint interno
// (/getLeagueData/LIGA/AÑO) que exige la cookie de la portada y la cabecera X-Requested-With.
const LIGAS = ['EPL', 'La_liga', 'Bundesliga', 'Serie_A', 'Ligue_1'];
const BASE = 'https://understat.com';
const UA = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36';

const media = (a, k) =>
  a.length ? +(a.reduce((s, x) => s + parseFloat(x[k]), 0) / a.length).toFixed(2) : null;

module.exports = async (req, res) => {
  const { league, season } = req.query;
  try {
    if (!LIGAS.includes(league) || !/^\d{4}$/.test(season || '')) throw new Error('Parámetros no válidos');

    // 1) cookies de la portada
    const home = await fetch(BASE, { headers: { 'User-Agent': UA, 'Accept-Language': 'en' } });
    const cookie = (home.headers.getSetCookie?.() || []).map((c) => c.split(';')[0]).join('; ');

    // 2) datos de la liga
    const r = await fetch(`${BASE}/getLeagueData/${league}/${season}`, {
      headers: {
        'User-Agent': UA,
        'X-Requested-With': 'XMLHttpRequest',
        Accept: 'application/json, text/javascript, */*; q=0.01',
        Referer: `${BASE}/league/${league}/${season}`,
        ...(cookie ? { Cookie: cookie } : {}),
      },
    });
    if (!r.ok) throw new Error('Understat respondió ' + r.status);
    const txt = await r.text();
    let data;
    try { data = JSON.parse(txt); } catch { throw new Error('Understat no devolvió JSON: ' + txt.slice(0, 80)); }
    if (!data.teams) throw new Error('Respuesta sin campo teams. Campos: ' + Object.keys(data).join(','));

    const teams = {};
    for (const t of Object.values(data.teams)) {
      const hist = [...t.history].sort((a, b) => (a.date < b.date ? -1 : 1));
      const l5 = hist.slice(-5);
      const casa = hist.filter((x) => x.h_a === 'h');
      const fuera = hist.filter((x) => x.h_a === 'a');
      teams[t.title] = {
        n: hist.length,
        l5: { xg: media(l5, 'xG'), xga: media(l5, 'xGA') },
        h: { xg: media(casa, 'xG'), xga: media(casa, 'xGA') },
        a: { xg: media(fuera, 'xG'), xga: media(fuera, 'xGA') },
      };
    }

    res.setHeader('Cache-Control', 's-maxage=21600, stale-while-revalidate=3600');
    res.json({ teams });
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
};
