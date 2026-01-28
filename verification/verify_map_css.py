from playwright.sync_api import sync_playwright, expect

def verify_map_css():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        # Login
        page.goto("http://localhost:5000/api/auth/login") # Using API login for simplicity if UI login is complex, but UI login is usually at /login
        # Actually, let's try the UI login page
        page.goto("http://localhost:5000/login")
        page.fill("input[name='username']", "admin")
        page.fill("input[name='password']", "admin")
        page.click("button[type='submit']")

        # Wait for login
        page.wait_for_url("**/")
        print("Logged in successfully.")

        # Go to Resources page (where the map is)
        page.goto("http://localhost:5000/resources")
        print("Navigated to /resources")

        # Check #new-booking-map-container CSS
        # We need to trigger the map view. Usually requires selecting date/location.
        # But the container might be present or we can check computed style of the hidden wrapper if rendered?
        # HTML: <div id="map-view-wrapper" style="display: none;"> ... <div id="new-booking-map-container" ...>

        # Even if hidden, we can check the style attribute or computed style.
        map_container = page.locator("#new-booking-map-container")

        # Check for background-position style
        # Since it's in the style attribute now (inline style) or CSS class.
        # I updated the inline style in templates/resources.html.

        style_attr = map_container.get_attribute("style")
        print(f"Style attribute: {style_attr}")

        if "background-position: left top" in style_attr or "background-position: 0% 0%" in style_attr:
             print("SUCCESS: background-position is correct in inline style.")
        else:
             print("FAILURE: background-position not found or incorrect in inline style.")
             # Check computed style just in case
             bg_pos = map_container.evaluate("element => window.getComputedStyle(element).backgroundPosition")
             print(f"Computed background-position: {bg_pos}")

             if bg_pos == "0% 0%" or bg_pos == "left top" or bg_pos == "0px 0px":
                 print("SUCCESS: Computed background-position is correct.")
             else:
                 print("FAILURE: Computed background-position is incorrect.")

        page.screenshot(path="verification/map_css.png")
        browser.close()

if __name__ == "__main__":
    verify_map_css()
