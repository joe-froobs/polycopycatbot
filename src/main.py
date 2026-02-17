import sys
import time

from src.config import Config
from src.api_client import ApiClient
from src.wallet_monitor import WalletMonitor
from src.trade_executor import TradeExecutor


def main():
    config = Config()

    errors = config.validate()
    if errors:
        for e in errors:
            print(f"[ERROR] {e}")
        sys.exit(1)

    mode = "PAPER" if config.paper_trading else "LIVE"
    print(f"[Bot] Starting in {mode} mode")
    print(f"[Bot] Max traders: {config.max_traders}")
    print(f"[Bot] Poll interval: {config.poll_interval}s")
    print(f"[Bot] Max position: ${config.max_position_usd}")
    print(f"[Bot] Max concurrent: {config.max_concurrent_positions}")
    print(f"[Bot] Daily loss limit: ${config.daily_loss_limit_usd}")
    print()

    api = ApiClient(config)
    monitor = WalletMonitor()
    executor = TradeExecutor(config)

    # Fetch trader addresses
    addresses = api.get_trader_addresses()
    if not addresses:
        print("[Bot] No trader addresses found. Check API key or MANUAL_TRADERS.")
        sys.exit(1)

    print(f"[Bot] Monitoring {len(addresses)} traders")
    for i, addr in enumerate(addresses, 1):
        print(f"  {i}. {addr[:8]}...{addr[-4:]}")
    print()

    # Initial scan to establish baseline (don't trade on first scan)
    print("[Bot] Running initial scan to establish baseline positions...")
    monitor.detect_changes(addresses)
    print("[Bot] Baseline established. Watching for changes...\n")

    try:
        while True:
            time.sleep(config.poll_interval)

            new, closed, adjusted = monitor.detect_changes(addresses)

            for pos in new:
                print(f"[Detected] NEW position: {pos}")
                executor.open_position(pos)

            for pos in closed:
                print(f"[Detected] CLOSED position: {pos}")
                executor.close_position(pos)

            for pos in adjusted:
                print(f"[Detected] ADJUSTED position: {pos}")
                executor.adjust_position(pos)

    except KeyboardInterrupt:
        print("\n[Bot] Shutting down...")
        print(f"[Bot] Open positions: {len(executor.open_positions)}")
        print(f"[Bot] Total exposure: ${executor.total_exposure:.2f}")
    finally:
        api.close()
        monitor.close()


if __name__ == "__main__":
    main()
