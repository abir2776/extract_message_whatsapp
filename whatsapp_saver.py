import os
import re
import time
import sqlite3
from datetime import datetime

from selenium import webdriver
from selenium.common.exceptions import (
    TimeoutException,
    StaleElementReferenceException,
    NoSuchElementException,
)
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager

# Configuration
WHATSAPP_WEB = "https://web.whatsapp.com/"
CHROME_PROFILE_DIR = os.path.abspath("./chrome-profile-wa")
DATABASE_FILE = "whatsapp_contacts.db"
BATCH_SIZE = 10  # Process chats in smaller batches


def init_database():
    """Initialize SQLite database and create table if not exists"""
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS contacts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            phone TEXT NOT NULL,
            email TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(phone, email)
        )
    """)

    conn.commit()
    conn.close()
    print(f"✓ Database initialized: {DATABASE_FILE}")


def save_contact(phone, email):
    """
    Save phone and email to database
    Only saves if both phone and email are provided
    Returns True if saved, False if already exists or invalid data
    """
    if not phone or not email:
        print("❌ Both phone and email are required")
        return False

    try:
        conn = sqlite3.connect(DATABASE_FILE)
        cursor = conn.cursor()

        # Check if this combination already exists
        cursor.execute(
            """
            SELECT COUNT(*) FROM contacts 
            WHERE phone = ? AND email = ?
        """,
            (phone, email),
        )

        if cursor.fetchone()[0] > 0:
            print(f"⚠️  Contact already exists: {phone} - {email}")
            conn.close()
            return False

        # Insert new contact
        cursor.execute(
            """
            INSERT INTO contacts (phone, email) 
            VALUES (?, ?)
        """,
            (phone, email),
        )

        conn.commit()
        conn.close()

        print(f"✅ New contact saved: {phone} - {email}")
        return True

    except sqlite3.IntegrityError:
        print(f"⚠️  Contact already exists: {phone} - {email}")
        return False
    except Exception as e:
        print(f"❌ Error saving contact: {e}")
        return False


def get_all_contacts():
    """Get all contacts from database"""
    try:
        conn = sqlite3.connect(DATABASE_FILE)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT phone, email, created_at FROM contacts 
            ORDER BY created_at DESC
        """)

        contacts = cursor.fetchall()
        conn.close()

        return contacts
    except Exception as e:
        print(f"❌ Error retrieving contacts: {e}")
        return []


def extract_email_from_text(text):
    """Extract email from text using regex"""
    pattern = r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"
    match = re.search(pattern, text)
    return match.group() if match else None


def clean_phone_number(phone_text):
    """Clean and format phone number"""
    # Remove common prefixes and clean the phone number
    phone = phone_text.strip()

    # Remove WhatsApp Web formatting
    phone = phone.replace("~", "").replace("+", "")

    # Extract only numbers and some special chars
    phone = re.sub(r"[^\d\s\-\(\)\+]", "", phone)

    return phone.strip() if phone else None


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


def get_chat_container(driver):
    """Find and return the chat container element"""
    chat_container_selectors = [
        "div[data-testid='chat-list']",
        "div[data-testid='side']",
        "#pane-side",
        "div[role='grid']",
    ]

    for selector in chat_container_selectors:
        try:
            container = driver.find_element(By.CSS_SELECTOR, selector)
            if container:
                return container
        except:
            continue

    return None


def get_current_visible_chats(driver):
    """Get currently visible chat elements in the viewport"""
    chat_selectors = [
        "div[data-testid='chat-list'] div[role='listitem']",
        "div[role='grid'] div[role='row']",
        "div[data-testid='cell-frame-container']",
        "#pane-side div[tabindex='-1'] > div > div",
    ]

    for selector in chat_selectors:
        try:
            chat_items = driver.find_elements(By.CSS_SELECTOR, selector)
            if chat_items:
                # Filter out only visible elements
                visible_chats = []
                for chat in chat_items:
                    try:
                        if chat.is_displayed() and chat.size["height"] > 0:
                            visible_chats.append(chat)
                    except StaleElementReferenceException:
                        continue

                return visible_chats
        except:
            continue

    return []


