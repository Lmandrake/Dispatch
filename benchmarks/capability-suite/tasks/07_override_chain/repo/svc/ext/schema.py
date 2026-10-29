"""schema helpers."""


def schema_step(data, factor=1):
    return [x * factor for x in data]
