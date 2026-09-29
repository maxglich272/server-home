import json, os, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
W = "/home/claude/mock2/www"
B = "http://127.0.0.1:9911"
STATE = {"slow": {}, "claims": {}, "tunnels": [], "created": 0, "config_calls": [], "secret": "a1b2c3d4e5f60718293a4b5c6d7e8f90a1b2c3d4e5f60718293a4b5c6d7e8f90"}
# (id, tipo, java) de la más nueva a la más antigua, como el manifiesto real de Mojang
VLIST = [("26.4-snapshot-2", "snapshot", 25), ("26.3", "release", 25), ("26.2", "release", 25), ("1.21.11", "release", 21),
         ("1.21.8", "release", 21), ("1.21.1", "release", 21), ("1.20.1", "release", 17), ("1.16.5", "release", 8),
         ("1.12.2", "release", 8), ("1.8.9", "release", 8)]
VERS = {v: j for v, _t, j in VLIST}
import io, tarfile
def fake_jre(major, pad=0):
    """JRE falso: dice ser Java <major> y por dentro usa el Java del sistema (le avisa al servidor falso
    qué Java simula con -Dfakejava). pad: bytes de relleno para que la descarga se note en la barra."""
    ver = "1.8.0_402" if major == 8 else f"{major}.0.1"
    script = ("#!/bin/sh\nfor a in \"$@\"; do if [ \"$a\" = \"-version\" ]; then echo 'openjdk version \"%s\"' >&2; exit 0; fi; done\n"
              "exec /usr/bin/java -Dfakejava=%d \"$@\"\n" % (ver, major)).encode()
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as t:
        info = tarfile.TarInfo(f"jdk-{major}-jre/bin/java"); info.size = len(script); info.mode = 0o755
        t.addfile(info, io.BytesIO(script))
        if pad:
            info = tarfile.TarInfo(f"jdk-{major}-jre/lib/modules"); info.size = pad
            t.addfile(info, io.BytesIO(os.urandom(pad)))
    return buf.getvalue()


# --- Modrinth falso: proyectos, versiones y archivos .jar generados ---
import hashlib, zipfile, urllib.parse
def mod_jar(loader, mid, version, name, pad=0):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        if pad:          # que pese algo, para ver el avance de la descarga
            z.writestr("assets/pad.bin", os.urandom(pad))
        if loader == "fabric":
            z.writestr("fabric.mod.json", json.dumps({"schemaVersion": 1, "id": mid, "version": version, "name": name, "environment": "*"}))
        else:
            z.writestr("META-INF/neoforge.mods.toml", f'modLoader="javafml"\nloaderVersion="[4,)"\nlicense="MIT"\n[[mods]]\n'
                                                       f'modId="{mid}"\nversion="{version}"\ndisplayName="{name}"\n')
        z.writestr(f"com/example/{mid.replace('-', '_')}/Main.class", b"\xca\xfe\xba\xbe")
    return buf.getvalue()
