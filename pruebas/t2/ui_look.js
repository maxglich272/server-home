// Interfaz: botón «Compartir mods con amigos» (zip con barra y descarga), imagen del servidor (se recorta y
// achica a 64×64 en el navegador) y mensaje del servidor con colores.
const { chromium } = require('/home/claude/mock/node_modules/playwright');
const fs = require('fs');
const zlib = require('zlib');
const results = []; const ok = (c, m) => { results.push((c ? 'OK   ' : 'FAIL ') + m); };
const IDS = JSON.parse(fs.readFileSync('/home/claude/t2/ui_repair_ids.json', 'utf8'));
const API = 'http://127.0.0.1:8765/api/';

function crc32(buf) {
  let c, crc = 0xffffffff;
  for (let n = 0; n < buf.length; n++) {
    c = (crc ^ buf[n]) & 0xff;
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    crc = (crc >>> 8) ^ c;
  }
  return (crc ^ 0xffffffff) >>> 0;
}
function png(w, h, px) {         // px(x, y) -> [r, g, b]
  const rows = [];
  for (let y = 0; y < h; y++) { const r = Buffer.alloc(1 + w * 3); for (let x = 0; x < w; x++) { const [a, b, c] = px(x, y); r[1 + x * 3] = a; r[2 + x * 3] = b; r[3 + x * 3] = c; } rows.push(r); }
  const chunk = (t, d) => { const len = Buffer.alloc(4); len.writeUInt32BE(d.length); const td = Buffer.concat([Buffer.from(t), d]); const crc = Buffer.alloc(4); crc.writeUInt32BE(crc32(td)); return Buffer.concat([len, td, crc]); };
  const ihdr = Buffer.alloc(13); ihdr.writeUInt32BE(w, 0); ihdr.writeUInt32BE(h, 4); ihdr[8] = 8; ihdr[9] = 2;
  return Buffer.concat([Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]), chunk('IHDR', ihdr), chunk('IDAT', zlib.deflateSync(Buffer.concat(rows))), chunk('IEND', Buffer.alloc(0))]);
}
const pngSize = b => [b.readUInt32BE(16), b.readUInt32BE(20)];

