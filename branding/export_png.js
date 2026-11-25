// Usage: node branding/export_png.js [dir]  – renders PNG versions of the SVGs in dir (default static/brand)
const { chromium } = require('playwright'); const fs = require('fs'); const DIR = (process.argv[2] || 'static/brand').replace(/\/$/, '') + '/';
(async () => {
  const b = await chromium.launch();
  const jobs = [
    ['hoteli-mark.svg', 'favicon-16.png', 16, 16], ['hoteli-mark.svg', 'favicon-32.png', 32, 32], ['hoteli-mark.svg', 'favicon-48.png', 48, 48],
    ['hoteli-mark.svg', 'hoteli-mark-512.png', 512, 512], ['hoteli-app-icon.svg', 'apple-touch-icon.png', 180, 180],
    ['hoteli-app-icon.svg', 'icon-192.png', 192, 192], ['hoteli-app-icon.svg', 'icon-512.png', 512, 512],
    ['hoteli-logo.svg', 'hoteli-logo.png', 1200, null], ['hoteli-logo-light.svg', 'hoteli-logo-light.png', 1200, null],
    ['hoteli-logo-tagline.svg', 'hoteli-logo-tagline.png', 1200, null], ['hoteli-logo-stacked.svg', 'hoteli-logo-stacked.png', 800, null],
    ['social-preview.svg', 'social-preview.png', 1280, 640],
  ];
  for (const [src, out, w, hFixed] of jobs) {
    const svg = fs.readFileSync(DIR + src, 'utf8');
    const m = svg.match(/viewBox="0 0 ([\d.]+) ([\d.]+)"/); const vw = +m[1], vh = +m[2];
    const h = hFixed || Math.round(w * vh / vw);
    const p = await b.newPage({ viewport: { width: w, height: h } });
    await p.setContent(`<html><body style="margin:0;background:transparent"><img src="data:image/svg+xml;base64,${Buffer.from(svg).toString('base64')}" style="display:block;width:${w}px;height:${h}px"></body></html>`);
    await p.waitForTimeout(80);
    await p.screenshot({ path: DIR + out, omitBackground: true, clip: { x: 0, y: 0, width: w, height: h } });
    await p.close();
    console.log(out, w + 'x' + h);
  }
  await b.close();
})();
