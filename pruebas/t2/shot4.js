const { chromium } = require('/home/claude/mock/node_modules/playwright');
(async () => {
  const b = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium' });
  const p = await b.newPage({ viewport: { width: 1100, height: 900 } });
  p.on('pageerror', e => console.log('PAGEERROR', e.message));
  await p.goto('http://127.0.0.1:8765/'); await p.waitForTimeout(1500);
  await p.selectOption('#serverPick', 'taller-de-max'); await p.waitForTimeout(1200);
  await p.click('.tab[data-t=addons]'); await p.waitForTimeout(800);
  await p.screenshot({ path: 'x1.png' });
  await p.click('.tab[data-t=settings]'); await p.waitForTimeout(800);
  await p.screenshot({ path: 'x2.png', fullPage: true });
  const m = await b.newPage({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2 });
  await m.goto('http://127.0.0.1:8765/'); await m.waitForTimeout(1500);
  await m.screenshot({ path: 'x3.png' });
  await b.close();
})();
