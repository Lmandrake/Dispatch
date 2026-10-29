import sys
from .client import RelayClient


def main(argv=None):
    print(RelayClient().describe())
    return 0


if __name__ == "__main__":
    sys.exit(main())
