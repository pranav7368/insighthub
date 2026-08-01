// PNG / PDF export.
//
// html-to-image and jsPDF are ~350 kB together and are needed only when
// someone actually clicks Export — which most sessions never do. They are
// imported dynamically so Vite splits them into their own chunk and the
// dashboard's first paint does not pay for them.

// Elements marked .no-export (e.g. the export buttons themselves) are skipped
// so they don't appear in the captured image.
const skipChrome = (node) => !(node.classList && node.classList.contains("no-export"));

async function capture(node) {
  const { toPng } = await import("html-to-image");
  const bg = getComputedStyle(document.body).backgroundColor || "#ffffff";
  return toPng(node, {
    backgroundColor: bg,
    pixelRatio: 2,
    cacheBust: true,
    filter: skipChrome,
    style: { margin: "0" },
  });
}

function stamp(name) {
  const d = new Date().toISOString().slice(0, 10);
  return `${(name || "dashboard").replace(/[^a-z0-9_-]+/gi, "_")}_${d}`;
}

export async function exportPng(node, name) {
  const dataUrl = await capture(node);
  const a = document.createElement("a");
  a.href = dataUrl;
  a.download = `${stamp(name)}.png`;
  a.click();
}

export async function exportPdf(node, name) {
  const dataUrl = await capture(node);
  const { default: jsPDF } = await import("jspdf");

  const img = new Image();
  await new Promise((res, rej) => { img.onload = res; img.onerror = rej; img.src = dataUrl; });

  const pdf = new jsPDF("p", "mm", "a4");
  const pageW = 210, pageH = 297;
  const imgH = (img.height / img.width) * pageW;   // full-width, preserve ratio
  let heightLeft = imgH;
  let position = 0;
  pdf.addImage(dataUrl, "PNG", 0, position, pageW, imgH);
  heightLeft -= pageH;
  while (heightLeft > 0) {                          // tile the tall capture across A4 pages
    position -= pageH;
    pdf.addPage();
    pdf.addImage(dataUrl, "PNG", 0, position, pageW, imgH);
    heightLeft -= pageH;
  }
  pdf.save(`${stamp(name)}.pdf`);
}