def extract_chat_data(chat_element):
    """Extract data from a single chat element"""
    try:
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
                name_el = chat_element.find_element(By.CSS_SELECTOR, name_sel)
                name = name_el.get_attribute("title") or name_el.text
                if name and name.strip():
                    chat_name = name.strip()
                    break
            except:
                continue

        # Get last message preview
        last_message = ""
        message_selectors = [
            "span[dir='ltr']",
            "span[dir='auto']:not([title])",
            "div[dir='auto']:not([title])",
            "span:last-child",
        ]

        for msg_sel in message_selectors:
            try:
                msg_elements = chat_element.find_elements(By.CSS_SELECTOR, msg_sel)
                for msg_el in msg_elements:
                    text = msg_el.text.strip()
                    if text and len(text) > 3 and ":" not in text[:10]:
                        last_message = text
                        break
                if last_message:
                    break
            except:
                continue

        return {
            "chat_name": chat_name,
            "last_message": last_message or "No preview available",
            "element": chat_element,  # Keep reference for clicking
        }

    except StaleElementReferenceException:
        return None
    except Exception as e:
        print(f"Error extracting chat data: {e}")
        return None


def scroll_down_and_get_chats(driver, container, scroll_amount=3):
    """Scroll down a bit and get newly visible chats"""
    try:
        # Scroll down gradually
        for _ in range(scroll_amount):
            driver.execute_script(
                "arguments[0].scrollTop += arguments[0].clientHeight * 0.3", container
            )
            time.sleep(0.2)

        # Wait for content to load
        time.sleep(0.5)

        # Get currently visible chats
        return get_current_visible_chats(driver)

    except Exception as e:
        print(f"Error scrolling: {e}")
        return []


def click_chat_element(driver, chat_element, chat_name):
    """Click on a chat element with error handling"""
    try:
        # Check if element is still valid
        if not chat_element.is_displayed():
            return False

        # Scroll element into view
        driver.execute_script(
            "arguments[0].scrollIntoView({block: 'center'});", chat_element
        )
        time.sleep(0.5)

        # Try to click
        chat_element.click()
        time.sleep(1.5)  # Wait for chat to load
        return True

    except StaleElementReferenceException:
        print(f"  ⚠️ Stale element for {chat_name}, trying name-based click")
        return click_chat_by_name(driver, chat_name)
    except Exception as e:
        print(f"  ❌ Error clicking chat element: {e}")
        return click_chat_by_name(driver, chat_name)


def click_chat_by_name(driver, chat_name, max_attempts=2):
    """
    Fallback method: Click on a chat by finding it by name
    """
    for attempt in range(max_attempts):
        try:
            # Find chat by name using XPath
            chat_xpath_selectors = [
                f"//span[@title='{chat_name}']//ancestor::div[@role='listitem']",
                f"//span[text()='{chat_name}']//ancestor::div[@role='listitem']",
                f"//*[contains(text(), '{chat_name}')]//ancestor::div[@role='listitem']",
            ]

            chat_element = None
            for xpath in chat_xpath_selectors:
                try:
                    chat_element = driver.find_element(By.XPATH, xpath)
                    if chat_element:
                        break
                except:
                    continue

            if chat_element:
                # Scroll the element into view
                driver.execute_script(
                    "arguments[0].scrollIntoView({block: 'center'});", chat_element
                )
                time.sleep(0.5)

                # Click the element
                chat_element.click()
                time.sleep(1.5)
                return True
            else:
                print(
                    f"  ⚠️ Chat not found by name: {chat_name} (attempt {attempt + 1})"
                )

        except Exception as e:
            print(f"  ❌ Error in name-based click (attempt {attempt + 1}): {e}")
            time.sleep(0.5)

    return False


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


