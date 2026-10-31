"""Turns a User-Agent string into a short label like "Chrome on Windows". Deliberately small: it only has to help a person
recognise their own devices, not identify browsers precisely."""


def describe(ua: str | None) -> str:
    if not ua:
        return "Unknown device"
    s = ua.lower()
    # order matters: Edge, Opera and Chrome on iOS all also say "chrome" or "safari"
    if "edg/" in s or "edga/" in s or "edgios/" in s:
        browser = "Edge"
    elif "opr/" in s or "opera" in s:
        browser = "Opera"
    elif "firefox/" in s or "fxios/" in s:
        browser = "Firefox"
    elif "chrome/" in s or "crios/" in s:
        browser = "Chrome"
    elif "safari/" in s:
        browser = "Safari"
    elif "curl/" in s or "python" in s or "httpx" in s or "testclient" in s:
        browser = "Script"
    else:
        browser = ""
    if "iphone" in s:
        os_ = "iPhone"
    elif "ipad" in s:
        os_ = "iPad"
    elif "android" in s:
        os_ = "Android"
    elif "windows" in s:
        os_ = "Windows"
    elif "mac os x" in s or "macintosh" in s:
        os_ = "Mac"
    elif "cros" in s:
        os_ = "ChromeOS"
    elif "linux" in s:
        os_ = "Linux"
    else:
        os_ = ""
    if browser and os_:
        return f"{browser} on {os_}"
    return browser or os_ or "Unknown device"
