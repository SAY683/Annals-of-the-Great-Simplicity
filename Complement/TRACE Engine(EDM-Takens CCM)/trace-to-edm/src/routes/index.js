module.exports = function mountRoutes(app, ctx) {
  require('./core')(app, ctx);
  require('./trajectory')(app, ctx);
  require('./pipeline')(app, ctx);
  require('./edm')(app, ctx);
  require('./dataset')(app, ctx);
  require('./models')(app, ctx);
  require('./projects')(app, ctx);
};
