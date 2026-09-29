"""Arma el modpack «Create: Volcanes y Estrellas» para el launcher de CurseForge y para Servidor Home.

Entrada (datos sacados de curseforge.com y verificados con sumas FNV-1a):
  mods.txt    slug projectID fileID lib releaseType lados hash
  names.txt   slug|nombre|autor|archivo
  deps.txt    slug:dependencias,requeridas
  hashes.txt  fileID tamaño sha1 sha512   (calculados descargando cada .jar del CDN de CurseForge)
Salida (en out/):
  Volcanes-y-Estrellas-<versión>.zip     para CurseForge (manifest.json + modlist.html + overrides/)
  Volcanes-y-Estrellas-<versión>.mrpack  para Servidor Home: la app descarga sola cada mod del CDN de CurseForge
                                         y comprueba su sha1 (no trae los .jar: son de sus autores)
  LEEME-Volcanes-y-Estrellas.txt
"""
import html
import json
import os
import urllib.parse
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")
NAME = "Create: Volcanes y Estrellas"
VERSION = "1.0.2"
AUTHOR = "Max"
MC = "1.21.1"
NEOFORGE = "21.1.250"          # la misma que usa «All of Create Aeronautics» v2.6 (probada con Aeronautics en CurseForge)
RAM = 8192
ZIPNAME = f"Volcanes-y-Estrellas-{VERSION}.zip"
MRPACKNAME = f"Volcanes-y-Estrellas-{VERSION}.mrpack"
# Los dos servidores del CDN de CurseForge están en MRPACK_HOSTS de Servidor Home (se prueban en orden).
CDN = ("https://mediafilez.forgecdn.net", "https://edge.forgecdn.net")
# Solo para el jugador: en el .mrpack van con env.server = "unsupported" y el servidor no los descarga.
# Se revisó que ninguno registra canales de red (PayloadRegistrar, CustomPacketPayload...), así que los
# jugadores igual pueden entrar al servidor con ellos instalados.
CLIENT_ONLY = set("""
    sodium sodium-extra reeses-sodium-options immediatelyfast entityculling moreculling dynamic-fps
    badoptimizations mouse-tweaks controlling searchables enhanced-boss-bars jade-sable-compat create-xaeros-map
""".split())
# server.properties del servidor importado (Servidor Home le agrega el puerto y el nombre).
SERVER_PROPERTIES = """#Ajustes de Create: Volcanes y Estrellas (solo ASCII: Minecraft lee este archivo como ISO-8859-1)
# allow-flight: sin esto el servidor echa a quien usa el jetpack o va parado en un barco volador
allow-flight=true
"""