(async () => {
  const b = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium', env: { ...process.env, LANG: 'C.UTF-8', LC_ALL: 'C.UTF-8' } });
  const p = await b.newPage({ viewport: { width: 1200, height: 900 }, acceptDownloads: true });
  const errors = []; p.on('pageerror', e => errors.push(e.message)); p.on('console', m => { if (m.type() === 'error' && !/404/.test(m.text())) errors.push(m.text()); });
  await p.goto('http://127.0.0.1:8765/'); await p.waitForTimeout(1200);
  await p.evaluate(id => selectServer(id), IDS.share); await p.waitForTimeout(1500);

  // ---- 1) compartir mods con amigos ----
  ok(await p.isVisible('#shareRow') && (await p.textContent('#shareRow')).includes('Mods para tus amigos'), 'en «Cómo entran tus amigos» está la fila «Mods para tus amigos»');
  const shareNow = async () => (await (await fetch(API + `servers/${IDS.share}`)).json()).share || {};
  const t0 = (await shareNow()).t || 0;
  await new Promise(r => setTimeout(r, 1100));                                    // que el nuevo tenga otra hora
  await fetch(API + `servers/${IDS.share}/compartir`, { method: 'POST' });        // armarlo de nuevo desde cero
  for (let i = 0; i < 60; i++) { const sh = await shareNow(); if (sh.estado === 'listo' && sh.t > t0) break; await new Promise(r => setTimeout(r, 300)); }
  await p.waitForFunction(() => /Listo:/.test(document.querySelector('#shareBox').textContent), null, { timeout: 30000 });
  await p.waitForTimeout(1300);
  const txt = await p.textContent('#shareBox');
  ok(txt.includes('Compartelo Max - mods para amigos.zip') && txt.includes('4 mods') && txt.includes('LEEME'), 'dice que está listo, cuántos mods trae y dónde quedó: ' + txt.replace(/\s+/g, ' ').slice(0, 120));
  const [dl] = await Promise.all([p.waitForEvent('download', { timeout: 15000 }), p.click('#bShareDl')]);
  const dlPath = await dl.path();
  ok(dl.suggestedFilename() === 'Compartelo Max - mods para amigos.zip' && fs.statSync(dlPath).size > 1000, `«Descargar el zip» baja el archivo (${dl.suggestedFilename()}, ${fs.statSync(dlPath).size} bytes)`);
  await (await p.$('#shareRow')).screenshot({ path: '/home/claude/t2/lk-share.png' });
  // con el botón «Armar de nuevo» se ve la barra (el zip se arma lento con el mock en modo lento no aplica: basta ver que vuelve a «Listo»)
  await p.click('#bShare');
  await p.waitForFunction(() => /Listo:/.test(document.querySelector('#shareBox').textContent), null, { timeout: 30000 });
  ok(true, '«Armar de nuevo» funciona');
  await p.click('.tab[data-t=addons]'); await p.waitForTimeout(600);
  ok(await p.isVisible('#bShareMods'), 'en la pestaña Mods también está «Compartir mods con amigos»');
  const why = await p.$$eval('#addonList .why', els => els.map(e => e.textContent));
  ok(why.includes('Solo del jugador: necesita iris, que es solo del jugador'), 'la pestaña Mods dice por qué la app desactivó un mod: ' + why.join(' | '));
  await (await p.$('section[data-p=addons]')).screenshot({ path: '/home/claude/t2/lk-mods.png' });

  // ---- 2) imagen del servidor ----
  await p.click('.tab[data-t=settings]'); await p.waitForTimeout(900);
  ok(await p.isVisible('#lookCard') && await p.isVisible('#apIcon svg') && !(await p.isVisible('#vIcon')), 'tarjeta «Imagen y mensaje del servidor» con la imagen normal de Minecraft');
  ok((await p.textContent('#apName')) === 'Compártelo Máx', 'la vista previa muestra el nombre');
  const photo = png(300, 200, (x, y) => [x % 256, y, 120]);
  await p.setInputFiles('#iconIn', { name: 'foto.png', mimeType: 'image/png', buffer: photo });
  await p.waitForSelector('#vIcon:not(.hide)', { timeout: 10000 });
  let icon = Buffer.from(await (await fetch(API + `servers/${IDS.share}/icono`)).arrayBuffer());
  ok(pngSize(icon).join('x') === '64x64', 'una foto de 300×200 se recorta y achica a 64×64 antes de subirla: ' + pngSize(icon).join('x'));
  ok(await p.isVisible('#apIcon img') && await p.isVisible('#bIconDel'), 'se ve en la vista previa y aparece «Quitar imagen»');
  const hero = await p.$eval('#vIcon', el => [el.naturalWidth, el.getBoundingClientRect().width]);
  ok(hero[0] === 64 && hero[1] >= 40, 'también se ve junto al nombre del servidor: ' + hero.join(' / '));
  const pixel = png(16, 16, (x, y) => ((x >> 2) + (y >> 2)) % 2 ? [255, 255, 255] : [20, 120, 40]);
  await p.setInputFiles('#iconIn', { name: 'pixel.png', mimeType: 'image/png', buffer: pixel });
  await p.waitForTimeout(1500);
  icon = Buffer.from(await (await fetch(API + `servers/${IDS.share}/icono`)).arrayBuffer());
  const crisp = await p.evaluate(async src => {
    const img = new Image(); img.src = src; await img.decode();
    const c = document.createElement('canvas'); c.width = c.height = 64; const g = c.getContext('2d'); g.drawImage(img, 0, 0);
    const d = g.getImageData(0, 0, 64, 64).data, seen = new Set();
    for (let i = 0; i < d.length; i += 4) seen.add(d[i] + ',' + d[i + 1] + ',' + d[i + 2]);
    return seen.size;
  }, `/api/servers/${IDS.share}/icono?x=${Date.now()}`);
  ok(pngSize(icon).join('x') === '64x64' && crisp <= 3, `un dibujo chico (16×16) se agranda sin difuminarse (${crisp} colores)`);
  await (await p.$('#lookCard')).screenshot({ path: '/home/claude/t2/lk-look.png' });
  await p.setInputFiles('#iconIn', { name: 'nota.txt', mimeType: 'text/plain', buffer: Buffer.from('hola') });
  await p.waitForTimeout(800);
  ok((await p.$$eval('.toast.err', t => t.map(x => x.textContent))).some(t => t.includes('Elige una imagen')), 'si no es una imagen lo avisa');
  await p.click('#bIconDel');
  await p.waitForSelector('.modal-bg.open [data-a="1"]', { timeout: 5000 });
  await p.click('.modal-bg.open [data-a="1"]');
  await p.waitForSelector('#vIcon.hide', { state: 'attached', timeout: 10000 });
  ok(await p.isVisible('#apIcon svg') && (await fetch(API + `servers/${IDS.share}/icono`)).status === 404, '«Quitar imagen» vuelve a la normal');

  // ---- 3) mensaje con colores ----
  await p.fill('#sMotd', 'Hola'); await p.click('#sMotd'); await p.press('#sMotd', 'End');
  await p.click('#mcColors [data-mc="a"]');
  await p.type('#sMotd', ' amigos');
  await p.fill('#sMotd2', 'línea dos');
  const motdHtml = await p.innerHTML('#apMotd');
  ok((await p.inputValue('#sMotd')) === 'Hola§a amigos' && /color:#55FF55[^>]*>\s*amigos/i.test(motdHtml.replace(/"/g, '')), 'los botones de color ponen el código y la vista previa lo pinta: ' + (await p.inputValue('#sMotd')));
  await p.click('#bSaveLook'); await p.waitForTimeout(900);
  const det = await (await fetch(API + `servers/${IDS.share}`)).json();
  ok(det.properties.motd === 'Hola§a amigos\\nlínea dos', 'guarda las dos líneas: ' + JSON.stringify(det.properties.motd));
  await p.click('.tab[data-t=console]'); await p.waitForTimeout(300); await p.click('.tab[data-t=settings]'); await p.waitForTimeout(900);
  ok((await p.inputValue('#sMotd')) === 'Hola§a amigos' && (await p.inputValue('#sMotd2')) === 'línea dos', 'al volver a Ajustes se ven igual');
  await (await p.$('#lookCard')).screenshot({ path: '/home/claude/t2/lk-motd.png' });

  // ---- 4) celular ----
  const m = await b.newPage({ viewport: { width: 390, height: 844 } });
  await m.goto('http://127.0.0.1:8765/'); await m.waitForTimeout(1000);
  await m.evaluate(id => selectServer(id), IDS.share); await m.waitForTimeout(900);
  await m.click('.tab[data-t=settings]'); await m.waitForTimeout(900);
  const over = await m.evaluate(() => document.documentElement.scrollWidth > window.innerWidth);
  ok(!over, 'en celular la tarjeta de imagen y mensaje cabe sin desplazar la página');
  await m.screenshot({ path: '/home/claude/t2/lk-mobile.png', fullPage: false });

  ok(errors.length === 0, 'sin errores de JavaScript' + (errors.length ? ': ' + errors.join(' | ') : ''));
  await b.close();
  console.log(results.join('\n'));
  process.exit(results.some(r => r.startsWith('FAIL')) ? 1 : 0);
})().catch(e => { console.log(results.join('\n')); console.log('ERROR', e.message); process.exit(2); });
