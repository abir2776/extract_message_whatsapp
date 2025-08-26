import os
import re
import time
from datetime import datetime

from selenium import webdriver
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager

# Configuration
WHATSAPP_WEB = "https://web.whatsapp.com/"
CHROME_PROFILE_DIR = os.path.abspath("./chrome-profile-wa")


def make_driver():
    os.makedirs(CHROME_PROFILE_DIR, exist_ok=True)
    options = webdriver.ChromeOptions()
    options.add_argument(f"--user-data-dir={CHROME_PROFILE_DIR}")
    options.add_argument("--profile-directory=Default")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")

    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)
    driver.set_window_size(1200, 900)
    return driver


def wait_for_login(driver, timeout=180):
    print("Loading WhatsApp Web...")
    driver.get(WHATSAPP_WEB)

    print("Waiting for login (scan QR if needed)...")
    wait = WebDriverWait(driver, timeout)

    try:
        # Wait for chat list to appear
        wait.until(
            EC.any_of(
                EC.presence_of_element_located(
                    (By.CSS_SELECTOR, "div[data-testid='chat-list']")
                ),
                EC.presence_of_element_located((By.CSS_SELECTOR, "div[role='grid']")),
                EC.presence_of_element_located(
                    (By.CSS_SELECTOR, "[data-testid='side']")
                ),
            )
        )
        print("✓ Login successful!")
        return True
    except TimeoutException:
        print("✗ Login failed or timed out")
        return False


def get_all_chats_with_last_message(driver):
    """
    Get unread chats and their last messages directly from the chat list
    """
    unread_data = []

    try:
        print("Scanning chat list for unread messages...")

        # Find all chat items in the sidebar
        chat_selectors = [
            "div[data-testid='chat-list'] div[role='listitem']",
            "div[role='grid'] div[role='row']",
            "div[data-testid='cell-frame-container']",
            "#pane-side div[tabindex='-1'] > div > div",
        ]

        chat_items = []
        for selector in chat_selectors:
            try:
                chat_items = driver.find_elements(By.CSS_SELECTOR, selector)
                if chat_items:
                    print(f"✓ Found {len(chat_items)} chats using selector: {selector}")
                    break
            except:
                continue

        if not chat_items:
            print("❌ No chat items found")
            return []

        # Process each chat to find unread ones
        for i, chat in enumerate(chat_items):
            try:
                print(f"Checking chat {i + 1}/{len(chat_items)}")

                # Check if chat has unread indicator
                # has_unread = False

                # # Look for unread badge/count
                # unread_badges = chat.find_elements(By.CSS_SELECTOR,
                #     "span[data-testid='icon-unread-count'], "
                #     "div[data-testid='unread-count'], "
                #     "span[aria-label*='unread'], "
                #     "div[aria-label*='unread']"
                # )

                # if unread_badges:
                #     has_unread = True
                #     print(f"  ✓ Found unread badge")

                # Alternative: check for bold chat name (another unread indicator)
                # if not has_unread:
                #     bold_names = chat.find_elements(By.CSS_SELECTOR,
                #         "span[dir='auto'] strong, "
                #         "div[dir='auto'] strong, "
                #         "span[title][style*='font-weight'], "
                #         "*[style*='font-weight: 700']"
                #     )
                #     if bold_names:
                #         has_unread = True
                #         print(f"  ✓ Found bold chat name (unread indicator)")

                # if not has_unread:
                #     continue

                # Get chat name
                chat_name = "Unknown"
                name_selectors = [
                    "span[dir='auto'][title]",
                    "div[dir='auto'] span[title]",
                    "span[title]",
                    "div[dir='auto']",
                ]

                for name_sel in name_selectors:
                    try:
                        name_el = chat.find_element(By.CSS_SELECTOR, name_sel)
                        name = name_el.get_attribute("title") or name_el.text
                        if name and name.strip():
                            chat_name = name.strip()
                            break
                    except:
                        continue

                # Get last message preview (usually visible in chat list)
                last_message = ""
                message_selectors = [
                    "span[dir='ltr']",  # Common for message previews
                    "span[dir='auto']:not([title])",  # Alternative
                    "div[dir='auto']:not([title])",
                    "span:last-child",
                ]

                for msg_sel in message_selectors:
                    try:
                        msg_elements = chat.find_elements(By.CSS_SELECTOR, msg_sel)
                        for msg_el in msg_elements:
                            text = msg_el.text.strip()
                            if (
                                text and len(text) > 3 and ":" not in text[:10]
                            ):  # Avoid timestamps
                                last_message = text
                                break
                        if last_message:
                            break
                    except:
                        continue

                # Get timestamp from chat list
                timestamp = ""
                time_selectors = [
                    "div[dir='auto'] span:last-child",
                    "span[dir='auto']:last-child",
                    "div:last-child span",
                ]

                for time_sel in time_selectors:
                    try:
                        time_el = chat.find_element(By.CSS_SELECTOR, time_sel)
                        time_text = time_el.text.strip()
                        # Check if it looks like a time (contains : or is short)
                        if (":" in time_text or len(time_text) < 10) and time_text:
                            timestamp = time_text
                            break
                    except:
                        continue

                if chat_name != "Unknown":
                    unread_data.append(
                        {
                            "chat_name": chat_name,
                            "last_message": last_message or "No preview available",
                            "timestamp": timestamp or "Unknown time",
                            "element": chat,  # Keep reference for potential clicking
                        }
                    )
                    print(f"  📱 {chat_name}: {last_message[:50]}...")

            except Exception as e:
                print(f"  ❌ Error processing chat {i + 1}: {e}")
                continue

    except Exception as e:
        print(f"❌ Error scanning chats: {e}")

    return unread_data


