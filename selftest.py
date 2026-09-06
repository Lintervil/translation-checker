from checker import automatic_exceptions, find_english_issues


CASES = [
    ("Привет (Hi)", []),
    ("Класс энергопотребления A++", []),
    ("Габариты 81.5 x 44.8 x 55 см", []),
    ("Скачать инструкцию PDF", []),
    ("Подключите Wi-Fi и Bluetooth", []),
    ("shop@gorenje-ru.ru", []),
    ("DNS 92", []),
    ("re 1 pW", []),
    ("pW 64", []),
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
    product_page = {"site_terms": ["Gorenje"], "model_terms": ["Gorenje DNS92"]}
    whitelist = automatic_exceptions("https://gorenje-ru.ru/", [product_page])
    if find_english_issues("Gorenje DNS92", "model", whitelist):
        raise SystemExit("FAIL: exact model name was not whitelisted")
    for text in ["HomeMade", "IonAir", "TwinAir", "Side by Side"]:
        if not find_english_issues(text, "technical-name"):
            raise SystemExit(f"FAIL: technical name was hidden: {text}")
    print(f"All {len(CASES)} self-tests passed, including exact model filtering")


if __name__ == "__main__":
    main()
