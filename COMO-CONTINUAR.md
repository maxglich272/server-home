# Servidor Home: cómo seguir trabajando en el proyecto

Esta carpeta guarda todo lo necesario para hacer cambios y publicar versiones nuevas de Servidor Home.
Si le pides a Claude un cambio en otra conversación, dile que lea este archivo primero.

## Qué hay en el zip del proyecto

- `servidor-home/`: el programa. `servidor_home.py` tiene todo el servidor (API HTTP, instalación de servidores
  de Minecraft, importación de modpacks, playit.gg, arreglos automáticos, barra de carga y actualizaciones
  automáticas). La interfaz está en `web/index.html`.
- `build/`: cómo se arma el instalador de Windows.
  - `construir.sh` copia el programa a `build/app/` y compila `Instalar Servidor Home.exe` con NSIS
    (`makensis`, paquete `nsis` de Linux).
  - `app/python/` trae Python 3.12 para Windows (python-build-standalone), que va dentro del instalador.
  - `publicar.py` prepara una versión para GitHub y la firma con la clave privada.
  - `construir_prueba.sh`, `prueba_constantes.py` y `claves-prueba/` sirven solo para las pruebas. Arman un
    instalador que se actualiza desde un GitHub simulado.
- `gpumod/`: el mod «GPU Dedicada» para el juego (no para el servidor). Se compila con `gpumod/construir.sh`, que
  solo necesita un JDK: compila contra «stubs» de los loaders, sin descargar Minecraft. Un mismo `.jar` sirve en
  Fabric, Quilt, Forge (1.14 o más nuevo) y NeoForge. Para probarlo sin Minecraft:
  `java -cp gpu-dedicada-1.0.0.jar gpudedicada.GpuDedicada`.
- `modpack-volcanes-y-estrellas/`: la fuente del modpack (`build.py` y sus listas) y lo que arma en `out/`. Ver la
  sección del modpack más abajo.
- `pruebas/`: las baterías de pruebas y el servidor simulado (`mock2/mockserver.py`), que imita Mojang, Fabric,
  NeoForge, Adoptium, Modrinth, playit.gg y GitHub, y trae un servidor de Minecraft falso (`mock2/src/fs/Main.java`).
  - Si cambias el servidor falso, recompílalo con `mock2/construir_falso.sh`: deja `fakeserver.jar` y también la
    copia `www/fabric-server.jar` que descargan los servidores Vanilla y Fabric de prueba.
  - En Linux: `run_update.sh`, `run_repair.sh` (arreglos, barra, compartir mods e imagen: `ui_repair.js` y
    `ui_look.js`), `run_ui.sh` (incluye `ui_255.js`: inicio, reiniciar, jugadores y buscador), `run_versions.sh` y
    `run_matrix.sh`. Todo junto: `regresion.sh`. Aparte: `harness_255.py` (buscador de Modrinth y CurseForge,
    jugadores, reiniciar y el diagnóstico con el log real; usa el puerto 8766 y el mock encendido).
  - En Windows simulado con Wine: `run_win*.sh`, `win_update_flow.py` y `win_app_flow.py`. Necesitan un prefijo
    de Wine con Python para Windows, un Edge falso y Xvfb, que hay que volver a preparar en cada entorno nuevo.

## Para diagnosticar un servidor que falla

- Cada servidor guarda lo que hizo la app (encender, arreglos automáticos, errores y las últimas líneas de la consola
  cuando falla) en `servidor-home.log`, dentro de su carpeta. Junto con `logs/latest.log` y `crash-reports/` es lo
  primero que hay que mirar.
- NeoForge y Forge terminan con código 0 cuando falla la carga de mods: por eso la app considera una falla cualquier
  salida antes de «Done (...)!», salvo que la persona haya pedido apagarlo.
- `displayTest="IGNORE_SERVER_VERSION"` en un mods.toml NO significa «solo cliente» (lo usan JEI, FTB Essentials,
  SmartBrainLib...). Solo cuentan como mods del jugador los de la lista `KNOWN_CLIENT_ONLY`, los que declaran
  `clientSideOnly=true` o `environment: client` (Fabric), y los que piden Minecraft solo del lado del cliente.
