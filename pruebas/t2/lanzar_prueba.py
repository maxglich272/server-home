# Arranca la app para las pruebas de actualización: mismo main(), pero apuntando al GitHub simulado, con la
# clave de prueba y tiempos cortos. Queda dentro de la carpeta de la app (el actualizador no lo toca).
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import servidor_home as sh  # noqa: E402

B = "http://127.0.0.1:9911"
sh.UPDATES_ENABLED = True
sh.UPDATE_MANIFEST_URL = os.environ["PRUEBA_URL"]
sh.UPDATE_KEY_N = int(os.environ["PRUEBA_KEY_N"], 16)
sh.UPDATE_FIRST_CHECK = float(os.environ.get("PRUEBA_FIRST", "1"))
sh.UPDATE_EVERY = float(os.environ.get("PRUEBA_EVERY", "4"))
sh.UPDATE_RETRY = 3
sh.UPDATE_TICK = 0.5
sh.UPDATE_UI_IDLE = float(os.environ.get("PRUEBA_UI_IDLE", "3"))
sh.MOJANG_MANIFEST = B + "/manifest.json"
sh.FABRIC_META = B + "/fabric"
sh.NEOFORGE_MAVEN = B + "/neoforge"
sh.ADOPTIUM_API = B + "/adoptium"
sh.PLAYIT_API = B
sh.PLAYIT_DOWNLOAD = B + "/playit-dl/"
sh.system_java_candidates = lambda: []
sh.main()
