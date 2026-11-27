"""Núcleo del CeroTouch Launcher (solo librería estándar de Python).

Hace lo mismo que cualquier launcher:
  1. Lee el manifiesto de versiones de Mojang (con caché en memoria)
  2. Descarga client.jar, librerías, assets (verificando hashes) y, si hace falta, Java
  3. Instala Fabric / Quilt si lo eliges
  4. Copia los mods elegidos (sin tocar los que hayas puesto a mano) y lanza el juego (modo offline)
  5. Busca e instala mods desde Modrinth, con sus dependencias obligatorias
"""
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import threading
import time
import urllib.request
import uuid
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import quote, urlparse

ROOT = Path(os.environ.get("APPDATA") or Path.home()) / ".cerotouch"
LIBS = ROOT / "libraries"
ASSETS = ROOT / "assets"
VERSIONS = ROOT / "versions"
INSTANCES = ROOT / "instances"
RUNTIME = ROOT / "runtime"

MANIFEST_URL = "https://piston-meta.mojang.com/mc/game/version_manifest_v2.json"
MODRINTH = "https://api.modrinth.com/v2"
UA = {"User-Agent": "CeroTouchLauncher/1.0"}
LAUNCHER_VERSION = "1.0"
LOADERS = ["Vanilla", "Fabric", "Quilt"]

OS_NAME = {"Windows": "windows", "Darwin": "osx", "Linux": "linux"}.get(platform.system(), "linux")
ARCH = platform.machine().lower()
IS_ARM = ARCH in ("arm64", "aarch64")
IS_32 = platform.architecture()[0] == "32bit"
CP_SEP = ";" if OS_NAME == "windows" else ":"

DEFAULT_JVM = ["-Djava.library.path=${natives_directory}", "-cp", "${classpath}"]


# ----------------------------------------------------------------- red / archivos
def get_json(url, timeout=30):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def fetch_bytes(url, timeout=15, limit=400_000):
    """Descarga pequeña en memoria (iconos). Corta a 'limit' bytes."""
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read(limit)


def sha1_file(path):
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def download(url, dest, sha1=None, size=None, retries=3):
    """Descarga con reintentos y verificación de hash. Si ya existe y coincide el tamaño, no vuelve a bajar."""
    dest = Path(dest)
    if dest.exists() and (size is None or dest.stat().st_size == size):
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".part")
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=60) as r, open(tmp, "wb") as f:
                shutil.copyfileobj(r, f)
            if sha1 and sha1_file(tmp) != sha1:
                raise IOError(f"Hash incorrecto: {url}")
            os.replace(tmp, dest)
            return
        except Exception:
            tmp.unlink(missing_ok=True)
            if i == retries - 1:
                raise
            time.sleep(1.2 * (i + 1))


def stream_download(url, dest, on_progress=None):
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=60) as r, open(dest, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        got = 0
        while True:
            chunk = r.read(1 << 16)
            if not chunk:
                break
            f.write(chunk)
            got += len(chunk)
            if on_progress and total:
                on_progress(got / total)


def run_tasks(tasks, cb, lo, hi, label, workers=16):
    total = len(tasks)
    if not total:
        return
    done = 0
    with ThreadPoolExecutor(workers) as ex:
        futs = [ex.submit(download, *t) for t in tasks]
        for f in as_completed(futs):
            f.result()
            done += 1
            if done % 10 == 0 or done == total:
                cb(lo + (hi - lo) * done / total, f"{label} {done}/{total}")


def open_folder(path):
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    if OS_NAME == "windows":
        os.startfile(path)  # type: ignore[attr-defined]
    elif OS_NAME == "osx":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])


# ----------------------------------------------------------------- equipo: RAM y disco
def total_ram_gb():
    """RAM física total en GB (None si no se puede saber)."""
    try:
        if OS_NAME == "windows":
            import ctypes

            class MemStatus(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
            ms = MemStatus()
            ms.dwLength = ctypes.sizeof(MemStatus)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(ms))  # type: ignore[attr-defined]
            return ms.ullTotalPhys / 2 ** 30
        if OS_NAME == "linux":
            with open("/proc/meminfo", encoding="utf-8") as f:
                for ln in f:
                    if ln.startswith("MemTotal"):
                        return int(ln.split()[1]) / 2 ** 20
        if OS_NAME == "osx":
            out = subprocess.check_output(["sysctl", "-n", "hw.memsize"], text=True)
            return int(out.strip()) / 2 ** 30
    except Exception:
        pass
    return None


