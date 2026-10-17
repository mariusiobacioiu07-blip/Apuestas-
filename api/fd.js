// Subir a GitHub como: api/fd.js
// Pequeño intermediario por si el navegador bloquea la llamada directa a football-data.org.
module.exports = async (req, res) => {
  const path = req.query.path || '';
  try {
    if (!/^\/(competitions|teams|matches)\//.test(path)) throw new Error('Ruta no válida');
    const r = await fetch('https://api.football-data.org/v4' + path, {
      headers: { 'X-Auth-Token': req.headers['x-token'] || '' },
    });
    res.status(r.status).json(await r.json());
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
};
