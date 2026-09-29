import zipfile, json, os, hashlib, shutil
M = "/home/claude/mock2"
def neo_jar(path, modid, name, mc="[1.21.1,1.22)", extra="", deps=()):
    more = "".join(f'[[dependencies.{modid}]] # comentario\n    modId="{d}"\n    type="required"\n    versionRange="[1.0,)"\n'
                   f'    side="BOTH"\n' for d in deps)
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("META-INF/neoforge.mods.toml", f'''modLoader="javafml"
loaderVersion="[4,)"
license="MIT"
[[mods]]
modId="{modid}"
version="1.0"
displayName="{name}"
description=\'\'\'Un mod de prueba
con varias lineas modId="trampa"\'\'\'
{extra}
[[dependencies.{modid}]]
    modId="neoforge"
    type="required"
    versionRange="[21.1.0,)"
    ordering="NONE"
    side="BOTH"
[[dependencies.{modid}]]
    modId="minecraft"
    type="required"
    versionRange="{mc}"
    ordering="NONE"
    side="BOTH"
''' + more)
        z.writestr(f"com/example/{modid}/Main.class", b"\xca\xfe\xba\xbe")
def fabric_jar(path, modid, env="*", mc="~1.21.1"):
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("fabric.mod.json", json.dumps({"schemaVersion": 1, "id": modid, "name": modid.title(), "version": "1.0", "environment": env, "depends": {"fabricloader": ">=0.15", "minecraft": mc}}))
os.makedirs(f"{M}/jars", exist_ok=True)
neo_jar(f"{M}/jars/create-1.21.1-6.0.jar", "create", "Create")
neo_jar(f"{M}/jars/jei-1.21.1.jar", "jei", "Just Enough Items", mc="[1.21,1.21.2)")
neo_jar(f"{M}/jars/oculus-1.21.1.jar", "oculus", "Oculus")
neo_jar(f"{M}/jars/badclient.jar", "badclient", "Bad Client Mod")
neo_jar(f"{M}/jars/fancytips.jar", "fancytips", "Fancy Tips", extra='clientSideOnly=true')
# displayTest="IGNORE_SERVER_VERSION" quiere decir que el jugador no lo necesita: va en el servidor (como FTB Essentials)
neo_jar(f"{M}/jars/serverside.jar", "serverside", "Server Side Tools", extra='displayTest="IGNORE_SERVER_VERSION"')
neo_jar(f"{M}/jars/cflib.jar", "cflib", "CF Lib")                                    # CurseForge lo marca de cliente, pero...
neo_jar(f"{M}/jars/needscflib.jar", "needscflib", "Needs CF Lib", deps=("cflib",))   # ...este mod lo necesita
neo_jar(f"{M}/jars/irisaddon.jar", "irisaddon", "Iris Addon", deps=("oculus",))       # necesita un mod de shaders
neo_jar(f"{M}/jars/cfclient.jar", "cfclient", "CF Client Marked")
fabric_jar(f"{M}/jars/fabric-api.jar", "fabric-api")
fabric_jar(f"{M}/jars/sodium-fabric.jar", "sodium", env="client")
fabric_jar(f"{M}/jars/lithium.jar", "lithium")

# A) Server pack NeoForge (carpeta raíz única, variables.txt, sin instalar)
with zipfile.ZipFile(f"{M}/ServerFiles-1.0.zip", "w") as z:
    r = "Create Ultimate Server 1.0/"
    for j in ("create-1.21.1-6.0.jar", "jei-1.21.1.jar", "badclient.jar"):
        z.write(f"{M}/jars/{j}", r + "mods/" + j)
    z.writestr(r + "config/create-common.toml", "x=1\n")
    z.writestr(r + "variables.txt", "MINECRAFT_VERSION=1.21.1\nMODLOADER=NeoForge\nMODLOADER_VERSION=21.1.77\nJAVA_ARGS=\"-Xmx4G\"\n")
    z.writestr(r + "start.sh", "#!/bin/bash\n. ./variables.txt\n")
    z.writestr(r + "../evil.txt", "zip slip")   # debe ignorarse

# B) Instancia de CurseForge en un HOME falso
H = f"{M}/home"
shutil.rmtree(H, ignore_errors=True)
inst = f"{H}/Documents/curseforge/minecraft/Instances/taller"
for d in ("mods", "config", "defaultconfigs", "saves/Mundo1", "resourcepacks", "shaderpacks", "logs", "kubejs/server_scripts", "screenshots"):
    os.makedirs(f"{inst}/{d}", exist_ok=True)
