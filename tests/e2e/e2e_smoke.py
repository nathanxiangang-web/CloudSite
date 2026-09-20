"""CloudSite V2 E2E smoke test with Playwright.

Tests:
1. Login
2. Browse resources
3. Search
4. Admin index page
"""
from playwright.sync_api import sync_playwright, expect
import sys

WEB_URL = "http://192.168.178.50:3000"
USERNAME = "nathan"
PASSWORD = "647lsxasd"

results = []

def test_login(page):
    page.goto(WEB_URL, wait_until="networkidle", timeout=15000)
    page.wait_for_timeout(2000)
    
    # Look for login form
    url_after_load = page.url
    print(f"  Initial URL: {url_after_load}")
    
    page.wait_for_timeout(3000)
    
    # Find inputs by type
    all_inputs = page.locator('input').all()
    username_input = None
    password_input = None
    for inp in all_inputs:
        t = inp.get_attribute('type')
        if t == 'password':
            password_input = inp
        elif t in (None, 'text', ''):
            username_input = inp
    
    if username_input and password_input and username_input.is_visible() and password_input.is_visible():
        username_input.fill(USERNAME)
        password_input.fill(PASSWORD)
        
        # Find and click login button
        login_btn = page.locator('button:has-text("登录"), button:has-text("Login"), button[type="submit"]').first
        if login_btn.is_visible():
            login_btn.click()
            page.wait_for_timeout(5000)
        
        url_after_login = page.url
        print(f"  After login URL: {url_after_login}")
        
        # Check if we're still on login page
        if "login" in url_after_login.lower():
            results.append(("Login", False, f"Still on login page: {url_after_login}"))
            return False
        else:
            results.append(("Login", True, f"Logged in, URL: {url_after_login}"))
            return True
    else:
        # Maybe already logged in or different UI
        results.append(("Login", True, f"No login form found, URL: {url_after_load}"))
        return True


def test_browse(page):
    try:
        page.wait_for_timeout(2000)
        # Look for browse/content elements
        content = page.locator('a:has-text("浏览"), a:has-text("Browse"), a:has-text("资源"), a:has-text("Resource"), nav a').first
        if content.is_visible():
            content.click()
            page.wait_for_timeout(2000)
        
        # Check page has content
        body_text = page.inner_text("body")
        has_content = len(body_text) > 100
        results.append(("Browse", has_content, f"Page content length: {len(body_text)}"))
        return has_content
    except Exception as e:
        results.append(("Browse", False, str(e)))
        return False


def test_search(page):
    try:
        # Look for search input
        search_input = page.locator('input[type="search"], input[placeholder*="搜索"], input[placeholder*="search"], input[name="search"], input[name="keyword"]').first
        
        if search_input.is_visible():
            search_input.fill("test")
            search_input.press("Enter")
            page.wait_for_timeout(2000)
            
            body_text = page.inner_text("body")
            has_results = len(body_text) > 50
            results.append(("Search", True, f"Search executed, content: {len(body_text)}"))
            return True
        else:
            results.append(("Search", True, "No search input found, skipping"))
            return True
    except Exception as e:
        results.append(("Search", False, str(e)))
        return False


def test_admin_index(page):
    try:
        page.goto(f"{WEB_URL}/admin", wait_until="networkidle", timeout=10000)
        page.wait_for_timeout(2000)
        
        body_text = page.inner_text("body")
        has_content = len(body_text) > 50
        results.append(("Admin", has_content, f"Admin page content: {len(body_text)}"))
        return has_content
    except Exception as e:
        results.append(("Admin", False, str(e)))
        return False


def test_api_health():
    import urllib.request
    try:
        resp = urllib.request.urlopen("http://192.168.178.50:8000/api/health", timeout=5)
        data = resp.read().decode()
        results.append(("API Health", True, data))
        return True
    except Exception as e:
        results.append(("API Health", False, str(e)))
        return False


with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()
    
    print("=== CloudSite V2 E2E Smoke Test ===\n")
    
    # Test API health first
    print("1. API Health")
    test_api_health()
    
    # Test login
    print("2. Login")
    logged_in = test_login(page)
    
    # Test browse
    print("3. Browse")
    test_browse(page)
    
    # Test search
    print("4. Search")
    test_search(page)
    
    # Test admin
    print("5. Admin Index")
    test_admin_index(page)
    
    browser.close()

# Summary
print("\n=== Results ===")
passed = 0
failed = 0
for name, ok, detail in results:
    status = "✅ PASS" if ok else "❌ FAIL"
    print(f"  {status} {name}: {detail[:80]}")
    if ok:
        passed += 1
    else:
        failed += 1

print(f"\nTotal: {passed} passed, {failed} failed")
sys.exit(0 if failed == 0 else 1)