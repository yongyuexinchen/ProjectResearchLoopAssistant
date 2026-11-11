import assert from "node:assert/strict";
import test from "node:test";
import { centerDiagram, fitDiagram, resizeViewport, zoomAt } from "../lib/diagram-viewport.ts";

test("fits very large graphs without a minimum zoom cropping the diagram", () => {
  const actual = fitDiagram({ width: 20000, height: 10000 }, { width: 1000, height: 600 });
  assert.equal(actual.scale, 0.0476);
  assert.ok(Math.abs(actual.x - 24) < 1e-9);
  assert.ok(Math.abs(actual.y - 62) < 1e-9);
});

test("fit uses the limiting viewport dimension and centers without stretching", () => {
  assert.deepEqual(
    fitDiagram({ width: 1000, height: 2000 }, { width: 1000, height: 600 }),
    { scale: 0.276, x: 362, y: 24 },
  );
});

test("reset centers a graph at its intrinsic one-to-one size", () => {
  assert.deepEqual(
    centerDiagram({ width: 2000, height: 1000 }, { width: 1000, height: 600 }, 1),
    { scale: 1, x: -500, y: -200 },
  );
});

test("zoom keeps the diagram point underneath the cursor stationary", () => {
  assert.deepEqual(
    zoomAt({ scale: 0.5, x: 30, y: -10 }, 1, { x: 230, y: 90 }),
    { scale: 1, x: -170, y: -110 },
  );
});

test("zooming out preserves the anchor after the graph has been dragged", () => {
  assert.deepEqual(
    zoomAt({ scale: 2, x: -120, y: 60 }, 0.5, { x: 200, y: 100 }),
    { scale: 0.5, x: 120, y: 90 },
  );
});

test("resizing keeps the viewed graph point at the viewport center", () => {
  assert.deepEqual(
    resizeViewport({ scale: 2, x: -120, y: 60 }, { width: 1000, height: 600 }, { width: 600, height: 800 }),
    { scale: 2, x: -320, y: 160 },
  );
});