for j in ("create-1.21.1-6.0.jar", "jei-1.21.1.jar", "oculus-1.21.1.jar", "fancytips.jar", "cfclient.jar", "serverside.jar",
          "cflib.jar", "needscflib.jar", "irisaddon.jar"):
    shutil.copy(f"{M}/jars/{j}", f"{inst}/mods/{j}")
open(f"{inst}/config/jei.toml", "w").write("a=1\n")
open(f"{inst}/kubejs/server_scripts/main.js", "w").write("// kubejs\n")
open(f"{inst}/saves/Mundo1/level.dat", "w").write("x")
open(f"{inst}/options.txt", "w").write("fov:1\n")
open(f"{inst}/logs/latest.log", "w").write("[main/INFO]: ModLauncher running: args [--launchTarget, forgeclient, --fml.neoForgeVersion, 21.1.99, --fml.mcVersion, 1.21.1]\n")
json.dump({"name": "Taller de Max", "gameVersion": "1.21.1",
           "baseModLoader": {"name": "neoforge-21.1.77", "minecraftVersion": "1.21.1"},
           "installedAddons": [
               {"addonID": 1, "name": "CF Client", "installedFile": {"fileName": "cfclient.jar", "fileNameOnDisk": "cfclient.jar", "gameVersion": ["1.21.1", "NeoForge", "Client"]}},
               {"addonID": 3, "name": "CF Lib", "installedFile": {"fileName": "cflib.jar", "fileNameOnDisk": "cflib.jar", "gameVersion": ["1.21.1", "NeoForge", "Client"]}},
               {"addonID": 2, "name": "Create", "installedFile": {"fileName": "create-1.21.1-6.0.jar", "gameVersion": ["1.21.1", "NeoForge", "Client", "Server"]}}]},
          open(f"{inst}/minecraftinstance.json", "w"))
# SKLauncher sin metadatos (solo mods fabric)
sk = f"{H}/.sklauncher/instances/fabric-pack"
os.makedirs(f"{sk}/mods", exist_ok=True)
for j in ("fabric-api.jar", "sodium-fabric.jar", "lithium.jar"):
    shutil.copy(f"{M}/jars/{j}", f"{sk}/mods/{j}")

# C) .mrpack de Fabric con descargas desde el mock
os.makedirs(f"{M}/www/modrinth", exist_ok=True)
files = []
for j, env in (("fabric-api.jar", "required"), ("lithium.jar", "required"), ("sodium-fabric.jar", "unsupported")):
    shutil.copy(f"{M}/jars/{j}", f"{M}/www/modrinth/{j}")
    data = open(f"{M}/jars/{j}", "rb").read()
    files.append({"path": f"mods/{j}", "hashes": {"sha1": hashlib.sha1(data).hexdigest(), "sha512": hashlib.sha512(data).hexdigest()},
                  "env": {"client": "required", "server": env}, "downloads": [f"http://127.0.0.1:9911/modrinth/{j}"], "fileSize": len(data)})
with zipfile.ZipFile(f"{M}/Fabulous.mrpack", "w") as z:
    z.writestr("modrinth.index.json", json.dumps({"formatVersion": 1, "game": "minecraft", "versionId": "1.0", "name": "Fabulous Pack",
                                                  "files": files, "dependencies": {"minecraft": "1.21.1", "fabric-loader": "0.16.14"}}))
    z.writestr("overrides/config/lithium.properties", "x=1\n")
    z.writestr("server-overrides/server.properties", "motd=Desde server-overrides\nmax-players=7\n")
    z.writestr("client-overrides/options.txt", "no debe copiarse\n")

# D) Zip de CurseForge para el launcher (sin mods)
with zipfile.ZipFile(f"{M}/ClientPack.zip", "w") as z:
    z.writestr("manifest.json", json.dumps({"manifestType": "minecraftModpack", "manifestVersion": 1, "name": "Client Pack",
        "minecraft": {"version": "1.21.1", "modLoaders": [{"id": "neoforge-21.1.77", "primary": True}]},
        "files": [{"projectID": i, "fileID": i * 10, "required": True} for i in range(1, 30)], "overrides": "overrides"}))
    z.writestr("overrides/config/a.toml", "a=1\n")
print("fixtures ok")

# La misma instancia de CurseForge para las pruebas en Windows (Wine), en su propia carpeta de usuario
wi = f"{M}/winhome/curseforge/minecraft/Instances/taller"
if os.path.isdir(wi):
    shutil.rmtree(f"{wi}/mods", ignore_errors=True)
    shutil.copytree(f"{inst}/mods", f"{wi}/mods")
    shutil.copy(f"{inst}/minecraftinstance.json", f"{wi}/minecraftinstance.json")
print("instancia de Windows al día")
