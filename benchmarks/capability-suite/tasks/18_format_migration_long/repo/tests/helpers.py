import math

from tsarc import Schema, Table

T0 = 1_772_323_200_000_000  # 2026-03-01T00:00:00Z
SEC = 1_000_000


def weather(n=50, step=60 * SEC):
    schema = Schema.parse("ts:ts,temp:float,hum:int,site:str")
    sites = ["roof", "yard", "lab"]
    rows = []
    for i in range(n):
        temp = 15.0 + (i % 17) * 0.5 if i % 23 != 7 else math.nan
        rows.append((T0 + i * step, temp, 40 + (i * 7) % 50, sites[i % 3]))
    return Table.from_rows(schema, rows)


def flags_table(n=20):
    schema = Schema.parse("ts:ts,ok:bool,level:float")
    return Table.from_rows(schema, [(T0 + i * SEC, i % 3 != 0, i / 4) for i in range(n)])
