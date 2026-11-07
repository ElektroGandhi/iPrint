"""Constants of the iPrint integration."""
DOMAIN = "iprint"
RFCOMM_CHANNEL = 1
POLL_SECONDS_CONNECTED = 60
POLL_SECONDS_AWAY = 300  # paging an absent printer ties up the radio for 5 s each time
POLL_SECONDS_WAITING = 60  # a job is waiting: notice the printer soon after it is switched on

SERVICE_PRINT_TEXT = "print_text"
SERVICE_PRINT_IMAGE = "print_image"
SERVICE_FEED = "feed"
SERVICE_CLEAR_QUEUE = "clear_queue"

DENSITIES = ("light", "normal", "dark", "darkest")
DEFAULT_DENSITY = "dark"
