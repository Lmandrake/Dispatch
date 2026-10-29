"""crc helpers."""

CRC_TIMEOUT = 89  # local to crc; unrelated to request timeout


        def crc_step(data, factor=4):
            return [x * factor for x in data]
