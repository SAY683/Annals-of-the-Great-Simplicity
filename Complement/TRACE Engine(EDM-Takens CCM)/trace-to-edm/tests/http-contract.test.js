'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const os = require('node:os');
const path = require('node:path');
const http = require('node:http');

const tempProjects = path.join(os.tmpdir(), `t2e_http_contract_${process.pid}`);
process.env.TRACE_TO_EDM_PROJECTS_DIR = tempProjects;
process.env.TRACE_TO_EDM_TRAJECTORY_CSV = path.join(tempProjects, 'narrative_meta_trajectories.csv');

const { createApp } = require('../src/app');

function listen(app) {
  return new Promise((resolve, reject) => {
    const server = http.createServer(app);
    server.once('error', reject);
    server.listen(0, '127.0.0.1', () => resolve(server));
  });
}

test('app exposes the split route groups', () => {
  const app = createApp({ getPort: () => 0 });
  const paths = app._router.stack
    .filter(layer => layer.route)
    .map(layer => layer.route.path);
  for (const expected of [
    '/api/health', '/api/version', '/api/status', '/api/trajectory',
    '/api/run', '/api/replay', '/api/edm/trigger', '/api/inputs',
    '/api/dataset', '/api/models', '/api/projects', '/api/work-scan',
  ]) {
    assert.ok(paths.includes(expected), `missing route ${expected}`);
  }
});

test('core read endpoints respond over HTTP', async () => {
  const app = createApp({ getPort: () => 0 });
  const server = await listen(app);
  const { port } = server.address();
  try {
    for (const route of ['/api/health', '/api/version', '/api/status', '/api/trajectory']) {
      const response = await fetch(`http://127.0.0.1:${port}${route}`);
      assert.equal(response.status, 200, `${route} -> ${response.status}`);
    }
  } finally {
    await new Promise(resolve => server.close(resolve));
  }
});