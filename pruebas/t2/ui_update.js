// Interfaz de las actualizaciones: aviso de versión nueva con novedades, «Actualizar ahora» (pantalla de espera y
// recarga sola con la versión nueva), aviso «se actualizó», botón desactivado con servidores encendidos, pie con
// la versión, «Actualizar automáticamente» y «Buscar actualizaciones».
const { chromium } = require('/home/claude/mock/node_modules/playwright');
const fs = require('fs');
const results = []; const ok = (c, m) => { results.push((c ? 'OK   ' : 'FAIL ') + m); };
const URL = 'http://127.0.0.1:8781/';
const publish = v => fs.writeFileSync('/home/claude/t2/upd/publicar.txt', v);
(async () => {
  const b = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium' });
  const p = await b.newPage({ viewport: { width: 1200, height: 900 } });
  const errors = []; p.on('pageerror', e => errors.push(e.message)); p.on('console', m => { if (m.type() === 'error' && !/Failed to load resource|ERR_CONNECTION_REFUSED/.test(m.text())) errors.push(m.text()); });
  const api = (path, method = 'GET', body) => p.evaluate(([u, m, bd]) => fetch('/api/' + u, { method: m, headers: { 'Content-Type': 'application/json' }, body: bd ? JSON.stringify(bd) : undefined }).then(r => r.json()), [path, method, body]);
  await p.goto(URL); await p.waitForTimeout(1500);

  // ---- aviso de versión nueva
  await p.waitForSelector('#updBox:not(.hide)', { timeout: 15000 });
  const box = await p.textContent('#updBox');
  ok(box.includes('Hay una versión nueva de Servidor Home: 2.6.1') && box.includes('tienes la 2.6.0'), 'avisa la versión nueva y cuál tienes: ' + box.replace(/\s+/g, ' ').slice(0, 90));
  ok(box.includes('Aviso de versión nueva en la ventana') && box.includes('Se actualiza sola cuando no molesta'), 'muestra las novedades');
  ok(await p.isEnabled('#bUpdNow') && box.includes('se instala sola la próxima vez'), 'botón «Actualizar ahora» disponible');
  const foot = await p.textContent('#appFoot');
  ok(foot.includes('Servidor Home 2.6.0') && await p.isChecked('#updAuto') && foot.includes('Buscar actualizaciones'), 'el pie muestra la versión, «Actualizar automáticamente» y «Buscar actualizaciones»: ' + foot.replace(/\s+/g, ' '));
  await p.screenshot({ path: '/home/claude/t2/upd-banner.png', clip: { x: 0, y: 0, width: 1200, height: 330 } });

  // ---- actualizar ahora: pantalla de espera y la página vuelve sola con la versión nueva (y al mismo servidor)
  const srv0 = (await api('state')).servers[0];
  await p.evaluate(id => selectServer(id), srv0.id); await p.waitForTimeout(600);
  await p.click('#bUpdNow');
  await p.waitForSelector('#updOverlay', { timeout: 5000 });
  ok((await p.textContent('#updOverlay')).includes('Actualizando Servidor Home a la versión 2.6.1'), 'muestra «Actualizando…» mientras se reinicia');
  await p.screenshot({ path: '/home/claude/t2/upd-overlay.png', clip: { x: 0, y: 0, width: 1200, height: 500 } });
  await p.waitForFunction(() => !document.querySelector('#updOverlay') && document.querySelector('#appFoot')?.textContent.includes('2.6.1'), null, { timeout: 60000 });
  ok(true, 'la página se recargó sola con la versión 2.6.1');
  await p.waitForTimeout(800);
  ok(await p.evaluate(() => CUR) === srv0.id && await p.isVisible('#view') && !(await p.isVisible('#home')), 'tras actualizarse vuelve al mismo servidor');
  await p.waitForSelector('#updBox.ok:not(.hide)', { timeout: 10000 });
  const done = await p.textContent('#updBox');
  ok(done.includes('Servidor Home se actualizó a la versión 2.6.1.') && done.includes('Aviso de versión nueva en la ventana'), 'avisa que se actualizó, con las novedades');
  ok(!(await p.isVisible('#offline')), 'no mostró «Servidor Home está cerrado» durante el reinicio');
  await p.screenshot({ path: '/home/claude/t2/upd-done.png', clip: { x: 0, y: 0, width: 1200, height: 300 } });
  await p.click('#bUpdSeen'); await p.waitForTimeout(1300);
  ok(!(await p.isVisible('#updBox')), '«Entendido» cierra el aviso');

  // ---- con un servidor encendido el botón queda desactivado y lo explica
  const st = await api('state');
  const srv = st.servers[0];
  await p.evaluate(id => selectServer(id), srv.id); await p.waitForTimeout(500);
  await api(`servers/${srv.id}/start`, 'POST');
  await p.waitForFunction(() => document.querySelector('#vStatus')?.textContent.startsWith('Encendido'), null, { timeout: 60000 });
  publish('2.6.2');
  await p.waitForFunction(() => document.querySelector('#updBox')?.textContent.includes('2.6.2'), null, { timeout: 40000 });
  ok(await p.isDisabled('#bUpdNow') && (await p.textContent('#updBox')).includes('apaga los servidores'), 'con un servidor encendido: botón desactivado y explica por qué');
  await api(`servers/${srv.id}/stop`, 'POST');
  await p.waitForFunction(() => !document.querySelector('#bUpdNow')?.disabled, null, { timeout: 40000 });
  ok(true, 'al apagarlo el botón se activa');

  // ---- pie: apagar y encender «Actualizar automáticamente», buscar ahora
  await p.uncheck('#updAuto'); await p.waitForTimeout(1200);
  ok((await api('info')).update.auto === false, 'se puede apagar «Actualizar automáticamente»');
  await p.check('#updAuto'); await p.waitForTimeout(1200);
  ok((await api('info')).update.auto === true, 'y volver a encender');
  await p.click('#updCheck'); await p.waitForTimeout(400);
  ok((await p.textContent('body')).includes('Buscando versiones nuevas'), '«Buscar actualizaciones» avisa que está buscando');

  // ---- celular
  const m = await b.newPage({ viewport: { width: 390, height: 844 } });
  await m.goto(URL); await m.waitForTimeout(1800);
  ok(await m.isVisible('#home') && !(await m.isVisible('#view')), 'al abrir la app de nuevo empieza en la lista de servidores');
  ok(await m.isVisible('#updBox') && !(await m.evaluate(() => document.documentElement.scrollWidth > window.innerWidth)), 'en celular el aviso cabe sin desplazar la página');
  await m.screenshot({ path: '/home/claude/t2/upd-mobile.png', clip: { x: 0, y: 0, width: 390, height: 520 } });

  ok(errors.length === 0, 'sin errores de JavaScript' + (errors.length ? ': ' + errors.join(' | ') : ''));
  await b.close();
  console.log(results.join('\n'));
  process.exit(results.some(r => r.startsWith('FAIL')) ? 1 : 0);
})().catch(e => { console.log(results.join('\n')); console.log('ERROR', e.message); process.exit(2); });
