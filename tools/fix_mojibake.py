"""Repara texto en UTF-8 doblemente codificado (mojibake) en ficheros del repo.

MEDIDO
------
El damage del area de alimentacion era una cadena de
``bytes.decode("cp1252").encode("utf-8")`` repetida 2-4 veces sobre el
texto original. Invertirla es ``str.encode("cp1252").decode("utf-8")``.

Detalles que importan (medidos sobre el repo, no inferidos):

* El numero de vueltas NO es el mismo para todos los caracteres. ``á``
  cae a un nivel menos que ``á`` (su byte 0xA1 en cp1252 es ``¡``), y
  ``─`` (U+2500) cae a 4 niveles (35 caracteres de mojibake por
  separador). Por eso la profundidad se elige por linea, no por
  fichero.

* Un round-trip estricto aborta a mitad de linea cuando un byte suelto
  no forma una secuencia UTF-8 valida (caso de ``¡``). Por eso el
  decodificador es tolerante: los bytes sueltos pasan como latin-1 en
  vez de lanzar excepcion.

* Para elegir la profundidad correcta se usa una lista blanca empirica:
  los caracteres no ASCII que el repo usa de verdad, extraidos de los
  ficheros SIN mojibake. Sin ella, el heuristica se queda en un nivel
  de profundidad y deja texto de aspecto correcto pero equivocado.

Contrato:
  - Preserva BOM y CRLF byte a byte (read_bytes/write_bytes).
  - Preserva el esqueleto ASCII de cada linea (invariante del round-trip).
  - No toca nada que no tenga marcadores de mojibake.
  - No escribe un fichero si la verificacion falla.

Uso:
    python tools/fix_mojibake.py --dry-run
    python tools/fix_mojibake.py areas/alimentacion/helpers/excel/
"""
from __future__ import annotations

import argparse
import pathlib
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent

# Marcadores tipicos de mojibake (cp1252 leido sobre utf-8).
MARKERS = (
    "\u00c3",  # A tilde
    "\u00c2",  # A circunflejo
    "\u00e2\u20ac",  # a euro (comillas tipograficas)
    "\u0192",  # f con guion
    "\u00c6",  # AE ligature
    "\u201a",  # coma baja simple
    "\ufffd",  # replacement char
)

SKIP_DIRS = {"__pycache__", ".git", "dist", "build", ".venv", "node_modules"}


def score(text: str) -> int:
    """Numero de marcadores de mojibake en el texto."""
    return sum(text.count(m) for m in MARKERS)


def encode_lenient(text: str) -> bytes:
    """utf-8 -> cp1252 con respaldo latin-1 para los bytes sin equivalente."""
    out = bytearray()
    for ch in text:
        try:
            out += ch.encode("cp1252")
        except UnicodeEncodeError:
            code = ord(ch)
            if code < 256:
                out.append(code)
            else:
                out += ch.encode("utf-8")
    return bytes(out)


def decode_lenient(raw: bytes) -> str:
    """utf-8 tolerante: los bytes sueltos pasan como latin-1 en vez de abortar."""
    out: list[str] = []
    i = 0
    n = len(raw)
    while i < n:
        for length in (2, 3, 4):
            if i + length <= n:
                try:
                    out.append(raw[i : i + length].decode("utf-8"))
                except UnicodeDecodeError:
                    continue
                i += length
                break
        else:
            out.append(chr(raw[i]))
            i += 1
    return "".join(out)


def apply_chain(text: str, rounds: int) -> str:
    """Aplica `rounds` veces el round-trip inverso."""
    for _ in range(rounds):
        text = decode_lenient(encode_lenient(text))
    return text


def ascii_skeleton(text: str) -> str:
    """Solo los caracteres ASCII: invariante del round-trip."""
    return "".join(ch for ch in text if ord(ch) < 128)


