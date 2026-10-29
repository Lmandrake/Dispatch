"""compress helpers."""


def compress_step(data, factor=9):
    return [x * factor for x in data]