def ram_check(ram_gb):
    """Devuelve (nivel, mensaje). nivel: None | 'warn' | 'error'."""
    total = total_ram_gb()
    if not total:
        return None, ""
    if ram_gb > total - 1:
        return "error", (f"Elegiste {ram_gb} GB pero tu equipo tiene {total:.0f} GB en total. "
                         "Baja la memoria asignada.")
    if ram_gb > total * 0.6:
        return "warn", (f"{ram_gb} GB es mucho para tu equipo ({total:.0f} GB): "
                        "el sistema podría ir lento.")
    return None, ""


def free_disk_gb():
    try:
        base = ROOT if ROOT.exists() else Path.home()
        return shutil.disk_usage(base).free / 2 ** 30
    except Exception:
        return None


def check_disk(primera_vez):
    """Falla con un mensaje claro si no hay espacio suficiente."""
    ROOT.mkdir(parents=True, exist_ok=True)
    libre = free_disk_gb()
    if libre is None:
        return
    necesario = 2.0 if primera_vez else 0.3
    if libre < necesario:
        raise RuntimeError(f"Poco espacio en disco: quedan {libre:.1f} GB y se necesitan al menos "
                           f"{necesario:.1f} GB. Libera espacio e inténtalo de nuevo.")


# ----------------------------------------------------------------- versiones
_MANIFEST = {"data": None, "t": 0.0}
_MANIFEST_LOCK = threading.Lock()


def load_manifest(max_age=600):
    """Manifiesto de Mojang: una sola petición cada 10 min (compartida entre hilos),
    con copia en disco como plan B si no hay internet."""
    with _MANIFEST_LOCK:
        if _MANIFEST["data"] is not None and time.time() - _MANIFEST["t"] < max_age:
            return _MANIFEST["data"]
        cache = ROOT / "version_manifest.json"
        try:
            data = get_json(MANIFEST_URL)
            ROOT.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps(data))
        except Exception:
            if _MANIFEST["data"] is not None:
                return _MANIFEST["data"]
            if not cache.exists():
                raise
            data = json.loads(cache.read_text())
        _MANIFEST["data"], _MANIFEST["t"] = data, time.time()
        return data


def get_versions(include_snapshots=False):
    data = load_manifest()
    return [v for v in data["versions"] if include_snapshots or v["type"] == "release"]


def _manifest_entry(mc):
    for v in load_manifest()["versions"]:
        if v["id"] == mc:
            return v
    raise RuntimeError(f"La versión {mc} no existe en el manifiesto de Mojang.")


def get_base_json(mc):
    f = VERSIONS / mc / f"{mc}.json"
    if f.exists():
        return json.loads(f.read_text())
    entry = _manifest_entry(mc)
    data = get_json(entry["url"])
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(data))
    return data


def loader_profile(mc, loader):
    base = {
        "Fabric": "https://meta.fabricmc.net/v2/versions/loader",
        "Quilt": "https://meta.quiltmc.org/v3/versions/loader",
    }[loader]
    f = VERSIONS / mc / f"{loader.lower()}_profile.json"
    try:
        loaders = get_json(f"{base}/{quote(mc)}")
        if not loaders:
            raise RuntimeError(f"{loader} todavía no es compatible con Minecraft {mc}.")
        pick = None
        for e in loaders:  # primero estable
            ver = e["loader"]["version"]
            if e["loader"].get("stable", True) and not re.search(r"beta|alpha|pre|rc", ver, re.I):
                pick = ver
                break
        pick = pick or loaders[0]["loader"]["version"]
        prof = get_json(f"{base}/{quote(mc)}/{quote(pick)}/profile/json")
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(prof))
        return prof
    except RuntimeError:
        raise
    except Exception:
        if f.exists():
            return json.loads(f.read_text())
        raise