CATS = [
    ("create", "Create y vehículos con física (Create Aeronautics)", """
        create create-aeronautics sable create-aeroworks create-propulsion-simulated
        create-simulated-jet-engines-aero-propulsion create-tracks
        create-aeronautics-gadgets-and-gizmos create-aeronautics-transmission-linkage
        create-aeronautics-automated-logistics create-aeronautics-climbable-ropes
        create-aeronautics-throwable-rope-connector create-linear-bearing absolute-kinematics
        create-aeronautics-copycat-wing copycats-aeronautics-weight create-aeronautics-covers
        aeronautics-calibrated sable-physics-compat create-aeronautics-compatability
        create-aeronautics-x-curios-api-compat jade-sable-compat create-xaeros-map waystones-sable
        create-stuff-n-additions-x-sable-aeronautics"""),
    ("portal", "Portales sin pantalla de carga", "immersive-aeronautics"),
    ("space", "Espacio (Create)", "northstar-redux create-creating-space"),
    ("war", "Cañones, radares, misiles y armas (Create)", """
        create-big-cannons create-radars create-aero-radars create-simulated-missiles-create-aeronautics
        cbcms cbc-enchanced-shells-create-big-cannons
        create-aeronautics-shield-generator-force-field cgs"""),
    ("more", "Más addons de Create", """
        createaddition create-enchantment-industry copycats create-connected create-deco create-stuff-additions
        create-diesel-generators create-new-age tfmg-community-edition steam-n-rails-neoforge interiors
        create-encased create-bits-n-bobs create-escalated create-trading-floor create-pattern-schematics
        create-mechanical-extruder create-design-n-decor create-misc-and-things create-ore-excavation
        create-power-loader create-enchantable-machinery create-sifting create-jetpack create-central-kitchen
        slice-and-dice create-extra-gauges create-mobile-packages hypertubes
        create-framed create-cobblestone create-transmission create-dreams-desires create-ultimate-factory
        create-confectionery sophisticated-backpacks-create-integration create-shimmer bellsandwhistles
        create-vibrant-vaults"""),
    ("terrain", "Terreno: biomas nuevos, montañas, volcanes y cráteres", "tectonic terralith moonstone-meteorites ohmymeteors volcanic-caverns"),
    ("dims", "Dimensiones nuevas (cada una con sus propios biomas)", "the-twilight-forest the-undergarden deeperdarker"),
    ("structures", "Estructuras del mundo", """
        explorify when-dungeons-arise yungs-better-dungeons-neoforge yungs-better-mineshafts-neoforge
        yungs-better-strongholds-neoforge yungs-better-desert-temples-neoforge yungs-better-jungle-temples-neoforge
        yungs-better-ocean-monuments-neoforge yungs-better-witch-huts-neoforge yungs-extras-neoforge lootr"""),
    ("nether", "Nether renovado", """
        incendium nether-depths-upgrade eternal-nether yungs-better-nether-fortresses-neoforge
        mns-moogs-nether-structures cataclysm-x-yungs"""),
    ("end", "End renovado", "nullscape unusual-end phantasm endremastered yungs-better-end-island-neoforge moogs-end-structures"),
    ("bosses", "Jefes", """
        lendercataclysm mowzies-mobs bosses-of-mass-destruction-forge
        mutant-monsters aquamirae legendary-monsters bossesrise enhanced-boss-bars"""),
    ("perf", "Rendimiento", """
        sodium reeses-sodium-options sodium-extra immediatelyfast entityculling moreculling dynamic-fps
        badoptimizations ferritecore modernfix lithium clumps fastsuite fastworkbench fastfurnace alltheleaks
        ai-improvements smooth-chunk-save structure-layout-optimizer chunky-pregenerator-forge spark"""),
    ("qol", "Utilidades", """
        jei jade xaeros-minimap xaeros-world-map appleskin mouse-tweaks controlling
        waystones sophisticated-backpacks corpse farmers-delight natures-compass explorers-compass polymorph"""),
]


def load():
    mods = []
    for line in open(os.path.join(HERE, "mods.txt"), encoding="utf-8"):
        if line.strip():
            s, p, f, lib, rt, sides, _h = line.split()
            mods.append({"slug": s, "project": int(p), "file": int(f), "lib": lib == "1", "rt": int(rt),
                         "sides": "" if sides == "-" else sides})
    names = {}
    for line in open(os.path.join(HERE, "names.txt"), encoding="utf-8"):
        if line.strip():
            s, n, a, fn = line.rstrip("\n").split("|")
            names[s] = (n, a, fn)
    deps = {}
    for line in open(os.path.join(HERE, "deps.txt"), encoding="utf-8"):
        if line.strip():
            s, d = line.strip().split(":")
            deps[s] = d.split(",")
    for m in mods:
        m["name"], m["author"], m["filename"] = names[m["slug"]]
        m["req"] = deps.get(m["slug"], [])
    return mods


def categorize(mods):
    where = {}
    for key, _title, slugs in CATS:
        for s in slugs.split():
            assert s not in where, f"{s} está en dos categorías"
            where[s] = key
    for m in mods:
        m["cat"] = "lib" if m["lib"] else where.get(m["slug"])
        assert m["cat"], f"{m['slug']} no tiene categoría"
    extra = set(where) - {m["slug"] for m in mods}
    assert not extra, f"categorías con mods que no están: {extra}"


def manifest(mods):
    return {
        "minecraft": {"version": MC, "modLoaders": [{"id": f"neoforge-{NEOFORGE}", "primary": True}],
                      "recommendedRam": RAM},
        "manifestType": "minecraftModpack",
        "manifestVersion": 1,
        "name": NAME,
        "version": VERSION,
        "author": AUTHOR,
        "files": [{"projectID": m["project"], "fileID": m["file"], "required": True} for m in mods],
        "overrides": "overrides",
    }


def load_hashes():
    out = {}
    for line in open(os.path.join(HERE, "hashes.txt"), encoding="utf-8"):
        if line.strip():
            fid, size, sha1, sha512 = line.split()
            out[int(fid)] = (int(size), sha1, sha512)
    return out


def cdn_urls(fid, filename):
    # Igual que encodeURIComponent de JavaScript, que es como se probaron las 179 direcciones contra el CDN.
    q = urllib.parse.quote(filename, safe="!~*'()")
    return [f"{host}/files/{fid // 1000}/{fid % 1000}/{q}" for host in CDN]


