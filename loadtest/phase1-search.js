// Search traffic for the zero downtime reindex test (M6).
// Run:  k6 run -e BASE_URL=http://127.0.0.1:8001 loadtest/phase1-search.js
// The test fails if any request fails or returns something other than 200.
import http from 'k6/http';
import { check } from 'k6';

export const options = {
  vus: Number(__ENV.VUS || 5),
  duration: __ENV.DURATION || '40s',
  thresholds: {
    http_req_failed: ['rate==0'],
    checks: ['rate==1'],
  },
};

const BASE = __ENV.BASE_URL || 'http://127.0.0.1:8001';
const TERMS = ['lamp', 'lamps', 'keyboard', 'mouse', 'headphones', 'confirmed', 'cancelled'];

export default function () {
  const term = TERMS[Math.floor(Math.random() * TERMS.length)];
  const res = http.get(`${BASE}/api/orders/search?q=${term}`, {
    timeout: '5s',
    tags: { name: 'search' },
  });
  check(res, { 'status is 200': (r) => r.status === 200 });
}
