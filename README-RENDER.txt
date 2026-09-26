BLADEX .l — Render

1. Sube este proyecto a GitHub.
2. En Render crea un Web Service usando el repositorio.
3. Render puede detectar render.yaml automáticamente.
4. En Environment añade DISCORD_TOKEN con el token de tu bot.
5. Despliega.
6. En Discord usa:
   .l
   y adjunta un .lua, .luau o .txt.

Este wrapper solo registra el comando .l.
No se agregaron comandos .deobf, .detect, .help ni otros comandos Discord.

Nota:
- El bot necesita Message Content Intent activado en Discord Developer Portal.
- Render Free puede suspender servicios inactivos; un bot de Discord requiere que el servicio permanezca activo.
- El deobfuscador original incluye un runtime Luau. Si el ZIP no contiene un binario Linux compatible en Deobfuscator/deobf/bin,
  Render puede necesitar construir Luau antes de ejecutar ciertos análisis.


COMANDO .l
- Archivo: .l + adjunto .lua/.luau/.txt
- Enlace: .l https://ejemplo.com/script.lua
- La descarga tiene límite de tamaño y tiempo.
- Render compila tanto `luau` como `luau-ast`; Luraph v15 necesita `luau-ast`.