def mrpack_index(mods, hashes):
    files = []
    for m in mods:
        size, sha1, sha512 = hashes[m["file"]]
        files.append({
            "path": "mods/" + m["filename"],
            "hashes": {"sha1": sha1, "sha512": sha512},
            "env": {"client": "required", "server": "unsupported" if m["slug"] in CLIENT_ONLY else "required"},
            "downloads": cdn_urls(m["file"], m["filename"]),
            "fileSize": size,
        })
    return {
        "formatVersion": 1,
        "game": "minecraft",
        "versionId": VERSION,
        "name": NAME,
        "summary": "Create Aeronautics, espacio, cañones y radares, volcanes y cráteres, Nether y End renovados, "
                   "dimensiones nuevas y jefes. Hecho para Servidor Home: descarga los mods desde CurseForge.",
        "files": files,
        "dependencies": {"minecraft": MC, "neoforge": NEOFORGE},
    }


def modlist(mods):
    out = ["<ul>"]
    for m in sorted(mods, key=lambda m: m["name"].lower()):
        url = f"https://www.curseforge.com/minecraft/mc-mods/{m['slug']}"
        out.append(f'<li><a href="{url}">{html.escape(m["name"])} (by {html.escape(m["author"])})</a></li>')
    out.append("</ul>")
    return "\n".join(out) + "\n"


BIOMAS = [
    # (cuántos, texto) — contados dentro de los .jar (data/<mod>/worldgen/biome), sin contar los biomas
    # normales que esos mods retocan ni los «biomas» vacíos del espacio
    (95, "Mundo normal, con Terralith: 95 (11 son cuevas). Entre ellos Volcanic Peaks (volcanes),\n"
         "  Volcanic Crater y Caldera (cráteres gigantes), Basalt Cliffs y Ashen Savanna."),
    (8, "Nether, con Incendium: 8 (Volcanic Deltas, Ash Barrens, Toxic Heap, Infernal Dunes y más)."),
    (7, "End: 7 (Nullscape 3, Unusual End 2 y End's Phantasm 2)."),
    (22, "The Twilight Forest: 22, en su propia dimensión."),
    (20, "The Undergarden: 20, en su propia dimensión subterránea."),
    (4, "Deeper and Darker: 4, en su dimensión Otherside."),
    (29, "Planetas: 29 (Create: Northstar 23 en la Luna, Marte, Mercurio y Venus; Create: Creating Space 6)."),
]