def get_last_message_from_open_chat(driver):
    """
    Get the actual last message from an opened chat (more detailed)
    """
    try:
        # Wait for messages to load
        time.sleep(1)

        # Find all message elements
        message_selectors = [
            "div[data-testid*='msg'] div.copyable-text",
            "div.copyable-text[data-pre-plain-text]",
            "span.copyable-text",
            "div.message-in div.copyable-text, div.message-out div.copyable-text",
        ]

        messages = []
        for selector in message_selectors:
            messages = driver.find_elements(By.CSS_SELECTOR, selector)
            if messages:
                break

        if not messages:
            return None

        # Get the last message
        last_msg = messages[-1]

        # Extract text
        body = ""
        try:
            text_el = last_msg.find_element(
                By.CSS_SELECTOR, "span.selectable-text, span._ao3e"
            )
            body = text_el.text.strip()
        except:
            body = last_msg.text.strip()

        # Extract metadata
        pre_plain = last_msg.get_attribute("data-pre-plain-text") or ""

        # Determine if it's incoming or outgoing
        direction = "in"
        try:
            parent = last_msg.find_element(
                By.XPATH, "./ancestor::div[contains(@class, 'message-')]"
            )
            if "message-out" in parent.get_attribute("class"):
                direction = "out"
        except:
            pass

        return {"body": body, "direction": direction, "pre_plain": pre_plain}

    except Exception as e:
        print(f"Error getting last message from open chat: {e}")
        return None


def main():
    driver = make_driver()

    if not wait_for_login(driver):
        driver.quit()
        return

    try:
        while True:
            print(f"\n--- Checking at {datetime.now().strftime('%H:%M:%S')} ---")

            # Get unread chats with preview messages
            unread_chats = get_all_chats_with_last_message(driver)

            if not unread_chats:
                print("No unread chats found")
            else:
                print(f"\n📬 Found {len(unread_chats)} unread chats:")
                print("=" * 60)

                # for i, chat in enumerate(unread_chats, 1):
                #     print(f"{i}. {chat['chat_name']}")
                #     print(f"   Last: {chat['last_message']}")
                #     print(f"   Time: {chat['timestamp']}")
                #     print("-" * 40)

                # Optionally, open each chat to get full last message
                print("\nGetting detailed last messages...")
                for chat in unread_chats:  # Limit to first 3 to avoid spam
                    try:
                        print(f"\nOpening {chat['chat_name']}...")
                        chat["element"].click()
                        time.sleep(2)

                        detailed_msg = get_last_message_from_open_chat(driver)
                        if detailed_msg:
                            print(f"  Full message: {detailed_msg['body']}")
                            print(f"  Direction: {detailed_msg['direction']}")
                            phone = chat["chat_name"]
                            phone = phone.strip()
                            last_meassage = detailed_msg["body"]
                            pattern = r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"
                            match = re.search(pattern, last_meassage)
                            email = None
                            if match:
                                email = match.group()
                            else:
                                print("No email found")

                    except Exception as e:
                        print(f"  Error opening chat: {e}")

            print("\nWaiting 10 seconds before next check...")
            time.sleep(10)

    except KeyboardInterrupt:
        print("\n🛑 Stopped by user")
    except Exception as e:
        print(f"❌ Error: {e}")
    finally:
        driver.quit()
        print("Browser closed.")


if __name__ == "__main__":
    main()
