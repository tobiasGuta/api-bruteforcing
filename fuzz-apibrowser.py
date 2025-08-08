import asyncio
import argparse
import time
from collections import deque
from datetime import timedelta
from playwright.async_api import async_playwright
import aiohttp  # <-- added for Discord webhook

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
    if not exact_set and not ranges:
        return True
    if value in exact_set:
        return True
    for start, end in ranges:
        if start <= value <= end:
            return True
    return False

async def send_discord_notification(webhook_url, target, endpoint, size, recursive_active):
    content = (
        f"**Target:** {target}\n"
        f"**Endpoint:** {endpoint}\n"
        f"**Size:** {size}\n"
        f"**Recursive:** {'active' if recursive_active else 'inactive'}"
    )
    async with aiohttp.ClientSession() as session:
        try:
            await session.post(webhook_url, json={"content": content})
        except Exception as e:
            print(f"{Colors.YELLOW}[!] Warning: Failed to send Discord notification: {e}{Colors.RESET}")

async def fuzz_with_queue(base_url, endpoints, page, delay, timeout,
                          filter_status, filter_size,
                          exclude_status, exclude_size,
                          status_set, status_ranges,
                          size_set, size_ranges,
                          ex_status_set, ex_status_ranges,
                          ex_size_set, ex_size_ranges,
                          max_depth, recursive,
                          discord_webhook=None):

    queue = deque()
    start_url = base_url.rstrip('/')
    queue.append((start_url, 1))
    discovered_dirs = set([start_url])

    total_requests = 0
    total_errors = 0
    start_time = time.time()

    while queue:
        current_url, current_depth = queue.popleft()
        total = len(endpoints)

        print(f"\n{Colors.BOLD}{Colors.CYAN}Starting fuzz at depth {current_depth}: {current_url}{Colors.RESET}")

        for word in endpoints:
            url = f"{current_url}/{word.lstrip('/')}"
            if not url.endswith('/'):
                url += '/'

            try:
                await asyncio.sleep(delay)
                req_start = time.time()
                response = await page.goto(url, wait_until="domcontentloaded", timeout=timeout * 1000)
                status = response.status if response else 0
                content = await page.content()
                duration = int((time.time() - req_start) * 1000)
                words = len(content.split())
                lines = content.count('\n')
                size = len(content.encode('utf-8'))

                total_requests += 1

                # Check filters
                if filter_status and not matches_filter(status, status_set, status_ranges):
                    pass
                elif filter_size and not matches_filter(size, size_set, size_ranges):
                    pass
                elif exclude_status and matches_filter(status, ex_status_set, ex_status_ranges):
                    pass
                elif exclude_size and matches_filter(size, ex_size_set, ex_size_ranges):
                    pass
                else:
                    colored_status = colorize_status(status)
                    print(f"{word:<24} [Status: {colored_status}, Size: {size}, Words: {words}, Lines: {lines}, Duration: {duration}ms]")

                    # Discord notify only on matched results
                    if discord_webhook:
                        await send_discord_notification(
                            discord_webhook,
                            current_url,
                            word,
                            size,
                            recursive_active=(recursive and current_depth < max_depth)
                        )

                # Handle recursion
                if recursive and current_depth < max_depth:
                    if status in (200, 301, 302) and url.rstrip('/') not in discovered_dirs:
                        discovered_dirs.add(url.rstrip('/'))
                        queue.append((url.rstrip('/'), current_depth + 1))

            except Exception as e:
                total_requests += 1
                total_errors += 1
                print(f"{word:<24} [Error: {e}]")

            # Update progress line live
            elapsed = time.time() - start_time
            rps = total_requests / elapsed if elapsed > 0 else 0
            elapsed_td = timedelta(seconds=int(elapsed))
            progress_line = (f":: Progress: [{total_requests}/{len(endpoints)*max_depth}] :: "
                             f"Job [1/1] :: {int(rps)} req/sec :: Duration: [{elapsed_td}] :: Errors: {total_errors} ::")
            print(progress_line.ljust(80), end='\r', flush=True)

    print()  # Move cursor to next line after progress overwrite

