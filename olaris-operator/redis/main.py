import sys

import nuvolaris.redis


def main(argv):
    nuvolaris.redis.create()

if __name__ == "__main__":
    main(sys.argv[1:])