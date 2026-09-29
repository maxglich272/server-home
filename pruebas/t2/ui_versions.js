// Interfaz del selector de versión: crear (buscar/escribir, atajos, snapshots, loader), cambiar la versión
// de un servidor (avisos, mundo nuevo, bloqueo si está encendido) e importar eligiendo versión.
const { chromium } = require('/home/claude/mock/node_modules/playwright');
const results = []; const ok = (c, m) => { results.push((c ? 'OK   ' : 'FAIL ') + m); };
(async () => {
  const b = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium' });
  const p = await b.newPage({ viewport: { width: 1200, height: 900 } });
  const errors = []; p.on('pageerror', e => errors.push(e.message)); p.on('console', m => { if (m.type() === 'error') errors.push(m.text()); });
  const apiGet = path => p.evaluate(u => fetch('/api/' + u).then(r => r.json()), path);
  const apiPost = (path, body) => p.evaluate(([u, bd]) => fetch('/api/' + u, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(bd || {}) }).then(r => r.json()), [path, body]);
  const waitStatus = async (id, st, ms = 30000) => { const t = Date.now(); while (Date.now() - t < ms) { const s = await apiGet('servers/' + id); if (st.includes(s.status)) return s; await p.waitForTimeout(400); } return null; };
  await p.goto('http://127.0.0.1:8765/'); await p.waitForTimeout(1500);
  const servers = (await apiGet('state')).servers;
  const V = servers.find(s => s.type === 'vanilla').id, F = servers.find(s => s.type === 'fabric' && !s.modpack).id, I = servers.find(s => s.type === 'fabric' && s.modpack).id;

  // ---- crear sin mods ----
  await p.click('#btnAdd'); await p.click('#seg button[data-s=plain]');
  await p.waitForFunction(() => document.querySelector('#nPick .vp-input')?.value, null, { timeout: 10000 });
  ok(await p.inputValue('#nPick .vp-input') === '26.3', 'por defecto la versión más nueva (26.3)');
  const chips = await p.$$eval('#nPick .vp-chip', els => els.map(e => e.dataset.v));
  ok(chips[0] === '26.3' && chips.includes('1.21.11') && chips.includes('1.8.9'), 'atajos a las versiones más usadas: ' + chips.join(', '));
  ok((await p.textContent('#nPick .vp-msg')).includes('Tus amigos tienen que entrar con Minecraft 26.3'), 'dice con qué versión entran los amigos');
  await p.click('#nPick .vp-input');
  ok(await p.isVisible('#nPick .vp-list') && (await p.$$('#nPick .vp-item')).length === 9, 'al hacer clic se abre la lista con todas las versiones (9)');
  await p.fill('#nPick .vp-input', '1.8');
  ok((await p.textContent('#nPick .vp-item')).includes('1.8.9'), 'escribir filtra la lista');
  await p.press('#nPick .vp-input', 'Enter');
  ok(await p.inputValue('#nPick .vp-input') === '1.8.9' && !(await p.isVisible('#nPick .vp-list')), 'Enter elige la versión 1.8.9');
  ok(await p.getAttribute('#nName', 'placeholder') === 'Vanilla 1.8.9', 'el nombre sugerido sigue la versión');
  await p.fill('#nPick .vp-input', '1.12'); await p.keyboard.press('ArrowDown'); await p.keyboard.press('Enter');
  ok(await p.inputValue('#nPick .vp-input') === '1.12.2', 'también con las flechas del teclado');
  await p.click('#nPick .vp-chip[data-v="1.21.11"]');
  ok(await p.inputValue('#nPick .vp-input') === '1.21.11' && await p.getAttribute('#nPick .vp-chip[data-v="1.21.11"]', 'class') === 'vp-chip act', 'los atajos eligen y se marcan');
  await p.fill('#nPick .vp-input', '1.99'); await p.press('#nPick .vp-input', 'Enter');
  ok((await p.getAttribute('#nPick .vp-msg', 'class')).includes('err') && (await p.textContent('#nPick .vp-msg')).includes('No encontré la versión «1.99»'), 'avisa si la versión no existe');
  await p.check('#nEula'); const before = (await apiGet('state')).servers.length;
  await p.click('#bCreatePlain'); await p.waitForTimeout(800);
  ok((await apiGet('state')).servers.length === before && await p.isVisible('.toast.err'), 'no crea el servidor con una versión inexistente');
  await p.check('#nPick .vp-snap'); await p.waitForTimeout(600); await p.click('#nPick .vp-open');
  ok((await p.textContent('#nPick .vp-list')).includes('26.4-snapshot-2'), 'con «snapshots» aparecen las versiones de prueba');
  await p.click('#nPick .vp-item >> text=26.4-snapshot-2');
  ok((await p.textContent('#nPick .vp-msg')).includes('Versión de prueba'), 'avisa que una snapshot es de prueba');
  await p.click('.type[data-type=fabric]'); await p.waitForTimeout(1200);
  ok(await p.isVisible('#nPick .vp-lwrap') && (await p.textContent('#nPick .vp-lname')) === 'Versión de Fabric' && (await p.$$('#nPick .vp-loader option')).length === 6, 'Fabric muestra sus versiones del loader (6)');
  ok(await p.inputValue('#nPick .vp-loader') === '0.16.14', 'con la recomendada elegida (0.16.14)');
  await p.evaluate(() => closeWizard());

  // ---- cambiar la versión de un servidor ----
  await p.evaluate(id => selectServer(id), F); await p.waitForTimeout(800);
  await p.click('.tab[data-t=settings]'); await p.waitForFunction(() => document.querySelector('#sPick .vp-input')?.value, null, { timeout: 10000 });
  await p.waitForTimeout(800);
  ok((await p.textContent('#vName')) === 'Fabric 1.21.8' && (await p.textContent('#verNow')).includes('Ahora: Fabric 0.17.0-beta · Minecraft 1.21.8') && (await p.textContent('#verNow')).includes('antes:'), 'muestra la versión actual y la anterior: ' + (await p.textContent('#verNow')));
  ok(await p.isDisabled('#bVersion') && (await p.textContent('#verOff')).includes('Elige otra versión'), 'botón desactivado si no cambias nada');
  await p.click('#sPick .vp-chip[data-v="1.21.1"]'); await p.waitForTimeout(900);
  ok((await p.textContent('#verWarn')).includes('Estás bajando de 1.21.8 a 1.21.1') && await p.isChecked('#verNewWorld'), 'al bajar de versión avisa y marca «mundo nuevo»');
  ok(!(await p.isDisabled('#bVersion')), 'botón activo');
  await p.click('#sPick .vp-chip[data-v="26.3"]'); await p.waitForTimeout(900);
  ok(!(await p.textContent('#verWarn')).includes('bajando') && !(await p.isChecked('#verNewWorld')), 'al subir de versión no hay aviso de mundo');
  await p.click('#sPick .vp-chip[data-v="1.21.1"]'); await p.waitForTimeout(900);
  await p.click('#bVersion'); await p.waitForSelector('.modal [data-a="1"]');
  const q = await p.textContent('.modal-bg.open .modal');
  ok(q.includes('pasará a Fabric 0.16.14 · Minecraft 1.21.1') && q.includes('respaldo') && q.includes('mundo nuevo'), 'pide confirmación explicando qué pasará: ' + q.replace(/\s+/g, ' ').slice(0, 300));
  await p.click('.modal [data-a="1"]');
  const sF = await waitStatus(F, ['detenido', 'error']);
  await p.waitForTimeout(2500);
  ok(sF && sF.status === 'detenido' && sF.mc_version === '1.21.1' && (await p.textContent('#vSub')).includes('Minecraft 1.21.1'), 'cambia la versión y la muestra arriba');
  ok(await p.isVisible('section[data-p=console]') && (await p.textContent('#console')).includes('Cambiando de versión'), 'muestra el avance en la consola');
  // servidor con mods
  await p.evaluate(id => selectServer(id), I); await p.waitForTimeout(800);
  await p.click('#bVerLink'); await p.waitForFunction(() => document.querySelector('#sPick .vp-input')?.value === '1.21.8', null, { timeout: 10000 });
  ok(await p.isVisible('section[data-p=settings]') && await p.isVisible('#verCard'), 'el enlace «cambiar versión» lleva a Ajustes');
  await p.click('#sPick .vp-chip[data-v="26.3"]'); await p.waitForTimeout(900);
  ok((await p.textContent('#verWarn')).includes('tiene 2 mods para Minecraft 1.21.8'), 'avisa que los mods son de otra versión');
  // encendido: no se puede
  await apiPost(`servers/${V}/start`); await waitStatus(V, ['en línea']);
  await p.evaluate(id => selectServer(id), V); await p.waitForTimeout(800);
  await p.click('.tab[data-t=settings]'); await p.waitForTimeout(1500);
  await p.click('#sPick .vp-chip[data-v="26.3"]'); await p.waitForTimeout(2500);
  ok(await p.isDisabled('#bVersion') && (await p.textContent('#verOff')).includes('Apaga el servidor'), 'con el servidor encendido no deja cambiar la versión');
  await apiPost(`servers/${V}/stop`); await waitStatus(V, ['detenido']); await p.waitForTimeout(2500);
  ok(!(await p.isDisabled('#bVersion')), 'al apagarlo se habilita solo');

  // ---- importar eligiendo versión ----
  await p.click('#btnAdd'); await p.setInputFiles('#packIn', '/home/claude/mock2/Fabulous.mrpack');
  await p.waitForSelector('#wConfirm:not(.hide)', { timeout: 30000 });
  await p.waitForFunction(() => document.querySelector('#cPick .vp-input')?.value && !document.querySelector('#cPick .vp-loader').disabled, null, { timeout: 10000 });
  ok(await p.inputValue('#cPick .vp-input') === '1.21.1' && await p.inputValue('#cPick .vp-loader') === '0.16.14' && await p.inputValue('#eType') === 'fabric', 'al importar muestra lo detectado (Fabric 0.16.14 · 1.21.1) listo para cambiar');
  ok((await p.textContent('#cVerWarn')) === '', 'sin avisos si no cambias nada');
  await p.fill('#cPick .vp-input', '1.21.8'); await p.press('#cPick .vp-input', 'Enter'); await p.waitForTimeout(900);
  ok((await p.textContent('#cVerWarn')).includes('Los mods de este modpack son para Minecraft 1.21.1'), 'avisa si eliges otra versión que la del modpack');
  await p.click('#bCancelImport'); await p.waitForTimeout(400);

  // ---- mod del jugador que bota el servidor: se desactiva solo y lo avisa ----
  const C = servers.find(s => s.name === 'Cliente').id;
  await p.evaluate(id => selectServer(id), C); await p.waitForTimeout(800);
  await p.click('#tabAddons'); await p.waitForTimeout(600);
  await p.setInputFiles('#fileIn', '/tmp/clientmod4.jar'); await p.waitForTimeout(1200);
  ok((await p.textContent('#addonList')).includes('clientmod4.jar'), 'sube un mod desde la pestaña Mods');
  await p.click('#power');
  let sC = await waitStatus(C, ['en línea', 'error'], 40000); await p.waitForTimeout(2500);
  ok(sC && sC.status === 'en línea' && (await p.isVisible('#vFixed')) && (await p.textContent('#vFixed')).includes('Desactivé clientmod4.jar'),
    'lo desactiva solo, enciende y avisa qué hizo: ' + (sC && sC.status) + ' ' + (await p.textContent('#vFixed')).replace(/\s+/g, ' ').slice(0, 80));
  await apiPost(`servers/${C}/stop`); await waitStatus(C, ['detenido']);

  // ---- con «Arreglar problemas solo» apagado: aviso y botón ----
  await p.evaluate(id => fetch(`/api/servers/${id}/settings`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ auto_fix: false }) }), C);
  await p.evaluate(id => fetch(`/api/servers/${id}/addons?name=clientmod4.jar.disabled`, { method: 'PUT' }), C);
  await p.waitForFunction(() => document.querySelector('#power').textContent.trim() === 'Encender', null, { timeout: 10000 });
  await p.click('#power'); await waitStatus(C, ['error']); await p.waitForTimeout(2500);
  ok(await p.isVisible('#vHint') && (await p.textContent('#bFix')).includes('Desactivar clientmod4.jar y reintentar') && (await p.textContent('#vHint')).includes('solo para el jugador'), 'explica qué pasó y ofrece desactivarlo');
  await p.click('#bFix');
  sC = await waitStatus(C, ['en línea'], 40000); await p.waitForTimeout(2500);
  ok(sC && !(await p.isVisible('#vHint')) && (await p.textContent('#vStatus')).includes('Encendido'), 'tras el clic enciende y el aviso desaparece: ' + JSON.stringify([sC && sC.status, await p.isVisible('#vHint'), await p.textContent('#vStatus')]) + (await apiGet('servers/' + C + '/log?since=0')).lines.slice(-8).map(l => l.s).join(' / '));
  await apiPost(`servers/${C}/stop`); await waitStatus(C, ['detenido']);
  await p.evaluate(id => fetch(`/api/servers/${id}/settings`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ auto_fix: true }) }), C);

  // ---- versión detectada que no está en la lista ----
  const t = await p.evaluate(async () => {
    const d = document.createElement('div'); document.body.appendChild(d);
    const pk = versionPicker(d, { type: 'vanilla', mc: '1.20.99', trusted: '1.20.99' });
    await new Promise(r => setTimeout(r, 900));
    const res = { msg: d.querySelector('.vp-msg').className + '|' + d.querySelector('.vp-msg').textContent, valid: pk.valid(), snap: d.querySelector('.vp-snap').checked };
    d.remove(); return res;
  });
  ok(t.valid && !t.msg.includes('err') && !t.snap, 'acepta la versión que ya tiene el servidor aunque no esté en la lista: ' + t.msg);

  // ---- celular ----
  const m = await b.newPage({ viewport: { width: 390, height: 844 } }); m.on('pageerror', e => errors.push(e.message));
  await m.goto('http://127.0.0.1:8765/'); await m.waitForTimeout(1200);
  await m.click('#btnAdd'); await m.click('#seg button[data-s=plain]'); await m.waitForTimeout(1200); await m.click('#nPick .vp-input');
  ok(!(await m.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1)), 'sin desborde horizontal en celular');
  await m.screenshot({ path: '/home/claude/t2/v-mobile.png' });
  await p.screenshot({ path: '/home/claude/t2/v-desktop.png' });
  ok(errors.length === 0, 'sin errores de JavaScript' + (errors.length ? ': ' + errors.join(' | ') : ''));
  await b.close();
  console.log(results.join('\n'));
  process.exit(results.some(r => r.startsWith('FAIL')) ? 1 : 0);
})().catch(e => { console.log(results.join('\n')); console.log('ERROR', e); process.exit(1); });
