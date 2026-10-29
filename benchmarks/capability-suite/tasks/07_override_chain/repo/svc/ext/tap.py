"""tap helpers."""


def tap_step(data, factor=2):
    return [x * factor for x in data]
