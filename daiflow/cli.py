import webbrowser

import click
import uvicorn

from daiflow.config import init_daiflow_dir


@click.group()
def cli():
    """DaiFlow - AI-powered programming workbench"""
    pass


@cli.command()
@click.option("--port", default=8000, help="Port to run on")
@click.option("--host", default="127.0.0.1", help="Host to bind to")
@click.option("--no-browser", is_flag=True, help="Don't auto-open browser")
def start(port: int, host: str, no_browser: bool):
    """Start the DaiFlow server."""
    init_daiflow_dir()

    if not no_browser:
        import threading
        threading.Timer(1.5, lambda: webbrowser.open(f"http://{host}:{port}")).start()

    uvicorn.run("daiflow.main:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    cli()