def merge_profiles(base, child):
    m = dict(base)
    m["id"] = child.get("id", base["id"])
    m["mainClass"] = child.get("mainClass", base["mainClass"])
    m["libraries"] = child.get("libraries", []) + base["libraries"]  # primero las del loader
    b_args, c_args = base.get("arguments", {}), child.get("arguments", {})
    m["arguments"] = {
        "jvm": (b_args.get("jvm") or DEFAULT_JVM) + c_args.get("jvm", []),
        "game": b_args.get("game", []) + c_args.get("game", []),
    }
    return m


# ----------------------------------------------------------------- reglas / librerías
def rule_ok(rules):
    if not rules:
        return True
    allowed = False
    for r in rules:
        match = True
        o = r.get("os")
        if o:
            if "name" in o and o["name"] != OS_NAME:
                match = False
            if o.get("arch") == "x86" and ARCH not in ("x86", "i386", "i686"):
                match = False
        if "features" in r:  # demo, resolución propia, quick play... todo desactivado
            if any(v for v in r["features"].values()):
                match = False
        if match:
            allowed = r["action"] == "allow"
    return allowed


def maven_path(name):
    parts = name.split(":")
    group, art, ver = parts[0], parts[1], parts[2]
    cls = parts[3] if len(parts) > 3 else None
    ext = "jar"
    if "@" in ver:
        ver, ext = ver.split("@")
    fn = f"{art}-{ver}" + (f"-{cls}" if cls else "") + f".{ext}"
    return f"{group.replace('.', '/')}/{art}/{ver}/{fn}"


def collect_libraries(m):
    tasks, cp, natives, seen = [], [], [], set()
    for lib in m["libraries"]:
        if not rule_ok(lib.get("rules")):
            continue
        name = lib["name"]
        parts = name.split(":")
        key = ":".join(parts[:2] + parts[3:4])
        dl = lib.get("downloads")

        if "natives" in lib:  # formato antiguo (<= 1.18)
            cls = lib["natives"].get(OS_NAME)
            if cls and dl:
                cls = cls.replace("${arch}", "32" if IS_32 else "64")
                a = dl.get("classifiers", {}).get(cls)
                if a:
                    p = LIBS / a["path"]
                    tasks.append((a["url"], p, a.get("sha1"), a.get("size")))
                    natives.append((p, lib.get("extract", {}).get("exclude", [])))

        art = dl.get("artifact") if dl else None
        if art:
            path, url, sha, size = art["path"], art["url"], art.get("sha1"), art.get("size")
        elif "natives" in lib:
            continue
        else:  # Fabric / Quilt: solo traen nombre maven + url base
            base = lib.get("url", "https://libraries.minecraft.net/")
            base += "" if base.endswith("/") else "/"
            path = maven_path(name)
            url, sha, size = base + path, None, None

        if key in seen:
            continue
        seen.add(key)
        p = LIBS / path
        tasks.append((url, p, sha, size))
        cp.append(p)
    return tasks, cp, natives


def extract_natives(jar, dest, exclude):
    with zipfile.ZipFile(jar) as z:
        for n in z.namelist():
            if n.endswith("/") or any(n.startswith(e) for e in exclude):
                continue
            z.extract(n, dest)


# ----------------------------------------------------------------- Java
def find_java(d):
    exe = "java.exe" if OS_NAME == "windows" else "java"
    if d.exists():
        for p in d.rglob(exe):
            if p.parent.name == "bin":
                return p
    return None


def ensure_java(major, cb, lo, hi):
    major = {16: 17}.get(major, major)
    try:
        return _download_java(major, cb, lo, hi)
    except Exception:
        sysj = shutil.which("java")  # plan B: el Java que ya tengas instalado
        if sysj:
            return Path(sysj)
        raise


