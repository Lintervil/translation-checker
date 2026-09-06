"""Built-in whitelist for brands, formats, abbreviations and identifiers."""

BASE_EXCEPTIONS = {
    # Common brands and product names.
    "gorenje", "bosch", "samsung", "lg", "apple", "philips", "siemens",
    "haier", "beko", "miele", "electrolux", "aeg", "xiaomi", "google",
    "sony", "panasonic", "toshiba", "asus", "lenovo", "hp", "huawei",
    "honor", "tesla", "ikea", "whirlpool", "indesit", "karcher", "tefal",
    "braun", "nespresso", "dolce gusto", "airpods", "iphone", "ipad",
    # File formats and common technical values.
    "jpg", "jpeg", "png", "gif", "svg", "webp", "mp4", "mp3", "avi",
    "pdf", "doc", "docx", "xls", "xlsx", "zip", "rar", "csv", "json",
    "url", "http", "https", "api", "id", "qr", "pin", "sim", "usb",
    "hdmi", "led", "oled", "qled", "hd", "4k", "wi-fi", "bluetooth",
    "nfc", "gps", "rgb", "cmyk", "css", "html", "seo", "faq", "vip",
    "top", "new", "sale", "ok", "dataMatrix", "gtin", "sscc", "gln",
    "ооо", "ип", "инн", "огрн", "kwh", "w", "v", "a", "hz",
    "com", "ru", "net", "org", "info", "рф",
    # Social networks and messengers.
    "instagram", "youtube", "facebook", "telegram", "whatsapp", "viber", "tiktok",
    # Payment systems and operating systems.
    "visa", "mastercard", "paypal", "android", "ios", "windows",
    # Common technical and marketing terms left in Latin script.
    "tv", "smart", "eco", "inverter", "wifi", "no frost", "hi-light",
    "online", "outlet", "premium", "alt", "title", "recaptcha",
}