- Fabric Loader 0.15 quitó la librería de mapeos `net.fabricmc.mapping` (tiny-mappings-parser). Los mods de la época
  de la 0.14 que la usan (por ejemplo Not Enough Crashes 4.1) botan el servidor con
  `NoClassDefFoundError: net/fabricmc/mapping/reader/v2/TinyVisitor`. El arreglo `downgrade_loader` baja Fabric Loader:
  prefiere la versión del registro del launcher (`logs/latest.log` de la instancia; la carpeta sale de
  `modpack.path` o de la línea «Copiando el modpack desde ...» de `servidor-home.log`) y si no, la más nueva que
  calce con los `depends`/`breaks` de los mods (`pick_fabric_loader`). Guarda el tope en `fabric_tope` para que
  `update_loader` no lo vuelva a subir. Al importar un modpack de Fabric de 1.20.1 o anterior sin versión conocida
  se elige la última 0.14 (`choose_import_loader`).
- Los nombres de las inyecciones de Mixin de Fabric (`handler$dmb000$<mod>$<método>`) dicen qué mod provocó una
  caída (`_culprit_near`).
- Ojo: en Windows la app escribe `servidor-home.log` con líneas `\r\n`; las expresiones con `$` tienen que aceptar `\r`.
  Lo mismo pasa con los `mods.toml` de muchos mods (`_toml_blocks` convierte `\r\n` antes de leer).
- Qué mod botó el servidor: `failed_mods()` lee lo que dice el loader (resumen «Loading errors encountered», secciones
  «-- Mod loading issue for: x --» con «Mod file:», «Failed to create mod instance», la entrada de Fabric) y clasifica
  cada uno: si su error es «invalid dist DEDICATED_SERVER» o clases del cliente, es del jugador (`disable_client`); si
  no, se busca una versión nueva y, si no sirve, `disable_content` con `"after": "update:<id>"` (se salta si la
  actualización funcionó en esa misma vuelta). Los mods que la app desactivó por fallar quedan en `broken_mods` (no se
  reactivan solos y sus dependientes se desactivan en cascada; más de `MAX_CASCADE` pide confirmación con
  `NeedsConfirmation`). Si el loader no lo dice, `_stack_suspect()` busca el mod en el rastro del error y solo se
  ofrece con un botón. `crash_message()` arma el mensaje «…por el mod «X»».
