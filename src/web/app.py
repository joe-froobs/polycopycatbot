from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from src.bot_runner import BotRunner
from src import db

WEB_DIR = Path(__file__).parent
TEMPLATE_DIR = WEB_DIR / "templates"
STATIC_DIR = WEB_DIR / "static"

templates = Jinja2Templates(directory=str(TEMPLATE_DIR))


def create_app(bot: BotRunner) -> FastAPI:
    app = FastAPI(title="Poly Copy Cat Dashboard")
    app.state.bot = bot
    app.state.templates = templates

    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    # Onboarding middleware: redirect to /setup/tos if setup not complete
    @app.middleware("http")
    async def onboarding_guard(request: Request, call_next):
        path = request.url.path
        # Allow setup routes, static files, and API status through
        if (
            path.startswith("/setup")
            or path.startswith("/static")
            or path == "/favicon.ico"
        ):
            return await call_next(request)

        onboarding = await db.get_onboarding()
        if not onboarding.get("setup_complete"):
            return RedirectResponse(url="/setup/tos", status_code=303)

        return await call_next(request)

    # Register route modules
    from src.web.routes import setup, dashboard, traders, settings, api
    app.include_router(setup.router)
    app.include_router(dashboard.router)
    app.include_router(traders.router)
    app.include_router(settings.router)
    app.include_router(api.router)

    return app