def build_whitelist(root: pathlib.Path) -> set[str]:
    """Caracteres no ASCII que el repo usa de verdad (ficheros SIN mojibake)."""
    allowed: set[str] = set()
    for pattern in ("core/**/*.py", "areas/**/*.py", "tests/**/*.py"):
        for path in root.glob(pattern):
            if any(part in SKIP_DIRS for part in path.parts):
                continue
            try:
                text = path.read_bytes().decode("utf-8")
            except UnicodeDecodeError:
                continue
            if score(text):
                continue
            allowed.update(ch for ch in text if ord(ch) > 127)
    return allowed


def plausibility(text: str, allowed: set[str]) -> int:
    """Caracteres no ASCII fuera de la lista blanca (menor es mejor)."""
    return sum(1 for ch in text if ord(ch) > 127 and ch not in allowed)


def repair_line(line: str, allowed: set[str]) -> str:
    """Repara una linea eligiendo la profundidad que mejor encaja."""
    if not score(line):
        return line
    best: tuple[int, int, str] | None = None
    for depth in range(1, 6):
        candidate = apply_chain(line, depth)
        key = (score(candidate), plausibility(candidate, allowed))
        if best is None or key < best[0]:
            best = (key[0], key[1], candidate)
        if key[0] == 0 and key[1] == 0:
            break
    return best[2] if best else line


def repair_text(text: str, allowed: set[str]) -> tuple[str, list[int]]:
    """Repara el texto linea a linea. Devuelve (texto, lineas_con_residuos)."""
    lines = text.split("\n")
    for index, line in enumerate(lines):
        repaired = repair_line(line, allowed)
        if repaired != line:
            lines[index] = repaired
    text = "\n".join(lines)
    residual = [i for i, line in enumerate(text.split("\n"), 1) if score(line)]
    return text, residual


def process(path: pathlib.Path, allowed: set[str], dry_run: bool) -> bool:
    raw = path.read_bytes()
    bom = raw.startswith(b"\xef\xbb\xbf")
    body = raw[3:] if bom else raw
    text = body.decode("utf-8")

    before = score(text)
    if not before:
        return True

    fixed, residual = repair_text(text, allowed)
    ok_ascii = ascii_skeleton(text) == ascii_skeleton(fixed)
    after = score(fixed)
    ok = ok_ascii and not residual and after == 0

    print(
        "%s | bom=%s crlf=%d | marcadores %d -> %d | ascii=%s | residuales=%s"
        % (
            path.relative_to(REPO_ROOT),
            bom,
            raw.count(b"\r\n"),
            before,
            after,
            "intacto" if ok_ascii else "ROTO",
            residual or "ninguna",
        )
    )
    if dry_run or not ok:
        if not ok:
            print("   no se escribe: la verificacion falla")
        return ok

    out = fixed.encode("utf-8")
    if bom:
        out = b"\xef\xbb\xbf" + out
    path.write_bytes(out)
    print("   escrito (%d bytes)" % len(out))
    return True


def iter_targets(paths: list[str]) -> list[pathlib.Path]:
    if not paths:
        targets = []
        for pattern in ("core/**/*.py", "areas/**/*.py", "tests/**/*.py"):
            targets.extend(p for p in REPO_ROOT.glob(pattern) if p.is_file())
        return sorted(targets)
    out = []
    for raw in paths:
        path = pathlib.Path(raw)
        if not path.is_absolute():
            path = REPO_ROOT / raw
        if path.is_dir():
            out.extend(sorted(p for p in path.rglob("*.py") if p.is_file()))
        else:
            out.append(path)
    return out


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", help="ficheros o directorios (por defecto, todo el repo)")
    parser.add_argument("--dry-run", action="store_true", help="no escribe, solo informa")
    args = parser.parse_args(argv)

    allowed = build_whitelist(REPO_ROOT)
    print("lista blanca: %d caracteres no ASCII" % len(allowed))

    failures = 0
    for path in iter_targets(args.paths):
        if not path.exists() or path.suffix != ".py":
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        try:
            if not process(path, allowed, args.dry_run):
                failures += 1
        except UnicodeDecodeError:
            print("%s | no es UTF-8 valido: se omite" % path.relative_to(REPO_ROOT))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
