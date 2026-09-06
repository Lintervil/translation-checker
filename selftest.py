from checker import find_english_issues


CASES = [
    ("Привет (Hi)", []),
    ("Класс энергопотребления A++", []),
    ("Габариты 81.5 x 44.8 x 55 см", []),
    ("Скачать инструкцию PDF", []),
    ("Подключите Wi-Fi и Bluetooth", []),
    ("Новая collection плит", ["collection"]),
    ("Buy now со скидкой", ["Buy now"]),
    ("Gorenje collection", ["collection"]),
]


def main() -> None:
    failed = []
    for text, expected in CASES:
        actual = [item["word"] for item in find_english_issues(text, "selftest")]
        if actual != expected:
            failed.append((text, expected, actual))
            print(f"FAIL: {text}\n  expected: {expected}\n  actual:   {actual}")
        else:
            print(f"OK: {text}")
    if failed:
        raise SystemExit(1)
    print(f"All {len(CASES)} self-tests passed")


if __name__ == "__main__":
    main()
