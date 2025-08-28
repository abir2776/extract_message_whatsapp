import os
import time
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from webdriver_manager.chrome import ChromeDriverManager

def make_driver():
    os.makedirs("./chrome-profile-telegram", exist_ok=True)
    options = webdriver.ChromeOptions()
    options.add_argument("--user-data-dir=./chrome-profile-telegram")
    options.add_argument("--profile-directory=Default")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")

    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)
    driver.set_window_size(1200, 900)
    return driver

def inspect_telegram():
    driver = make_driver()
    
    try:
        # Try both Telegram versions
        urls_to_try = [
            "https://web.telegram.org/",
            "https://web.telegram.org/k/",  # New version
            "https://web.telegram.org/a/",  # Another version
        ]
        
        for url in urls_to_try:
            print(f"\n{'='*50}")
            print(f"INSPECTING: {url}")
            print(f"{'='*50}")
            
            driver.get(url)
            time.sleep(3)
            
            print(f"Page title: {driver.title}")
            print(f"Current URL: {driver.current_url}")
            
            # Check if we need to login
            if "login" in driver.current_url.lower() or "auth" in driver.current_url.lower():
                print("⚠️ Login required - please log in manually and press Enter")
                input("Press Enter after logging in...")
                time.sleep(5)
            
            # Find all elements with 'chat' in class name
            chat_elements = driver.find_elements(By.CSS_SELECTOR, "[class*='chat' i]")
            print(f"\nFound {len(chat_elements)} elements with 'chat' in class:")
            for i, elem in enumerate(chat_elements[:10]):  # Show first 10
                try:
                    classes = elem.get_attribute("class")
                    tag = elem.tag_name
                    text = elem.text[:100] if elem.text else "(no text)"
                    print(f"  {i+1}. <{tag}> class='{classes}' text='{text}'")
                except:
                    continue
            
            # Find all list items
            list_items = driver.find_elements(By.CSS_SELECTOR, "li")
            print(f"\nFound {len(list_items)} <li> elements:")
            for i, elem in enumerate(list_items[:10]):  # Show first 10
                try:
                    classes = elem.get_attribute("class") or "(no class)"
                    text = elem.text[:100] if elem.text else "(no text)"
                    print(f"  {i+1}. class='{classes}' text='{text}'")
                except:
                    continue
            
            # Find all divs that might contain chats
            divs = driver.find_elements(By.CSS_SELECTOR, "div[class*='list' i], div[class*='dialog' i], div[class*='conversation' i]")
            print(f"\nFound {len(divs)} divs with list/dialog/conversation in class:")
            for i, elem in enumerate(divs[:10]):
                try:
                    classes = elem.get_attribute("class")
                    text = elem.text[:100] if elem.text else "(no text)"
                    print(f"  {i+1}. class='{classes}' text='{text}'")
                except:
                    continue
            
            # Show page structure
            print(f"\nPage source (first 2000 chars):")
            print(driver.page_source[:2000])
            
            print(f"\n\nInspection complete for {url}")
            response = input("Try next URL? (y/n): ").lower().strip()
            if response != 'y':
                break
                
    finally:
        driver.quit()

if __name__ == "__main__":
    inspect_telegram()