def _download_java(major, cb, lo, hi):
    d = RUNTIME / str(major)
    j = find_java(d)
    if j:
        return j
    osn = {"windows": "windows", "osx": "mac", "linux": "linux"}[OS_NAME]
    arch = "aarch64" if IS_ARM else "x64"
    url = f"https://api.adoptium.net/v3/binary/latest/{major}/ga/{osn}/{arch}/jre/hotspot/normal/eclipse"
    ext = ".zip" if OS_NAME == "windows" else ".tar.gz"
    arc = RUNTIME / f"jre{major}{ext}"
    cb(lo, f"Descargando Java {major} (solo la primera vez)…")
    stream_download(url, arc, lambda f: cb(lo + (hi - lo) * 0.9 * f, f"Descargando Java {major}… {int(f * 100)}%"))
    cb(lo + (hi - lo) * 0.92, "Instalando Java…")
    d.mkdir(parents=True, exist_ok=True)
    if ext == ".zip":
        with zipfile.ZipFile(arc) as z:
            z.extractall(d)
    else:
        with tarfile.open(arc) as t:
            t.extractall(d)
    arc.unlink(missing_ok=True)
    j = find_java(d)
    if not j:
        raise RuntimeError("No se pudo instalar Java.")
    if OS_NAME != "windows":
        j.chmod(0o755)
    return j


# ----------------------------------------------------------------- lanzamiento
def _java_uuid_hash(b):
    """UUID.hashCode() de Java: el juego lo usa para elegir la skin por defecto."""
    hilo = int.from_bytes(b[:8], "big") ^ int.from_bytes(b[8:], "big")
    h = ((hilo >> 32) ^ hilo) & 0xFFFFFFFF
    return h - (1 << 32) if h >= (1 << 31) else h


def offline_uuid(name, slim=None):
    """UUID offline estándar. Si hay skin propia, se busca (con una sal) uno cuya skin
    por defecto use el modelo correcto: brazos delgados (slim) o normales (wide)."""
    buenos = {1, 3, 5, 7} if slim else {10, 12, 14, 16}
    for salt in range(400):
        seed = "OfflinePlayer:" + name + (f"#{salt}" if salt else "")
        h = bytearray(hashlib.md5(seed.encode()).digest())
        h[6] = (h[6] & 0x0F) | 0x30
        h[8] = (h[8] & 0x3F) | 0x80
        if slim is None or _java_uuid_hash(bytes(h)) % 18 in buenos:
            return uuid.UUID(bytes=bytes(h)).hex
    return uuid.UUID(bytes=bytes(h)).hex


# ----------------------------------------------------------------- skin offline
SKIN_FILE = ROOT / "skin.png"
SKIN_PACK = "CeroTouchSkin.zip"
SKIN_NAMES = ["alex", "ari", "efe", "kai", "makena", "noor", "steve", "sunny", "zuri"]


