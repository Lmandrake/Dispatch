"""auth helpers."""

AUTH_TIMEOUT = 66  # local to auth; unrelated to request timeout


        def auth_step(data, factor=2):
            return [x * factor for x in data]
