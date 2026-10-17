// Subir a GitHub como: api/understat.js  (Vercel la publica en /api/understat)
// Lee los datos que Understat incluye en la página de cada liga. No es una API oficial:
// si Understat cambia su web, esta función devolverá un error y la app usará API-Football.
const LIGAS = ['EPL', 'La_liga', 'Bundesliga', 'Serie_A', 'Ligue_1'];

const media = (a, k) =>
  a.length ? +(a.reduce((s, x) => s + parseFloat(x[k]), 0) / a.length).toFixed(2) : null;

module.exports = async (req, res) => {
  const { league, season } = req.query;
  try {
    if (!LIGAS.includes(league) || !/^\d{4}$/.test(season || '')) throw new Error('Parámetros no válidos');

    const r = await fetch(`https://understat.com/league/${league}/${season}`, {
      headers: { 'User-Agent': 'Mozilla/5.0', 'Accept-Language': 'en' },
    });
    if (!r.ok) throw new Error('Understat respondió ' + r.status);
    const html = await r.text();

    const m = html.match(/teamsData\s*=\s*JSON\.parse\('([^']+)'\)/);
    if (!m) throw new Error('Understat cambió su web: no encuentro teamsData');
    const data = JSON.parse(m[1].replace(/\\x([0-9A-Fa-f]{2})/g, (_, h) => String.fromCharCode(parseInt(h, 16))));

    const teams = {};
    for (const t of Object.values(data)) {
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
