from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager


def get_headless_chrome_driver() -> webdriver.Chrome:
    """
       Initializes and returns a headless Chrome WebDriver instance.

       This function configures Chrome to run in headless mode using modern `--headless=new` flag (for Chrome v109+),
       sets necessary flags for sandboxing and shared memory usage, and defines a custom user-agent.

       ChromeDriver is automatically managed and updated via `webdriver-manager`.
    """

    options = webdriver.ChromeOptions()
    options.add_argument("--headless=new")  # For Chrome v109+ use --headless=new
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")

    options.add_argument(
        "user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )

    # Automatically manage and update chromedriver
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)
    return driver