def leeme(mods, hashes):
    by = {}
    for m in mods:
        by.setdefault(m["cat"], []).append(m)
    n_lib = sum(m["lib"] for m in mods)
    L = []
    w = L.append
    w(f"{NAME}  (versión {VERSION})")
    w("=" * 60)
    n_server = sum(m["slug"] not in CLIENT_ONLY for m in mods)
    mb_server = sum(hashes[m["file"]][0] for m in mods if m["slug"] not in CLIENT_ONLY) / 1048576
    w(f"Minecraft {MC} con NeoForge {NEOFORGE}. {len(mods)} mods en total: {len(mods) - n_lib} elegidos y {n_lib} librerías")
    w("que esos mods necesitan. Son dos archivos:")
    w(f"- {ZIPNAME}: para JUGAR. Se importa en el launcher de CurseForge (tú y tus amigos).")
    w(f"- {MRPACKNAME}: para el SERVIDOR. Se importa en Servidor Home.")
    w("")
    w("SI YA TIENES UNA VERSIÓN ANTERIOR")
    w("- 1.0.0: no iba a arrancar (mods que chocan entre sí). Bórrala e importa esta.")
    w("- 1.0.1: el servidor se cae un segundo después de encender (y el juego, al entrar a un mundo).")
    w("  Basta con quitarle el mod «CBC Neo Warfare» (cbcmodernwarfare-...jar) a la instancia y al")
    w("  servidor, o importar esta versión.")
    w("")
    w("CÓMO INSTALARLO PARA JUGAR (CURSEFORGE)")
    w("1. Abre CurseForge y entra a Minecraft.")
    w("2. Arriba a la derecha: «Create Custom Profile» (Crear perfil personalizado).")
    w("3. En esa ventana elige «Import» (importar) y selecciona el archivo " + ZIPNAME + ".")
    w("   No lo descomprimas: CurseForge lo lee así y descarga los mods solo.")
    w("4. Dale 8 GB de RAM: en CurseForge, ⚙ Settings > Minecraft > Java Settings > Allocated Memory.")
    w("   Con 6 GB también anda, pero puede ir a tirones al cargar mucho terreno.")
    w("5. El primer inicio tarda varios minutos. Crea un MUNDO NUEVO: el terreno nuevo solo aparece en mundos nuevos.")
    w("")
    total = sum(n for n, _t in BIOMAS)
    w(f"BIOMAS NUEVOS: {total}")
    for _n, text in BIOMAS:
        for line in ("- " + text).split("\n"):
            w(line)
    w("Además, Tectonic hace las montañas, valles y ríos mucho más grandes, y Volcanic Caverns llena el")
    w("subsuelo de cuevas volcánicas. No trae Biomes O' Plenty ni otros packs de biomas a propósito: con")
    w("Terralith se reparten el mundo y los volcanes y cráteres quedarían escasos.")
    w("")
    w("CONSEJOS PARA JUGAR")
    w("- Volcanes: usa la Brújula de la Naturaleza (Nature's Compass) y busca «Volcanic Peaks».")
    w("  Cráteres gigantes: busca «Volcanic Crater» o «Caldera» con la misma brújula.")
    w("- Cráteres de meteorito: la Brújula del Explorador (Explorer's Compass) encuentra los de Moonstone")
    w("  Meteorites (busca «moonstone»; con Terralith salen solo en los biomas normales, así que hay menos).")
    w("  Además caen meteoritos de verdad (OhMyMeteors) que dejan cráteres nuevos; si rompen demasiado,")
    w("  se ajustan en Mods > OhMyMeteors > Config (o apágalos ahí).")
    w("- Portales: cruzas el portal del Nether caminando, sin pantalla de carga, y ves el otro lado")
    w("  (Immersive Aeronautics, la versión de Immersive Portals hecha para Create Aeronautics: hasta los")
    w("  barcos voladores cruzan). Es el mod más delicado del pack: si algún día falla, desactívalo en")
    w("  CurseForge y los portales vuelven a ser los normales.")
    w("- Dimensiones nuevas:")
    w("  · Twilight Forest: haz un charco de agua de 2x2 rodeado de tierra o pasto, pon flores en todos los")
    w("    bloques del borde y tira un diamante al agua.")
    w("    Está lleno de jefes (la Naga, el Lich, la Hidra, la Reina de las Nieves...).")
    w("  · Undergarden: arma un marco de ladrillos de piedra como el del Nether y úsale un Catalizador")
    w("    (Catalyst: 4 lingotes de cobre, 4 de piedra y una perla de ender; la receta está en JEI).")
    w("  · Otherside (Deeper and Darker): mata al Warden, toma su Corazón de las Profundidades (Heart of the")
    w("    Deep) y úsalo en el marco de portal de una Ciudad Antigua (Ancient City).")
    w("- NO actualices Sodium, Sodium Extra, Reese's Sodium Options, MoreCulling, Entity Culling ni")
    w("  ImmediatelyFast: están en la versión exacta que pide Immersive Aeronautics (Sodium 0.8.12).")
    w("- Shaders: no vienen, porque Create Aeronautics tiene fallas visuales con Iris. Si igual los quieres,")
    w("  agrega Iris Shaders 1.8.14-beta.1 (es la única versión que acepta Immersive Aeronautics).")
    w("- Espacio: Create: Northstar (cohetes armados con Create para ir a la Luna, Marte, Mercurio y Venus) y")
    w("  Create: Creating Space (cohetes realistas con contraptions). Usa «Ponder» (tecla W sobre un bloque")
    w("  de Create) y JEI para ver cómo se arma todo.")
    w("")
    w("EL SERVIDOR EN SERVIDOR HOME")
    w("1. En Servidor Home: «Agregar servidor» > pestaña «Archivo» > «Elegir archivo», y elige")
    w(f"   {MRPACKNAME} (o arrástralo ahí). No lo descomprimas.")
    w(f"2. La app muestra «NeoForge {NEOFORGE} · Minecraft {MC}» y {n_server} mods. Los otros {len(mods) - n_server} son solo para el")
    w("   jugador (Sodium y otros de gráficos o controles) y no se instalan en el servidor.")
    w("3. Deja 6 a 8 GB de RAM, marca el EULA y dale a «Importar y encender». La app descarga sola los mods")
    w(f"   desde CurseForge (unos {mb_server:.0f} MB), revisa que cada uno llegue completo, instala NeoForge y enciende")
    w("   el servidor. La primera vez tarda varios minutos.")
    w("4. Ya viene con «allow-flight=true» (permitir volar): sin eso el servidor echa a quien usa el jetpack o")
    w("   va parado en un barco volador.")
    w("5. Tus amigos entran con el .zip importado en CurseForge: así tienen los mismos mods que el servidor.")
    w("6. Para que vaya fluido, pre-genera el mundo con Chunky: en la consola escribe  chunky radius 3000  y")
    w("   luego  chunky start  (tarda, pero después no hay tirones).")
    w("Si algún mod no deja encender el servidor, la app dice cuál es y lo arregla o lo desactiva.")
    w("")
    w("QUÉ SE ARREGLÓ EN LA 1.0.2")
    w("- Salió CBC Neo Warfare: uno de sus cambios al juego (la cámara de SecurityCraft) choca con Immersive")
    w("  Aeronautics, y el servidor se caía un segundo después de encender, apenas cargaba las primeras")
    w("  criaturas del mundo. Se vio encendiendo el servidor. Quítalo también de tu juego si lo tenías.")
    w("")
    w("QUÉ SE ARREGLÓ EN LA 1.0.1")
    w("Revisé por dentro los archivos de todos los mods: qué versiones de otros mods acepta cada uno, con")
    w("cuáles dice que choca y si los cambios que le hace al juego calzan con las versiones del pack.")
    w("Estos habrían impedido abrir el juego o lo habrían botado al cargar:")
    w("- CBC: Advanced Technologies crash fix: pide Create Radars 5.0 o más nuevo, y en CurseForge la última")
    w("  es la 0.4.9.4. Por precaución también salió Create Big Cannons: Advanced Technologies, porque ese")
    w("  arreglo existe justamente para que no se caiga junto a Create Aeronautics.")
    w("- Create Big Cannons: Scope and Laser: solo acepta versiones viejas de Create Aeronautics y Sable.")
    w("- Create: The Factory Must Grow 1.2.2: Create: Bits 'n' Bobs lo marca como incompatible. Se cambió por")
    w("  Create: TFMG Community Edition 1.3.1, la versión que recomienda Bits 'n' Bobs.")
    w("- Xaero's Maps x Waystones: dice ser incompatible con el Xaero's Minimap actual.")
    w("- Create Factory Logistics: la librería Deployer (la necesita Create: Extra Gauges) lo marca incompatible.")
    w("- Create Deep Seas: modifica partes de Create y Sable que ya no existen en estas versiones.")
    w("- TwilightForest Thread Safety Addon: busca código que esta versión de Twilight Forest ya no tiene.")
    w("Se agregaron The Undergarden y Deeper and Darker (dos dimensiones nuevas con 24 biomas).")
    w("")
    w("QUÉ TRAE")
    for key, title, _ in CATS:
        items = sorted(by.get(key, []), key=lambda m: m["name"].lower())
        w("")
        w(f"{title} ({len(items)})")
        for m in items:
            w(f"  - {m['name']}")
    libs = sorted(by.get("lib", []), key=lambda m: m["name"].lower())
    w("")
    w(f"Librerías ({len(libs)}): " + ", ".join(m["name"] for m in libs))
    w("")
    return "\r\n".join(L) + "\r\n"


