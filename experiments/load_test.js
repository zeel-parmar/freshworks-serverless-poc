// =============================================================================
// OPTIONAL, LOW-VOLUME k6 load test.  Do NOT run this until:
//   1. You have checked the AWS Billing console, and
//   2. scripts/invoke_api.sh works, and
//   3. you understand that every request can cost money.
//
// Default: 1 virtual user, 20 requests to GET /health, ~1 second apart (about 20 s).
// Hard caps inside this file: at most 3 users and 200 requests, whatever you pass.
// Stop the test at any time with Ctrl+C.
// The API itself also throttles bursts (see ThrottlingRateLimit in template.yaml).
//
// Run (from the project root):
//   k6 run -e BASE_URL=https://abc123.execute-api.ap-south-1.amazonaws.com experiments/load_test.js
//   k6 run -e BASE_URL=https://... -e ITERATIONS=50 -e VUS=2 experiments/load_test.js
//   k6 run -e BASE_URL=https://... -e PATH_NAME=/tickets -e METHOD=POST experiments/load_test.js
//
// Install k6: https://grafana.com/docs/k6/latest/set-up/install-k6/
// =============================================================================
import http from 'k6/http';
import { check, sleep, fail } from 'k6';

const BASE_URL = (__ENV.BASE_URL || '').replace(/\/$/, '');
const PATH_NAME = __ENV.PATH_NAME || '/health';
const METHOD = (__ENV.METHOD || 'GET').toUpperCase();
const VUS = Math.min(parseInt(__ENV.VUS || '1', 10), 3);
const ITERATIONS = Math.min(parseInt(__ENV.ITERATIONS || '20', 10), 200);
const SLEEP_SECONDS = parseFloat(__ENV.SLEEP_SECONDS || '1');

export const options = {
  scenarios: {
    low_volume: {
      executor: 'shared-iterations',
      vus: VUS,
      iterations: ITERATIONS,
      maxDuration: '5m',
    },
  },
  thresholds: {
    http_req_failed: ['rate<0.05'],
    http_req_duration: ['p(95)<2000'],
  },
};

export function setup() {
  if (!BASE_URL.startsWith('https://')) {
    fail('Set BASE_URL, for example: -e BASE_URL=https://abc123.execute-api.ap-south-1.amazonaws.com');
  }
  if (METHOD === 'POST' && PATH_NAME !== '/tickets') {
    fail('POST is only meant for PATH_NAME=/tickets');
  }
  console.log(`Sending ${ITERATIONS} ${METHOD} request(s) to ${BASE_URL}${PATH_NAME} with ${VUS} user(s).`);
}

export default function () {
  const url = `${BASE_URL}${PATH_NAME}`;
  let res;
  if (METHOD === 'POST') {
    const payload = JSON.stringify({
      subject: 'Synthetic k6 ticket',
      description: 'Synthetic data created by experiments/load_test.js',
      customerEmail: 'student@example.com',
    });
    res = http.post(url, payload, { headers: { 'Content-Type': 'application/json' } });
  } else {
    res = http.get(url);
  }
  check(res, { 'status is 2xx': (r) => r.status >= 200 && r.status < 300 });
  sleep(SLEEP_SECONDS);
}
