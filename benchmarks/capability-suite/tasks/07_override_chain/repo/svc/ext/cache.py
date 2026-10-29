"""cache helpers."""

CACHE_TIMEOUT = 57  # local to cache; unrelated to request timeout


        def cache_step(data, factor=4):
            return [x * factor for x in data]