async def fuzz_endpoints(base_url, wordlist_path, rps, timeout,
                         headless=True, use_burp=False,
                         filter_status=None, filter_size=None,
                         exclude_status=None, exclude_size=None,
                         token=None, recursive=False, max_depth=1,
                         discord_webhook=None):

    with open(wordlist_path, 'r') as f:
        endpoints = [line.strip() for line in f if line.strip()]

    fuzz_mode = "FUZZ" in base_url
    delay = 1.0 / rps

    # Parse include filters
    status_set, status_ranges = parse_filter_values(filter_status) if filter_status else (set(), [])
    size_set, size_ranges = parse_filter_values(filter_size) if filter_size else (set(), [])

    # Parse exclude filters
    ex_status_set, ex_status_ranges = parse_filter_values(exclude_status) if exclude_status else (set(), [])
    ex_size_set, ex_size_ranges = parse_filter_values(exclude_size) if exclude_size else (set(), [])

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
 :: Recursive        : {recursive}
 :: Max Depth        : {max_depth}
{Colors.RESET}""")

    async with async_playwright() as p:
        browser_args = []
        if not headless:
            browser_args.extend(['--window-position=2000,2000', '--window-size=1,1'])
        context_args = {"ignore_https_errors": True}
        if use_burp:
            proxy = "http://127.0.0.1:8080"
            print(f"{Colors.BOLD}{Colors.MAGENTA}[*] Routing requests through Burp proxy at {proxy}{Colors.RESET}")
            context_args["proxy"] = {"server": proxy}

        browser = await p.chromium.launch(headless=headless, args=browser_args)
        context = await browser.new_context(**context_args)

        if token:
            await context.set_extra_http_headers({"Authorization": f"Bearer {token}"})

        page = await context.new_page()

        start_url = base_url if not fuzz_mode else base_url.replace("FUZZ", "")
        await fuzz_with_queue(start_url, endpoints, page, delay, timeout,
                             filter_status, filter_size,
                             exclude_status, exclude_size,
                             status_set, status_ranges,
                             size_set, size_ranges,
                             ex_status_set, ex_status_ranges,
                             ex_size_set, ex_size_ranges,
                             max_depth, recursive,
                             discord_webhook=discord_webhook)

        print()
        await page.close()
        await browser.close()

def main():
    parser = argparse.ArgumentParser(description="Browser-based FUZZ fuzzer with include/exclude filters + recursion")
    parser.add_argument('--url', required=True, help='Target URL. Use FUZZ to indicate injection point')
    parser.add_argument('--wordlist', required=True, help='Path to wordlist file')
    parser.add_argument('--rps', type=float, default=10, help='Requests per second')
    parser.add_argument('--timeout', type=int, default=10, help='Timeout per request in seconds')
    parser.add_argument('--headless', action='store_true', help='Run browser in headless mode')
    parser.add_argument('--burp', action='store_true', help='Route through Burp proxy')
    parser.add_argument('--filter-status', help='Include only these status codes/ranges')
    parser.add_argument('--filter-size', help='Include only these sizes/ranges')
    parser.add_argument('--exclude-status', help='Exclude these status codes/ranges')
    parser.add_argument('--exclude-size', help='Exclude these sizes/ranges')
    parser.add_argument('--token', help='Bearer token to send in Authorization header')
    parser.add_argument('--recursive', action='store_true', help='Enable recursive fuzzing')
    parser.add_argument('--max-depth', type=int, default=1, help='Maximum recursion depth')
    parser.add_argument('--discord-webhook', help='Discord webhook URL for notifications')  # <-- added arg

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
        token=args.token,
        recursive=args.recursive,
        max_depth=args.max_depth,
        discord_webhook=args.discord_webhook  # <-- pass arg
    ))

if __name__ == "__main__":
    main()
