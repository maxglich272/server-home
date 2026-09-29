// En la ventana de la app, los enlaces externos se mandan a /api/abrir (navegador predeterminado)
// y no abren ventanas nuevas; en el navegador normal se abren como siempre.
const { chromium } = require('/home/claude/mock/node_modules/playwright');
const results = []; const ok = (c, m) => { results.push((c ? 'OK   ' : 'FAIL ') + m); };
(async () => {
  const b = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium' });
  for (const appWindow of [true, false]) {
    const ctx = await b.newContext({ viewport: { width: 1200, height: 900 } });
    const p = await ctx.newPage();
    const errors = []; p.on('pageerror', e => errors.push(e.message));
    const opened = []; ctx.on('page', pg => opened.push(pg));
    const sent = [];
    await p.route('**/api/info', async route => {
      const r = await route.fetch(); const j = await r.json(); j.app_window = appWindow;
      await route.fulfill({ response: r, json: j });
    });
    await p.route('**/api/abrir', async route => { sent.push(route.request().postDataJSON()); await route.fulfill({ json: { ok: true } }); });
    await p.goto('http://127.0.0.1:8765/'); await p.waitForTimeout(1500);
    await p.click('#btnAdd'); await p.click('#seg button[data-s=plain]'); await p.waitForTimeout(800);
    const link = p.locator('label:has(#nEula) a');
    ok(await link.isVisible(), `[${appWindow ? 'ventana' : 'navegador'}] enlace del EULA visible`);
    await link.click(); await p.waitForTimeout(1500);
    if (appWindow) {
      ok(sent.length === 1 && sent[0].url === 'https://aka.ms/MinecraftEULA', '[ventana] el enlace se manda a /api/abrir: ' + JSON.stringify(sent));
      ok(opened.length === 0, '[ventana] no se abrió otra ventana del navegador');
      ok(!(await p.isChecked('#nEula')), '[ventana] el clic en el enlace no marca la casilla');
    } else {
      ok(sent.length === 0, '[navegador] no usa /api/abrir');
      ok(opened.length === 1, '[navegador] se abre en una pestaña nueva como siempre');
    }
    ok(errors.length === 0, `[${appWindow ? 'ventana' : 'navegador'}] sin errores de JavaScript ` + errors.join(' | '));
    await ctx.close();
  }
  await b.close();
  console.log(results.join('\n'));
  process.exit(results.some(r => r.startsWith('FAIL')) ? 1 : 0);
})().catch(e => { console.log(results.join('\n')); console.log('ERROR', e); process.exit(1); });
