// Subir a GitHub como: api/odds.js
// Intermediario para The Odds API (clave gratuita en the-odds-api.com). La clave viaja en la cabecera x-token.
module.exports = async (req, res) => {
  try {
    const sport = req.query.sport || '';
    if (!/^soccer_[a-z0-9_]+$/.test(sport)) throw new Error('Deporte no válido');
    const key = req.headers['x-token'] || '';
    const url = `https://api.the-odds-api.com/v4/sports/${sport}/odds?regions=eu&markets=h2h,totals&oddsFormat=decimal&apiKey=${encodeURIComponent(key)}`;
    const r = await fetch(url);
    const j = await r.json();
    res.setHeader('x-requests-remaining', r.headers.get('x-requests-remaining') || '');
    res.status(r.status).json(j);
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
};
