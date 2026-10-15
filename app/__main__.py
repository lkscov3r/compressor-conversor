"""Inicia o app localmente: `python -m app`."""

import argparse
import threading
import webbrowser

import uvicorn


def main() -> None:
    parser = argparse.ArgumentParser(description="Compressor e conversor de vídeo e imagem")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--sem-navegador", action="store_true", help="não abrir o navegador")
    args = parser.parse_args()

    url = f"http://{args.host}:{args.port}"
    print(f"Abrindo {url}  (Ctrl+C para encerrar)")
    if not args.sem_navegador:
        threading.Timer(1.0, webbrowser.open, args=(url,)).start()
    uvicorn.run("app.main:app", host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
