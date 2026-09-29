package net.neoforged.fml.common;
import java.lang.annotation.*;
/** Solo para compilar: la anotación real viene con NeoForge. */
@Retention(RetentionPolicy.RUNTIME) @Target(ElementType.TYPE)
public @interface Mod { String value(); }
