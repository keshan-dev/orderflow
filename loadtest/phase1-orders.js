// Order load test for Phase 1 (M8). Run it through nginx, ideally with the chaos script.
//
//   k6 run -e BASE_URL=http://localhost:8080 -e VUS=10 -e DURATION=180s \
//     --summary-export results/phase-1/<date>-orders.json loadtest/phase1-orders.js
//
// Every virtual user has its own X-Client-Id, so the rate limit (per client) does not
// dominate the run. About 1 in 10 iterations sends the same order twice with the same
// Idempotency-Key on purpose: both answers must name the same order.
import http from 'k6/http';
import { check, sleep } from 'k6';
import { Counter } from 'k6/metrics';

const BASE = __ENV.BASE_URL || 'http://localhost:8080';
const REPEAT_SHARE = Number(__ENV.REPEAT_SHARE || 0.1);

const accepted = new Counter('orders_accepted');
const limited = new Counter('orders_rate_limited');
const repeatsMatching = new Counter('repeats_same_order');
const repeatsDifferent = new Counter('repeats_different_order');

export const options = {
  vus: Number(__ENV.VUS || 10),
  duration: __ENV.DURATION || '60s',
  thresholds: {
    // During chaos a few requests may fail while nginx notices a dead container.
    checks: ['rate>0.98'],
    repeats_different_order: ['count==0'],
  },
};

export function setup() {
  const res = http.get(`${BASE}/api/products`, { timeout: '10s' });
  if (res.status !== 200) {
    throw new Error(`cannot load products: ${res.status}`);
  }
  // Leave out the 10-piece lamp so most orders can succeed; the lamp is tested elsewhere.
  return { products: res.json().filter((p) => p.available > 20).map((p) => p.id) };
}

function placeOrder(body, key) {
  return http.post(`${BASE}/api/orders`, body, {
    timeout: '10s',
    tags: { name: 'POST /api/orders' },
    headers: {
      'Content-Type': 'application/json',
      'Idempotency-Key': key,
      'X-Client-Id': `k6-vu-${__VU}`,
    },
    responseCallback: http.expectedStatuses(202, 429),
  });
}

export default function (data) {
  const product = data.products[Math.floor(Math.random() * data.products.length)];
  const body = JSON.stringify({
    customer_email: `load-${__VU}@example.com`,
    items: [{ product_id: product, quantity: 1 }],
  });
  const key = `k6-${__VU}-${__ITER}-${Date.now()}`;

  const first = placeOrder(body, key);
  if (first.status === 429) {
    limited.add(1);
    sleep(Number(first.headers['Retry-After'] || 1));
    return;
  }
  const ok = check(first, { 'order accepted (202)': (r) => r.status === 202 });
  if (!ok) {
    return;
  }
  accepted.add(1);

  if (Math.random() < REPEAT_SHARE) {
    const again = placeOrder(body, key); // the same request again, as a retrying client would
    if (again.status === 202) {
      if (again.json('order_id') === first.json('order_id')) {
        repeatsMatching.add(1);
      } else {
        repeatsDifferent.add(1);
      }
    }
  }
  sleep(0.2);
}
