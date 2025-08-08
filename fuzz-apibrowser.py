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
    except:
        return f"{Colors.MAGENTA}{status}{Colors.RESET}"

def parse_filter_values(filter_str):
    """Parse filter or exclude input into exact set and ranges."""
    exact_set = set()
    ranges = []
    for part in filter_str.split(','):
        part = part.strip()
        if '-' in part:
            start, end = part.split('-')
            ranges.append((int(start), int(end)))
        else:
            exact_set.add(int(part))
    return exact_set, ranges

def matches_filter(value, exact_set, ranges):
    """Check if a value matches exact or range filter."""
    if not exact_set and not ranges:
        return True  # No filter provided → allow all
    if value in exact_set:
        return True
    for start, end in ranges:
        if start <= value <= end:
            return True
    return False

async def fuzz_endpoints(base_url, wordlist_path, rps, timeout,
                         headless=True, use_burp=False,
                         filter_status=None, filter_size=None,
                         exclude_status=None, exclude_size=None,
                         token=None):

    with open(wordlist_path, 'r') as f:
        endpoints = [line.strip() for line in f if line.strip()]

    total = len(endpoints)  # total count for progress tracking
    fuzz_mode = "FUZZ" in base_url
    delay = 1.0 / rps

    # Parse include filters
    status_set, status_ranges = parse_filter_values(filter_status) if filter_status else (set(), [])
    size_set, size_ranges = parse_filter_values(filter_size) if filter_size else (set(), [])

    # Parse exclude filters
    ex_status_set, ex_status_ranges = parse_filter_values(exclude_status) if exclude_status else (set(), [])
    ex_size_set, ex_size_ranges = parse_filter_values(exclude_size) if exclude_size else (set(), [])

    # Banner
    print(f"""{Colors.BOLD}{Colors.CYAN}
 :: Method           : GET
 :: URL              : {base_url}
 :: Wordlist         : {wordlist_path}
 :: Timeout          : {timeout}
 :: Threads(RPS)     : {rps}
 :: Include Status   : {filter_status or 'All'}
 :: Exclude Status   : {exclude_status or 'None'}
 :: Include Size     : {filter_size or 'All'}
 :: Exclude Size     : {exclude_size or 'None'}
{Colors.RESET}""")

    async with async_playwright() as p:
        browser_args = []
        if not headless:
            browser_args.extend([
                '--window-position=2000,2000',
                '--window-size=1,1'
            ])

        context_args = {"ignore_https_errors": True}

        if use_burp:
            proxy = "http://127.0.0.1:8080"
            print(f"{Colors.BOLD}{Colors.MAGENTA}[*] Routing requests through Burp proxy at {proxy}{Colors.RESET}")
            context_args["proxy"] = {"server": proxy}

        browser = await p.chromium.launch(headless=headless, args=browser_args)
        context = await browser.new_context(**context_args)

        if token:
            # Set Authorization header with Bearer token
            await context.set_extra_http_headers({
                "Authorization": f"Bearer {token}"
            })

        page = await context.new_page()

        for i, word in enumerate(endpoints, 1):  # start counting at 1
            url = base_url.replace("FUZZ", word) if fuzz_mode else f"{base_url.rstrip('/')}/{word.lstrip('/')}"

            start_time = time.time()
            try:
                response = await page.goto(url, wait_until="domcontentloaded", timeout=timeout * 1000)
                status = response.status if response else 0
                content = await page.content()
                duration = int((time.time() - start_time) * 1000)  # ms

                words = len(content.split())
                lines = content.count("\n")
                size = len(content.encode('utf-8'))

                # Always print progress on the same bottom line
                progress_text = f"Progress: {i}/{total}"
                print(f"\r{progress_text:<60}", end="", flush=True)

                # Filtering logic
                if filter_status and not matches_filter(status, status_set, status_ranges):
                    await asyncio.sleep(delay)
                    continue
                if filter_size and not matches_filter(size, size_set, size_ranges):
                    await asyncio.sleep(delay)
                    continue
                if exclude_status and matches_filter(status, ex_status_set, ex_status_ranges):
                    await asyncio.sleep(delay)
                    continue
                if exclude_size and matches_filter(size, ex_size_set, ex_size_ranges):
                    await asyncio.sleep(delay)
                    continue

                colored_status = colorize_status(status)
                # Print filtered result on a new line, above progress line
                print(f"\n{i}/{total} {word:<20} [Status: {colored_status}, Size: {size}, Words: {words}, Lines: {lines}, Duration: {duration}ms]")

            except Exception as e:
                print(f"\n{Colors.RED}{word:<20} [Error: {e}]{Colors.RESET}")

            await asyncio.sleep(delay)

        # After finishing, move cursor to next line so prompt isn't stuck on progress line
        print()

        await page.close()
        await browser.close()

def main():
    parser = argparse.ArgumentParser(description="Browser-based FUZZ fuzzer with include/exclude filters")
    parser.add_argument('--url', required=True, help='Target URL. Use FUZZ to indicate injection point')
    parser.add_argument('--wordlist', required=True, help='Path to wordlist file')
    parser.add_argument('--rps', type=float, default=10, help='Requests per second')
    parser.add_argument('--timeout', type=int, default=10, help='Timeout per request in seconds')
    parser.add_argument('--headless', action='store_true', help='Run browser in headless mode')
    parser.add_argument('--burp', action='store_true', help='Route through Burp proxy')
    parser.add_argument('--filter-status', help='Include only these status codes/ranges (e.g. 200,301,500-599)')
    parser.add_argument('--filter-size', help='Include only these sizes/ranges (e.g. 1000,500-1500)')
    parser.add_argument('--exclude-status', help='Exclude these status codes/ranges (e.g. 403,404,400-499)')
    parser.add_argument('--exclude-size', help='Exclude these sizes/ranges (e.g. 13966,500-1000)')
    parser.add_argument('--token', help='Bearer token to send in Authorization header')

    args = parser.parse_args()
    asyncio.run(fuzz_endpoints(
        args.url, args.wordlist,
        rps=args.rps,
        timeout=args.timeout,
        headless=args.headless,
        use_burp=args.burp,
        filter_status=args.filter_status,
        filter_size=args.filter_size,
        exclude_status=args.exclude_status,
        exclude_size=args.exclude_size,
        token=args.token
    ))

if __name__ == "__main__":
    main()
