"""
Big Ben Tour ticket availability checker.
Navigates to the Parliament ticketing page, clicks the August 2026
month block in the carousel, then checks whether Aug 4, 5, or 6
have available (non-disabled, non-unavailableDay) slots.

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


def log(msg: str) -> None:
    timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    print(f"[{timestamp}] {msg}", flush=True)


def navigate_to_august(page) -> bool:
    """
    Clicks the 'August' month block in the Alice Carousel to load
    the August calendar. Returns True on success.
    """
    log("Looking for August 2026 carousel block...")

    try:
        august_block = page.locator(
            ".time-slot-month__block",
        ).filter(has_text="August").filter(has_text="2026").first

        august_block.wait_for(state="visible", timeout=15000)
        august_block.click()
        log("Clicked August 2026 block.")

        # Give the page a moment to fire its API request after the click
        page.wait_for_timeout(4000)

        # Wait for the calendar label to update to August.
        # The navigation label span shows the current month name.
        page.wait_for_selector(
            ".react-calendar__navigation__label__labelText",
            timeout=20000,
        )

        # Confirm the label actually says August
        label_text = page.locator(
            ".react-calendar__navigation__label__labelText"
        ).first.inner_text()
        log(f"Calendar label now reads: '{label_text}'")

        if "August" not in label_text:
            # Label didn't update -- try waiting a bit longer for the
            # aria-label buttons as a fallback signal
            log("Label not yet August, waiting for August date buttons...")
            page.wait_for_selector(
                "button[aria-label*='August 2026']",
                timeout=15000,
            )

        log("August calendar rendered.")
        return True

    except PlaywrightTimeout:
        log("ERROR: Timed out waiting for August calendar to render.")
        return False
    except Exception as e:
        log(f"ERROR: Failed to navigate to August -- {e}")
        return False


def find_available_dates(page) -> list[str]:
    """
    Returns a list of target date strings that are available.

    Strategy: collect all calendar day buttons that are currently
    rendered, log every one so we can see the exact aria-label format,
    then match our target days (4, 5, 6) against whatever format is
    actually present.

    A date is available when its button lacks both the 'disabled'
    attribute and the 'unavailableDay' class.
    """
    available = []
    target_days = {4, 5, 6}

    # Grab every button inside the calendar day grid
    all_buttons = page.locator(
        ".react-calendar__month-view__days button.react-calendar__tile"
    )
    count = all_buttons.count()
    log(f"Found {count} calendar day buttons in August view.")

    for i in range(count):
        btn = all_buttons.nth(i)
        try:
            aria = btn.get_attribute("aria-label") or ""
            class_attr = btn.get_attribute("class") or ""
            is_disabled = btn.get_attribute("disabled")
            # Log every button so we can see the real aria-label format
            log(f"  Button {i}: aria-label='{aria}' disabled={is_disabled is not None} classes='{class_attr}'")
        except Exception as e:
            log(f"  Button {i}: error reading attributes -- {e}")
            continue

        # Match target days: aria-label contains the day number and
        # some form of "August" -- handles formats like:
        #   "4 August 2026", "Wednesday, 4 August 2026", "Aug 4, 2026", etc.
        matched_day = None
        for day in target_days:
            if str(day) in aria and "August" in aria:
                matched_day = day
                break
            # Also handle abbreviated or numeric month formats just in case
            if str(day) in aria and "Aug" in aria:
                matched_day = day
                break

        if matched_day is None:
            continue

        # Found a target day -- check availability
        is_disabled = btn.get_attribute("disabled")
        if is_disabled is not None:
            log(f"August {matched_day}: disabled -- unavailable")
            continue

        if "unavailableDay" in class_attr:
            log(f"August {matched_day}: unavailableDay class -- unavailable")
            continue

        log(f"August {matched_day}: AVAILABLE")
        available.append(f"{matched_day} August 2026")

    return available


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

        # Give the JS app a moment to fully initialise before we interact
        page.wait_for_timeout(5000)

        # Wait for the carousel to render
        try:
            page.wait_for_selector(".time-slot-month__block", timeout=20000)
            log("Carousel detected.")
        except PlaywrightTimeout:
            log("ERROR: Carousel did not appear -- page may not have rendered correctly.")
            browser.close()
            return 2

        # Navigate to August
        if not navigate_to_august(page):
            browser.close()
            return 2

        # Check target dates
        available = find_available_dates(page)
        browser.close()

    if available:
        log(f"AVAILABILITY FOUND: {', '.join(available)}")
        result = {
            "available_dates": available,
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
