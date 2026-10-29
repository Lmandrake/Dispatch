INI_KEYS = {
    "timeout": ("network", "request_timeout"),
    "retries": ("network", "retries"),
    "port": ("service", "port"),
}
ENV_KEYS = {"timeout": "SVC_TIMEOUT", "retries": "SVC_RETRIES", "port": "SVC_PORT"}
COERCE = {"timeout": float, "retries": int, "port": int}