def build_skin_pack(png_path, dest_zip):
    """Paquete de recursos que reemplaza TODAS las skins por defecto con la tuya."""
    png = Path(png_path).read_bytes()
    meta = {"pack": {"pack_format": 34, "min_format": 15, "max_format": 999,
                     "supported_formats": {"min_inclusive": 1, "max_inclusive": 999},
                     "description": "CeroTouch Launcher - skin"}}
    with zipfile.ZipFile(dest_zip, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("pack.mcmeta", json.dumps(meta))
        for p in ("textures/entity/steve.png", "textures/entity/alex.png"):  # versiones antiguas
            z.writestr(f"assets/minecraft/{p}", png)
        for model in ("wide", "slim"):  # versiones nuevas
            for n in SKIN_NAMES:
                z.writestr(f"assets/minecraft/textures/entity/player/{model}/{n}.png", png)


def set_pack_enabled(inst, entry, enabled):
    f = Path(inst) / "options.txt"
    lines = f.read_text(encoding="utf-8").splitlines() if f.exists() else []
    if not lines and not enabled:
        return
    out, found = [], False
    for ln in lines:
        if ln.startswith("resourcePacks:"):
            found = True
            try:
                packs = json.loads(ln.split(":", 1)[1])
            except Exception:
                packs = ["vanilla"]
            packs = [p for p in packs if p != entry]
            if enabled:
                packs.append(entry)
            ln = "resourcePacks:" + json.dumps(packs, separators=(",", ":"))
        out.append(ln)
    if not found and enabled:
        out.append("resourcePacks:" + json.dumps(["vanilla", entry], separators=(",", ":")))
    f.write_text("\n".join(out) + "\n", encoding="utf-8")


def apply_skin(inst, skin):
    zp = Path(inst) / "resourcepacks" / SKIN_PACK
    if skin:
        zp.parent.mkdir(parents=True, exist_ok=True)
        build_skin_pack(skin["png"], zp)
        set_pack_enabled(inst, f"file/{SKIN_PACK}", True)
    else:
        zp.unlink(missing_ok=True)
        set_pack_enabled(inst, f"file/{SKIN_PACK}", False)


def _sub(s, vars_):
    return re.sub(r"\$\{(\w+)\}", lambda mo: str(vars_.get(mo.group(1), "")), s)


def expand_args(items, vars_):
    out = []
    for it in items:
        if isinstance(it, str):
            vals = [it]
        else:
            if not rule_ok(it.get("rules")):
                continue
            v = it["value"]
            vals = [v] if isinstance(v, str) else v
        out += [_sub(x, vars_) for x in vals]
    return out


# ----------------------------------------------------------------- mods de la instancia
MODS_TRACK = ".cerotouch_mods.json"


def sync_mods(instance_dir, jars, library=None):
    """Copia los mods elegidos a la instancia SIN borrar los que pusiste a mano.

    Se guarda una lista (.cerotouch_mods.json) con lo que copió el launcher; en la
    siguiente ejecución solo se quitan esos. Si un .jar con el mismo nombre ya estaba
    (puesto por ti), se respeta y no se sobrescribe.
    Devuelve cuántos mods se respetaron por ser tuyos.
    """
    md = Path(instance_dir) / "mods"
    md.mkdir(parents=True, exist_ok=True)
    track = md / MODS_TRACK
    previos = None
    try:
        previos = set(json.loads(track.read_text(encoding="utf-8")))
    except Exception:
        pass
    if previos is None:
        # primera vez con esta versión: las copias antiguas del launcher se reconocen
        # por nombre contra la biblioteca de mods
        previos = {p.name for p in Path(library).rglob("*.jar")} if library and Path(library).exists() else set()
    for nombre in previos:
        (md / Path(nombre).name).unlink(missing_ok=True)
    copiados, respetados = [], 0
    for j in jars:
        j = Path(j)
        dst = md / j.name
        if dst.exists():
            respetados += 1
            continue
        shutil.copy2(j, dst)
        copiados.append(j.name)
    track.write_text(json.dumps(copiados), encoding="utf-8")
    return respetados


# ----------------------------------------------------------------- Modrinth
def _mr_loaders(loader):
    """Quilt también carga mods de Fabric; Vanilla no carga mods, buscamos los de Fabric."""
    return ["quilt", "fabric"] if loader == "Quilt" else ["fabric"]


def modrinth_search(query, mc, loader, limit=20):
    """Mods compatibles con la versión y el loader. Sin texto: los más descargados."""
    facets = [["project_type:mod"],
              [f"versions:{mc}"],
              [f"categories:{l}" for l in _mr_loaders(loader)],
              ["client_side:required", "client_side:optional"]]
    index = "relevance" if query.strip() else "downloads"
    url = (f"{MODRINTH}/search?query={quote(query.strip())}&facets={quote(json.dumps(facets))}"
           f"&limit={limit}&index={index}")
    return get_json(url).get("hits", [])


def modrinth_best_version(project_id, mc, loader):
    for l in _mr_loaders(loader):
        url = (f"{MODRINTH}/project/{quote(project_id)}/version"
               f"?loaders={quote(json.dumps([l]))}&game_versions={quote(json.dumps([mc]))}")
        versiones = get_json(url)
        if versiones:
            estables = [v for v in versiones if v.get("version_type") == "release"]
            return (estables or versiones)[0]
    return None


def modrinth_install(project_id, mc, loader, library, categoria, cb=None):
    """Descarga el mod a library/categoria y sus dependencias obligatorias a library/otros.

    Devuelve la lista de rutas (el mod principal primero). Si un .jar con ese nombre ya
    estaba en la biblioteca, se reutiliza en vez de bajarlo otra vez.
    """
    library = Path(library)
    categoria = Path(categoria).name or "otros"
    existentes = {p.name: p for p in library.rglob("*.jar")} if library.exists() else {}
    vistos, resultado, hechos = set(), [], [0]

    def paso(texto):
        if cb:
            cb(1 - 0.9 * 0.55 ** hechos[0], texto)

    def instalar(pid, carpeta, nivel):
        if pid in vistos or nivel > 3:
            return
        vistos.add(pid)
        v = modrinth_best_version(pid, mc, loader)
        if not v:
            if nivel == 0:
                raise RuntimeError(f"Este mod no tiene una versión para Minecraft {mc} con {_mr_loaders(loader)[0].capitalize()}.")
            return
        archivos = v.get("files") or []
        if not archivos:
            if nivel == 0:
                raise RuntimeError("La versión elegida no trae archivos descargables.")
            return
        f = next((x for x in archivos if x.get("primary")), archivos[0])
        nombre = Path(f["filename"]).name
        if not nombre.lower().endswith(".jar"):
            raise RuntimeError(f"Archivo inesperado: {nombre}")
        host = urlparse(f["url"]).hostname or ""
        if not host.endswith("modrinth.com"):
            raise RuntimeError("Descarga bloqueada: el archivo no viene de Modrinth.")
        if nombre in existentes:
            destino = existentes[nombre]
        else:
            destino = library / carpeta / nombre
            paso(f"Descargando {nombre}…")
            download(f["url"], destino, (f.get("hashes") or {}).get("sha1"), f.get("size"))
            existentes[nombre] = destino
        hechos[0] += 1
        resultado.append(destino)
        for dep in v.get("dependencies", []):
            if dep.get("dependency_type") == "required" and dep.get("project_id"):
                try:
                    paso("Instalando dependencias…")
                    instalar(dep["project_id"], "otros", nivel + 1)
                except Exception:
                    pass  # una dependencia que falla no debe tumbar el mod principal

    paso("Buscando versión compatible…")
    instalar(project_id, categoria, 0)
    if cb:
        cb(1.0, "Listo")
    return resultado


def prepare(mc, loader, username, ram_gb, mods, cb, skin=None, library=None):
    """Descarga todo lo necesario y devuelve (comando, carpeta_instancia)."""
    if not re.fullmatch(r"[A-Za-z0-9_]{3,16}", username or ""):
        raise ValueError("El usuario debe tener 3-16 caracteres (letras, números o _).")
    if mods and loader == "Vanilla":
        raise ValueError("Para usar mods elige Fabric o Quilt como loader.")
    nivel, msg = ram_check(ram_gb)
    if nivel == "error":
        raise ValueError(msg)
    check_disk(primera_vez=not (VERSIONS / mc / f"{mc}.jar").exists())

    cb(0.0, "Obteniendo información de la versión…")
    base = get_base_json(mc)
    m = base if loader == "Vanilla" else merge_profiles(base, loader_profile(mc, loader))
    cb(0.03, "Preparando Java…")

    java = ensure_java(base.get("javaVersion", {}).get("majorVersion", 8), cb, 0.03, 0.2)

    # client.jar + librerías
    client = VERSIONS / mc / f"{mc}.jar"
    c = base["downloads"]["client"]
    tasks, cp, natives = collect_libraries(m)
    tasks.insert(0, (c["url"], client, c.get("sha1"), c.get("size")))
    run_tasks(tasks, cb, 0.2, 0.45, "Librerías")

    natives_dir = VERSIONS / mc / "natives"
    shutil.rmtree(natives_dir, ignore_errors=True)
    natives_dir.mkdir(parents=True, exist_ok=True)
    for jar, excl in natives:
        extract_natives(jar, natives_dir, excl)

    # assets (sonidos, idiomas, texturas de menú…), cada archivo verificado por su hash
    ai = base["assetIndex"]
    idx_path = ASSETS / "indexes" / f"{ai['id']}.json"
    download(ai["url"], idx_path, ai.get("sha1"))
    objects = json.loads(idx_path.read_text())["objects"]
    a_tasks = []
    for o in objects.values():
        h = o["hash"]
        a_tasks.append((f"https://resources.download.minecraft.net/{h[:2]}/{h}",
                        ASSETS / "objects" / h[:2] / h, h, o["size"]))
    run_tasks(a_tasks, cb, 0.45, 0.95, "Recursos")

    # instancia + mods
    inst = INSTANCES / f"{mc}-{loader.lower()}"
    inst.mkdir(parents=True, exist_ok=True)
    apply_skin(inst, skin)
    if loader != "Vanilla":
        cb(0.95, "Copiando mods…")
        sync_mods(inst, mods, library)

    # comando
    vars_ = {
        "auth_player_name": username,
        "version_name": m.get("id", mc),
        "game_directory": str(inst),
        "assets_root": str(ASSETS),
        "assets_index_name": ai["id"],
        "auth_uuid": offline_uuid(username, skin["slim"] if skin else None),
        "auth_access_token": "0",
        "clientid": "0",
        "auth_xuid": "0",
        "user_type": "legacy",
        "version_type": base.get("type", "release"),
        "natives_directory": str(natives_dir),
        "launcher_name": "CeroTouchLauncher",
        "launcher_version": LAUNCHER_VERSION,
        "classpath": CP_SEP.join(str(p) for p in cp + [client]),
        "library_directory": str(LIBS),
        "classpath_separator": CP_SEP,
        "user_properties": "{}",
        "game_assets": str(ASSETS),
    }
    args = m.get("arguments", {})
    jvm = expand_args(args.get("jvm") or DEFAULT_JVM, vars_)
    game = expand_args(args.get("game", []), vars_)
    if "minecraftArguments" in m:  # formato antiguo
        game = [_sub(x, vars_) for x in m["minecraftArguments"].split()] + game

    cmd = [str(java), f"-Xmx{ram_gb}G", f"-Xms{min(ram_gb, 2)}G"] + jvm + [m["mainClass"]] + game
    cb(1.0, "¡Iniciando Minecraft!")
    return cmd, inst


def launch(cmd, cwd, log_path):
    log = open(log_path, "w", encoding="utf-8", errors="replace")
    log.write("COMANDO: " + " ".join(f'"{c}"' if " " in c else c for c in cmd) + "\n\n")
    log.flush()
    flags = subprocess.CREATE_NO_WINDOW if OS_NAME == "windows" else 0
    return subprocess.Popen(cmd, cwd=cwd, stdout=log, stderr=subprocess.STDOUT, creationflags=flags)


def tail(path, n=12):
    """Últimas n líneas de un archivo (para mostrar por qué falló el juego)."""
    try:
        lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
        return "\n".join(l for l in lines if l.strip())[-1200:].splitlines()[-n:]
    except Exception:
        return []


# ----------------------------------------------------------------- título de la ventana
def watch_title(proc, nombre="CeroTouch"):
    """Cambia 'Minecraft 1.21.11' por 'CeroTouch - 1.21.11' (solo Windows).

    El título está escrito dentro del código del juego, así que desde fuera
    se reescribe mientras el proceso siga vivo.
    """
    if OS_NAME != "windows":
        return
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    EnumProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    patron = re.compile(r"^Minecraft\*? (.+?)((?: - (?:Singleplayer|Multiplayer).*)?)$")

    def ventanas_del_proceso():
        found = []

        def cb(hwnd, _):
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value == proc.pid and user32.IsWindowVisible(hwnd):
                found.append(hwnd)
            return True
        user32.EnumWindows(EnumProc(cb), 0)
        return found

    def loop():
        while proc.poll() is None:
            for hwnd in ventanas_del_proceso():
                n = user32.GetWindowTextLengthW(hwnd)
                buf = ctypes.create_unicode_buffer(n + 1)
                user32.GetWindowTextW(hwnd, buf, n + 1)
                m = patron.match(buf.value)
                if m:
                    user32.SetWindowTextW(hwnd, f"{nombre} - {m.group(1)}{m.group(2)}")
            time.sleep(0.3)

    threading.Thread(target=loop, daemon=True).start()

# ----------------------------------------------------------------- acceso directo (como una app)
APP_NOMBRE = "CeroTouch Launcher"


def build_ico(png_por_lado, dest):
    """Arma un .ico (con transparencia) a partir de PNGs {lado: bytes}. Sin librerías externas."""
    import struct
    lados = sorted(png_por_lado)
    cabecera = struct.pack("<HHH", 0, 1, len(lados))
    entradas, datos = b"", b""
    base = 6 + 16 * len(lados)
    for s in lados:
        png = png_por_lado[s]
        dim = s if s < 256 else 0
        entradas += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(png), base + len(datos))
        datos += png
    Path(dest).parent.mkdir(parents=True, exist_ok=True)
    Path(dest).write_bytes(cabecera + entradas + datos)


