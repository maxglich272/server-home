import java.io.*; import java.nio.file.*; import java.util.*;
public class Main {
  static boolean has(String name) { return Files.exists(Paths.get("mods/" + name)); }
  static boolean hasPrefix(String prefix) {
    File md = new File("mods"); String[] n = md.isDirectory() ? md.list() : new String[0];
    for (String x : n) if (x.startsWith(prefix) && x.endsWith(".jar")) return true;
    return false;
  }
  static String read(String p) { try { return new String(Files.readAllBytes(Paths.get(p)), "UTF-8").trim(); } catch (Exception e) { return null; } }
  static String prop(String key) {
    String t = read("server.properties"); if (t == null) return null;
    for (String l : t.split("\n")) if (l.startsWith(key + "=")) return l.substring(key.length() + 1).trim();
    return null;
  }
  static void die(String... lines) { for (String l : lines) System.out.println(l); System.exit(1); }
  // lo que el mock le metió al .jar (la versión de Fabric Loader que pidió la app)
  static String res(String name) {
    try (InputStream in = Main.class.getResourceAsStream(name)) {
      if (in == null) return null;
      ByteArrayOutputStream b = new ByteArrayOutputStream(); byte[] buf = new byte[256]; int n;
      while ((n = in.read(buf)) > 0) b.write(buf, 0, n);
      return b.toString("UTF-8").trim();
    } catch (Exception e) { return null; }
  }
  static int cmpVer(String a, String b) {
    String[] x = a.split("[^0-9]+"), y = b.split("[^0-9]+");
    for (int i = 0; i < Math.max(x.length, y.length); i++) {
      int p = i < x.length && !x[i].isEmpty() ? Integer.parseInt(x[i]) : 0, q = i < y.length && !y[i].isEmpty() ? Integer.parseInt(y[i]) : 0;
      if (p != q) return p < q ? -1 : 1;
    }
    return 0;
  }
  // Como NeoForge de verdad: si falla la carga de mods escribe un informe de error y Java termina con código 0
  static void neoFail(String... issues) throws Exception {
    StringBuilder rep = new StringBuilder("---- Minecraft Crash Report ----\nDescription: Mod loading failures have occurred\n\n");
    System.out.println("[main/ERROR] [net.neoforged.fml.loading.ModSorter/LOADING]: Missing or unsupported mandatory dependencies:");
    for (int i = 0; i + 1 < issues.length; i += 2)
      System.out.println("\tMod ID: '" + issues[i + 1] + "', Requested by: '" + issues[i] + "', Expected range: '[1.0,)', Actual version: '[MISSING]'");
    for (int i = 0; i + 1 < issues.length; i += 2) {
      System.out.println("[main/FATAL] [net.neoforged.fml.ModLoader/CORE]: Error during pre-loading phase: Mod " + issues[i] + " requires " + issues[i + 1] + " 1.0 or above");
      System.out.println("Currently, " + issues[i + 1] + " is not installed");
      System.out.println("");
      rep.append("-- Mod loading issue for: ").append(issues[i]).append(" --\nDetails:\n\tFailure message: Mod ").append(issues[i])
         .append(" requires ").append(issues[i + 1]).append(" 1.0 or above\n\t\tCurrently, ").append(issues[i + 1]).append(" is not installed\n\n");
    }
    Files.createDirectories(Paths.get("crash-reports"));
    String name = "crash-reports/crash-" + System.currentTimeMillis() + "-fml.txt";
    Files.write(Paths.get(name), rep.toString().getBytes("UTF-8"));
    System.out.println("[main/FATAL] [net.neoforged.neoforge.server.loading.ServerModLoader/]: Crash report saved to .\\" + name.replace('/', '\\'));
    System.out.println("[main/ERROR] [net.minecraft.server.Main/FATAL]: Failed to start the minecraft server");
    System.out.println("net.neoforged.fml.ModLoadingException: Loading errors encountered:");
    if (Files.exists(Paths.get("hang-on-fail"))) {           // algún mod deja un hilo vivo: Java no se cierra solo
      Thread t = new Thread(() -> { try { Thread.sleep(Long.MAX_VALUE); } catch (Exception e) {} });
      t.setDaemon(false); t.start();
      return;
    }
    System.exit(0);
  }
  public static void main(String[] a) throws Exception {
    System.out.println("[main/INFO]: ModLauncher running: args [--launchTarget, forgeserver, --fml.neoForgeVersion, 21.1.77, --fml.mcVersion, 1.21.1]");
    System.out.println("[main/INFO]: Xmx=" + Runtime.getRuntime().maxMemory()/1048576 + "MB args=" + String.join(" ", a));
    for (int i = 0; i < 40; i++) System.out.println("[main/INFO]: Loading mod file " + i);
    // encendido lento (para ver la barra de carga): /tmp/fakeserver-slow = "<líneas> <ms por línea>"
    String sl = read("/tmp/fakeserver-slow");
    int stageMs = (sl != null && !sl.isEmpty()) ? 150 : 40;
    if (sl != null && !sl.isEmpty()) {
      String[] q = sl.split("\\s+"); int n = Integer.parseInt(q[0]), ms = Integer.parseInt(q[1]);
      for (int i = 0; i < n; i++) { System.out.println("[main/INFO]: Scanning mod candidate " + i); Thread.sleep(ms); }
    }
    // Java no pudo reservar la memoria pedida
    if (Files.exists(Paths.get("heap-fail")) && Runtime.getRuntime().maxMemory() / 1048576 > 3100)
      die("Error occurred during initialization of VM", "Could not reserve enough space for 4194304KB object heap");
    // un .jar dañado (descarga cortada)
    File mdir = new File("mods");
    String[] all = mdir.isDirectory() ? mdir.list() : new String[0];
    Arrays.sort(all);
    for (String n : all) if (n.endsWith(".jar")) {
      try { new java.util.zip.ZipFile(new File(mdir, n)).close(); }
      catch (Exception e) { die("[main/ERROR] [net.neoforged.fml.loading.moddiscovery.ModDiscoverer/SCAN]: Failed to load mod file mods/" + n,
                              "java.util.zip.ZipException: zip END header not found"); }
    }
    // Fabric: la versión del loader que pidió la app
    String fl = res("/loader.txt"), fmc = res("/mc.txt");
    if (fl != null) System.out.println("[main/INFO]: Loading Minecraft " + fmc + " with Fabric Loader " + fl);
    // un mod antiguo que usa la librería de mapeos que Fabric Loader 0.15 dejó de traer (como Not Enough Crashes 4.1)
    if (fl != null && has("oldcrash.jar") && cmpVer(fl, "0.15") >= 0)
      die("[main/ERROR]: Minecraft has crashed!",
          "net.fabricmc.loader.impl.FormattedException: java.lang.NoClassDefFoundError: net/fabricmc/mapping/reader/v2/TinyVisitor",
          "\tat net.fabricmc.loader.impl.FormattedException.ofLocalized(FormattedException.java:63) ~[fabric-loader-" + fl + ".jar:?]",
          "\tat net.fabricmc.loader.impl.launch.knot.Knot.launch(Knot.java:72) [fabric-loader-" + fl + ".jar:?]",
          "Caused by: java.lang.NoClassDefFoundError: net/fabricmc/mapping/reader/v2/TinyVisitor",
          "\tat net.minecraft.server.Main.handler$dmb000$oldcrash$createPlatformInstance(Main.java:4517) ~[server-intermediary.jar:?]",
          "\tat net.minecraft.server.Main.main(Main.java) ~[server-intermediary.jar:?]",
          "Caused by: java.lang.ClassNotFoundException: net.fabricmc.mapping.reader.v2.TinyVisitor");
    // un mod (metido dentro de otro) pide un Fabric Loader más nuevo, sin decirlo en el fabric.mod.json de afuera
    if (fl != null && has("needsnewfabric.jar") && cmpVer(fl, "0.14.21") < 0)
      die("[main/ERROR]: Incompatible mods found!",
          "net.fabricmc.loader.impl.FormattedException: Some of your mods are incompatible with the game or each other!",
          "A potential solution has been determined, this may resolve your problem:",
          "\t - Replace mod 'Fabric Loader' (fabricloader) " + fl + " with version 0.14.21 or later.",
          "More details:",
          "\t - Mod 'Needs New Fabric' (needsnewfabric) 1.0 requires version 0.14.21 or later of fabricloader, but only the wrong version is present: " + fl + "!");
    // NeoForge: avisos de un mod que prueba clases del cliente pero no falla (como Majrusz's Difficulty)
    if (has("noisy.jar"))
      System.out.println("[modloading-worker-0/ERROR] [net.neoforged.fml.common.asm.RuntimeDistCleaner/DISTXFORM]: Attempted to load class com/example/noisy/NoisyClient for invalid dist DEDICATED_SERVER");
    // NeoForge: varios mods del jugador fallan a la vez (como WeatherRefind y guy's Armor HUD en «kyalita world»)
    java.util.List<String[]> cli = new java.util.ArrayList<>();
    if (has("hudmod.jar")) cli.add(new String[]{"hudmod", "Hud Mod", "hudmod.jar", "net/minecraft/client/gui/screens/Screen"});
    if (has("weatherfx.jar")) cli.add(new String[]{"weatherfx", "Weather FX", "weatherfx.jar", "net/minecraft/client/particle/Particle"});
    if (!cli.isEmpty()) {
      StringBuilder rep = new StringBuilder("---- Minecraft Crash Report ----\n// Why did you do that?\n\nDescription: Mod loading failures have occurred; consult the issue messages for more details\n\n"
          + "A detailed walkthrough of the error, its code path and all known details is as follows:\n\n");
      for (String[] c : cli) {
        String err = "java.lang.RuntimeException: Attempted to load class " + c[3] + " for invalid dist DEDICATED_SERVER";
        System.out.println("[modloading-worker-0/ERROR] [net.neoforged.fml.javafmlmod.FMLModContainer/LOADING]: Failed to create mod instance. ModID: " + c[0] + ", class com.example." + c[0] + ".Main");
        System.out.println(err);
        System.out.println("\tat TRANSFORMER/" + c[0] + "@1.0/com.example." + c[0] + ".Main.<init>(Main.java:23) ~[?:?]");
        rep.append("-- Mod loading issue for: ").append(c[0]).append(" --\nDetails:\n\tCaused by 0: ").append(err)
           .append("\n\t\tat TRANSFORMER/").append(c[0]).append("@1.0/com.example.").append(c[0]).append(".Main.<init>(Main.java:23)\n\n")
           .append("\tMod file: /C:/Users/max/Documents/servidor home/servidores/x/mods/").append(c[2]).append("\n")
           .append("\tFailure message: ").append(c[1]).append(" (").append(c[0]).append(") has failed to load correctly\n\t\t").append(err)
           .append("\n\tMod version: 1.0\n\tException message: ").append(err)
           .append("\nStacktrace:\n\tat MC-BOOTSTRAP/fml_loader@4.0.44/net.neoforged.fml.common.asm.RuntimeDistCleaner.processClassWithFlags(RuntimeDistCleaner.java:60)\n\n\n");
      }
      Files.createDirectories(Paths.get("crash-reports"));
      String name = "crash-reports/crash-" + System.currentTimeMillis() + "-fml.txt";
      Files.write(Paths.get(name), rep.toString().getBytes("UTF-8"));
      System.out.println("[main/FATAL] [net.neoforged.neoforge.server.loading.ServerModLoader/]: Crash report saved to .\\" + name.replace('/', '\\'));
      System.out.println("[main/ERROR] [net.minecraft.server.Main/FATAL]: Failed to start the minecraft server");
      System.out.println("net.neoforged.fml.ModLoadingException: Loading errors encountered:");
      for (String[] c : cli) {
        System.out.println("\t- " + c[1] + " (" + c[0] + ") has failed to load correctly");
        System.out.println("\t  java.lang.RuntimeException: Attempted to load class " + c[3] + " for invalid dist DEDICATED_SERVER");
      }
      System.out.println("");
      System.exit(0);
    }
    // NeoForge 1.21: mods desactivados que otros necesitan (y un mod que necesita un mod de shaders)
    if (has("needsjei.jar") && !hasPrefix("jeidep")) { neoFail("needsjei", "jeidep"); return; }
    if (hasPrefix("jeidep") && !hasPrefix("jeiconfig")) { neoFail("jeidep", "jeiconfig"); return; }
    if (has("shaderaddon.jar") && !hasPrefix("iris")) { neoFail("shaderaddon", "iris"); return; }
    if (has("choque.jar") && hasPrefix("oculus"))
      { System.out.println("[main/FATAL] [net.neoforged.fml.ModLoader/CORE]: Error during pre-loading phase: Mod choque is incompatible with oculus any");
        System.out.println("Currently, oculus is 1.0"); System.out.println("[main/ERROR] [net.minecraft.server.Main/FATAL]: Failed to start the minecraft server"); System.exit(0); }
    if (Files.exists(Paths.get("mods/badclient.jar"))) {
      System.out.println("[main/ERROR] [net.neoforged.fml.ModLoader/]: Bad Client Mod (badclient) has failed to load correctly");
      System.out.println("java.lang.RuntimeException: Attempted to load class net/minecraft/client/player/LocalPlayer for invalid dist DEDICATED_SERVER");
      System.out.println("\tat TRANSFORMER/badclient@1.0/com.example.bad.Bad.<init>(Bad.java:10)");
      System.exit(1);
    }
    // Fabric: mod del jugador declarado para ambos lados que usa clases del cliente (como enchant-outline)
    File md = new File("mods");
    String[] names = md.isDirectory() ? md.list() : new String[0];
    Arrays.sort(names);
    for (String n : names) {
      if (n.startsWith("clientmod") && n.endsWith(".jar")) {
        String id = n.substring(0, n.length() - 4);
        die("[main/ERROR]: Failed to start the minecraft server",
            "java.lang.RuntimeException: Could not execute entrypoint stage 'main' due to errors, provided by '" + id + "' at 'com.example." + id + ".Main'!",
            "Caused by: java.lang.NoClassDefFoundError: net/minecraft/class_3879");
      }
    }
    // Java: un mod compilado para una versión más nueva
    String nj = read("needs-java");
    if (nj != null) {
      String fj = System.getProperty("fakejava");
      int cur = fj != null ? Integer.parseInt(fj) : Integer.parseInt(System.getProperty("java.specification.version").replace("1.", ""));
      int need = Integer.parseInt(nj);
      if (cur < need) die("Exception in thread \"main\" java.lang.UnsupportedClassVersionError: com/example/Mod has been compiled by a more recent version of the Java Runtime (class file version " + (need + 44) + ".0), this version of the Java Runtime only recognizes class file versions up to " + (cur + 44) + ".0");
    }
    // memoria
    if (Files.exists(Paths.get("oom.txt")) && Runtime.getRuntime().maxMemory() / 1048576 < 3500)
      die("[Server thread/ERROR]: Encountered an unexpected exception", "java.lang.OutOfMemoryError: Java heap space");
    // puerto ocupado
    String busy = read("port-busy");
    if (busy != null && busy.equals(prop("server-port")))
      die("[Server thread/WARN]: **** FAILED TO BIND TO PORT!", "[Server thread/WARN]: The exception was: java.net.BindException: Address already in use", "[Server thread/WARN]: Perhaps a server is already running on that port?");
    // Fabric: dependencias
    if (has("needslib.jar") && !hasPrefix("libdep-2")) {
      if (has("libdep-1.0.jar")) die("[main/ERROR]: Incompatible mods found!",
          "net.fabricmc.loader.impl.FormattedException: Some of your mods are incompatible with the game or each other!",
          "A potential solution has been determined, this may resolve your problem:",
          "\t - Replace mod 'Lib Dep' (libdep) 1.0 with version 2.0 or later.",
          "More details:",
          "\t - Mod 'Needs Lib' (needslib) 1.0 requires version 2.0 or later of libdep, but only the wrong version is present: 1.0!");
      die("[main/ERROR]: Incompatible mods found!",
          "net.fabricmc.loader.impl.FormattedException: Some of your mods are incompatible with the game or each other!",
          "A potential solution has been determined, this may resolve your problem:",
          "\t - Install libdep, any version.",
          "More details:",
          "\t - Mod 'Needs Lib' (needslib) 1.0 requires any version of libdep, which is missing!");
    }
    if (has("ghost.jar")) die("[main/ERROR]: Incompatible mods found!",
          "A potential solution has been determined, this may resolve your problem:",
          "\t - Install ghostlib, any version.",
          "More details:",
          "\t - Mod 'Ghost' (ghost) 1.0 requires any version of ghostlib, which is missing!");
    // Forge/NeoForge: dependencias
    if (has("needsgecko.jar") && !hasPrefix("geckolib")) die("[main/ERROR] [net.neoforged.fml.loading.moddiscovery.ModDiscoverer/SCAN]: Missing or unsupported mandatory dependencies:",
          "\tMod ID: 'geckolib', Requested by: 'needsgecko', Expected range: '[4.4.4,)', Actual version: '[MISSING]'");
    if (has("needsbalm.jar") && !hasPrefix("balm")) die("[main/ERROR] [net.neoforged.fml.loading.ModSorter/]: Mod Needs Balm requires balm 21.0.0 or above",
          "Currently, balm is not installed");
    // NeoForge: un mod pide una versión más nueva del loader
    String neo = System.getProperty("fakeneo");
    if (has("needsneo.jar") && "21.1.66".equals(neo)) die("[main/ERROR] [net.neoforged.fml.loading.moddiscovery.ModDiscoverer/SCAN]: Missing or unsupported mandatory dependencies:",
          "\tMod ID: 'neoforge', Requested by: 'needsneo', Expected range: '[21.1.77,)', Actual version: '21.1.66'");
    // configuración dañada
    String roto = read("config/roto.toml");
    if (roto != null && roto.startsWith("ROTO")) die("[main/ERROR] [net.neoforged.fml.config.ConfigTracker/CONFIG]: Failed loading config file roto.toml of type COMMON for modid roto",
          "com.electronwill.nightconfig.core.io.ParsingException: Not enough data available");
    // mod con contenido que falla
    if (has("buggy-1.0.jar")) die("[main/ERROR] [net.neoforged.fml.ModLoader/]: Buggy Mod (buggy) has failed to load correctly",
          "java.lang.NullPointerException: Cannot invoke \"Object.toString()\" because \"value\" is null",
          "\tat TRANSFORMER/buggy@1.0/com.example.buggy.Buggy.<init>(Buggy.java:12)");
    // un mod cualquiera que falla al cargar y no tiene versión nueva: broken-<id>.jar
    for (String n : names) if (n.startsWith("broken-") && n.endsWith(".jar")) {
      String id = n.substring(7, n.length() - 4); if (id.indexOf('-') > 0) id = id.substring(0, id.indexOf('-'));
      die("[main/ERROR] [net.neoforged.fml.ModLoader/]: Broken " + id + " (" + id + ") has failed to load correctly",
          "java.lang.NullPointerException: boom", "\tat TRANSFORMER/" + id + "@1.0/com.example." + id + ".Main.<init>(Main.java:5)");
    }
    // mods repetidos
    if (has("dupe-1.0.jar") && has("dupe-2.0.jar")) die("[main/ERROR]: Found duplicate mods:", "\tMod ID: 'dupe' from mod files: dupe-1.0.jar, dupe-2.0.jar");
    System.out.println("[Server thread/INFO]: Starting minecraft server version 1.21.1"); Thread.sleep(stageMs);
    System.out.println("[Server thread/INFO]: Loading properties"); Thread.sleep(stageMs);
    System.out.println("[Server thread/INFO]: Preparing level \"world\""); Thread.sleep(stageMs);
    Files.createDirectories(Paths.get("world/region")); Files.write(Paths.get("world/level.dat"), "x".getBytes());
    for (int p = 0; p <= 100; p += 25) { System.out.println("[Server thread/INFO]: Preparing spawn area: " + p + "%"); Thread.sleep(stageMs); }
    Thread.sleep(200);
    System.out.println("[Server thread/INFO]: Done (2.345s)! For help, type \"help\"");
    // se traba después de encender (vigilante)
    if (Files.exists(Paths.get("watchdog")) && !"-1".equals(prop("max-tick-time"))) {
      Thread.sleep(800);
      die("[Server Watchdog/FATAL]: A single server tick took 60.00 seconds (should be max 0.05)", "[Server Watchdog/FATAL]: Considering it to be crashed, server will forcibly shutdown.");
    }
    // se cae una vez sin causa conocida
    if (Files.exists(Paths.get("crash-once"))) {
      Thread.sleep(800); Files.delete(Paths.get("crash-once"));
      die("[Server thread/ERROR]: Encountered an unexpected exception", "java.lang.IllegalStateException: something odd happened");
    }
    BufferedReader r = new BufferedReader(new InputStreamReader(System.in)); String l;
    while ((l = r.readLine()) != null) {
      if (l.equals("stop")) { System.out.println("[Server thread/INFO]: Stopping the server"); System.exit(0); }
      if (l.startsWith("say ")) System.out.println("[Server thread/INFO]: [Server] " + l.substring(4));
      if (l.startsWith("whitelist add ")) System.out.println("[Server thread/INFO]: Added " + l.substring(14) + " to the whitelist");
      if (l.equals("join")) System.out.println("[Server thread/INFO]: Steve joined the game");
      String[] w = l.trim().split(" ", 3);
      if (w[0].equals("join") && w.length > 1) { listPut("usercache.json", w[1], ""); System.out.println("[Server thread/INFO]: " + w[1] + " joined the game"); }
      if (w[0].equals("leave") && w.length > 1) System.out.println("[Server thread/INFO]: " + w[1] + " left the game");
      if (w[0].equals("kick") && w.length > 1) { System.out.println("[Server thread/INFO]: Kicked " + w[1]); System.out.println("[Server thread/INFO]: " + w[1] + " left the game"); }
      if (w[0].equals("op") && w.length > 1) { listPut("ops.json", w[1], ",\"level\":4,\"bypassesPlayerLimit\":false"); System.out.println("[Server thread/INFO]: Made " + w[1] + " a server operator"); }
      if (w[0].equals("deop") && w.length > 1) { listDel("ops.json", w[1]); System.out.println("[Server thread/INFO]: Made " + w[1] + " no longer a server operator"); }
      if (w[0].equals("ban") && w.length > 1) { listPut("banned-players.json", w[1], ",\"reason\":\"" + (w.length > 2 ? w[2] : "Banned by an operator.") + "\""); System.out.println("[Server thread/INFO]: Banned " + w[1]); }
      if (w[0].equals("pardon") && w.length > 1) { listDel("banned-players.json", w[1]); System.out.println("[Server thread/INFO]: Unbanned " + w[1]); }
      if (w[0].equals("whitelist") && w.length > 2 && w[1].equals("add")) listPut("whitelist.json", w[2], "");
      if (w[0].equals("whitelist") && w.length > 2 && w[1].equals("remove")) { listDel("whitelist.json", w[2]); System.out.println("[Server thread/INFO]: Removed " + w[2] + " from the whitelist"); }
    }
    Runtime.getRuntime().addShutdownHook(new Thread(() -> { try { Files.write(Paths.get("apagado-por-senal.txt"), "ok".getBytes()); } catch (Exception e) {} }));
    Thread.sleep(Long.MAX_VALUE);
  }

  static java.util.List<String> listRead(String f) {
    java.util.List<String> out = new java.util.ArrayList<>();
    try { String s = new String(Files.readAllBytes(Paths.get(f)), "UTF-8").trim();
      java.util.regex.Matcher m = java.util.regex.Pattern.compile("\\{[^{}]*\\}").matcher(s); while (m.find()) out.add(m.group()); } catch (Exception e) {}
    return out;
  }
  static void listWrite(String f, java.util.List<String> items) {
    try { Files.write(Paths.get(f), ("[" + String.join(",", items) + "]").getBytes("UTF-8")); } catch (Exception e) {}
  }
  static void listDel(String f, String name) {
    java.util.List<String> it = listRead(f); it.removeIf(x -> x.toLowerCase().contains("\"name\":\"" + name.toLowerCase() + "\""));
    listWrite(f, it);
  }
  static void listPut(String f, String name, String extra) {
    listDel(f, name); java.util.List<String> it = listRead(f);
    String uuid = java.util.UUID.nameUUIDFromBytes(("OfflinePlayer:" + name).getBytes()).toString();
    it.add("{\"uuid\":\"" + uuid + "\",\"name\":\"" + name + "\"" + extra + "}"); listWrite(f, it);
  }
}
