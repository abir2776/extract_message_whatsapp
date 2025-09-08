import json
import os
import re
import sqlite3
import time
from datetime import datetime

import requests
from selenium import webdriver
from selenium.common.exceptions import (
    StaleElementReferenceException,
    TimeoutException,
)
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager

# Configuration
TELEGRAM_WEB = "https://web.telegram.org/"
CHROME_PROFILE_DIR = os.path.abspath("./chrome-profile-telegram")
DATABASE_FILE = "whats_app_telegram_contacts.db"
BATCH_SIZE = 10  # Process chats in smaller batches


def init_database():
    """Initialize SQLite database and create table if not exists"""
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()

    # First, create the table with the new structure
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS contacts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            phone TEXT NOT NULL,
            email TEXT NOT NULL,
            is_verified BOOLEAN DEFAULT FALSE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(email)
        )
    """)

    # Check if the is_verified column exists (for existing databases)
    cursor.execute("PRAGMA table_info(contacts)")
    columns = [column[1] for column in cursor.fetchall()]

    # If is_verified column doesn't exist, add it
    if "is_verified" not in columns:
        cursor.execute(
            "ALTER TABLE contacts ADD COLUMN is_verified BOOLEAN DEFAULT FALSE"
        )
        print("✓ Added is_verified column to existing table")

    # If chat_name column doesn't exist, add it
    if "chat_name" not in columns:
        cursor.execute("ALTER TABLE contacts ADD COLUMN chat_name TEXT")
        print("✓ Added chat_name column to existing table")

    conn.commit()
    conn.close()
    print(f"✓ Database initialized: {DATABASE_FILE}")


def save_contact(phone, email):
    """
    Save phone and email to database with is_verified set to False
    Only saves if both phone and email are provided
    Returns True if saved, False if already exists or invalid data
    """
    if not phone or not email:
        print("❌ Both phone and email are required")
        return False
    if len(phone) < 12:
        print("Phone number is not valid")
        return False

    try:
        conn = sqlite3.connect(DATABASE_FILE)
        cursor = conn.cursor()

        # Check if this combination already exists
        cursor.execute(
            """
            SELECT COUNT(*) FROM contacts 
            WHERE email = ?
            AND is_verified = 1
        """,
            (email,),
        )

        if cursor.fetchone()[0] > 0:
            print(f"⚠️  Contact already exists: {phone} - {email}")
            conn.close()
            return False
        url = (
            "http://api.topofstacksoftware.com/quran-hadith/api/verify-by-whatsapp-text"
        )

        # Request payload
        payload = {"key": "9ej33TVT1", "cell": phone, "email": email}

        # Headers (optional, but good practice)
        headers = {"Content-Type": "application/json", "Accept": "application/json"}

        try:
            # Make the POST request
            response = requests.post(url, json=payload, headers=headers)

            # Print response status code
            print(f"Status Code: {response.status_code}")

            # Print response headers
            print(f"Response Headers: {dict(response.headers)}")

            # Try to parse JSON response
            try:
                response_data = response.json()
                print(f"Response JSON: {json.dumps(response_data, indent=2)}")
            except json.JSONDecodeError:
                print(f"Response Text: {response.text}")

            # Check if request was successful
            if response.status_code == 200:
                print("✅ Request successful!")
                is_replaced = response_data.get("is_replaced", None)
                if is_replaced == "true":
                    cursor.execute(
                        """
                        UPDATE contacts 
                        SET is_verified = ? 
                        WHERE phone = ?
                        """,
                        (False, phone),
                    )
                    conn.commit()
                    print("✅ Email replaced")
                cursor.execute(
                    """
                    INSERT INTO contacts (phone, email, is_verified) 
                    VALUES (?, ?, ?)
                """,
                    (phone, email, True),
                )
                conn.commit()
                print(f"✅ New contact saved: {phone} - {email} (verified: True)")
                conn.close()
                return True
            else:
                print(f"❌ Request failed with status code: {response.status_code}")

        except requests.exceptions.RequestException as e:
            print(f"❌ Request failed with error: {e}")
        except Exception as e:
            print(f"❌ Unexpected error: {e}")

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
            SELECT phone, email, chat_name, is_verified, created_at FROM contacts 
            ORDER BY created_at DESC
        """)

        contacts = cursor.fetchall()
        conn.close()

        return contacts
    except Exception as e:
        print(f"❌ Error retrieving contacts: {e}")
        return []