# slug: (id del mod, nombre, [(versión, loaders, versiones de Minecraft, archivo, fecha, tipo)])
MR = {
    "libdep": ("libdep", "Lib Dep", [("1.0", ["fabric"], ["1.21.8"], "libdep-1.0.jar", "2025-01-10T00:00:00Z", "release"),
                                     ("2.0", ["fabric"], ["1.21.8"], "libdep-2.0.jar", "2026-02-10T00:00:00Z", "release"),
                                     ("2.1-beta", ["fabric"], ["1.21.8"], "libdep-2.1-beta.jar", "2026-08-10T00:00:00Z", "beta")]),
    "gecko-decoy": ("geckoextra", "Gecko Extra", [("1.0", ["neoforge"], ["1.21.1"], "geckolib-addon-extra-1.0.jar", "2026-05-01T00:00:00Z", "release")]),
    "geckolib-real": ("geckolib", "GeckoLib", [("4.7.1", ["neoforge"], ["1.21.1"], "geckolib-neoforge-1.21.1-4.7.1.jar", "2026-03-01T00:00:00Z", "release"),
                                               ("4.7.1", ["fabric"], ["1.21.1"], "geckolib-fabric-1.21.1-4.7.1.jar", "2026-03-01T00:00:00Z", "release")]),
    "balm": ("balm", "Balm", [("21.0.20", ["neoforge"], ["1.21.1"], "balm-neoforge-1.21.1-21.0.20.jar", "2026-01-05T00:00:00Z", "release")]),
    "buggy": ("buggy", "Buggy Mod", [("1.0", ["neoforge"], ["1.21.1"], "buggy-1.0.jar", "2025-06-01T00:00:00Z", "release"),
                                     ("1.1", ["neoforge"], ["1.21.1"], "buggy-1.1.jar", "2026-04-01T00:00:00Z", "release")]),
    "newloader": ("newloader", "Needs New Loader", []),
    "lithium": ("lithium", "Lithium", [("0.18.0", ["fabric"], ["1.21.8"], "lithium-fabric-0.18.0+mc1.21.8.jar", "2026-07-01T00:00:00Z", "release"),
                                       ("0.15.1", ["neoforge"], ["1.21.1"], "lithium-neoforge-0.15.1+mc1.21.1.jar", "2026-02-01T00:00:00Z", "release")]),
    "ferrite-core": ("ferritecore", "FerriteCore", [("8.0.0", ["fabric"], ["1.21.8"], "ferritecore-8.0.0-fabric.jar", "2026-06-01T00:00:00Z", "release"),
                                                   ("7.0.2", ["neoforge"], ["1.21.1"], "ferritecore-7.0.2-neoforge.jar", "2026-01-01T00:00:00Z", "release")]),
    "modernfix": ("modernfix", "ModernFix", [("5.24.0", ["fabric"], ["1.21.8"], "modernfix-fabric-5.24.0+mc1.21.8.jar", "2026-07-01T00:00:00Z", "release"),
                                             ("5.24.0", ["neoforge"], ["1.21.1"], "modernfix-neoforge-5.24.0+mc1.21.1.jar", "2026-07-01T00:00:00Z", "release")]),
    "stubborn2": ("stubborn2", "Stubborn Two", [("1.1", ["neoforge"], ["1.21.1"], "broken-stubborn2-1.1.jar", "2026-04-01T00:00:00Z", "release")]),
}
SEARCH = {"geckolib": ["gecko-decoy", "geckolib-real"]}
MR_FILES = {}
for _slug, (_mid, _name, _vers) in MR.items():
    for _v, _loaders, _gv, _fname, _date, _typ in _vers:
        MR_FILES[_fname] = mod_jar(_loaders[0], _mid, _v, _name, pad=600 * 1024 if _mid == "libdep" else 0)
def mr_versions(slug, qs):
    loaders = json.loads(qs.get("loaders", ["[]"])[0]); gvs = json.loads(qs.get("game_versions", ["[]"])[0])
    out = []
    for v, ld, gv, fname, date, typ in MR[slug][2]:
        if (loaders and not set(loaders) & set(ld)) or (gvs and not set(gvs) & set(gv)):
            continue
        b = MR_FILES[fname]
        out.append({"id": f"{slug}-{v}-{ld[0]}", "project_id": slug, "version_number": v, "version_type": typ, "date_published": date,
                    "loaders": ld, "game_versions": gv,
                    "files": [{"url": f"{B}/mr-files/{fname}", "filename": fname, "primary": True, "size": len(b),
                               "hashes": {"sha1": hashlib.sha1(b).hexdigest(), "sha512": hashlib.sha512(b).hexdigest()}}]})
    out.reverse()      # como la API real: sin un orden garantizado (la app ordena)
    return out

# --- modpacks falsos (buscador) ---
def _zip(entries):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for n, b in entries.items():
            z.writestr(n, b)
    return buf.getvalue()
def client_jar(mid):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("META-INF/neoforge.mods.toml", f'modLoader="javafml"\nloaderVersion="[4,)"\nlicense="MIT"\n[[mods]]\nmodId="{mid}"\nversion="1.0"\ndisplayName="{mid}"\n')
        z.writestr(f"com/example/{mid}/Main.class", b"\xca\xfe\xba\xbe")
    return buf.getvalue()
MR_FILES["sodium-neoforge-9.9.jar"] = client_jar("sodium")          # conocido solo-cliente, sin marcar en el .mrpack
MR_FILES["zoomify-neoforge-1.0.jar"] = client_jar("zoomify")
def _mrfile(name, env_server="required"):
    b = MR_FILES[name]
    return {"path": "mods/" + name, "hashes": {"sha1": hashlib.sha1(b).hexdigest(), "sha512": hashlib.sha512(b).hexdigest()},
            "env": {"client": "required", "server": env_server}, "downloads": [f"{B}/mr-files/{name}"], "fileSize": len(b)}
