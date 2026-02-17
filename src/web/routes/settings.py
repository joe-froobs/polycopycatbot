from fastapi import APIRouter, Request, Form
from fastapi.responses import RedirectResponse

from src.config import Config
from src import db

router = APIRouter(tags=["settings"])


@router.get("/settings")
async def settings_page(request: Request, saved: bool = False, was_running: bool = False):
    config = await Config.from_db()
    return request.app.state.templates.TemplateResponse(
        "settings.html",
        {
            "request": request,
            "active": "settings",
            "config": config,
            "saved": saved,
            "was_running": was_running,
        },
    )


@router.post("/settings")
async def settings_save(
    request: Request,
    api_key: str = Form(""),
    paper_trading: str = Form(None),
    max_position_usd: str = Form("50"),
    max_concurrent_positions: str = Form("10"),
    daily_loss_limit_usd: str = Form("100"),
    poll_interval: str = Form("5"),
    max_traders: str = Form("5"),
    private_key: str = Form(""),
    funder: str = Form(""),
    rpc_url: str = Form("https://polygon-rpc.com"),
):
    settings = {
        "api_key": api_key.strip(),
        "paper_trading": "true" if paper_trading == "1" else "false",
        "max_position_usd": max_position_usd,
        "max_concurrent_positions": max_concurrent_positions,
        "daily_loss_limit_usd": daily_loss_limit_usd,
        "poll_interval": poll_interval,
        "max_traders": max_traders,
        "private_key": private_key.strip(),
        "funder": funder.strip(),
        "rpc_url": rpc_url.strip(),
    }
    await db.save_settings(settings)

    # Restart bot if it was running
    bot = request.app.state.bot
    was_running = bot.status == "running"
    if was_running:
        await bot.stop()
        await bot.start()

    return RedirectResponse(
        url=f"/settings?saved=true&was_running={was_running}",
        status_code=303,
    )