def update_verification_status(email, is_verified=True):
    """
    Update the verification status of a contact by email
    """
    try:
        conn = sqlite3.connect(DATABASE_FILE)
        cursor = conn.cursor()

        cursor.execute(
            """
            UPDATE contacts 
            SET is_verified = ? 
            WHERE email = ?
        """,
            (is_verified, email),
        )

        if cursor.rowcount > 0:
            conn.commit()
            conn.close()
            print(f"✅ Updated verification status for {email}: {is_verified}")
            return True
        else:
            conn.close()
            print(f"⚠️  No contact found with email: {email}")
            return False

    except Exception as e:
        print(f"❌ Error updating verification status: {e}")
        return False


def extract_email_from_text(text):
    """Extract email from text using regex"""
    pattern = r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"
    match = re.search(pattern, text)
    return match.group() if match else None


def extract_phone_from_text(text):
    """Extract phone number from text using regex"""
    # Common phone number patterns
    patterns = [
        r"\+\d{1,4}[\s\-]?\d{6,14}",  # International format
        r"\(\d{3}\)\s?\d{3}[\s\-]?\d{4}",  # US format (xxx) xxx-xxxx
        r"\d{3}[\s\-]?\d{3}[\s\-]?\d{4}",  # US format xxx-xxx-xxxx
        r"\d{10,15}",  # Simple 10-15 digit numbers
    ]

    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group()
    return None


def clean_phone_number(phone_text):
    """Clean and format phone number"""
    if not phone_text:
        return None

    # Remove common prefixes and clean the phone number
    phone = phone_text.strip()

    # Extract only numbers and some special chars (including + sign)
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
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)

    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)
    driver.execute_script(
        "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
    )
    driver.set_window_size(1200, 900)
    return driver


def wait_for_login(driver, timeout=180):
    print("Loading Telegram Web...")
    # Use the /a/ version since that's what you're getting
    driver.get("https://web.telegram.org/a/")

    print("Waiting for login (enter phone and verification code)...")
    print("Make sure to:")
    print("1. Enter your phone number")
    print("2. Enter the verification code from your Telegram app")
    print("3. Wait for the chat list to load")

    wait = WebDriverWait(driver, timeout)

    try:
        # Wait for the chat list to appear after login - using your actual selectors
        wait.until(
            EC.any_of(
                EC.presence_of_element_located(
                    (By.CSS_SELECTOR, ".chat-list.custom-scroll")
                ),
                EC.presence_of_element_located((By.CSS_SELECTOR, ".chat-list")),
                EC.presence_of_element_located((By.CSS_SELECTOR, ".ListItem.Chat")),
                EC.presence_of_element_located((By.CSS_SELECTOR, ".ChatFolders")),
            )
        )
        print("✓ Login successful!")

        # Add a pause to let everything load
        print("Waiting 5 seconds for full page load...")
        time.sleep(5)

        return True
    except TimeoutException:
        print("✗ Login failed or timed out")
        return False


def get_chat_container(driver):
    """Find and return the chat container element"""
    chat_container_selectors = [
        # Based on your actual structure
        ".chat-list.custom-scroll",
        ".chat-list",
        "div.chat-list",
        # Fallback selectors
        "[class*='chat-list']",
        ".ChatFolders",
        "[class*='ChatFolders']",
        # Generic containers
        ".custom-scroll",
        "[class*='scroll']",
    ]

    print("\n🔍 Looking for chat container...")
    for i, selector in enumerate(chat_container_selectors):
        try:
            print(f"Trying container selector {i + 1}: {selector}")
            container = driver.find_element(By.CSS_SELECTOR, selector)
            if container:
                print(f"✓ Found chat container with selector: {selector}")

                # Check if container has any content
                container_html = container.get_attribute("outerHTML")[:500]
                print(f"Container preview: {container_html}...")

                return container
        except Exception as e:
            print(f"  Failed: {e}")
            continue

    print("⚠️ Chat container not found with any selector")
    return None