- ¡Cuidado con el ruido! Algunos mods (Majrusz's Difficulty) escriben «invalid dist» en rojo sin fallar: solo cuenta
  lo que el loader lista como falla, no cualquier línea.
- Un mixin que no se puede inyectar («Critical injection failure», «failed injection check»,
  `INJECTION_FAIL_RE`) bota el servidor la primera vez que se usa la clase afectada, que puede ser justo después
  de «Done» (la clase se transforma al cargarse): `_failed_mod` saca el mod de «`<mixins>.json:<clase> from mod <id>`» y se trata como
  un mod que no carga (`broken()`), también con el servidor ya encendido. Después de ese error el vigilante
  (watchdog) salta mientras el servidor se apaga: por eso `max_tick` no se propone si antes hubo una inyección
  fallida o una excepción del tick. `_crash_report_lines(since)` junta los últimos 3 crash-reports.
- `pruebas/real_mundillo.py` enciende el modpack real de «un mundillo» (146 mods) con Fabric Loader de verdad
  (librerías 0.14.9 y 0.18.4 copiadas de SKLauncher, en `realtest/`); no está en la batería porque necesita esos
  archivos y unos 8 minutos.

## Lo nuevo de la 2.5.5

- **Inicio «Mis servidores»:** `refresh()` ya no entra solo a un servidor; `renderHome()` dibuja las tarjetas,
  `selectServer()` entra y `goHome()` vuelve. Si la página se recarga sola (la app se actualizó), `reloadHere()`
  guarda el servidor abierto en `sessionStorage` (`sh-volver`) y vuelve a él; al abrir la app se empieza en la lista.
- **Reiniciar:** `POST servers/<id>/restart` (`stop(restart=True)`). En la interfaz, `.powerbox`: el botón
  grande `#power` lleva una máscara que le recorta la esquina y ahí va el redondo `#restart`.
- **Buscador:** `packs_search()`, `packs_versions()` y `packs_import()` (rutas `packs/search`, `packs/versions`,
  `packs/import`). La importación usa el mismo `ImportJob`, con `job.fetch` (la URL se baja en `_fetch_pack()`,
  solo desde `MRPACK_HOSTS`) y `job.source_info`.
  - Modrinth no pide clave. CurseForge sí (header `x-api-key`, `_cf_request()`): cada persona saca la suya en
    console.curseforge.com y la pega en «Buscar → CurseForge» (`PUT packs/curseforge-key`, que la prueba antes de
    guardarla). Queda en `%LOCALAPPDATA%\Servidor Home\ajustes.json` (`app_settings()`, `set_app_setting()`) y la
    API nunca la devuelve entera (solo «…» y los últimos 4). Las claves traen `$`: no hay que escaparlas.
  - De CurseForge se usa el pack de servidor de esa versión (`serverPackFileId`) si existe; si no, el zip normal
    (solo `manifest.json` y overrides): `_analyze_cf_manifest()` resuelve la lista con `POST /mods/files` y
    `POST /mods`, deja solo mods (`classId` 6) y salta los archivos marcados «Client» sin «Server».
    `cf_file_urls()` da la URL de la API y las del CDN de repuesto (los autores que no permiten descargas
    externas dejan `downloadUrl` vacío).
  - Después de bajar los mods de un `.mrpack` o de una lista de CurseForge, `run_import_steps` revisa cada jar con
    `scan_mod_jar()` y desactiva los que son solo del jugador aunque el pack no los marque.
- **Jugadores:** `players_info()` junta `usercache.json`, `ops.json`, `whitelist.json`, `banned-players.json`,
  los conectados y `meta["vistos"]` (la última vez que se vio a cada uno, de las líneas de entrada y salida).
  `player_action()`: con el servidor encendido manda el comando (`PLAYER_CMDS`); apagado, `_player_offline_edit()`
  edita esos JSON con el mismo formato que Minecraft. El UUID sale de lo conocido, de `offline_uuid()` si
  `online-mode=false`, o de Mojang (`mojang_uuid()`). El motivo del ban se deja en una sola línea (sin caracteres
  de control), para que no se pueda colar otro comando en la consola.

## Borrar servidores y acceso remoto (después de la 2.5.5)

- **Borrar:** botón «Borrar servidor» arriba, en la tarjeta del servidor (y el de siempre en Ajustes → Opciones
  avanzadas). Pide escribir el nombre. `Manager.delete()` apaga el servidor guardando el mundo si está encendido,
  quita sus accesos remotos y reintenta borrar la carpeta si Windows todavía tiene archivos tomados.
- **Acceso remoto (solo entre apps):** pestaña «Acceso remoto» de cada servidor. El dueño crea un código por
  persona (`SH1.` + base64 de `dirección|id|clave`) y se lo pasa. El amigo necesita Servidor Home: lo pega en
  «Servidores de amigos» (inicio) y administra desde `/remoto?f=<id>` de su propia app, que habla con la del dueño
  (`RemoteFriends`, rutas `api/amigos/...` que la app del amigo reenvía cifradas).
  - `RemoteAccess` abre una segunda puerta HTTP solo en `127.0.0.1:<puerto de la app + 15>` (8780) cuando hay al
    menos una invitación, y `Playit.ensure_admin_tunnel()` crea para ella un túnel TCP aparte en playit.gg
    (`"ports": {"type": "custom-tcp", "details": 1}`, nombre `servidor-home-admin`). Si no puede, explica cómo
    crearlo a mano.
  - La puerta solo acepta `POST /sh-remoto`; a un navegador no le responde nada. Pedido y respuesta van cifrados y
    firmados con la clave de 256 bits del código (`remote_seal` / `remote_open`: HMAC-SHA256 en modo contador
    para cifrar y HMAC-SHA256 para firmar, solo biblioteca estándar). Se rechazan firmas malas, mensajes
    repetidos y horas con más de 2 minutos de diferencia (la app del amigo corrige su reloj sola con el `t` que
    devuelve el error `hora`). Cada respuesta va atada al número de su pedido.
  - Las invitaciones están en `acceso-remoto.json` y, en el PC del amigo, los servidores en
    `servidores-de-amigos.json` (junto a `ajustes.json`, permisos 600 en Linux).
  - `remote_action()` solo tiene rutas sobre el servidor de la invitación: estado, encender/apagar/reiniciar/forzar,
    consola y comandos, jugadores, ajustes del juego (`REMOTE_PROPERTIES`: sin puerto ni rcon) y crear respaldos.
    A propósito no hay mods, argumentos de Java, versiones ni borrar: con eso se podrían ejecutar programas en el
    PC del dueño. Todo lo que hace el amigo queda en la consola y en `servidor-home.log` con su nombre.
  - Pruebas: `pruebas/t2/harness_remoto.py` (con el mock encendido; el mock ya acepta túneles `custom-tcp`).

## El modpack «Create: Volcanes y Estrellas»

Está en `Documentos\servidor home\modpacks\` (versión 1.0.2; la 1.0.0 no arrancaba y la 1.0.1 botaba el servidor
cuando entraba un jugador; hay que borrarlas):

- `Volcanes-y-Estrellas-1.0.2.zip`: para jugar, se importa en el launcher de CurseForge (solo la lista de mods).
- `Volcanes-y-Estrellas-1.0.2.mrpack`: para el servidor, se importa en Servidor Home («Agregar servidor» >
  «Archivo»). La app descarga sola cada mod del CDN de CurseForge y revisa su sha1. El zip de CurseForge también
  sirve desde la 2.5.5, pero solo con la clave de CurseForge puesta; el `.mrpack` no la necesita.
- `LEEME-Volcanes-y-Estrellas.txt` y la carpeta `fuente-volcanes-y-estrellas` para rehacerlo: `python build.py`
  arma los dos desde `mods.txt`, `names.txt`, `deps.txt` y `hashes.txt`. Cada mod tiene que estar en una
  categoría de `CATS`, y los biomas del LEEME están en `BIOMAS`.

- Minecraft 1.21.1 con NeoForge 21.1.250; 178 mods (149 elegidos + 29 librerías) y 185 biomas nuevos.
- 1.0.2: se sacó **CBC Neo Warfare** (`cbcmodernwarfare-0.0.6v`). Su mixin `camera.TrackedEntityMixin` (para
  SecurityCraft) inyecta en `ChunkMap.TrackedEntity.updatePlayer`, que Immersive Aeronautics (usa Immersive
  Portals) reescribe: «Critical injection failure ... (0/1) succeeded» un segundo después de «Done», cuando el mundo
  registra la primera entidad (`ChunkMap.addEntity` carga `TrackedEntity`), y luego el vigilante corta el apagado. También hay que quitarlo del juego: NeoForge no deja entrar con mods de contenido
  distintos a los del servidor, y un mundo de un jugador corre ese mismo código. `hashes.txt` todavía tiene su
  línea: las líneas de más se ignoran.
- El `.mrpack` (formato de Modrinth) contiene:
  - `modrinth.index.json`: `path` `mods/<archivo>`, `hashes` sha1 y sha512 y `fileSize`.
  - Descargas en `https://mediafilez.forgecdn.net/files/<id/1000>/<id%1000>/<nombre>`, con `edge.forgecdn.net`
    de repuesto. El nombre va codificado como `encodeURIComponent`: `+` → `%2B`, espacio → `%20`.
  - `server-overrides/server.properties` con `allow-flight=true`: el jetpack y los barcos voladores lo necesitan.

  Servidor Home acepta esos dos servidores desde la 2.5.0 (`MRPACK_HOSTS`). Probado con el código de la 2.5.0
  y el de la 2.5.4: `ImportJob` y `download_mrpack_files`, con el CDN simulado.
- `hashes.txt` se sacó descargando los 179 jar desde el navegador (`crypto.subtle.digest`), porque la API del
  sitio de CurseForge no da los hashes. Si cambias la versión de un mod, vuelve a calcular su línea.
- En el `.mrpack` van con `env.server = "unsupported"` los 14 mods de `CLIENT_ONLY` en build.py: Sodium y sus
  extras, cullings, ImmediatelyFast, Dynamic FPS, BadOptimizations, Mouse Tweaks, Controlling, Searchables,
  Enhanced Boss Bars y las compatibilidades de Sable con Jade y el mapa.
  - Ninguno registra canales de red (`PayloadRegistrar`/`CustomPacketPayload`), así que los jugadores entran al
    servidor aunque ellos sí los tengan.
  - Ningún mod del servidor los pide.
  - En los mods del servidor (165 en la 1.0.1; 164 en la 1.0.2) se buscaron clases `@Mod` o `@EventBusSubscriber` sin `dist = CLIENT` que usen clases
    de `net/minecraft/client` en sus métodos. Solo aparecieron lambdas privadas en Create y Diesel Generators, y
    esas no las carga el bus de eventos (usa `getMethods()`, que solo mira los métodos públicos).
- El registro de la app dice «desde Modrinth» al descargar un `.mrpack` aunque vengan de CurseForge (es solo el
  texto).
- Los datos salen de `https://www.curseforge.com/api/v1/mods/<id>/files` (filtrar `gameFlavorId=6` y revisar que
  `gameVersions` traiga `1.21.1` y `NeoForge`) y `.../files/<fileId>/dependencies`. El ID del proyecto está en la
  página del mod (`class="project-id"`). Desde el sandbox curseforge.com está bloqueado: hay que usar el navegador.
- Revisión contra la API: cada archivo es del proyecto correcto, es 1.21.1 + NeoForge, está aprobado (`status` 4),
  tiene sus dependencias requeridas en el pack y ninguno está marcado `Incompatible` con otro del pack.
  Create: Escalated pide «create-fabric» en CurseForge por error; en NeoForge eso lo cumple Create.
- La API de CurseForge NO ve los choques reales: esos están dentro de cada `.jar`. Así se encontraron los de la
  1.0.0, leyendo los jar desde una pestaña en `https://mediafilez.forgecdn.net/robots.txt` (mismo origen) con
  pedidos `Range` a `/files/<fileId/1000>/<fileId%1000>/<nombre>` (no acepta rangos «desde el final»), el
  directorio central del ZIP y `DecompressionStream('deflate-raw')`. Qué revisar, imitando a FML 1.21.1
  (código en GitHub, neoforged/FancyModLoader, rama 1.21.1):
  - `META-INF/neoforge.mods.toml` de cada mod y de los jar que trae dentro (`META-INF/jarjar/metadata.json`):
    dependencias `required`, `optional` (si está instalada con una versión fuera del rango TAMBIÉN es error),
    `incompatible` (error) y `discouraged` (solo aviso); modIds repetidos; paquetes repetidos entre jar.
  - Las librerías de `jarjar` se agrupan por nombre de módulo (`module-info.class` o `Automatic-Module-Name`) y
    gana la más nueva; no son choques.
  - Un rango de Minecraft como `[1.21,1.21.1)` NO es error en 1.21.1: FML lo acepta (VersionSupportMatrix).
  - Mixins: un `@Inject`/`@Redirect`/etc. cuyo método destino no existe, con `require` ≥ 1 (o
    `injectors.defaultRequire` en el json del mixin), bota el juego al cargar. Ojo: los métodos que agrega otro
    mixin no se ven leyendo la clase (Simulated le agrega métodos a `KineticBlockEntity`), y los mixins con
    `@Pseudo` o protegidos por un «plugin» del mixin son opcionales: esos se revisan a mano.
- Lo que tenía la 1.0.0 y se sacó: CBC: Advanced Technologies crash fix (pide Create Radars ≥ 5.0; la última en
  CurseForge es 0.4.9.4) junto con CBC: Advanced Technologies; CBC Scope and Laser (pide Aeronautics < 1.3.0 y
  Sable < 1.3.0); TFMG 1.2.2 (Bits 'n' Bobs lo marca incompatible: se cambió por TFMG Community Edition 1.3.1);
  Xaero's Maps x Waystones (incompatible con Xaero's Minimap ≥ 26.2.0) y su librería YACL; Create Factory
  Logistics (Deployer lo marca incompatible); Create Deep Seas (mixin a `renderFluidStack` que ya no existe y
  clases de Sable que se movieron) y TwilightForest Thread Safety Addon (busca un método de Twilight Forest que ya
  no existe). Se agregaron The Undergarden y Deeper and Darker.
