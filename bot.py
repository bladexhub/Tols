import asyncio
import ipaddress
import os
import pathlib
import re
import socket
import tempfile
import shutil
from urllib.parse import urlparse

import aiohttp
import discord
from discord.ext import commands

TOKEN = os.getenv("DISCORD_TOKEN")
PREFIX = "."
MAX_FILE_MB = int(os.getenv("MAX_FILE_MB", "8"))
MAX_URL_MB = int(os.getenv("MAX_URL_MB", "8"))
JOB_TIMEOUT = int(os.getenv("JOB_TIMEOUT", "600"))
MAX_CONCURRENT = int(os.getenv("MAX_CONCURRENT", "2"))
URL_TIMEOUT = int(os.getenv("URL_TIMEOUT", "30"))

if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN is required")

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix=PREFIX, intents=intents, help_command=None)
sem = asyncio.Semaphore(MAX_CONCURRENT)
ALLOWED_EXTENSIONS = {".lua", ".luau", ".txt", ".l"}


def safe_name(name: str) -> str:
    name = pathlib.Path(name).name
    return re.sub(r"[^A-Za-z0-9._-]", "_", name) or "input.lua"


def is_public_host(host: str) -> bool:
    try:
        infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
        for info in infos:
            ip = ipaddress.ip_address(info[4][0])
            if not ip.is_global:
                return False
        return True
    except (ValueError, OSError):
        return False


async def download_url(url: str, dst: pathlib.Path):
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("El enlace debe usar http:// o https://")
    if not await asyncio.to_thread(is_public_host, parsed.hostname):
        raise ValueError("El enlace apunta a un destino no permitido.")

    timeout = aiohttp.ClientTimeout(total=URL_TIMEOUT)
    headers = {"User-Agent": "BLADEX-L/1.0"}
    async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
        async with session.get(url, allow_redirects=True, max_redirects=5) as resp:
            if resp.status != 200:
                raise RuntimeError(f"No se pudo obtener el enlace (HTTP {resp.status}).")
            length = resp.content_length
            if length and length > MAX_URL_MB * 1024 * 1024:
                raise ValueError(f"El contenido supera el límite de {MAX_URL_MB} MB.")
            total = 0
            with dst.open("wb") as f:
                async for chunk in resp.content.iter_chunked(64 * 1024):
                    total += len(chunk)
                    if total > MAX_URL_MB * 1024 * 1024:
                        raise ValueError(f"El contenido supera el límite de {MAX_URL_MB} MB.")
                    f.write(chunk)
    if total == 0:
        raise ValueError("El enlace no devolvió contenido.")


def runtime_paths():
    root = pathlib.Path(__file__).resolve().parent
    bindir = root / "Deobfuscator" / "deobf" / "bin"
    return bindir / "luau", bindir / "luau-ast"


def ensure_luau_runtimes():
    luau, luau_ast = runtime_paths()
    if luau.is_file() and luau_ast.is_file():
        return
    builder = pathlib.Path(__file__).resolve().parent / "Deobfuscator" / "deobf" / "build_luau.py"
    if not builder.is_file():
        raise RuntimeError("No se encontró build_luau.py para construir los runtimes de Luau.")
    print("[*] Faltan los runtimes de Luau; iniciando compilación automática...", flush=True)
    import subprocess
    try:
        subprocess.run(
            ["python3", str(builder), "--portable"],
            cwd=str(builder.parent.parent),
            check=True,
        )
    except FileNotFoundError as e:
        raise RuntimeError("No se pudo iniciar la compilación de Luau: falta git, cmake o Python.") from e
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"La compilación de Luau falló (código {e.returncode}). Revisa el Build Command de Render.") from e
    if not luau.is_file() or not luau_ast.is_file():
        raise RuntimeError("La compilación terminó sin generar luau y luau-ast.")
    try:
        luau.chmod(luau.stat().st_mode | 0o111)
        luau_ast.chmod(luau_ast.stat().st_mode | 0o111)
    except OSError:
        pass
    print("[+] Runtimes listos: luau + luau-ast", flush=True)