def debug_page_structure(driver):
    """Debug function to inspect the page structure"""
    print("\n🔍 DEBUG: Inspecting page structure...")

    try:
        # Get page title
        title = driver.title
        print(f"Page title: {title}")

        # Get current URL
        current_url = driver.current_url
        print(f"Current URL: {current_url}")

        # Try to find any elements that might contain chats
        debug_selectors = [
            "div",
            "ul",
            "li",
            "[class*='chat']",
            "[class*='dialog']",
            "[class*='list']",
            "[class*='conversation']",
            "[class*='message']",
        ]

        for selector in debug_selectors:
            try:
                elements = driver.find_elements(By.CSS_SELECTOR, selector)
                if len(elements) > 0:
                    print(f"Found {len(elements)} elements with selector: {selector}")

                    # Show first few elements' classes and text
                    for i, elem in enumerate(elements[:3]):
                        try:
                            classes = elem.get_attribute("class") or "no-class"
                            text = (
                                elem.text[:50] + "..."
                                if len(elem.text) > 50
                                else elem.text
                            )
                            print(
                                f"  Element {i + 1}: class='{classes}', text='{text}'"
                            )
                        except:
                            continue
            except:
                continue

        # Try to get the HTML structure of sidebar
        try:
            sidebar = driver.find_element(
                By.CSS_SELECTOR,
                ".sidebar-left, .left-column, [class*='sidebar'], [class*='left']",
            )
            if sidebar:
                print("\nSidebar HTML structure (first 1000 chars):")
                print(sidebar.get_attribute("outerHTML")[:1000] + "...")
        except:
            print("No sidebar found")

    except Exception as e:
        print(f"Debug error: {e}")


def get_current_visible_chats(driver):
    """Get currently visible chat elements in the viewport"""

    # First run debug if no chats found
    debug_page_structure(driver)

    # Extended list of selectors based on different Telegram versions
    chat_selectors = [
        # Based on your actual Telegram structure
        ".ListItem.Chat.chat-item-clickable",
        "div.ListItem.Chat",
        ".chat-list .ListItem.Chat",
        ".ListItem.Chat",
        # Fallback selectors
        ".chat-list div[class*='ListItem']",
        "[class*='chat-item-clickable']",
        "div[class*='Chat'][class*='clickable']",
        ".chat-list > div",
        # Very broad selectors as last resort
        ".chat-list div",
        "[class*='chat-list'] div",
    ]

    print(f"\n🔍 Trying {len(chat_selectors)} different selectors...")

    for i, selector in enumerate(chat_selectors):
        try:
            print(f"Trying selector {i + 1}: {selector}")
            chat_items = driver.find_elements(By.CSS_SELECTOR, selector)
            print(f"  Found {len(chat_items)} elements")

            if chat_items:
                # Filter out only visible elements with meaningful content
                visible_chats = []
                for j, chat in enumerate(chat_items):
                    try:
                        if chat.is_displayed() and chat.size["height"] > 10:
                            # Check if it has any text content that looks like a chat
                            text = chat.text.strip()
                            if text and len(text) > 1:
                                visible_chats.append(chat)
                                if j < 3:  # Show first 3 for debugging
                                    print(f"    Chat {j + 1}: {text[:50]}...")
                    except StaleElementReferenceException:
                        continue
                    except Exception as e:
                        print(f"    Error checking chat {j}: {e}")

                if visible_chats:
                    print(
                        f"✓ Found {len(visible_chats)} visible chats with selector: {selector}"
                    )
                    return visible_chats
                else:
                    print("  No visible chats with meaningful content")
        except Exception as e:
            print(f"  Error with selector {selector}: {e}")
            continue

    print("⚠️ No visible chats found with any selector")

    # Last resort: try to get page source to see what's actually there
    try:
        print("\n📄 Page source sample (first 2000 chars):")
        print(driver.page_source[:2000] + "...")
    except:
        pass

    return []


