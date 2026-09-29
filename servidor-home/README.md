# Servidor Home

Busca un modpack de Modrinth o CurseForge (o importa el tuyo), presiona **Encender** y comparte con tus amigos una
dirección fija de playit.gg. El servidor corre en este mismo PC y no hay que abrir puertos del router.

## Instalar (Windows)

Descarga el instalador desde
[github.com/contrerasmaximiliano2407-wq/server-home](https://github.com/contrerasmaximiliano2407-wq/server-home/releases/latest/download/Instalar-Servidor-Home.exe)
y ábrelo → *Siguiente* → *Terminar*. Se instala solo para tu usuario (no pide permisos de administrador) y deja el
acceso directo **Servidor Home** en el Escritorio y en el menú Inicio.

Como el instalador no tiene firma digital, la primera vez Windows puede mostrar *«Windows protegió su PC»*:
toca **Más información → Ejecutar de todas formas**.

No hay que instalar nada más: Python viene incluido, y Java y el programa de playit.gg se descargan solos
la primera vez que hacen falta.

## Abrir y cerrar

Servidor Home se abre en su propia ventana, como cualquier programa (usa el motor de Microsoft Edge, que ya
viene con Windows; no necesitas usar Edge como navegador). Mientras funciona, su ícono aparece junto al reloj.

Al abrirla aparece **Mis servidores**: una tarjeta por servidor con su imagen, su versión, si está encendido y
cuántos jugadores hay. Haz clic en uno para entrar; **← Mis servidores** (arriba) vuelve a la lista.

- **Cerrar la ventana** sin servidores encendidos cierra la app.
- Si hay un servidor encendido, pregunta: **Sí** lo apaga guardando el mundo y cierra la app;
  **No** lo deja funcionando en segundo plano para que tus amigos sigan jugando.
- Para volver a la ventana: clic en el ícono junto al reloj o en el acceso directo.
- **Salir** (arriba a la derecha, o clic derecho en el ícono junto al reloj) apaga todo guardando el mundo.

Los enlaces (playit.gg, EULA) se abren en tu navegador de siempre.

## 1. Agregar un servidor

En *Mis servidores*, **＋ Agregar servidor**. Hay cuatro formas:

- **Buscar:** escribe el nombre del modpack y elige si buscar en **Modrinth** o en **CurseForge** (sin escribir nada
  salen los más descargados). Abre el modpack, elige la versión y presiona **Crear servidor**. La app baja solo lo
  que usa el servidor: de Modrinth, el `.mrpack` y los mods que van en el servidor; de CurseForge, el *pack de
  servidor* si esa versión lo trae y, si no, los mods de la lista sin los que son solo del jugador.
- **Archivo:** arrastra el `.zip` del *Server Pack / Server Files* (en CurseForge: página del modpack → *Files*)
  o un `.mrpack` de Modrinth.
- **Desde mi launcher:** la app busca los modpacks instalados en este PC (CurseForge, SKLauncher, Prism,
  Modrinth App, ATLauncher). Sirve para modpacks propios que no tienen pack de servidor: copia mods y
  configuración, y deja fuera mundos, shaders, capturas y todo lo que es solo del jugador.
- **Sin mods:** Vanilla, Paper, Fabric, Forge o NeoForge en la versión que quieras.

**CurseForge pide una clave** para usar su buscador (Modrinth no): entra a
[console.curseforge.com](https://console.curseforge.com) con tu cuenta, abre *API Keys*, copia la clave y pégala una
vez en *Buscar → CurseForge*. Es gratis y queda guardada solo en este PC (se puede quitar con **Quitarla**). Con la
clave también se pueden crear servidores desde los `.zip` de CurseForge que solo traen la lista de mods (los que
exporta el launcher de CurseForge).

**Elegir la versión:** escribe la versión de Minecraft (por ejemplo `1.21.11`) o elígela de la lista; los botones
de abajo son atajos a las más usadas. Con *Mostrar snapshots* aparecen también las versiones de prueba. Para Fabric,
Forge y NeoForge puedes elegir además la versión del loader (viene marcada la recomendada). Tus amigos tienen que
jugar con la misma versión de Minecraft que el servidor.

Mientras se prepara el servidor, una barra muestra cuánto lleva.

Al importar, la app detecta el loader (NeoForge, Forge o Fabric) y la versión de Minecraft, y los muestra ya
elegidos: puedes cambiarlos, aunque los mods de un modpack solo funcionan en la versión para la que se hicieron.
También desactiva los mods que solo sirven en el cliente (Oculus, Sodium, Embeddium, menús, etc.): en el
servidor no aportan y a veces lo botan. Tus amigos los pueden seguir usando en su juego. Antes de desactivar uno,
revisa que ningún otro mod del servidor lo necesite (por ejemplo JEI, que muchos mods piden), y desactiva también los
mods que necesitan uno de shaders o gráficos (como Colorwheel, que necesita Iris).

En un modpack de Fabric, la versión de Fabric Loader sale del registro del launcher (si el modpack ya se abrió) o de lo
que piden sus mods. Si el modpack es de Minecraft 1.20.1 o anterior, usa la última 0.14: esos modpacks se hicieron con
ella, y desde la 0.15 algunos mods de esa época ya no funcionan (por ejemplo Not Enough Crashes 4.1).

## 2. Encender

El botón grande enciende y apaga. La primera vez un modpack puede tardar 2 a 5 minutos.
El botón redondo de su esquina **reinicia** el servidor: guarda el mundo, lo apaga y lo vuelve a encender (si hay
jugadores conectados, pregunta antes). Sirve, por ejemplo, para que se apliquen cambios de configuración.

Mientras el servidor se crea, se instala o se enciende, aparece una **barra de carga** con el porcentaje, lo que está
haciendo (por ejemplo *Descargando Java 21: 30 de 52 MB*), en qué paso va y cuánto tiempo lleva. Desde la segunda
vez, la barra del encendido se guía por lo que tardó la vez anterior.

### Si algo falla, se arregla solo

Si el servidor no enciende o se cae, la app lee la consola, busca la causa, la arregla y lo vuelve a encender.
Mientras tanto dice *Arreglando un problema…* y la barra muestra qué está haciendo. Arregla, entre otras cosas:

- **Mods que son solo del jugador** (gráficos, menús, minimapas): los desactiva en el servidor, todos los que fallaron
  de una vez. Si un mod necesita uno de esos (como Colorwheel, que necesita el mod de shaders Iris), desactiva también
  ese.
- **Un mod que necesita otro que está desactivado:** lo vuelve a activar, junto con lo que ese otro necesite.
- **Un mod que necesita otro que falta, o en otra versión:** lo descarga desde Modrinth para tu versión de Minecraft
  y tu loader, y revisa que el archivo sea de verdad ese mod.
- **Dos mods que chocan** y uno es solo del jugador: desactiva ese.
- **Un archivo de mod dañado** (una descarga que se cortó): lo desactiva y, si otro mod lo necesita, busca una copia buena.
- **Un mod que pide un Forge, NeoForge o Fabric más nuevo:** actualiza el loader.
- **Un Fabric Loader demasiado nuevo para un mod antiguo** (por ejemplo `NoClassDefFoundError:
  net/fabricmc/mapping/reader/v2/TinyVisitor` con Not Enough Crashes en un modpack de 1.18.2): cambia a la versión de
  Fabric Loader con la que tu launcher abre ese modpack, o a la más nueva que sirva para todos los mods (la 0.14.x).
  Se acuerda de ese tope para no volver a subirlo después. Si ninguna versión sirve para todos (un mod pide la 0.15 y
  otro no funciona desde ella), lo explica y ofrece desactivar el mod antiguo.
- **Un mod que no se puede enganchar en otro** (en la consola: *Critical injection failure* o *failed injection
  check*; por ejemplo CBC Neo Warfare con Immersive Aeronautics, que botaba el servidor un segundo después de
  encender): dice cuál es y lo desactiva. Tus amigos también tienen que quitarlo de su juego.
- **Un mod que falla al cargar:** busca una versión más nueva y, si no hay o también falla, lo desactiva junto con los
  mods que lo necesitan (sin él no pueden cargar). Si son más de 8, no lo hace solo porque cambiaría mucho el modpack:
  lo explica y ofrece un botón.
- **Mods repetidos** (el mismo mod dos veces): deja el más nuevo.
- **Falta de memoria:** sube la RAM, sin pasar del 75 % de la del PC. Si Java no alcanza a reservar la RAM pedida
  (el PC no tiene tanta libre), la baja.
- **Una opción de Java que tu Java no conoce** (en los argumentos extra): la quita.
- **Faltan archivos del servidor** (una instalación que quedó a medias): reinstala Forge, NeoForge o Fabric sin tocar
  el mundo ni los mods.
- **Un mod que necesita otro Java:** lo descarga.
- **Puerto ocupado:** usa otro (la dirección de playit.gg no cambia).
- **Un archivo de configuración dañado:** lo guarda aparte y el mod crea uno nuevo.
- **El vigilante de Minecraft** que corta el servidor en momentos de mucha carga: lo desactiva.
- **Una caída sin causa conocida** mientras juegan: lo vuelve a encender (hasta 3 veces en media hora).

El mensaje de error dice qué mod causó la caída, por ejemplo *El servidor no pudo encender por los mods «WeatherRefind» y
«guy's Armor HUD»*. Si solo se sabe por el rastro del error (no porque el loader lo diga), dice *el error apunta al mod
«…»* y ofrece desactivarlo con un botón, sin hacerlo solo. En la pestaña **Mods**, cada mod que la app desactivó dice
por qué.

NeoForge y Forge terminan «sin error» cuando falla la carga de mods; la app igual lo detecta como una falla y lo
arregla (hasta la versión 2.5.1 lo tomaba como un apagado normal). Si Java queda abierto después de fallar, lo cierra.
Todo lo que hace queda anotado en `servidor-home.log`, dentro de la carpeta de cada servidor.

Antes de encender con mods cambiados o con otro loader, respalda el mundo (queda en *Respaldos*). Los mods que quita no
se borran: quedan desactivados en la pestaña Mods y se pueden volver a activar. Al terminar aparece **Se arregló solo**
con la lista de lo que hizo.

Desactivar un mod que agrega bloques o criaturas puede quitar esas cosas del mundo: por eso antes respalda el mundo, y
solo lo hace si ese mod no deja encender el servidor. Si no encuentra cómo arreglarlo (por ejemplo, un mod que solo está
en CurseForge), explica qué pasó y qué hacer.
Mientras arregla puedes presionar **Detener**. Si prefieres arreglar las cosas tú, desactiva *Ajustes → Arreglar
problemas solo*: la app seguirá diciendo qué pasó y ofrecerá el arreglo con un botón.

## 3. Jugar por internet con playit.gg

En la tarjeta **Cómo entran tus amigos** presiona **Conectar con playit.gg**:

1. Abre el enlace, entra a tu cuenta de playit.gg (o crea una gratis) y aprueba el programa.
2. Vuelve a Servidor Home: la app crea sola la dirección de Minecraft (algo como `nombre.gl.joinmc.link`).
3. Copia la dirección y pásasela a tus amigos. Ellos la pegan en *Multijugador → Agregar servidor*.

Esa dirección es fija: no cambia aunque se reinicie el router o cambie la IP de tu casa, y funciona
aunque tu internet no permita abrir puertos. Si más adelante quieres un dominio propio o una IP dedicada,
eso se contrata como *playit Premium* en su página.

Servidor Home tiene que estar funcionando (aunque sea en segundo plano, con el ícono junto al reloj)
para que tus amigos puedan entrar.

### Compartir los mods con tus amigos

Para entrar a un servidor con mods, tus amigos necesitan los mismos mods en su juego. En **Cómo entran tus amigos**
(o en la pestaña Mods) presiona **Compartir mods con amigos**: la app arma un `.zip` con los mods que el jugador
necesita (sin los que solo sirven en el servidor, y con los de gráficos o interfaz que el servidor tiene desactivados),
los scripts de KubeJS que hagan falta y un `LEEME.txt` con los pasos: qué versión de Forge, NeoForge o Fabric
instalar, dónde copiar los mods y a qué dirección entrar. El zip se descarga con **Descargar el zip** y además queda
en `Documentos\servidor home\compartir`. Si pesa mucho para Discord o WhatsApp, súbelo a Google Drive y comparte el
enlace.

## Jugadores

La pestaña **Jugadores** de cada servidor muestra a todos los que han entrado alguna vez, con su cabeza de Minecraft,
si están conectados ahora y cuándo se vieron por última vez. Desde la misma lista puedes:

- **Hacer admin** (operador) o quitarle el admin.
- **Expulsar** a alguien conectado (puede volver a entrar).
- **Banear** (con un motivo, si quieres) o **desbanear**.
- **Agregarlo o quitarlo de la lista blanca.**

Arriba puedes escribir el nombre de alguien que todavía no ha entrado para agregarlo a la lista blanca, hacerlo admin
o banearlo de antemano. Con el servidor encendido los cambios se aplican al instante; apagado, quedan guardados y valen
desde que se encienda. Si el servidor permite cuentas no premium, la app usa el identificador que Minecraft les da a
esas cuentas; si no, lo busca en Mojang.

## Imagen y mensaje del servidor

En *Ajustes → Imagen y mensaje del servidor* ves cómo aparece tu servidor en la lista de servidores de Minecraft.
Arrastra una imagen encima (o **Cambiar imagen**): se recorta al centro y se ajusta a los 64×64 píxeles que pide
Minecraft (los dibujos chicos se agrandan sin difuminarse). El mensaje tiene dos líneas y botones para ponerle colores,
negrita o cursiva. Los cambios se ven en la lista de servidores después de reiniciar el servidor.

## Cambiar la versión de un servidor

En *Ajustes → Versión* (o con el enlace **cambiar versión** junto al nombre del servidor) eliges otra versión de
Minecraft o del loader y presionas **Cambiar versión** con el servidor apagado. La app respalda el mundo antes
(queda en *Respaldos*), instala la versión nueva y conserva mods, plugins y ajustes.

Si bajas de versión (por ejemplo de 26.3 a 1.21.11) te recomienda **empezar con un mundo nuevo**: Minecraft no está
hecho para abrir un mundo de una versión más nueva. El mundo anterior no se borra; queda en la carpeta
`mundos-anteriores` del servidor. Si el servidor tiene mods, al cambiar la versión de Minecraft tendrás que cambiarlos
por sus versiones para la nueva.

Las versiones antiguas (1.7 a 1.18) se encienden con la protección contra el fallo *Log4Shell* que publicó Mojang,
y la app descarga sola el Java que necesita cada versión (Java 8 para las más antiguas).

## Rendimiento

El servidor de Minecraft no dibuja nada: calcula el mundo (mobs, redstone, cultivos, terreno) con el **procesador**
y la **RAM**. Por eso ningún servidor de Minecraft usa la tarjeta gráfica. Lo que sí hace Servidor Home para que
el servidor ande fluido:

- **Java optimizado** (*Ajustes → Rendimiento*, activado de fábrica): usa los ajustes de memoria probados para
  servidores de Minecraft, con menos tirones cuando Java limpia la memoria. Si un modpack trae sus propios ajustes
  de memoria, se respetan.
- **Mientras haya un servidor encendido, el PC no se suspende solo** (la pantalla sí puede apagarse), y Windows no
  lo pone en «modo eficiencia», que en laptops con batería le baja la velocidad.
- **Mods de rendimiento** (*Ajustes → Rendimiento*, botón opcional para Fabric, Forge y NeoForge): agrega desde
  Modrinth **Lithium**, **FerriteCore** y **ModernFix** en la versión correcta. Hacen que el servidor calcule más
  rápido y use menos memoria, sin cambiar cómo se juega. Si alguno choca con el modpack, la app lo detecta al encender.
- Si hay lag con muchos jugadores, baja `simulation-distance` a 6 u 8 (*Opciones avanzadas → Todas las
  propiedades*): el mundo lejos de los jugadores se detiene y el servidor trabaja mucho menos.
- La ventana de la app consulta menos cuando está minimizada.

Para anclar Servidor Home a la barra de tareas, haz clic derecho en su ícono mientras está abierto → *Anclar a la
barra de tareas* (o desde el menú Inicio).

## Actualizaciones automáticas

Servidor Home se mantiene al día solo. Cada algunas horas revisa si hay una versión nueva; si la hay, la descarga
y comprueba su **firma digital**: solo se aceptan versiones publicadas por el autor, así que nadie puede colarte una
versión falsa. Luego la instala sin molestar:

- Si la ventana está abierta, aparece arriba el aviso **Hay una versión nueva**, con sus novedades y el botón
  **Actualizar ahora** (tarda unos segundos; la ventana vuelve sola).
- Si no, se instala la próxima vez que abras Servidor Home, o sola cuando no haya servidores encendidos ni la
  ventana abierta. **Nunca se reinicia con un servidor encendido**: no corta a nadie que esté jugando.
- Si una versión nueva no arranca bien, vuelve sola a la anterior y esa versión no se vuelve a instalar.

Tus servidores, mundos y ajustes no se tocan. Abajo de la ventana se ve la versión que tienes, el botón
**Buscar actualizaciones** y la opción **Actualizar automáticamente** (si la apagas, igual te avisa y actualizas con
el botón). La versión portable (la carpeta suelta) no se actualiza sola.

## Seguridad

- **Permitir cuentas no premium** (Ajustes) sirve para amigos con SKLauncher o TLauncher. Si lo activas,
  cualquiera con la dirección podría entrar usando cualquier nombre. Activa también la **lista blanca**
  y agrega a tus amigos en la pestaña **Jugadores**.
- El panel solo se puede usar desde este PC. playit.gg solo expone el puerto de Minecraft, nunca el panel.
- La primera vez que enciendas un servidor, Windows puede preguntar si Java puede usar la red.
  Permite *Redes privadas* (hace falta solo para jugar en la misma casa; playit.gg funciona igual).

## Dónde quedan las cosas

- `Documentos\servidor home\servidores\<nombre>\`: cada servidor (mundo, mods, configuración).
  Los respaldos quedan en `respaldos\` dentro de cada servidor.
- `%LOCALAPPDATA%\Servidor Home\`: Java, el programa y la clave de playit.gg (la clave es privada,
  no la compartas), la clave de CurseForge si la pusiste (`ajustes.json`) y el registro `servidor-home.log`.
- `%LOCALAPPDATA%\Programs\Servidor Home\`: el programa.

## Desinstalar

*Configuración → Aplicaciones → Servidor Home → Desinstalar*. Tus servidores y mundos en
`Documentos\servidor home` no se borran. El desinstalador pregunta si también quieres borrar Java y
el vínculo con playit.gg.

## Problemas comunes

- **"Le faltó memoria":** la app sube la RAM sola. Si el PC no tiene más, cierra otros programas o usa un modpack
  más liviano (los modpacks grandes usan 6 a 10 GB). Deja algo libre si vas a jugar en el mismo PC.
- **"El puerto ya está en uso":** la app pasa sola a otro puerto. Para entrar desde tu casa usa la dirección que
  muestra la tarjeta *Cómo entran tus amigos* (termina en `:25566` o parecido).
- **Faltan mods:** la app los busca en Modrinth. Si un mod solo está en CurseForge, descárgalo de ahí y agrega el
  `.jar` en la pestaña Mods.
- **playit no conecta:** revisa que el PC tenga internet. En *Detalles de playit* se ve el registro del programa.
- **Windows borró o bloqueó playit:** algunos antivirus desconfían de los programas de túneles. En
  *Seguridad de Windows → Protección contra virus y amenazas → Historial de protección* puedes permitirlo.
- **No aparece la ventana:** abre `http://127.0.0.1:8765` en tu navegador; el panel es el mismo.

## Versión portable y Linux

La carpeta del proyecto también funciona sin instalar: en Windows, doble clic en **Servidor Home.bat**
(la primera vez descarga Python); en Linux, `bash iniciar.sh`. En ese modo todo queda dentro de la carpeta.
Si pasas de la versión portable a la instalada y la portable estaba en `Documentos\servidor home`,
la instalada usa los mismos servidores y el mismo vínculo con playit.gg (tus amigos no tienen que cambiar
la dirección). Opciones para usuarios avanzados: `--lan` (abrir el panel desde otros equipos de tu red,
sin contraseña), `--navegador` (usar el navegador en vez de la ventana propia) y `--port 8766`.