- Biomas: se cuentan en `data/<mod>/worldgen/biome/*.json` de cada jar (sin los biomas normales que retocan).
  No se agregó Biomes O' Plenty ni otros mods de biomas con TerraBlender: con Terralith los volcanes y cráteres
  quedarían escasos. The Aether se descartó: owo-lib trae dentro forgified-fabric-api.
- Versiones fijadas a propósito: Sodium 0.8.12 (Immersive Aeronautics exige esa exacta), Sodium Extra 0.9.3,
  Reese's Sodium Options 2.2.3, MoreCulling 1.0.9, Entity Culling 1.10.5 e ImmediatelyFast 1.6.12 (de la época de
  Sodium 0.8.12). Sin Iris: Create Aeronautics tiene fallas visuales con shaders. Incendium no va con Amplified
  Nether. Terralith sin Biomes O' Plenty (con BOP sus biomas quedan escasos).

## Publicar una versión nueva

1. Haz el cambio en `servidor-home/` y sube `APP_VERSION` en `servidor_home.py` (por ejemplo, de 2.5.0 a 2.5.1).
   La versión tiene que ser mayor que la última publicada; si no, las apps no la instalan.
2. Prueba (idealmente, toda la batería).
3. Ejecuta `build/construir.sh` para armar el instalador.
4. Ejecuta
   `python3 build/publicar.py --clave RUTA/clave-privada-NO-SUBIR.json --novedades novedades.txt`
   (en `novedades.txt` va una novedad por línea, en español simple).
   Queda todo en `build/publicar/<versión>/`, con un `LEEME.txt` que explica los pasos.
