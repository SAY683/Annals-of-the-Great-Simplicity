const _apiCache = new Map();
const API_CACHE_TTL_MS = 5000;

function getCached(key) {
  const entry = _apiCache.get(key);
  if (!entry) return null;
  if (Date.now() > entry.expireAt) {
    _apiCache.delete(key);
    return null;
  }
  return entry.data;
}

function setCached(key, data) {
  _apiCache.set(key, { data, expireAt: Date.now() + API_CACHE_TTL_MS });
}

function invalidateCache(key) {
  if (key) _apiCache.delete(key);
  else _apiCache.clear();
}

module.exports = { getCached, setCached, invalidateCache };