async def run_deobfuscator(src: pathlib.Path, dst: pathlib.Path):
    ensure_luau_runtimes()
    script = pathlib.Path(__file__).parent / "Deobfuscator" / "deobf" / "deob.py"
    cmd = [
        "python3", str(script), str(src), "-o", str(dst),
        "--timeout", str(JOB_TIMEOUT), "--budget", str(min(JOB_TIMEOUT, 120)), "--no-pypy",
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd, cwd=str(script.parent.parent),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=JOB_TIMEOUT + 30)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise TimeoutError("El análisis superó el tiempo máximo permitido.")
    if proc.returncode != 0:
        err = stderr.decode("utf-8", "replace").strip()
        if "FileNotFoundError" in err and "luau-ast" in err:
            raise RuntimeError("Falta el runtime luau-ast. El despliegue debe reconstruirlo antes de iniciar el bot.")
        raise RuntimeError(err[-1800:] if err else "El motor de deofuscación terminó con error.")


@bot.event
async def on_ready():
    print(f"Conectado como {bot.user} | comando único: .l")


@bot.command(name="l")
async def l_command(ctx: commands.Context, *, target: str = ""):
    if not ctx.message.attachments and not target:
        await ctx.reply("Usa `.l` con un archivo adjunto o `.l https://enlace-del-script`")
        return

    async with sem:
        status = await ctx.reply("⏳ Preparando análisis…")
        tempdir = pathlib.Path(tempfile.mkdtemp(prefix="bladex_l_"))
        try:
            if target:
                src = tempdir / "fetched.lua"
                await status.edit(content="🌐 Extrayendo script desde el enlace…")
                await download_url(target.strip(), src)
                source_name = "fetched.lua"
            else:
                attachment = ctx.message.attachments[0]
                ext = pathlib.Path(attachment.filename).suffix.lower()
                if ext not in ALLOWED_EXTENSIONS:
                    await status.edit(content="❌ Formato no compatible. Usa `.lua`, `.luau` o `.txt`.")
                    return
                if attachment.size > MAX_FILE_MB * 1024 * 1024:
                    await status.edit(content=f"❌ El archivo supera el límite de {MAX_FILE_MB} MB.")
                    return
                src = tempdir / safe_name(attachment.filename)
                source_name = attachment.filename
                await status.edit(content="⏳ Analizando el archivo…")
                await attachment.save(src)

            output = tempdir / "deobfuscated.luau"
            await run_deobfuscator(src, output)
            if not output.exists() or output.stat().st_size == 0:
                raise RuntimeError("El motor no generó un resultado.")

            await status.edit(content="✅ Análisis terminado.")
            await ctx.send(content=f"Resultado de `{source_name}`:", file=discord.File(str(output), filename=output.name))
        except TimeoutError as e:
            await status.edit(content=f"⏱️ {e}")
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            await status.edit(content=f"🌐 Error de red: {str(e)[:1700]}")
        except Exception as e:
            await status.edit(content=f"❌ Error: {str(e)[:1800]}")
        finally:
            shutil.rmtree(tempdir, ignore_errors=True)


from aiohttp import web

async def health(request):
    return web.Response(text="BLADEX .l bot OK")


async def start_web():
    app = web.Application()
    app.router.add_get("/", health)
    app.router.add_get("/health", health)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.getenv("PORT", "10000"))
    await web.TCPSite(runner, "0.0.0.0", port).start()
    return runner


async def main():
    # El bot puede arrancar incluso si el Build Command no dejó los binarios.
    # Esto también hace que funcione en hosts donde el directorio es /home/container.
    ensure_luau_runtimes()
    runner = await start_web()
    try:
        await bot.start(TOKEN)
    finally:
        await runner.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