5. En GitHub: https://github.com/maxglich272/server-home/releases/new
   (el repositorio antes se llamaba `contrerasmaximiliano2407-wq/server-home`; GitHub redirige el nombre viejo,
   y las apps hasta la 2.5.5 todavía lo usan: no crees otro repositorio `server-home` en esa cuenta).
   - Etiqueta `v<versión>` y título `Servidor Home <versión>`.
   - Adjunta `actualizacion.json`, `servidor-home-<versión>.zip` y `Instalar-Servidor-Home.exe`.
   - Publica la release como «latest».

Las apps instaladas revisan cada 6 horas y también cada vez que se abren. Descargan
`releases/latest/download/actualizacion.json` y comprueban la firma con la clave pública que trae
`servidor_home.py` (`UPDATE_KEY_N`). Luego descargan el zip y comprueban su SHA-256. Antes de instalar, prueban que
el código nuevo cargue. Instalan la versión:

- al abrir la app,
- con el botón «Actualizar ahora»,
- o solas cuando no hay servidores encendidos ni ventana abierta.

Si la versión nueva no arranca, vuelven a la anterior y no reintentan esa versión.

Qué hace cada tipo de publicación:

- El zip solo reemplaza `servidor_home.py`, `README.md` y `web/*`. Para cambiar el Python que trae el instalador,
  los accesos directos o el desinstalador, la gente tiene que instalar el instalador nuevo a mano. Eso también
  sirve para quien tenga una versión anterior a la 2.5.0, que no traía el actualizador.
- Las apps solo instalan paquetes firmados con la clave privada. Sin ella no se puede publicar. Si se pierde, hay
  que hacer una clave nueva, poner su parte pública en `UPDATE_KEY_N` y pedirle a todos que instalen el
  instalador nuevo a mano.

## La clave privada

`clave-privada-NO-SUBIR.json` está en `Documentos\servidor home\clave-de-firma\`.

- No la subas a GitHub ni se la mandes a nadie: quien la tenga puede publicar versiones que tus amigos
  instalarían solos.
- Guarda una copia en un pendrive.
- Activa la verificación en dos pasos en tu cuenta de GitHub.
