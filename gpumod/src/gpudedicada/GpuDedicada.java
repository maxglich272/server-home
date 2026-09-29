package gpudedicada;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.InputStream;
import java.util.ArrayList;
import java.util.List;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * GPU Dedicada: en laptops con dos tarjetas gráficas (la integrada Intel/AMD y la dedicada NVIDIA/AMD/Intel Arc),
 * Windows suele abrir Minecraft con la integrada, que es mucho más lenta. Minecraft no puede cambiar de tarjeta
 * una vez abierto, así que este mod deja configurado en Windows («Configuración → Pantalla → Gráficos → Alto
 * rendimiento») el Java con el que corre Minecraft. Desde el próximo inicio del juego se usa la tarjeta dedicada.
 *
 * No toca nada del juego ni del mundo: no usa clases de Minecraft, por eso el mismo archivo sirve en Fabric,
 * Forge y NeoForge y en muchas versiones. En servidores y en otros sistemas no hace nada.
 */
public final class GpuDedicada {
    static final String PREFERENCIAS = "HKCU\\Software\\Microsoft\\DirectX\\UserGpuPreferences";
    static final String ADAPTADORES = "HKLM\\SYSTEM\\CurrentControlSet\\Control\\Class\\{4d36e968-e325-11ce-bfc1-08002be10318}";
    static final Pattern DEDICADA = Pattern.compile(
            "nvidia|geforce|quadro|\\brtx\\b|\\bgtx\\b|radeon\\s*(\\(tm\\)\\s*)?(rx|pro)\\b|firepro|arc\\s*(\\(tm\\)\\s*)?[ab]\\d",
            Pattern.CASE_INSENSITIVE);
    static final Pattern VIRTUAL = Pattern.compile(
            "microsoft basic|remote|virtual|parsec|meta |oculus|displaylink|indirect|iddcx|citrix|vmware|virtualbox|spacedesk|luminon",
            Pattern.CASE_INSENSITIVE);

    private GpuDedicada() {
    }

    /** Lo llaman Fabric, Forge o NeoForge al abrir el juego. No demora el inicio: trabaja en segundo plano. */
    public static void iniciar(String loader) {
        try {
            if (!System.getProperty("os.name", "").toLowerCase().startsWith("windows") || !esCliente()) {
                return;
            }
            Thread t = new Thread(() -> revisar(true), "GPU Dedicada");
            t.setDaemon(true);
            t.start();
        } catch (Throwable e) {
            log("no pude revisar la tarjeta gráfica: " + e);
        }
    }

    static boolean esCliente() {
        try {
            Class.forName("net.minecraft.client.main.Main", false, GpuDedicada.class.getClassLoader());
            return true;
        } catch (Throwable e) {
            return false;          // es un servidor: ahí no hay nada que dibujar
        }
    }