def extract_chat_data(chat_element):
    """Extract data from a single chat element"""
    try:
        # Get chat name - based on your actual structure
        chat_name = "Unknown"

        # Your structure shows text content directly in the ListItem
        full_text = chat_element.text.strip()

        if full_text:
            # The format appears to be: "Name\nTime\nMessage preview"
            lines = full_text.split("\n")
            if lines:
                # First line is usually the chat name
                chat_name = lines[0].strip()

                # If first line looks like a time, try second line
                if ":" in chat_name and ("AM" in chat_name or "PM" in chat_name):
                    if len(lines) > 1:
                        chat_name = lines[1].strip()

        # Try specific selectors for chat name as fallback
        if chat_name == "Unknown" or not chat_name:
            name_selectors = [
                ".chat-title",
                ".peer-title",
                "h3",
                ".name",
                "[class*='title']",
                "[class*='name']",
            ]

            for name_sel in name_selectors:
                try:
                    name_el = chat_element.find_element(By.CSS_SELECTOR, name_sel)
                    name = name_el.text.strip()
                    if name:
                        chat_name = name
                        break
                except:
                    continue

        # Get last message preview from the full text
        last_message = ""
        if full_text:
            lines = full_text.split("\n")
            if len(lines) > 2:
                # Usually the last line or lines contain the message
                last_message = "\n".join(lines[2:]).strip()
            elif len(lines) > 1:
                # Check if second line is not a time
                second_line = lines[1].strip()
                if not (
                    ":" in second_line and ("AM" in second_line or "PM" in second_line)
                ):
                    last_message = second_line

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
            time.sleep(0.3)

        # Wait for content to load
        time.sleep(0.8)

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
        time.sleep(2)  # Wait for chat to load (Telegram might be slower)
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
                f"//*[contains(@class, 'user-title') and text()='{chat_name}']//ancestor::*[contains(@class, 'chatlist-chat')]",
                f"//*[contains(@class, 'dialog-title') and text()='{chat_name}']//ancestor::li",
                f"//*[contains(@class, 'peer-title') and text()='{chat_name}']//ancestor::*[contains(@class, 'chatlist-chat')]",
                f"//*[text()='{chat_name}']//ancestor::*[contains(@class, 'chatlist-chat')]",
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
                time.sleep(2)
                return True
            else:
                print(
                    f"  ⚠️ Chat not found by name: {chat_name} (attempt {attempt + 1})"
                )

        except Exception as e:
            print(f"  ❌ Error in name-based click (attempt {attempt + 1}): {e}")
            time.sleep(0.5)

    return False


def get_last_messages_from_open_chat(driver, num_messages=10):
    """
    Get the last N messages from an opened chat to search for emails and phones
    """
    try:
        # Wait for messages to load
        time.sleep(2)

        # Find all message elements - Updated selectors for /a/ version
        message_selectors = [
            # Try specific message content selectors first
            ".message-content .text-content",
            ".Message .message-content",
            ".Message .text-content",
            ".message .text-content",
            ".Message",
            ".message",
            # Broader selectors as fallback
            "[class*='Message']",
            "[class*='message']",
            "[class*='text-content']",
            "div[dir='auto']",  # Telegram often uses dir='auto' for text
        ]

        messages = []
        for selector in message_selectors:
            try:
                found_messages = driver.find_elements(By.CSS_SELECTOR, selector)
                if found_messages:
                    # Filter messages that actually contain text
                    text_messages = []
                    for msg in found_messages:
                        text = msg.text.strip()
                        if text and len(text) > 2:  # Must have some meaningful content
                            text_messages.append(msg)

                    if text_messages:
                        messages = text_messages
                        print(
                            f"    Found {len(messages)} messages using selector: {selector}"
                        )
                        break
            except Exception as e:
                print(f"    Error with selector {selector}: {e}")
                continue

        if not messages:
            print("    No messages found with any selector")
            # Try to get any text elements as last resort
            try:
                all_text_elements = driver.find_elements(
                    By.XPATH,
                    "//*[contains(text(), '@') or contains(text(), '+') or string-length(text()) > 10]",
                )
                if all_text_elements:
                    print(
                        f"    Found {len(all_text_elements)} text elements as fallback"
                    )
                    messages = (
                        all_text_elements[-num_messages:]
                        if len(all_text_elements) > num_messages
                        else all_text_elements
                    )
            except:
                pass

            if not messages:
                return []

        # Get the last N messages (or all if fewer than N)
        last_messages = (
            messages[-num_messages:] if len(messages) >= num_messages else messages
        )

        extracted_messages = []

        for i, msg in enumerate(
            reversed(last_messages)
        ):  # Process from newest to oldest
            try:
                # Extract text
                body = msg.text.strip()

                # Skip empty messages
                if not body:
                    continue

                # Try to determine direction (in Telegram /a/ version)
                direction = "in"  # Default to incoming
                try:
                    # Look for outgoing message indicators
                    msg_classes = msg.get_attribute("class") or ""
                    parent_element = msg.find_element(
                        By.XPATH,
                        "./ancestor::*[contains(@class, 'Message') or contains(@class, 'message')]",
                    )
                    parent_classes = parent_element.get_attribute("class") or ""

                    if (
                        "own" in parent_classes.lower()
                        or "out" in parent_classes.lower()
                        or "outgoing" in parent_classes.lower()
                    ):
                        direction = "out"
                except:
                    pass

                extracted_messages.append(
                    {
                        "body": body,
                        "direction": direction,
                        "position": i
                        + 1,  # 1 = most recent, 2 = second most recent, etc.
                    }
                )

            except Exception as e:
                print(f"    Warning: Error extracting message {i + 1}: {e}")
                continue

        return extracted_messages

    except Exception as e:
        print(f"    Error getting messages from open chat: {e}")
        return []


