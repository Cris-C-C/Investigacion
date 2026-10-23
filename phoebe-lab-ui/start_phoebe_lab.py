import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

def main():
    print("==================================================")
    print("           Iniciando PHOEBE Lab UI                ")
    print("==================================================")
    print("[1/2] Iniciando servidor API backend (puerto 8001)...")

    api_proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "api.main:app", "--host", "127.0.0.1", "--port", "8001"],
        cwd=str(BASE_DIR)
    )

    ready = False
    for _ in range(40):
        try:
            with urllib.request.urlopen("http://127.0.0.1:8001/dash/sessions", timeout=1):
                ready = True
                break
        except Exception:
            time.sleep(0.5)

    if not ready:
        print("Error: No se pudo conectar con el servidor API.")
        api_proc.terminate()
        sys.exit(1)

    print("[2/2] Servidor API listo. Iniciando interfaz web (puerto 8082)...")
    print("Se abrira tu navegador en: http://localhost:8082")
    print("Para detener la aplicacion, presiona Ctrl+C en esta ventana.")
    print("==================================================")

    def open_browser():
        time.sleep(3.5)
        url = "http://localhost:8082"
        browser_paths = [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
            r"C:\Program Files (x86)\BraveSoftware\Brave-Browser\Application\brave.exe"
        ]
        opened = False
        for bp in browser_paths:
            if Path(bp).exists():
                try:
                    subprocess.Popen([bp, url])
                    opened = True
                    break
                except Exception:
                    pass
        if not opened:
            webbrowser.open(url)

    import threading
    threading.Thread(target=open_browser, daemon=True).start()

    ui_proc = subprocess.Popen(
        [sys.executable, "-m", "ui.phoebe_ui"],
        cwd=str(BASE_DIR)
    )

    try:
        ui_proc.wait()
    except KeyboardInterrupt:
        print("\nCerrando PHOEBE Lab...")
    finally:
        ui_proc.terminate()
        api_proc.terminate()
        try:
            ui_proc.wait(timeout=3)
        except Exception:
            ui_proc.kill()
        try:
            api_proc.wait(timeout=3)
        except Exception:
            api_proc.kill()
        print("PHOEBE Lab se ha cerrado correctamente.")

if __name__ == "__main__":
    main()
