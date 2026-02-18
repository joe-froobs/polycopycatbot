import re

from fastapi import APIRouter, Request, Form
from fastapi.responses import RedirectResponse

from src import db
from src.config import Config
from src.web.routes.settings import _validate_settings

router = APIRouter(prefix="/setup", tags=["setup"])

_ETH_ADDR_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")


def _is_valid_eth_address(addr: str) -> bool:
    return bool(_ETH_ADDR_RE.match(addr))


@router.get("/tos")
async def tos_page(request: Request):
    return request.app.state.templates.TemplateResponse(
        "setup/tos.html", {"request": request}
    )


@router.post("/tos")
async def tos_accept(request: Request, accept: str = Form(None)):
    if accept != "1":
        return request.app.state.templates.TemplateResponse(
            "setup/tos.html", {"request": request}
        )
    await db.set_tos_accepted()
    return RedirectResponse(url="/setup/source", status_code=303)


@router.get("/source")
async def source_page(request: Request):
    onboarding = await db.get_onboarding()
    if not onboarding.get("tos_accepted"):
        return RedirectResponse(url="/setup/tos", status_code=303)

    api_key = await db.get_setting("api_key")
    traders = await db.get_traders()
    manual = "\n".join(t["address"] for t in traders)

    return request.app.state.templates.TemplateResponse(
        "setup/source.html",
        {"request": request, "api_key": api_key, "manual_traders": manual, "error": ""},
    )


@router.post("/source")
async def source_save(
    request: Request,
    api_key: str = Form(""),
    manual_traders: str = Form(""),
):
    api_key = api_key.strip()
    raw_addresses = [
        line.strip()
        for line in manual_traders.strip().splitlines()
        if line.strip()
    ]

    # Validate Ethereum addresses
    valid_addresses = []
    skipped = 0
    for addr in raw_addresses:
        if _is_valid_eth_address(addr):
            valid_addresses.append(addr)
        else:
            skipped += 1

    if not api_key and not valid_addresses:
        error = "Please enter an API key or at least one valid trader address."
        if skipped:
            error = f"{skipped} invalid address(es) skipped. {error}"
        return request.app.state.templates.TemplateResponse(
            "setup/source.html",
            {
                "request": request,
                "api_key": api_key,
                "manual_traders": manual_traders,
                "error": error,
            },
        )

    warning = f" ({skipped} invalid address(es) skipped)" if skipped else ""

    # Save API key
    if api_key:
        await db.set_setting("api_key", api_key)

    # Save valid manual traders
    for addr in valid_addresses[:20]:
        await db.add_trader(addr, source="manual")

    return RedirectResponse(url="/setup/risk", status_code=303)


@router.get("/risk")
async def risk_page(request: Request):
    onboarding = await db.get_onboarding()
    if not onboarding.get("tos_accepted"):
        return RedirectResponse(url="/setup/tos", status_code=303)

    config = await Config.from_db()
    return request.app.state.templates.TemplateResponse(
        "setup/risk.html",
        {
            "request": request,
            "paper_trading": config.paper_trading,
            "account_balance_usd": int(config.account_balance_usd),
            "max_position_pct": round(config.max_position_pct * 100, 1),
            "max_position_usd": int(config.max_position_usd),
            "max_concurrent_positions": config.max_concurrent_positions,
            "daily_loss_limit_usd": int(config.daily_loss_limit_usd),
            "poll_interval": config.poll_interval,
            "max_traders": config.max_traders,
            "private_key": config.private_key,
            "funder": config.funder,
            "rpc_url": config.rpc_url,
        },
    )


@router.post("/risk")
async def risk_save(
    request: Request,
    paper_trading: str = Form(None),
    account_balance_usd: str = Form("0"),
    max_position_pct: str = Form("5"),
    max_position_usd: str = Form("50"),
    max_concurrent_positions: str = Form("10"),
    daily_loss_limit_usd: str = Form("100"),
    poll_interval: str = Form("5"),
    max_traders: str = Form("5"),
    private_key: str = Form(""),
    funder: str = Form(""),
    rpc_url: str = Form("https://polygon-rpc.com"),
):
    # Validate numeric inputs
    validation_errors = _validate_settings(
        max_position_usd, max_concurrent_positions,
        daily_loss_limit_usd, poll_interval, max_traders,
    )
    if validation_errors:
        config = await Config.from_db()
        return request.app.state.templates.TemplateResponse(
            "setup/risk.html",
            {
                "request": request,
                "paper_trading": paper_trading == "1",
                "account_balance_usd": account_balance_usd,
                "max_position_pct": max_position_pct,
                "max_position_usd": max_position_usd,
                "max_concurrent_positions": max_concurrent_positions,
                "daily_loss_limit_usd": daily_loss_limit_usd,
                "poll_interval": poll_interval,
                "max_traders": max_traders,
                "private_key": private_key,
                "funder": funder,
                "rpc_url": rpc_url,
                "error": "; ".join(validation_errors),
            },
        )

    # Convert percentage input (e.g. "5") to decimal (0.05)
    try:
        pct_decimal = str(float(max_position_pct) / 100.0)
    except (ValueError, TypeError):
        pct_decimal = "0.05"

    settings = {
        "paper_trading": "true" if paper_trading == "1" else "false",
        "account_balance_usd": account_balance_usd,
        "max_position_pct": pct_decimal,
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
    return RedirectResponse(url="/setup/done", status_code=303)


@router.get("/done")
async def done_page(request: Request):
    onboarding = await db.get_onboarding()
    if not onboarding.get("tos_accepted"):
        return RedirectResponse(url="/setup/tos", status_code=303)

    config = await Config.from_db()
    traders = await db.get_traders()

    return request.app.state.templates.TemplateResponse(
        "setup/done.html",
        {
            "request": request,
            "paper_trading": config.paper_trading,
            "api_key": config.api_key,
            "trader_count": len(traders),
            "max_position_usd": int(config.max_position_usd),
            "max_concurrent_positions": config.max_concurrent_positions,
            "daily_loss_limit_usd": int(config.daily_loss_limit_usd),
            "poll_interval": config.poll_interval,
        },
    )


@router.post("/done")
async def done_complete(request: Request):
    await db.set_setup_complete()
    # Auto-start the bot
    bot = request.app.state.bot
    await bot.start()
    return RedirectResponse(url="/", status_code=303)
