"""sink helpers."""


def sink_step(data, factor=8):
    return [x * factor for x in data]
