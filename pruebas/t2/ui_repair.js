// Interfaz de la barra de carga (crear → encender) y de los arreglos automáticos (reparando, «Se arregló solo»,
// Detener mientras arregla, opción en Ajustes).
const { chromium } = require('/home/claude/mock/node_modules/playwright');
const fs = require('fs');
const results = []; const ok = (c, m) => { results.push((c ? 'OK   ' : 'FAIL ') + m); };
const IDS = JSON.parse(fs.readFileSync('/home/claude/t2/ui_repair_ids.json', 'utf8'));
const mock = (path, body) => fetch('http://127.0.0.1:9911' + path, { method: 'POST', body: JSON.stringify(body || {}) }).then(r => r.json());
(async () => {
  const b = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium' });
  const p = await b.newPage({ viewport: { width: 1200, height: 900 } });
  const errors = []; p.on('pageerror', e => errors.push(e.message)); p.on('console', m => { if (m.type() === 'error') errors.push(m.text()); });
  const apiGet = path => p.evaluate(u => fetch('/api/' + u).then(r => r.json()), path);
  const view = () => p.evaluate(() => ({
    prog: !document.querySelector('#vProg').classList.contains('hide'),
    fixing: document.querySelector('#vProg').classList.contains('fixing'),
    label: document.querySelector('#vProgLabel').textContent, pct: document.querySelector('#vProgPct').textContent,
    width: parseFloat(document.querySelector('#vProgBar').style.width) || 0,
    detail: document.querySelector('#vProgDetail').textContent, status: document.querySelector('#vStatus').textContent,
    power: document.querySelector('#power').textContent.trim(),
    fixed: !document.querySelector('#vFixed').classList.contains('hide') ? document.querySelector('#vFixed').textContent : '',
  }));
  const watch = async (until, ms = 60000, every = 250) => {
    const snaps = [], t = Date.now();
    while (Date.now() - t < ms) { const v = await view(); snaps.push(v); if (until(v)) break; await p.waitForTimeout(every); }
    return snaps;
  };
  await p.goto('http://127.0.0.1:8765/'); await p.waitForTimeout(1200);

  // ---- 1) crear un servidor: la barra aparece al tiro y avanza hasta que enciende ----
  fs.writeFileSync('/tmp/fakeserver-slow', '400 10');
  await mock('/__slow', { java: 4 });
  await p.click('#btnAdd'); await p.click('#seg button[data-s=plain]');
  await p.click('#types .type[data-type=vanilla]');
  await p.waitForFunction(() => document.querySelector('#nPick .vp-input')?.value, null, { timeout: 10000 });
  await p.fill('#nPick .vp-input', '1.20.1'); await p.press('#nPick .vp-input', 'Enter');
  await p.fill('#nName', 'Con barra'); await p.check('#nEula');
  await p.click('#bCreatePlain');
  const snaps = await watch(v => v.status.startsWith('Encendido'), 90000);
  const withProg = snaps.filter(v => v.prog);
  ok(withProg.length >= 5 && snaps.findIndex(v => v.prog) <= 2, `la barra aparece apenas se crea (${withProg.length} lecturas con barra)`);
  ok(withProg.every(v => /^\d{1,2}%$/.test(v.pct)), 'muestra el porcentaje: ' + [...new Set(withProg.map(v => v.pct))].join(' '));
  ok(withProg.some(v => v.label === 'Preparando Java 17' && /Descargando Java 17: \d de 3 MB · paso 1 de 4 · \d+ s/.test(v.detail)),
    'dice qué hace, cuánto lleva descargado, en qué paso va y el tiempo: ' + (withProg.find(v => v.detail.includes('MB')) || {}).detail);
  ok(withProg.some(v => v.label.startsWith('Encendiendo por primera vez')) && withProg.some(v => v.detail.includes('paso 4 de 4')), 'sigue con el primer encendido (paso 4 de 4)');
  const widths = withProg.map(v => v.width);
  ok(widths.every((w, i) => i === 0 || w >= widths[i - 1]) && widths[widths.length - 1] - widths[0] >= 40, `la barra solo avanza (${widths[0]}% → ${widths[widths.length - 1]}%)`);
  const end = snaps[snaps.length - 1];
  ok(end.status.startsWith('Encendido') && !end.prog, 'al quedar encendido la barra se va: ' + end.status);
  fs.unlinkSync('/tmp/fakeserver-slow');

  // captura de la barra (mitad del encendido) para revisar cómo se ve
  const servers = (await apiGet('state')).servers, C = servers.find(s => s.name === 'Con barra').id;
  await p.evaluate(id => fetch(`/api/servers/${id}/stop`, { method: 'POST' }), C);
  await p.waitForTimeout(1500);
  fs.writeFileSync('/tmp/fakeserver-slow', '600 10');
  await p.waitForFunction(() => document.querySelector('#power').textContent.trim() === 'Encender', null, { timeout: 10000 });
  await p.click('#power');
  await watch(v => v.prog && parseInt(v.pct) >= 25, 20000, 150);
  await p.screenshot({ path: '/home/claude/t2/rp-progress.png', clip: { x: 0, y: 0, width: 1200, height: 420 } });
  const again = await watch(v => v.status.startsWith('Encendido'), 30000);
  ok(again.some(v => v.prog && v.label && !v.label.startsWith('Encendiendo por primera vez')), 'al encender de nuevo también hay barra: ' + (again.find(v => v.prog) || {}).label);
  fs.unlinkSync('/tmp/fakeserver-slow');
  await p.evaluate(id => fetch(`/api/servers/${id}/stop`, { method: 'POST' }), C);
  await p.waitForTimeout(1200);

  // ---- 2) arreglo automático: «Arreglando un problema…» y luego «Se arregló solo» ----
  await mock('/__slow', { mr: 3 });
  await p.evaluate(id => selectServer(id), IDS.repair); await p.waitForTimeout(1200);
  await p.waitForFunction(() => document.querySelector('#power').textContent.trim() === 'Encender', null, { timeout: 10000 });
  await p.click('#power');
  const fixSnaps = await watch(v => v.status.startsWith('Encendido'), 60000);
  const fixing = fixSnaps.filter(v => v.status === 'Arreglando un problema…');
  ok(fixing.length >= 2 && fixing.every(v => v.power === 'Detener'), `mientras arregla dice «Arreglando un problema…» y el botón es «Detener» (${fixing.length} lecturas)`);
  ok(fixing.some(v => v.prog && v.fixing && v.label === 'Descargando libdep'), 'la barra (en ámbar) dice qué arregla: ' + (fixing.find(v => v.prog) || {}).label);
  ok(!fixSnaps.some(v => /^Error|no pudo encender/.test(v.status)), 'no muestra el error mientras lo arregla');
  await p.waitForSelector('#vFixed:not(.hide)', { timeout: 10000 });
  const fixedText = await p.textContent('#vFixed');
  ok(fixedText.includes('Se arregló solo:') && fixedText.includes('Descargué libdep-2.0.jar'), 'cuando enciende avisa qué se arregló: ' + fixedText.replace(/\s+/g, ' ').slice(0, 90));
  await p.screenshot({ path: '/home/claude/t2/rp-fixed.png', clip: { x: 0, y: 0, width: 1200, height: 460 } });
  await p.click('#bFixedOk'); await p.waitForTimeout(1300);
  ok(!(await p.isVisible('#vFixed')) && (await apiGet('servers/' + IDS.repair)).repairs.length === 0, '«Entendido» cierra el aviso');
  await p.evaluate(id => fetch(`/api/servers/${id}/stop`, { method: 'POST' }), IDS.repair);
  await p.waitForTimeout(1200);

  // ---- 2b) no se pudo arreglar solo: el error dice qué mod fue y ofrece el botón ----
  await p.evaluate(id => selectServer(id), IDS.culprit); await p.waitForTimeout(1500);
  const st = await p.textContent('#vStatus');
  ok(st === 'El servidor no pudo encender por el mod «Broken hubx».', 'el error dice qué mod lo botó: ' + st);
  const hintTxt = await p.textContent('#vHint');
  ok(hintTxt.includes('9 mods lo necesitan') && await p.isVisible('#bFix') && (await p.textContent('#bFix')) === 'Desactivar broken-hubx.jar y los que lo necesitan',
    'explica y ofrece desactivarlo con un botón: ' + (await p.textContent('#bFix')));
  await p.screenshot({ path: '/home/claude/t2/rp-culprit.png', clip: { x: 0, y: 0, width: 1200, height: 520 } });

  // ---- 3) Detener mientras arregla ----
  await p.evaluate(id => selectServer(id), IDS.cancel); await p.waitForTimeout(1200);
  await p.waitForFunction(() => document.querySelector('#power').textContent.trim() === 'Encender', null, { timeout: 10000 });
  await p.click('#power');
  await watch(v => v.status === 'Arreglando un problema…', 20000, 150);
  await p.waitForTimeout(400);
  await p.screenshot({ path: '/home/claude/t2/rp-fixing.png', clip: { x: 0, y: 0, width: 1200, height: 420 } });
  ok((await view()).power === 'Detener', 'el botón grande dice «Detener»');
  await p.click('#power');
  await p.waitForTimeout(1300);
  let v = await view();
  ok(v.status === 'Apagado' && !v.prog && v.power === 'Encender', 'Detener lo apaga y quita la barra: ' + v.status);
  await p.waitForTimeout(3500);
  v = await view();
  ok(v.status === 'Apagado', 'y no se vuelve a encender solo');
  await mock('/__slow', {});

  // ---- 4) opción en Ajustes ----
  await p.click('.tab[data-t=settings]'); await p.waitForTimeout(800);
  ok(await p.isChecked('#sAutoFix'), '«Arreglar problemas solo» viene activado');
  await p.uncheck('#sAutoFix'); await p.click('#bSaveBasic'); await p.waitForTimeout(800);
  ok((await apiGet('servers/' + IDS.cancel)).auto_fix === false, 'se puede desactivar');
  await p.check('#sAutoFix'); await p.click('#bSaveBasic'); await p.waitForTimeout(800);
  ok((await apiGet('servers/' + IDS.cancel)).auto_fix === true, 'y volver a activar');

  // ---- Rendimiento: Java optimizado y mods de rendimiento
  ok(await p.isChecked('#sJavaOpt') && await p.isVisible('#perfMods') && (await p.textContent('#perfModsText')).includes('Lithium, FerriteCore y ModernFix'),
    'tarjeta «Rendimiento»: Java optimizado activado y el botón de mods para Fabric');
  await p.uncheck('#sJavaOpt'); await p.click('#bSavePerf'); await p.waitForTimeout(800);
  ok((await apiGet('servers/' + IDS.cancel)).java_opt === false, 'se puede apagar «Optimizar Java»');
  await p.check('#sJavaOpt'); await p.click('#bSavePerf'); await p.waitForTimeout(800);
  ok((await apiGet('servers/' + IDS.cancel)).java_opt === true, 'y volver a encender');
  await p.click('#bPerfMods');
  await p.waitForSelector('.modal-bg.open [data-a="1"]', { timeout: 5000 });
  ok((await p.textContent('.modal-bg.open')).includes('mods de rendimiento'), 'pregunta antes de agregar mods');
  await p.click('.modal-bg.open [data-a="1"]');
  await p.waitForFunction(() => document.querySelector('#perfMsg').textContent.includes('Agregué'), null, { timeout: 30000 });
  ok((await p.textContent('#perfMsg')).includes('Lithium') && (await p.textContent('#perfMsg')).includes('ModernFix'), 'agrega los mods y dice cuáles: ' + await p.textContent('#perfMsg'));
  await p.screenshot({ path: '/home/claude/t2/rp-perf.png', clip: await (await p.$('#perfCard')).boundingBox() });

  // ---- 5) celular ----
  const m = await b.newPage({ viewport: { width: 390, height: 844 } });
  await m.goto('http://127.0.0.1:8765/'); await m.waitForTimeout(1000);
  await m.evaluate(id => selectServer(id), C); await m.waitForTimeout(800);
  await m.waitForFunction(() => document.querySelector('#power').textContent.trim() === 'Encender', null, { timeout: 10000 });
  fs.writeFileSync('/tmp/fakeserver-slow', '600 10');
  await m.click('#power');
  await m.waitForFunction(() => !document.querySelector('#vProg').classList.contains('hide') && parseInt(document.querySelector('#vProgPct').textContent) >= 20, null, { timeout: 20000 });
  const over = await m.evaluate(() => document.documentElement.scrollWidth > window.innerWidth);
  ok(!over, 'en celular la barra cabe sin desplazar la página');
  await m.screenshot({ path: '/home/claude/t2/rp-mobile.png', clip: { x: 0, y: 0, width: 390, height: 520 } });
  fs.unlinkSync('/tmp/fakeserver-slow');

  ok(errors.length === 0, 'sin errores de JavaScript' + (errors.length ? ': ' + errors.join(' | ') : ''));
  await b.close();
  console.log(results.join('\n'));
  process.exit(results.some(r => r.startsWith('FAIL')) ? 1 : 0);
})().catch(e => { console.log(results.join('\n')); console.log('ERROR', e.message); process.exit(2); });
