import os, sys, shutil, threading, time
APP = "/home/claude/t3/app"; shutil.rmtree("/home/claude/t3", ignore_errors=True); shutil.copytree("/home/claude/servidor-home", APP)
os.environ["HOME"] = "/home/claude/mock2/home"
sys.path.insert(0, APP)
import servidor_home as sh
B = "http://127.0.0.1:9911"
sh.MOJANG_MANIFEST = B + "/manifest.json"; sh.FABRIC_META = B + "/fabric"; sh.NEOFORGE_MAVEN = B + "/neoforge"; sh.PLAYIT_API = B
sh.manager = sh.Manager(); sh.manager.playit = sh.Playit()
sh.ThreadingHTTPServer(("127.0.0.1", 8766), sh.Handler).serve_forever()