def process_chats_with_scrolling(driver):
    """
    Main function to process chats by scrolling through the entire list
    """
    container = get_chat_container(driver)
    if not container:
        print("❌ Chat container not found")
        return 0, 0

    # Reset to top
    driver.execute_script("arguments[0].scrollTop = 0", container)
    time.sleep(1)

    processed_chats = set()  # Track processed chats by name
    total_processed = 0
    total_saved = 0
    batch_count = 0
    no_new_chats_count = 0

    print("📜 Starting automated scrolling and processing...")

    while no_new_chats_count < 3:  # Stop after 3 attempts with no new chats
        batch_count += 1
        print(f"\n--- Batch {batch_count} ---")

        # Get current visible chats
        visible_chats = get_current_visible_chats(driver)

        if not visible_chats:
            print("No visible chats found, scrolling...")
            scroll_down_and_get_chats(driver, container)
            no_new_chats_count += 1
            continue

        # Extract data from visible chats
        current_batch_chats = []
        new_chats_found = 0

        for chat_element in visible_chats:
            chat_data = extract_chat_data(chat_element)
            if chat_data and chat_data["chat_name"] != "Unknown":
                if chat_data["chat_name"] not in processed_chats:
                    current_batch_chats.append(chat_data)
                    processed_chats.add(chat_data["chat_name"])
                    new_chats_found += 1

        if new_chats_found == 0:
            print(f"No new chats in this batch, scrolling...")
            scroll_down_and_get_chats(driver, container)
            no_new_chats_count += 1
            continue
        else:
            no_new_chats_count = 0  # Reset counter

        print(f"Found {new_chats_found} new chats to process in this batch")

        # Process each chat in current batch
        batch_saved = 0
        for i, chat_data in enumerate(current_batch_chats):
            try:
                print(
                    f"\n  [{i + 1}/{len(current_batch_chats)}] Opening {chat_data['chat_name']}..."
                )

                # Click chat
                if click_chat_element(
                    driver, chat_data["element"], chat_data["chat_name"]
                ):
                    detailed_msg = get_last_message_from_open_chat(driver)

                    if detailed_msg:
                        print(f"    Message: {detailed_msg['body'][:80]}...")

                        # Extract phone and email
                        phone = clean_phone_number(chat_data["chat_name"])
                        email = extract_email_from_text(detailed_msg["body"])

                        print(f"    Phone: {phone}")
                        print(f"    Email: {email}")

                        # Save to database if both exist
                        if phone and email:
                            if save_contact(phone, email):
                                print("    💾 Saved to database!")
                                batch_saved += 1
                                total_saved += 1
                            else:
                                print("    📝 Already exists")
                        else:
                            print("    ⚠️  Missing phone or email")

                        total_processed += 1
                    else:
                        print("    ⚠️  No message found")
                else:
                    print(f"    ❌ Could not open chat")

            except Exception as e:
                print(f"    ❌ Error processing chat: {e}")
                continue

        print(f"  Batch {batch_count} completed: {batch_saved} new contacts saved")

        # Scroll down for next batch
        if batch_count < 100:  # Reasonable limit
            scroll_down_and_get_chats(driver, container, scroll_amount=5)
            time.sleep(0.5)
        else:
            print("Reached maximum batch limit")
            break

    print(f"\n📊 Final Summary:")
    print(f"   Total unique chats processed: {total_processed}")
    print(f"   New contacts saved: {total_saved}")
    print(f"   Batches processed: {batch_count}")

    return total_processed, total_saved


def print_database_stats():
    """Print current database statistics"""
    contacts = get_all_contacts()
    print(f"\n📊 Database Stats:")
    print(f"   Total contacts: {len(contacts)}")

    if contacts:
        print(f"   Latest contacts:")
        for phone, email, created_at in contacts[:3]:  # Show latest 3
            print(f"     • {phone} - {email} ({created_at})")


def main():
    # Initialize database
    init_database()

    driver = make_driver()

    if not wait_for_login(driver):
        driver.quit()
        return

    try:
        print_database_stats()

        while True:
            print(f"\n--- Starting scan at {datetime.now().strftime('%H:%M:%S')} ---")

            # Process all chats with automatic scrolling
            processed, saved = process_chats_with_scrolling(driver)

            if processed == 0:
                print("No chats found or processed")

            print_database_stats()
            print("\nWaiting 30 seconds before next full scan...")
            time.sleep(30)

    except KeyboardInterrupt:
        print("\n🛑 Stopped by user")
        print_database_stats()
    except Exception as e:
        print(f"❌ Error: {e}")
    finally:
        driver.quit()
        print("Browser closed.")


if __name__ == "__main__":
    main()