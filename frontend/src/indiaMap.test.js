import { describe, expect, it } from "vitest";
import indiaGeo from "./assets/india.geo.json";
import { INDIA_BBOX } from "./geo";

// India's map must show its official boundary. These places pin it, so a
// future swap of the outline data cannot quietly drop a territory.
const INSIDE = {
  "Muzaffarabad (PoK)": [73.47, 34.37],
  "Mirpur (PoK)": [73.75, 33.15],
  "Gilgit (Gilgit-Baltistan)": [74.31, 35.92],
  "Hunza (Gilgit-Baltistan)": [74.66, 36.32],
  "Shaksgam valley": [76.5, 36.0],
  "Aksai Chin": [79.4, 35.2],
  "Srinagar": [74.8, 34.08],
  "Leh": [77.58, 34.15],
  "Tawang (Arunachal Pradesh)": [91.86, 27.59],
  "South Andaman": [92.64, 11.75],
  "Car Nicobar": [92.8, 9.17],
  "Kavaratti (Lakshadweep)": [72.64, 10.565],
};
const OUTSIDE = {
  Lahore: [74.35, 31.55], Kabul: [69.17, 34.53], Kathmandu: [85.32, 27.71],
  Thimphu: [89.64, 27.47], Dhaka: [90.41, 23.81], Colombo: [79.86, 6.93],
};

const geom = indiaGeo.features[0].geometry;
const polygons = geom.type === "MultiPolygon" ? geom.coordinates : [geom.coordinates];

function inRing([x, y], ring) {
  let inside = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const [x1, y1] = ring[i], [x2, y2] = ring[j];
    if ((y1 > y) !== (y2 > y) && x < ((x2 - x1) * (y - y1)) / (y2 - y1) + x1) inside = !inside;
  }
  return inside;
}
const inIndia = (pt) => polygons.some(([outer, ...holes]) => inRing(pt, outer) && !holes.some((h) => inRing(pt, h)));

describe("India map outline", () => {
  it.each(Object.entries(INSIDE))("includes %s", (_name, pt) => {
    expect(inIndia(pt)).toBe(true);
  });

  it.each(Object.entries(OUTSIDE))("does not include %s", (_name, pt) => {
    expect(inIndia(pt)).toBe(false);
  });

  it("fits inside the map's projection box", () => {
    const [minLng, minLat, maxLng, maxLat] = INDIA_BBOX;
    for (const poly of polygons) for (const ring of poly) for (const [x, y] of ring) {
      expect(x >= minLng && x <= maxLng && y >= minLat && y <= maxLat).toBe(true);
    }
  });
});
