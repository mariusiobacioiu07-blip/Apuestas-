// Subir a GitHub como: api/sofa.js
// Uso personal. API no oficial de Sofascore: puede bloquear las peticiones desde Vercel.
//   Prueba rápida:  https://TU-APP.vercel.app/api/sofa?test=1
//   Consulta libre: https://TU-APP.vercel.app/api/sofa?path=/event/123456/lineups
const BASE = 'https://api.sofascore.com/api/v1';
const HEADERS = {
  'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36',
  Accept: 'application/json',
  'Accept-Language': 'en-US,en;q=0.9',
  Referer: 'https://www.sofascore.com/',
  Origin: 'https://www.sofascore.com',
};

async function get(path) {
  const r = await fetch(BASE + path, { headers: HEADERS });
  const t = await r.text();
  let j = null;
  try { j = JSON.parse(t); } catch {}
  return { status: r.status, json: j, bloqueado: j === null };
}

const dia = (d) => d.toISOString().slice(0, 10);

module.exports = async (req, res) => {
  try {
    if (req.query.test) {
      const rep = {};
      const hoy = new Date(), ayer = new Date(Date.now() - 864e5);
      let ev = null;
      for (const d of [hoy, ayer]) {
        const a = await get(`/sport/football/scheduled-events/${dia(d)}`);
        rep['partidos_' + dia(d)] = a.bloqueado ? { status: a.status, error: 'bloqueado o sin JSON' } : { status: a.status, total: a.json.events?.length ?? 0 };
        ev = ev || a.json?.events?.find((e) => e.status?.type === 'finished');
      }
      if (!ev) return res.json({ ...rep, aviso: 'No pude obtener ningún partido terminado para probar el resto' });

      rep.partido_de_prueba = `${ev.homeTeam.name} vs ${ev.awayTeam.name} (${ev.tournament?.name})`;
      const id = ev.id;

      const l = await get(`/event/${id}/lineups`);
      rep.alineaciones = l.bloqueado ? { status: l.status } : {
        status: l.status,
        bajas_local: l.json.home?.missingPlayers?.length ?? 'no hay campo',
        bajas_visitante: l.json.away?.missingPlayers?.length ?? 'no hay campo',
      };

      const s = await get(`/event/${id}/statistics`);
      rep.estadisticas = s.bloqueado ? { status: s.status } : { status: s.status, trae_xG: JSON.stringify(s.json).includes('xpected goals') };

      const h = await get(`/event/${id}/h2h`);
      rep.cara_a_cara = h.bloqueado ? { status: h.status } : { status: h.status, ok: true };

      return res.json(rep);
    }

    const path = req.query.path || '';
    if (!/^\/(sport|unique-tournament|event|team|config)\//.test(path) || path.includes('..')) throw new Error('Ruta no válida');
    const r = await get(path);
    if (r.bloqueado) return res.status(r.status || 502).json({ error: 'Sofascore bloqueó la petición', status: r.status });
    if (r.status === 200) res.setHeader('Cache-Control', 's-maxage=900, stale-while-revalidate=600');
    res.status(r.status).json(r.json);
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
};
