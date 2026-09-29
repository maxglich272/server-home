const { chromium } = require('/home/claude/mock/node_modules/playwright');
(async () => {
  const b = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium' });
  const p = await b.newPage({ viewport: { width: 1100, height: 760 } });
  p.on('pageerror', e => console.log('PAGEERROR', e.message));
  await p.goto('http://127.0.0.1:8766/'); await p.waitForTimeout(1200);
  await p.screenshot({ path: 'w1.png' });
  // móvil
  const m = await b.newPage({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2 });
  await m.goto('http://127.0.0.1:8765/'); await m.waitForTimeout(1500);
  await m.screenshot({ path: 'm1.png', fullPage: false });
  // playit: desvincular y vincular
  const q = await b.newPage({ viewport: { width: 1100, height: 800 } });
  q.on('dialog', d => d.accept());
  await q.goto('http://127.0.0.1:8765/'); await q.waitForTimeout(1500);
  await q.click('#playitBox details summary'); await q.waitForTimeout(300);
  await q.click('#bPlayitUnlink'); await q.waitForTimeout(2500);
  await q.screenshot({ path: 'p1.png', clip: { x: 0, y: 0, width: 1100, height: 700 } });
  await q.click('#bPlayit'); await q.waitForTimeout(700);
  await q.screenshot({ path: 'p2.png', clip: { x: 0, y: 0, width: 1100, height: 760 } });
  await q.waitForTimeout(9000);
  await q.screenshot({ path: 'p3.png', clip: { x: 0, y: 0, width: 1100, height: 760 } });
  await b.close();
})();
