function wrapHandler(handler) {
  if (typeof handler !== 'function' || handler.length === 4) return handler;
  return function wrapped(req, res, next) {
    try {
      const result = handler(req, res, next);
      if (result && typeof result.then === 'function') return result.catch(next);
      return result;
    } catch (error) {
      return next(error);
    }
  };
}

function installAsyncBoundary(app) {
  for (const method of ['get', 'post', 'put', 'patch', 'delete']) {
    const original = app[method].bind(app);
    app[method] = (...args) => original(...args.map(arg => (typeof arg === 'function' ? wrapHandler(arg) : arg)));
  }
  return app;
}

module.exports = { wrapHandler, installAsyncBoundary };
