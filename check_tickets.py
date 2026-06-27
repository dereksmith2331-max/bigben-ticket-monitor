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

# aria-label values on the date buttons match "4 August 2026" format
TARGET_ARIA_LABELS = [
    "4 August 2026",
    "5 August 2026",
    "6 August 2026",
]


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
    Returns a list of target date labels that are available.

    A date button is available when:
      - Its aria-label matches one of our target dates, AND
      - It does NOT have the 'unavailableDay' class, AND
      - It does NOT have the 'disabled' attribute.
    """
    available = []

    for label in TARGET_ARIA_LABELS:
        try:
            # Select the button with this exact aria-label
            btn = page.locator(f"button[aria-label='{label}']").first
            btn.wait_for(state="attached", timeout=5000)

            # Check disabled attribute
            is_disabled = btn.get_attribute("disabled")
            if is_disabled is not None:
                log(f"{label}: disabled attribute present -- unavailable")
                continue

            # Check for unavailableDay class
            class_attr = btn.get_attribute("class") or ""
            if "unavailableDay" in class_attr:
                log(f"{label}: has unavailableDay class -- unavailable")
                continue

            log(f"{label}: AVAILABLE (no disabled attribute, no unavailableDay class)")
            available.append(label)

        except PlaywrightTimeout:
            log(f"{label}: button not found in time -- treating as unavailable")
        except Exception as e:
            log(f"{label}: error checking -- {e}")

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