def find_email_and_phone_in_messages(messages):
    """
    Search for email addresses and phone numbers in a list of messages
    Returns the first email and phone found
    """
    email_result = None
    phone_result = None

    for msg in messages:
        # Look for email if not found yet
        if not email_result:
            email = extract_email_from_text(msg["body"])
            if email:
                email_result = {
                    "email": email,
                    "found_in_message": msg["body"][:100] + "..."
                    if len(msg["body"]) > 100
                    else msg["body"],
                    "message_position": msg["position"],
                    "direction": msg["direction"],
                }

        # Look for phone if not found yet
        if not phone_result:
            phone = extract_phone_from_text(msg["body"])
            if phone:
                phone_result = {
                    "phone": phone,
                    "found_in_message": msg["body"][:100] + "..."
                    if len(msg["body"]) > 100
                    else msg["body"],
                    "message_position": msg["position"],
                    "direction": msg["direction"],
                }

        # If both found, break early
        if email_result and phone_result:
            break

    return email_result, phone_result


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
        if total_processed >= 20:
            break
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
            print("No new chats in this batch, scrolling...")
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
                    # Get last 10 messages to search for emails and phones
                    messages = get_last_messages_from_open_chat(driver, num_messages=10)

                    if messages:
                        print(f"    Retrieved {len(messages)} messages")

                        # Search for email and phone in all messages
                        email_result, phone_result = find_email_and_phone_in_messages(
                            messages
                        )

                        phone = None
                        email = None

                        # Use found phone or try to extract from chat name as fallback
                        if phone_result:
                            phone = clean_phone_number(phone_result["phone"])
                            print(
                                f"    Phone: {phone} (found in message #{phone_result['message_position']})"
                            )
                        else:
                            # Try to extract phone from chat name as fallback
                            phone = clean_phone_number(chat_data["chat_name"])
                            if phone:
                                print(f"    Phone: {phone} (from chat name)")
                            else:
                                print("    Phone: Not found")

                        if email_result:
                            email = email_result["email"]
                            print(
                                f"    Email: {email} (found in message #{email_result['message_position']})"
                            )
                            print(f"    Found in: {email_result['found_in_message']}")
                        else:
                            print(
                                f"    Email: Not found in last {len(messages)} messages"
                            )

                        # Save to database if both phone and email exist
                        if phone and email:
                            if save_contact(phone, email):
                                print("    💾 Saved to database!")
                                batch_saved += 1
                                total_saved += 1
                            else:
                                print("    📝 Already exists")
                        else:
                            missing = []
                            if not phone:
                                missing.append("phone")
                            if not email:
                                missing.append("email")
                            print(f"    ⚠️  Missing {', '.join(missing)}")

                        total_processed += 1
                        if total_processed >= 20:
                            break
                    else:
                        print("    ⚠️  No messages found")
                else:
                    print("    ❌ Could not open chat")

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

    print("\n📊 Final Summary:")
    print(f"   Total unique chats processed: {total_processed}")
    print(f"   New contacts saved: {total_saved}")
    print(f"   Batches processed: {batch_count}")

    return total_processed, total_saved


def print_database_stats():
    """Print current database statistics"""
    contacts = get_all_contacts()
    print("\n📊 Database Stats:")
    print(f"   Total contacts: {len(contacts)}")

    verified_count = sum(
        1
        for contact in contacts
        if contact[3]  # is_verified is at index 3
    )
    unverified_count = len(contacts) - verified_count

    print(f"   Verified contacts: {verified_count}")
    print(f"   Unverified contacts: {unverified_count}")

    if contacts:
        print("   Latest contacts:")
        for phone, email, chat_name, is_verified, created_at in contacts[
            :3
        ]:  # Show latest 3
            status = "✓" if is_verified else "✗"
            print(f"     • {phone} - {email} ({chat_name}) [{status}] ({created_at})")


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
