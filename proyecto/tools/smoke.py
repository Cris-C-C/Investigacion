"""Run the optional browser test against a temporary local static server."""

from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import shutil
import subprocess
from threading import Thread


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, _format, *_args):
        pass


def smoke_test(audit):
    script = Path(__file__).with_name("smoke.cjs")
    location = Path("index.html")
    node = shutil.which("node")
    if not node:
        audit.warning(location, 1, "Prueba de humo omitida. Instala Node y Playwright.")
        return "Omitida por falta de Node."
    try:
        check = subprocess.run([node, str(script), "--available"], capture_output=True, text=True,
                               encoding="utf-8", errors="replace", timeout=15)
        if check.returncode == 3:
            audit.warning(location, 1, check.stdout.strip() or "Playwright no está disponible.")
            return "Omitida por falta de Playwright o Chromium."
        if check.returncode:
            raise OSError(check.stderr.strip() or "No se pudo comprobar Playwright.")
        handler = partial(QuietHandler, directory=str(audit.root))
        with ThreadingHTTPServer(("127.0.0.1", 0), handler) as server:
            thread = Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                address = f"http://127.0.0.1:{server.server_port}/"
                result = subprocess.run([node, str(script), address], capture_output=True, text=True,
                                        encoding="utf-8", errors="replace", timeout=300)
            finally:
                server.shutdown()
                thread.join()
    except (OSError, subprocess.TimeoutExpired) as error:
        audit.error(location, 1, f"No se pudo ejecutar la prueba de humo: {error}")
        return "Falló la ejecución."
    if result.returncode:
        for message in (result.stderr.strip() or "Falló Playwright.").splitlines():
            audit.error(location, 1, message)
        return "Falló."
    return result.stdout.strip() or "Correcta."
