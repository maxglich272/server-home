package gpudedicada;
/** Fabric y Quilt: se ejecuta al abrir el juego. */
public class FabricEntrada implements net.fabricmc.api.ClientModInitializer {
    @Override public void onInitializeClient() { GpuDedicada.iniciar("Fabric"); }
}
