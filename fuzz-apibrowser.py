import asyncio
import argparse
import time
from playwright.async_api import async_playwright

class Colors:
    RESET = "\033[0m"
    GREEN = "\033[32m"
    CYAN = "\033[36m"
    YELLOW = "\033[33m"
    RED = "\033[31m"
    MAGENTA = "\033[35m"
    BOLD = "\033[1m"

def colorize_status(status):
    try:
        status_code = int(status)
        if 200 <= status_code < 300:
            return f"{Colors.GREEN}{status}{Colors.RESET}"
        elif 300 <= status_code < 400:
            return f"{Colors.CYAN}{status}{Colors.RESET}"
        elif 400 <= status_code < 500:
            return f"{Colors.YELLOW}{status}{Colors.RESET}"
        elif 500 <= status_code < 600:
            return f"{Colors.RED}{status}{Colors.RESET}"
        else:
            return f"{Colors.MAGENTA}{status}{Colors.RESET}"
    except Exception:
        return f"{Colors.MAGENTA}{status}{Colors.RESET}"

async def fuzz_endpoints(base_url, wordlist_path, rps, headless=True, use_burp=False):
    with open(wordlist_path, 'r') as f:
        endpoints = [line.strip() for line in f if line.strip()]

    delay = 1.0 / rps

    async with async_playwright() as p:
        browser_args = []
        # Option 2: tiny off-screen window if not headless
        if not headless:
            browser_args.extend([
                '--window-position=2000,2000',  # Off-screen position (adjust if needed)
                '--window-size=1,1'             # Tiny 1x1 pixel window
            ])

        context_args = {
            "ignore_https_errors": True  # Ignore SSL errors, useful with Burp
        }

        if use_burp:
            proxy = "http://127.0.0.1:8080"
            print(f"{Colors.BOLD}{Colors.MAGENTA}[*] Routing requests through Burp proxy at {proxy}{Colors.RESET}")
            context_args["proxy"] = {
                "server": proxy
            }

        browser = await p.chromium.launch(headless=headless, args=browser_args)
        context = await browser.new_context(**context_args)

        # Reuse a single page instead of opening new ones each request to reduce window flicker
        page = await context.new_page()

        for endpoint in endpoints:
            url = f"{base_url.rstrip('/')}/{endpoint.lstrip('/')}"
            timestamp = time.strftime("%H:%M:%S")
            try:
                response = await page.goto(url, wait_until="domcontentloaded")
                status = response.status if response else 'No Response'
                content = await page.content()
                colored_status = colorize_status(status)
                print(f"[{timestamp}] [{colored_status}] {url} - {len(content)} bytes")
            except Exception as e:
                print(f"{Colors.RED}Error accessing {url}: {e}{Colors.RESET}")

            await asyncio.sleep(delay)

        await page.close()
        await browser.close()

def main():
    parser = argparse.ArgumentParser(description="Browser-based endpoint fuzzing with real RPS control + Burp support")
    parser.add_argument('--url', required=True, help='Base URL to fuzz')
    parser.add_argument('--wordlist', required=True, help='Path to wordlist file')
    parser.add_argument('--headless', action='store_true', help='Run browser in headless mode')
    parser.add_argument('--rps', type=float, default=10, help='Requests per second (default: 10)')
    parser.add_argument('--burp', action='store_true', help='Route traffic through Burp Suite proxy at 127.0.0.1:8080')

    args = parser.parse_args()
    asyncio.run(fuzz_endpoints(
        args.url, args.wordlist,
        rps=args.rps,
        headless=args.headless,
        use_burp=args.burp
    ))

if __name__ == "__main__":
    main()