MR_PACK = _zip({"modrinth.index.json": json.dumps({"formatVersion": 1, "game": "minecraft", "versionId": "1.0", "name": "Volcanes de Prueba",
    "files": [_mrfile("balm-neoforge-1.21.1-21.0.20.jar"), _mrfile("geckolib-neoforge-1.21.1-4.7.1.jar"),
              _mrfile("sodium-neoforge-9.9.jar"), _mrfile("zoomify-neoforge-1.0.jar", "unsupported")],
    "dependencies": {"minecraft": "1.21.1", "neoforge": "21.1.77"}}),
    "overrides/config/volcanes.toml": "lava = true\n"})
MR_FILES["volcanes-1.0.mrpack"] = MR_PACK
MR_PACK_VERSION = {"id": "volc10", "name": "Volcanes 1.0", "version_number": "1.0", "game_versions": ["1.21.1"], "loaders": ["neoforge"],
                   "date_published": "2026-09-01T00:00:00Z", "version_type": "release",
                   "files": [{"url": f"{B}/mr-files/volcanes-1.0.mrpack", "filename": "volcanes-1.0.mrpack", "primary": True, "size": len(MR_PACK)}]}
MR_MODPACKS = [{"project_id": "volcanes", "slug": "volcanes", "title": "Volcanes de Prueba", "description": "Un modpack de prueba con volcanes.",
                "icon_url": None, "downloads": 12345, "author": "max", "versions": ["1.21.1"], "categories": ["neoforge", "adventure"],
                "display_categories": ["neoforge"], "server_side": "required"},
               {"project_id": "soloclient", "slug": "soloclient", "title": "Solo Cliente", "description": "Pack de gráficos.", "icon_url": None,
                "downloads": 99, "author": "otro", "versions": ["1.21.1"], "categories": ["fabric"], "server_side": "unsupported"}]

# --- CurseForge falso: pide la clave «clave-de-prueba-123456» ---
CF_KEY = "clave-de-prueba-123456"
CF_JARS = {7001: ("balm-neoforge-1.21.1-21.0.20.jar", MR_FILES["balm-neoforge-1.21.1-21.0.20.jar"], ["1.21.1", "NeoForge", "Client", "Server"], 501),
           7002: ("fancyhud-1.0.jar", client_jar("fancyhud"), ["1.21.1", "NeoForge", "Client"], 502),
           7003: ("Texturas Bonitas.zip", b"PK\x05\x06" + b"\x00" * 18, ["1.21.1"], 503),
           7004: ("Mod Con Espacios 1.0.jar", client_jar("conespacios"), ["1.21.1", "NeoForge", "Server"], 504)}
CF_MODS = {501: {"id": 501, "name": "Balm", "classId": 6}, 502: {"id": 502, "name": "Fancy HUD", "classId": 6},
           503: {"id": 503, "name": "Texturas Bonitas", "classId": 12}, 504: {"id": 504, "name": "Con Espacios", "classId": 6}}
CF_CLIENT_ZIP = _zip({"manifest.json": json.dumps({"minecraft": {"version": "1.21.1", "modLoaders": [{"id": "neoforge-21.1.77", "primary": True}]},
    "manifestType": "minecraftModpack", "manifestVersion": 1, "name": "Pack CF", "version": "0.9", "overrides": "overrides",
    "files": [{"projectID": CF_JARS[i][3], "fileID": i, "required": True} for i in CF_JARS]}),
    "overrides/config/packcf.toml": "x = 1\n"})
def cf_file(fid):
    if fid in CF_JARS:
        n, b, gv, mid = CF_JARS[fid]
        return {"id": fid, "modId": mid, "fileName": n, "displayName": n, "fileLength": len(b), "gameVersions": gv,
                "downloadUrl": f"{B}/cf-files/{urllib.parse.quote(n)}" if fid != 7004 else f"{B}/cf-files/{n}",
                "hashes": [{"value": hashlib.sha1(b).hexdigest(), "algo": 1}, {"value": "x", "algo": 2}]}
    base = {"modId": 900, "fileDate": "2026-09-10T00:00:00Z", "releaseType": 1, "gameVersions": ["1.21.1", "NeoForge"], "isServerPack": False}
    if fid == 9001: return {**base, "id": 9001, "displayName": "Pack CF 1.0", "fileName": "PackCF-1.0.zip", "serverPackFileId": 9002, "fileLength": 10, "downloadUrl": None}
    if fid == 9002: return {**base, "id": 9002, "displayName": "Pack CF 1.0 Server", "fileName": "PackCF-Server-1.0.zip", "isServerPack": True, "fileLength": 10,
                            "downloadUrl": f"{B}/cf-files/PackCF-Server-1.0.zip"}
    if fid == 9003: return {**base, "id": 9003, "displayName": "Pack CF 0.9", "fileName": "PackCF-0.9.zip", "serverPackFileId": None, "fileDate": "2026-08-01T00:00:00Z",
                            "fileLength": len(CF_CLIENT_ZIP), "downloadUrl": f"{B}/cf-files/PackCF-0.9.zip"}
    return None
