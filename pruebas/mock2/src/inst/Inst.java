import java.nio.file.*;
import java.io.*;
public class Inst { public static void main(String[] a) throws Exception {
  if (a.length == 0 || !a[0].equals("--installServer")) { System.out.println("uso: --installServer"); System.exit(2); }
  String v = "21.1.77";
  try (InputStream in = Inst.class.getResourceAsStream("/version.txt")) {
    if (in != null) { ByteArrayOutputStream o = new ByteArrayOutputStream(); int c; while ((c = in.read()) >= 0) o.write(c); v = o.toString("UTF-8").trim(); }
  }
  Path lib = Paths.get("libraries/net/neoforged/neoforge/" + v); Files.createDirectories(lib);
  Files.write(lib.resolve("unix_args.txt"), ("-Dfakeneo=" + v + "\n-cp\n/home/claude/mock2/fakeserver.jar\nMain\n").getBytes());
  if (!Files.exists(Paths.get("user_jvm_args.txt")))
    Files.write(Paths.get("user_jvm_args.txt"), "# Xmx and Xms set the maximum and minimum RAM usage\n".getBytes());
  Files.write(Paths.get("run.sh"), ("#!/usr/bin/env sh\njava @user_jvm_args.txt @libraries/net/neoforged/neoforge/" + v + "/unix_args.txt \"$@\"\n").getBytes());
  Files.write(lib.resolve("win_args.txt"), ("-Dfakeneo=" + v + "\n-cp\nZ:/home/claude/mock2/fakeserver.jar\nMain\n").getBytes());
  Files.write(Paths.get("run.bat"), ("@echo off\r\nREM NeoForge\r\njava @user_jvm_args.txt @libraries/net/neoforged/neoforge/" + v + "/win_args.txt %*\r\npause\r\n").getBytes());
  for (int i = 0; i < 60; i++) System.out.println("Downloading library net.example:lib" + i);
  System.out.println("Installing NeoForge " + v);
  System.out.println("The server installed successfully");
}}