def main():
    mods = load()
    categorize(mods)
    os.makedirs(OUT, exist_ok=True)
    zpath = os.path.join(OUT, ZIPNAME)
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("manifest.json", json.dumps(manifest(mods), indent=2, ensure_ascii=False) + "\n")
        z.writestr("modlist.html", modlist(mods))
        z.writestr(zipfile.ZipInfo("overrides/"), "")
        z.writestr(zipfile.ZipInfo("overrides/config/"), "")
    hashes = load_hashes()
    missing = [m["slug"] for m in mods if m["file"] not in hashes]
    assert not missing, f"faltan hashes de {missing}"
    assert CLIENT_ONLY <= {m["slug"] for m in mods}, CLIENT_ONLY - {m["slug"] for m in mods}
    mpath = os.path.join(OUT, MRPACKNAME)
    with zipfile.ZipFile(mpath, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("modrinth.index.json", json.dumps(mrpack_index(mods, hashes), indent=2, ensure_ascii=False) + "\n")
        z.writestr("server-overrides/server.properties", SERVER_PROPERTIES)
    with open(os.path.join(OUT, "LEEME-Volcanes-y-Estrellas.txt"), "w", encoding="utf-8", newline="") as fh:
        fh.write(leeme(mods, hashes))
    n_server = sum(m["slug"] not in CLIENT_ONLY for m in mods)
    print("listo:", zpath, len(mods), "mods;", mpath, n_server, "para el servidor")


if __name__ == "__main__":
    main()