def cf_blob(name):
    name = urllib.parse.unquote(name)
    if name == "PackCF-Server-1.0.zip": return open("/home/claude/mock2/ServerFiles-1.0.zip", "rb").read()
    if name == "PackCF-0.9.zip": return CF_CLIENT_ZIP
    for n, b, _g, _m in CF_JARS.values():
        if n == name: return b
    return None
class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def j(self, obj, code=200):
        b = json.dumps(obj).encode(); self.send_response(code); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
    def slow(self, b, secs=0.0):
        self.send_response(200); self.send_header("Content-Length", str(len(b))); self.end_headers()
        if not secs:
            return self.wfile.write(b)
        step = max(1, len(b) // 30)
        for i in range(0, len(b), step):
            self.wfile.write(b[i:i + step]); self.wfile.flush(); time.sleep(secs / 30)
    def f(self, path, ctype="application/octet-stream"):
        b = open(path, "rb").read(); self.send_response(200); self.send_header("Content-Type", ctype); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
    def do_GET(self):
        p = self.path
        if p == "/manifest.json":
            return self.j({"latest": {"release": "26.3", "snapshot": "26.4-snapshot-2"},
                           "versions": [{"id": v, "type": t, "url": f"{B}/v/{v}.json"} for v, t, _j in VLIST]})
        if p.startswith("/v/"):
            v = p[3:-5]; return self.j({"id": v, "javaVersion": {"majorVersion": VERS[v]}, "downloads": {"server": {"url": f"{B}/fabric-server.jar"}}})
        if p == "/fabric/game": return self.j([{"version": "26.4-snapshot-2", "stable": False}, {"version": "26.3", "stable": True},
                                               {"version": "1.21.11", "stable": True}, {"version": "1.21.8", "stable": True}, {"version": "1.21.1", "stable": True},
                                               {"version": "1.18.2", "stable": True}])
        if p.startswith("/adoptium/"):
            major = int(p.split("/")[2]); STATE.setdefault("java_downloads", []).append(major)
            secs = STATE["slow"].get("java", 0)
            return self.slow(fake_jre(major, pad=3 * 1048576 if secs else 0), secs)
        if p.startswith("/modrinth-api/v2/"):
            u = urllib.parse.urlparse(p); qs = urllib.parse.parse_qs(u.query); parts = u.path.split("/")[3:]
            STATE.setdefault("mr_requests", []).append(p)
            if parts == ["search"] and "project_type:modpack" in qs.get("facets", [""])[0]:
                q = qs.get("query", [""])[0].lower()
                hits = [h for h in MR_MODPACKS if not q or q in h["title"].lower()]
                return self.j({"hits": hits, "total_hits": len(hits)})
            if parts == ["project", "volcanes", "version"]:
                return self.j([MR_PACK_VERSION])
            if parts == ["version", "volc10"]:
                return self.j(MR_PACK_VERSION)
            if parts == ["search"]:
                q = qs.get("query", [""])[0].replace(" ", "").lower()
                hits = SEARCH.get(q) or [slug for slug in MR if q and q in slug]
                return self.j({"hits": [{"slug": h, "project_id": h, "title": MR[h][1]} for h in hits], "total_hits": len(hits)})
            if len(parts) == 3 and parts[0] == "project" and parts[2] == "version":
                slug = urllib.parse.unquote(parts[1])
                if slug not in MR:
                    return self.j({"error": "not_found", "description": "the requested route does not exist"}, 404)
                return self.j(mr_versions(slug, qs))
            return self.j({"error": "not_found"}, 404)
        if p.startswith("/cf-api/v1/"):
            if self.headers.get("x-api-key") != CF_KEY:
                return self.j({"error": "forbidden"}, 403)
            u = urllib.parse.urlparse(p); parts = u.path.split("/")[3:]
            STATE.setdefault("cf_requests", []).append(p)
            if parts == ["games", "432"]: return self.j({"data": {"id": 432, "name": "Minecraft"}})
            if parts == ["mods", "search"]:
                return self.j({"data": [{"id": 900, "name": "Pack CF", "summary": "Un modpack de CurseForge de prueba", "slug": "pack-cf",
                                         "logo": {"thumbnailUrl": None}, "downloadCount": 5000, "authors": [{"name": "cfautor"}],
                                         "latestFilesIndexes": [{"gameVersion": "1.21.1", "modLoader": 6}], "links": {"websiteUrl": "https://www.curseforge.com/minecraft/modpacks/pack-cf"}}],
                               "pagination": {"totalCount": 1}})
            if parts == ["mods", "900", "files"]:
                return self.j({"data": [cf_file(9001), cf_file(9002), cf_file(9003)]})
            if len(parts) == 4 and parts[:3] == ["mods", "900", "files"]:
                f = cf_file(int(parts[3]))
                return self.j({"data": f}) if f else self.j({"error": "nf"}, 404)
            return self.j({"error": "not_found"}, 404)
        if p.startswith("/cf-files/"):
            b = cf_blob(p[len("/cf-files/"):])
            STATE.setdefault("cf_downloads", []).append(p)
            if b is None:
                self.send_response(404); self.end_headers(); return
            return self.slow(b)
        if p.startswith("/gh/latest/download/"):              # GitHub: la última release redirige a su etiqueta
            name = p.rsplit("/", 1)[-1]
            STATE.setdefault("gh_requests", []).append(name)
            try:
                tag = open(W + "/gh/latest/TAG").read().strip()
            except OSError:
                tag = ""
            if not tag or not os.path.isfile(f"{W}/gh/{tag}/{name}"):
                self.send_response(404); self.end_headers(); return
            self.send_response(302); self.send_header("Location", f"{B}/gh/releases/download/{tag}/{name}")
            self.send_header("Content-Length", "0"); self.end_headers(); return
        if p.startswith("/gh/releases/download/"):
            _e, _g, _r, _d, tag, name = p.split("/")
            path = f"{W}/gh/{tag}/{name}"
            if ".." in tag or ".." in name or not os.path.isfile(path):
                self.send_response(404); self.end_headers(); return
            STATE.setdefault("gh_downloads", []).append(f"{tag}/{name}")
            return self.f(path)
        if p.startswith("/mr-files/"):
            name = p[len("/mr-files/"):]
            STATE.setdefault("mr_downloads", []).append(name)
            if name not in MR_FILES:
                self.send_response(404); self.end_headers(); return
            return self.slow(MR_FILES[name], STATE["slow"].get("mr", 0))
        # como la API real: solo la versión más nueva (que no es de prueba) viene marcada «stable»
        if p == "/fabric/loader": return self.j([{"version": "0.17.0-beta", "stable": False}, {"version": "0.16.14", "stable": True},
                                                 {"version": "0.15.11", "stable": False}, {"version": "0.14.25", "stable": False},
                                                 {"version": "0.14.9", "stable": False}, {"version": "0.13.3", "stable": False}])
        if p == "/fabric/installer": return self.j([{"version": "1.1.0", "stable": True}])
        if p.startswith("/fabric/loader/") and p.endswith("/server/jar"):
            import zipfile as zf
            _e, _f, _l, gmc, lver = p.split("/")[:5]
            STATE.setdefault("fabric_jars", []).append(f"{gmc}/{lver}")
            buf = io.BytesIO(open(W + "/fabric-server.jar", "rb").read())
            with zf.ZipFile(buf, "a") as z:           # el servidor falso sabe qué Fabric Loader pidió la app
                z.writestr("loader.txt", lver); z.writestr("mc.txt", gmc)
            b = buf.getvalue(); self.send_response(200); self.send_header("Content-Length", str(len(b))); self.end_headers(); return self.wfile.write(b)
        if p == "/neoforge/maven-metadata.xml":
            b = b"<metadata><versioning><versions><version>21.1.66</version><version>21.1.77</version><version>21.1.80-beta</version><version>21.8.10</version></versions></versioning></metadata>"
            self.send_response(200); self.send_header("Content-Length", str(len(b))); self.end_headers(); return self.wfile.write(b)
        if p.startswith("/neoforge/") and p.endswith("-installer.jar"):
            import zipfile as zf
            buf = io.BytesIO(open(W + "/neoforge-installer.jar", "rb").read())
            with zf.ZipFile(buf, "a") as z:
                z.writestr("version.txt", p.split("/")[2])          # el instalador falso instala la versión pedida
            b = buf.getvalue(); self.send_response(200); self.send_header("Content-Length", str(len(b))); self.end_headers(); return self.wfile.write(b)
        if p.startswith("/modrinth/"): return self.f(W + p)
        if p == "/fabric-server.jar": return self.f(W + "/fabric-server.jar")
        if p.startswith("/playit-dl/") and p.endswith(".exe"):
            return self.f("/home/claude/win/playitd-win.exe") if "-signed" in p else (self.send_response(404), self.end_headers())
        if p.startswith("/playit-dl/"): return self.f(W + "/playitd-bin")
        self.send_response(404); self.end_headers()
    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0); body = json.loads(self.rfile.read(n) or b"{}")
        p = self.path; auth = self.headers.get("Authorization", "")
        if p.startswith("/cf-api/v1/"):
            if self.headers.get("x-api-key") != CF_KEY:
                return self.j({"error": "forbidden"}, 403)
            if p == "/cf-api/v1/mods/files":
                return self.j({"data": [cf_file(i) for i in body.get("fileIds", []) if cf_file(i)]})
            if p == "/cf-api/v1/mods":
                return self.j({"data": [CF_MODS[i] for i in body.get("modIds", []) if i in CF_MODS]})
            return self.j({"error": "not_found"}, 404)
        if p == "/__slow":
            STATE["slow"] = body; return self.j(STATE["slow"])
        if p == "/__reset-mr":
            STATE["mr_requests"] = []; STATE["mr_downloads"] = []; return self.j({})
        if p == "/claim/setup":
            c = STATE["claims"].setdefault(body["code"], 0); STATE["claims"][body["code"]] += 1
            assert body["agent_type"] == "self-managed"
            st = ["WaitingForUserVisit", "WaitingForUser"][c] if c < 2 else "UserAccepted"
            return self.j({"status": "success", "data": st})
        if p == "/claim/exchange":
            return self.j({"status": "success", "data": {"secret_key": STATE["secret"]}})
        if auth != "Agent-Key " + STATE["secret"]:
            return self.j({"status": "error", "data": {"type": "auth", "message": "InvalidAgentKey"}}, 401)
        if p == "/v1/agents/rundata":
            tun = []
            for t in STATE["tunnels"]:
                if time.time() - t["created"] > 2:   # "asignando" durante 2 s
                    tun.append({"id": t["id"], "internal_id": 1, "name": t["name"], "display_address": "prueba-max.gl.joinmc.link", "port_type": "tcp", "port_count": 1,
                                "tunnel_type": "minecraft-java", "tunnel_type_display": "Minecraft Java", "agent_config": {"fields": t["fields"]}, "disabled_reason": None})
            pend = [{"id": t["id"], "name": t["name"], "tunnel_type": "minecraft-java", "tunnel_type_display": "Minecraft Java", "port_type": "tcp", "port_count": 1, "status_msg": "Asignando dirección…"} for t in STATE["tunnels"] if time.time() - t["created"] <= 2]
            return self.j({"status": "success", "data": {"agent_id": "11111111-2222-3333-4444-555555555555", "tunnels": tun, "pending": pend, "notices": [], "permissions": {"is_self_managed": True, "has_premium": False, "account_status": "verified"}}})
        if p == "/v1/tunnels/create":
            assert body["ports"] == {"type": "tunnel-type", "details": "minecraft-java"}, body
            assert body["origin"]["type"] == "agent" and body["origin"]["data"]["agent_id"]
            STATE["created"] += 1
            STATE["tunnels"].append({"id": "7c9e6679-7425-40de-944b-e07fc1f90ae7", "name": body["name"], "fields": body["origin"]["data"]["config"]["fields"], "created": time.time()})
            return self.j({"status": "success", "data": {"id": "7c9e6679-7425-40de-944b-e07fc1f90ae7"}})
        if p == "/v1/tunnels/config":
            STATE["config_calls"].append(body)
            for t in STATE["tunnels"]:
                if t["id"] == body["tunnel_id"]: t["fields"] = body["new_config"]["fields"]
            return self.j({"status": "success", "data": None})
        if p == "/__state": return self.j(STATE)
        return self.j({"status": "error", "data": {"type": "path-not-found", "message": {"path": p}}}, 404)
ThreadingHTTPServer(("127.0.0.1", 9911), H).serve_forever()
