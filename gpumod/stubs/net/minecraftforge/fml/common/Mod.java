package net.minecraftforge.fml.common;
import java.lang.annotation.*;
/** Solo para compilar: la anotación real viene con Forge. */
@Retention(RetentionPolicy.RUNTIME) @Target(ElementType.TYPE)
public @interface Mod { String value(); }
