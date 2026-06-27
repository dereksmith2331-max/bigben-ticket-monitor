"""
Big Ben Tour ticket availability checker.
Navigates to the Parliament ticketing page, advances to August 2026,
and checks whether Aug 4, 5, or 6 have available (non-greyed-out) slots.

Exit codes:
  0 -- one or more target dates are available
  1 -- no availability found (normal, expected most of the time)
  2 -- script error (page failed to load, selector not found, etc.)
"""

import sys
import json
from datetime import datetime
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

URL = "https://tickets.parliament.uk/timeslot/big-ben-tour"
TARGET_DATES = [4, 5, 6]   # August days to check
TARGET_MONTH = "August"
TARGET_YEAR = "2026"


def log(msg: str) -> None:
    timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    print(f"[{timestamp}] {msg}", flush=True)


def find_available_dates(page) -> list[int]:
    """
    Returns a list of target day numbers that appear available on the calendar.
    A date is considered available if it has a clickable/active day cell
    and is NOT greyed out / disabled.
    """
    available = []

    for day in TARGET_DATES:
        # Playwright locator strategy:
        # The SEE Tickets calendar renders each date as a button or div
        # with the day number as text. Disabled/unavailable dates typically
        # carry an aria-disabled attribute or a CSS class like 'disabled',
        # 'unavailable', or 'greyed'. We try multiple selector patterns.

        # Try to find any element containing the day number that is NOT disabled.
        # We look for elements with the exact text of the day number.
        day_str = str(day)

        # Primary: look for a button/td/div with day text that lacks disabled markers
        candidates = page.locator(
            f"button:not([disabled]):not(.disabled):not(.unavailable), "
            f"td:not(.disabled):not(.unavailable):not(.greyed), "
            f"div:not(.disabled):not(.unavailable):not(.greyed)"
        ).filter(has_text=day_str)

        count = candidates.count()
        found = False

        for i in range(count):
            el = candidates.nth(i)
            try:
                text = el.inner_text().strip()
                # Exact match only -- avoid matching "14" when looking for "4"
                if text != day_str:
                    continue

                # Check aria-disabled
                aria_disabled = el.get_attribute("aria-disabled")
                if aria_disabled == "true":
                    continue

                # Check class for common disabled patterns
                class_attr = el.get_attribute("class") or ""
                disabled_classes = {"disabled", "unavailable", "greyed", "inactive",
                                    "sold-out", "soldout", "closed"}
                if any(c in class_attr.lower() for c in disabled_classes):
                    continue

                # Passed all checks -- treat as available
                found = True
                break

            except Exception:
                continue

        if found:
            log(f"August {day} appears AVAILABLE")
            available.append(day)
        else:
            log(f"August {day} appears unavailable or greyed out")

    return available


def navigate_to_august(page) -> bool:
    """
    Clicks the calendar's 'next month' control until August 2026 is displayed.
    Returns True on success, False if navigation fails.
    """
    max_clicks = 6  # safety limit -- we should never need more than 2 from July

    for attempt in range(max_clicks):
        # Check what month/year is currently displayed
        # SEE Tickets typically renders the month header in an element like
        # h2, .month-title, .calendar-header, or similar
        header_selectors = [
            ".month-title",
            ".calendar-header",
            ".datepicker-switch",
            "[class*='month']",
            "h2",
            "h3",
        ]

        current_header = ""
        for sel in header_selectors:
            try:
                el = page.locator(sel).first
                if el.is_visible(timeout=2000):
                    current_header = el.inner_text().strip()
                    break
            except Exception:
                continue

        log(f"Calendar header reads: '{current_header}'")

        if TARGET_MONTH in current_header and TARGET_YEAR in current_header:
            log("August 2026 is now displayed.")
            return True

        # Click the next-month arrow
        next_selectors = [
            "button[aria-label*='next' i]",
            "button[aria-label*='forward' i]",
            ".next-month",
            ".next",
            "[class*='next']",
            "button:has-text('>')",
            "button:has-text('›')",
            "button:has-text('→')",
        ]

        clicked = False
        for sel in next_selectors:
            try:
                btn = page.locator(sel).first
                if btn.is_visible(timeout=2000):
                    btn.click()
                    page.wait_for_timeout(1200)  # wait for calendar to re-render
                    clicked = True
                    log(f"Clicked next-month button (attempt {attempt + 1})")
                    break
            except Exception:
                continue

        if not clicked:
            log("ERROR: Could not find a next-month button to click.")
            return False

    log(f"ERROR: Reached August navigation limit ({max_clicks} clicks) without finding August 2026.")
    return False


def main() -> int:
    log("Starting Big Ben ticket check...")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
        )
        page = context.new_page()

        try:
            log(f"Loading {URL}")
            page.goto(URL, wait_until="networkidle", timeout=30000)
            log("Page loaded.")
        except PlaywrightTimeout:
            log("ERROR: Page load timed out.")
            browser.close()
            return 2
        except Exception as e:
            log(f"ERROR: Failed to load page -- {e}")
            browser.close()
            return 2

        # Wait a moment for JS calendar to initialise
        page.wait_for_timeout(3000)

        # Navigate to August 2026
        if not navigate_to_august(page):
            # Dump page text for debugging
            log("Page text snippet for debugging:")
            try:
                print(page.inner_text("body")[:2000])
            except Exception:
                pass
            browser.close()
            return 2

        # Check target dates
        available = find_available_dates(page)

        browser.close()

    if available:
        days_str = ", ".join(f"August {d}" for d in available)
        log(f"AVAILABILITY FOUND: {days_str}")
        # Write a summary file that the GitHub Actions step reads
        result = {
            "available_dates": [f"August {d}, 2026" for d in available],
            "url": URL,
            "checked_at": datetime.utcnow().isoformat() + "Z",
        }
        with open("availability_result.json", "w") as f:
            json.dump(result, f, indent=2)
        return 0
    else:
        log("No availability found for August 4, 5, or 6.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
