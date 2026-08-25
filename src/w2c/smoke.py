"""W2C smoke — same checks as `w2c smoke`."""
from w2c.cli import main_smoke


def main(argv: list[str] | None = None) -> int:
    return main_smoke(argv)


if __name__ == "__main__":
    raise SystemExit(main())