    /** Devuelve lo que hizo, en una frase (también queda en el registro del juego). */
    static String revisar(boolean avisar) {
        try {
            List<String> reales = new ArrayList<>();
            List<String> dedicadas = new ArrayList<>();
            for (String nombre : adaptadores()) {
                if (VIRTUAL.matcher(nombre).find() || reales.contains(nombre)) {
                    continue;
                }
                reales.add(nombre);
                if (DEDICADA.matcher(nombre).find()) {
                    dedicadas.add(nombre);
                }
            }
            if (dedicadas.isEmpty()) {
                return log("este PC no tiene tarjeta gráfica dedicada " + reales + ": no hay nada que cambiar.");
            }
            if (reales.size() < 2) {
                return log("este PC tiene una sola tarjeta gráfica (" + dedicadas.get(0) + "): Minecraft ya la usa.");
            }
            String tarjeta = dedicadas.get(0);
            List<String> cambiados = new ArrayList<>();
            List<String> respetados = new ArrayList<>();
            for (String exe : javasDeMinecraft()) {
                String actual = ejecutar("reg", "query", PREFERENCIAS, "/v", exe);
                if (actual.contains("GpuPreference=2")) {
                    continue;                                  // ya en «Alto rendimiento»
                }
                if (actual.contains("GpuPreference=1")) {
                    respetados.add(exe);                       // la persona eligió «Ahorro de energía»: no se toca
                    continue;
                }
                ejecutar("reg", "add", PREFERENCIAS, "/v", exe, "/t", "REG_SZ", "/d", "GpuPreference=2;", "/f");
                if (ejecutar("reg", "query", PREFERENCIAS, "/v", exe).contains("GpuPreference=2")) {
                    cambiados.add(exe);
                }
            }
            if (!respetados.isEmpty()) {
                log("en Windows elegiste «Ahorro de energía» para " + respetados + "; no lo cambio.");
            }
            if (cambiados.isEmpty()) {
                return log("Minecraft ya está configurado para usar " + tarjeta + ".");
            }
            String msg = "Desde el próximo inicio, Minecraft va a usar tu tarjeta gráfica " + tarjeta
                    + ". Cierra Minecraft y vuelve a abrirlo para notarlo.";
            if (avisar) {
                avisar(msg);
            }
            return log(msg + " (configurado en Windows para " + cambiados + ")");
        } catch (Throwable e) {
            return log("no pude revisar la tarjeta gráfica: " + e);
        }
    }

    /** El Java que está corriendo Minecraft (y su hermano javaw/java de la misma carpeta). */
    static List<String> javasDeMinecraft() {
        List<String> out = new ArrayList<>();
        File bin = new File(System.getProperty("java.home"), "bin");
        for (String n : new String[]{"javaw.exe", "java.exe"}) {
            File f = new File(bin, n);
            if (f.isFile()) {
                out.add(f.getAbsolutePath());
            }
        }
        return out;
    }

    /** Nombres de las tarjetas gráficas instaladas (según los controladores de Windows). */
    static List<String> adaptadores() throws Exception {
        List<String> out = new ArrayList<>();
        String prueba = System.getProperty("gpudedicada.prueba.adaptadores");     // solo para las pruebas
        if (prueba != null) {
            for (String n : prueba.split("\\|")) {
                if (!n.trim().isEmpty()) {
                    out.add(n.trim());
                }
            }
            return out;
        }
        Matcher m = Pattern.compile("DriverDesc\\s+REG_SZ\\s+(.+)").matcher(ejecutar("reg", "query", ADAPTADORES, "/s", "/v", "DriverDesc"));
        while (m.find()) {
            out.add(m.group(1).trim());
        }
        return out;
    }

    static String ejecutar(String... cmd) throws Exception {
        Process p = new ProcessBuilder(cmd).redirectErrorStream(true).start();
        p.getOutputStream().close();
        ByteArrayOutputStream buf = new ByteArrayOutputStream();
        try (InputStream in = p.getInputStream()) {
            byte[] b = new byte[4096];
            int n;
            while ((n = in.read(b)) > 0) {
                buf.write(b, 0, n);
            }
        }
        p.waitFor();
        return buf.toString("ISO-8859-1");
    }

    /** Un aviso de Windows que no interrumpe el juego (si no se puede mostrar, queda igual en el registro). */
    static void avisar(String msg) {
        try {
            String m = msg.replace("'", "''");
            new ProcessBuilder("powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command",
                    "Add-Type -AssemblyName PresentationFramework; [System.Windows.MessageBox]::Show('" + m
                            + "', 'GPU Dedicada', 'OK', 'Information') | Out-Null").start();
        } catch (Throwable ignored) {
        }
    }

    static String log(String msg) {
        System.out.println("[GPU Dedicada] " + msg);
        return msg;
    }

    /** Para probar sin Minecraft: java -cp gpu-dedicada.jar gpudedicada.GpuDedicada */
    public static void main(String[] args) {
        revisar(args.length > 0 && args[0].equals("--avisar"));
    }
}
