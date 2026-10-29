"""replay helpers."""


def replay_step(data, factor=6):
    return [x * factor for x in data]