def _q(s):
    """Texto entre comillas simples para PowerShell."""
    return "'" + str(s).replace("'", "''") + "'"


def _ps(cmd, timeout=25):
    cmd = "[Console]::OutputEncoding=[System.Text.Encoding]::UTF8; " + cmd
    r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                        "-Command", cmd], capture_output=True, timeout=timeout,
                       creationflags=subprocess.CREATE_NO_WINDOW)
    if r.returncode != 0:
        err = (r.stderr or r.stdout or "PowerShell falló".encode()).decode("utf-8", errors="replace").strip()
        raise RuntimeError(err[:200])
    return r.stdout.decode("utf-8", errors="replace").strip()


def pythonw_exe():
    """pythonw.exe abre la app sin esa ventana negra de consola."""
    exe = Path(sys.executable)
    w = exe.with_name("pythonw.exe")
    return w if w.exists() else exe


def install_shortcuts(script, ico, png=None, escritorio=True, inicio=True):
    """Crea los accesos directos y devuelve las rutas creadas.

    Windows: .lnk en el Escritorio (respeta OneDrive) y en el menú Inicio.
    Linux:   .desktop en el menú de aplicaciones y en el Escritorio.
    """
    script = Path(script).resolve()
    creados = []
    if OS_NAME == "windows":
        carpetas = []
        if escritorio:
            carpetas.append(Path(_ps("[Environment]::GetFolderPath('Desktop')")))
        if inicio:
            carpetas.append(Path(_ps("[Environment]::GetFolderPath('Programs')")))
        for d in carpetas:
            d.mkdir(parents=True, exist_ok=True)
            lnk = d / f"{APP_NOMBRE}.lnk"
            _ps(f"$s=(New-Object -ComObject WScript.Shell).CreateShortcut({_q(lnk)});"
                f"$s.TargetPath={_q(pythonw_exe())};$s.Arguments={_q(chr(34) + str(script) + chr(34))};"
                f"$s.WorkingDirectory={_q(script.parent)};$s.IconLocation={_q(str(ico) + ',0')};"
                f"$s.Description={_q('Launcher de Minecraft')};$s.Save()")
            creados.append(lnk)
    elif OS_NAME == "linux":
        texto = ("[Desktop Entry]\nType=Application\nName=%s\nComment=Launcher de Minecraft\n"
                 'Exec="%s" "%s"\nPath=%s\nIcon=%s\nTerminal=false\nCategories=Game;\n'
                 % (APP_NOMBRE, sys.executable, script, script.parent, png or ico))
        destinos = []
        if inicio:
            destinos.append(Path.home() / ".local/share/applications")
        if escritorio and (Path.home() / "Desktop").exists():
            destinos.append(Path.home() / "Desktop")
        for d in destinos:
            d.mkdir(parents=True, exist_ok=True)
            f = d / "cerotouch-launcher.desktop"
            f.write_text(texto, encoding="utf-8")
            f.chmod(0o755)
            creados.append(f)
    else:
        raise RuntimeError("Los accesos directos solo están disponibles en Windows y Linux.")
    return creados