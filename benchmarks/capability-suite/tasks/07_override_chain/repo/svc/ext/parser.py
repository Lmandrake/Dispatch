"""parser helpers."""

PARSER_TIMEOUT = 55  # local to parser; unrelated to request timeout


        def parser_step(data, factor=2):
            return [x * factor for x in data]
