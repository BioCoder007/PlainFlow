"""Start PlainFlow: python main.py"""
import argparse
import sys
import threading
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "server"))


def main() -> None:
    parser = argparse.ArgumentParser(description="Run PlainFlow locally.")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    if not (ROOT / "server" / "app" / "static" / "index.html").is_file():
        sys.exit("The web app is not built. Run: cd web && npm install && npm run build")

    import uvicorn

    url = f"http://localhost:{args.port}"
    print(f"PlainFlow running at {url}  (Ctrl+C to stop)")
    if not args.no_browser:
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    uvicorn.run("app.main:app", host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
