// 2.5.5: pantalla de inicio, reiniciar, jugadores y buscador de modpacks
const { chromium } = require('/home/claude/mock/node_modules/playwright');
const results = []; const ok = (c, m) => { results.push((c ? 'OK   ' : 'FAIL ') + m); };
(async () => {
  const b = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium' });
  const p = await b.newPage({ viewport: { width: 1280, height: 860 } });
  const errors = []; p.on('pageerror', e => errors.push(e.message)); p.on('console', m => { if (m.type() === 'error' && !/mc-heads|Failed to load resource/.test(m.text())) errors.push(m.text()); });
  const apiGet = u => p.evaluate(x => fetch('/api/' + x).then(r => r.json()), u);
  const apiPost = (u, bd) => p.evaluate(([x, y]) => fetch('/api/' + x, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(y || {}) }).then(r => r.json()), [u, bd]);
  await p.goto('http://127.0.0.1:8765/'); await p.waitForTimeout(1500);
  const st = await apiGet('state');
  ok(await p.isVisible('#home') && (await p.$$('#srvGrid .srv[data-srv]')).length === st.servers.length, `inicio con ${st.servers.length} servidores para elegir`);
  await p.screenshot({ path: 'n-home.png' });
  const on = st.servers.find(s => s.status === 'en línea') || st.servers[0];
  if (on.status !== 'en línea') { await apiPost(`servers/${on.id}/start`); }
  await p.click(`[data-srv="${on.id}"]`); await p.waitForTimeout(600);
  await p.waitForFunction(() => document.querySelector('#vStatus').textContent.startsWith('Encendido'), null, { timeout: 90000 });
  ok(!(await p.isDisabled('#restart')), 'reiniciar se puede usar con el servidor encendido');
  // jugadores
  await apiPost(`servers/${on.id}/command`, { command: 'join Alex' }); await p.waitForTimeout(1500);
  ok((await p.textContent('#vPlayers')).includes('Alex') && /\(\d+\)/.test(await p.textContent('#tabPlayersN')), 'la ficha y la pestaña muestran quién está jugando');
  await p.screenshot({ path: 'n-server.png' });
  await p.click('.tab[data-t=players]'); await p.waitForTimeout(900);
  ok((await p.textContent('#pList')).includes('Alex') && (await p.textContent('#pList')).includes('En línea'), 'la lista de jugadores muestra a Alex en línea');
  await p.click('#pList [data-pa=op][data-pn=Alex]'); await p.click('.modal [data-a="1"]');
  await p.waitForFunction(() => document.querySelector('#pList').textContent.includes('ADMIN'), null, { timeout: 8000 });
  ok(true, 'hacer admin desde la lista');
  await p.fill('#pAdd', 'Troll_99'); await p.click('[data-padd=ban]');
  ok(await p.isVisible('.modal .ask-in'), 'al banear se puede escribir el motivo');
  await p.fill('.modal .ask-in', 'Griefing'); await p.click('.modal [data-a="1"]');
  await p.waitForFunction(() => document.querySelector('#pList').textContent.includes('Troll_99'), null, { timeout: 8000 });
  await p.waitForTimeout(1200);
  ok((await p.textContent('#pList')).includes('BANEADO') && (await p.textContent('#pList')).includes('Griefing'), 'banear a alguien por su nombre, con el motivo');
  await p.screenshot({ path: 'n-players.png', fullPage: true });
  // reiniciar
  await p.click('#restart'); await p.click('.modal [data-a="1"]');
  await p.waitForFunction(() => !document.querySelector('#vStatus').textContent.startsWith('Encendido'), null, { timeout: 15000 });
  await p.waitForFunction(() => document.querySelector('#vStatus').textContent.startsWith('Encendido'), null, { timeout: 90000 });
  ok(true, 'reiniciar apaga y vuelve a encender');
  // buscador
  await p.click('#btnAdd'); await p.waitForTimeout(300);
  ok(await p.isVisible('#qPack'), 'el asistente abre en «Buscar»');
  await p.waitForSelector('#packResults .pack', { timeout: 10000 });
  ok((await p.textContent('#packResults')).includes('Volcanes de Prueba') && (await p.textContent('#packResults')).includes('sin soporte para servidor'), 'muestra los modpacks más descargados y avisa si uno no sirve para servidor');
  await p.fill('#qPack', 'volcanes'); await p.press('#qPack', 'Enter'); await p.waitForTimeout(800);
  await p.screenshot({ path: 'n-search.png' });
  await p.click('#packResults .pack'); await p.waitForSelector('[data-pv]', { timeout: 10000 });
  await p.click('[data-pv="0"]'); await p.waitForSelector('#wConfirm:not(.hide)', { timeout: 30000 });
  ok((await p.textContent('#cDetected')).includes('NeoForge 21.1.77') && (await p.textContent('#cKind')).includes('3 mods'), 'descarga el modpack elegido y muestra lo detectado');
  await p.click('#bCancelImport'); await p.waitForTimeout(300);
  await p.click('#btnAdd'); await p.click('#srcSw [data-src=curseforge]'); await p.waitForTimeout(600);
  ok(await p.isVisible('#cfKeyBox') && !(await p.isVisible('#qPack')), 'CurseForge pide la clave');
  await p.fill('#cfKey', 'clave-de-prueba-123456'); await p.click('#bCfKey');
  await p.waitForSelector('#packResults .pack', { timeout: 10000 });
  ok((await p.textContent('#packResults')).includes('Pack CF') && (await p.textContent('#cfKeyNow')).includes('…3456'), 'con la clave busca en CurseForge');
  await p.click('#packResults .pack'); await p.waitForSelector('[data-pv]', { timeout: 10000 });
  ok((await p.textContent('#pdVersions')).includes('con pack de servidor'), 'dice qué versiones traen pack de servidor');
  await p.screenshot({ path: 'n-cf.png' });
  await p.click('#bCfKeyDel'); await p.click('.modal [data-a="1"]'); await p.waitForTimeout(600);
  ok(await p.isVisible('#cfKeyBox'), 'se puede quitar la clave');
  await p.click('#srcFoot .btn'); await p.waitForTimeout(300);
  // celular
  const m = await b.newPage({ viewport: { width: 390, height: 844 } }); m.on('pageerror', e => errors.push(e.message));
  await m.goto('http://127.0.0.1:8765/'); await m.waitForTimeout(1200);
  await m.screenshot({ path: 'n-mobile-home.png' });
  await m.click(`[data-srv="${on.id}"]`); await m.waitForTimeout(900);
  await m.click('.tab[data-t=players]'); await m.waitForTimeout(900);
  ok(!(await m.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1)), 'sin desborde en celular (jugadores)');
  await m.screenshot({ path: 'n-mobile-players.png', fullPage: true });
  ok(errors.length === 0, 'sin errores de JavaScript' + (errors.length ? ': ' + errors.join(' | ') : ''));
  await b.close();
  console.log(results.join('\n'));
})();
