import assert from 'node:assert/strict';
import test from 'node:test';

test('browser proxy follows the same public backend address as server requests', async () => {
  const savedOrigin = process.env.LOOP_API_ORIGIN;
  const savedPublic = process.env.NEXT_PUBLIC_API_BASE_URL;
  try {
    delete process.env.LOOP_API_ORIGIN;
    process.env.NEXT_PUBLIC_API_BASE_URL = 'http://127.0.0.1:8088/';
    const { default: config } = await import('../next.config.ts?public-fallback');
    assert.equal((await config.rewrites())[0].destination, 'http://127.0.0.1:8088/:path*');
  } finally {
    if (savedOrigin === undefined) delete process.env.LOOP_API_ORIGIN;
    else process.env.LOOP_API_ORIGIN = savedOrigin;
    if (savedPublic === undefined) delete process.env.NEXT_PUBLIC_API_BASE_URL;
    else process.env.NEXT_PUBLIC_API_BASE_URL = savedPublic;
  }
});
