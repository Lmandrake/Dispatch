"""queue helpers."""


def queue_step(data, factor=1):
    return [x * factor for x in data]
