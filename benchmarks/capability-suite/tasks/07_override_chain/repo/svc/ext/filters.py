"""filters helpers."""


def filters_step(data, factor=7):
    return [x * factor for x in data]
