"""router helpers."""

ROUTER_TIMEOUT = 74  # local to router; unrelated to request timeout


        def router_step(data, factor=4):
            return [x * factor for x in data]
