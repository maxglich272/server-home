const { chromium } = require('/home/claude/mock/node_modules/playwright');
(async () => {
  const b = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium' });
  const p = await b.newPage({ viewport: { width: 1180, height: 1000 } });
  p.on('pageerror', e => console.log('PAGEERROR', e.message));
  p.on('console', m => { if (m.type() === 'error') console.log('CONSOLE', m.text()); });
  await p.goto('http://127.0.0.1:8765/'); await p.waitForTimeout(1500);
  await p.selectOption('#serverPick', 'taller-de-max'); await p.waitForTimeout(1500);
  await p.screenshot({ path: 'u1.png', fullPage: true });
  await p.selectOption('#serverPick', 'serverfiles-1-0'); await p.waitForTimeout(1500);
  await p.screenshot({ path: 'u2.png' });
  await p.click('#btnAdd'); await p.waitForTimeout(500); await p.screenshot({ path: 'u3.png' });
  await p.click('#seg button[data-s=launcher]'); await p.waitForTimeout(1200); await p.screenshot({ path: 'u4.png' });
  await p.click('[data-inst="0"]'); await p.waitForTimeout(2500); await p.screenshot({ path: 'u5.png', fullPage: true });
  await p.click('#bCancelImport'); await p.waitForTimeout(500);
  await p.click('#btnAdd'); await p.click('#seg button[data-s=plain]'); await p.waitForTimeout(1200); await p.screenshot({ path: 'u6.png' });
  await b.close();
})();
