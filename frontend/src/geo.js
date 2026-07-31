// City / state centroid coordinates [lng, lat] for placing map bubbles, plus a
// simple equirectangular projection over India's bounding box. Self-contained
// (no tiles, no external services). Extend freely for more places.

export const INDIA_BBOX = [67.5, 6.5, 98.5, 37.5]; // minLng, minLat, maxLng, maxLat

const PLACES = {
  // major cities
  delhi: [77.21, 28.61], "new delhi": [77.21, 28.61], mumbai: [72.88, 19.08],
  bangalore: [77.59, 12.97], bengaluru: [77.59, 12.97], chennai: [80.27, 13.08],
  pune: [73.86, 18.52], hyderabad: [78.47, 17.38], kolkata: [88.36, 22.57],
  ahmedabad: [72.57, 23.03], jaipur: [75.79, 26.91], lucknow: [80.95, 26.85],
  surat: [72.83, 21.17], kanpur: [80.33, 26.45], nagpur: [79.09, 21.15],
  indore: [75.86, 22.72], bhopal: [77.41, 23.26], patna: [85.14, 25.59],
  chandigarh: [76.78, 30.73], kochi: [76.27, 9.93], cochin: [76.27, 9.93],
  coimbatore: [76.96, 11.02], visakhapatnam: [83.22, 17.69], vizag: [83.22, 17.69],
  gurgaon: [77.03, 28.46], gurugram: [77.03, 28.46], noida: [77.39, 28.54],
  thiruvananthapuram: [76.95, 8.52], trivandrum: [76.95, 8.52], guwahati: [91.74, 26.14],
  bhubaneswar: [85.82, 20.30], ranchi: [85.31, 23.34], raipur: [81.63, 21.25],
  dehradun: [78.03, 30.32], amritsar: [74.87, 31.63], ludhiana: [75.85, 30.90],
  vadodara: [73.19, 22.31], nashik: [73.79, 19.99], rajkot: [70.80, 22.30],
  madurai: [78.12, 9.93], mysore: [76.65, 12.30], mysuru: [76.65, 12.30],
  goa: [73.83, 15.49], panaji: [73.83, 15.49], faridabad: [77.31, 28.41],
  srinagar: [74.80, 34.08], jammu: [74.86, 32.73], leh: [77.58, 34.15],
  // states / UTs (centroids)
  maharashtra: [75.71, 19.75], karnataka: [75.71, 15.32], "tamil nadu": [78.66, 11.13],
  "uttar pradesh": [80.95, 26.85], "west bengal": [87.85, 22.99], gujarat: [71.19, 22.26],
  rajasthan: [74.22, 27.02], telangana: [79.02, 18.11], kerala: [76.27, 10.85],
  "andhra pradesh": [79.74, 15.91], "madhya pradesh": [78.66, 22.97], bihar: [85.31, 25.10],
  punjab: [75.34, 31.15], haryana: [76.09, 29.06], odisha: [85.10, 20.95],
  assam: [92.94, 26.20], jharkhand: [85.28, 23.61], chhattisgarh: [81.87, 21.28],
  uttarakhand: [79.02, 30.07], "himachal pradesh": [77.17, 31.10], goa_state: [74.12, 15.30],
  "jammu and kashmir": [76.00, 34.20], "jammu & kashmir": [76.00, 34.20], ladakh: [77.50, 34.50],
};

export function coordFor(name) {
  if (name == null) return null;
  return PLACES[String(name).trim().toLowerCase()] || null;
}

// how many of these names we can place on the map (0..1)
export function mappableFraction(names) {
  if (!names.length) return 0;
  return names.filter((n) => coordFor(n)).length / names.length;
}

export function makeProjection(bbox, width, height, pad = 12) {
  const [minLng, minLat, maxLng, maxLat] = bbox;
  const w = width - pad * 2, h = height - pad * 2;
  const sx = w / (maxLng - minLng);
  const sy = h / (maxLat - minLat);
  const s = Math.min(sx, sy);                    // keep aspect (avoid stretching)
  const offX = pad + (w - s * (maxLng - minLng)) / 2;
  const offY = pad + (h - s * (maxLat - minLat)) / 2;
  return ([lng, lat]) => [offX + (lng - minLng) * s, offY + (maxLat - lat) * s];
}
