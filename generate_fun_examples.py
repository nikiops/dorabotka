from pathlib import Path

from bot import OUTPUT_DIR, process_screenshot


FUN_CASES = [
    {
        "source": "PagarConDeuna.jpg",
        "amount": {"whole": "666", "cents": "66"},
        "sender": "Don Diablo Supremo",
        "account": "2207031220",
        "user_id": 666001,
    },
    {
        "source": "PagarConDeuna.jpg",
        "amount": {"whole": "7777", "cents": "77"},
        "sender": "El Jefe Final",
        "account": "1234567890",
        "user_id": 777001,
    },
    {
        "source": "test1.jpg",
        "amount": {"whole": "13", "cents": "37"},
        "sender": "Modo Leyenda Activado",
        "account": "2207031220",
        "user_id": 133701,
    },
    {
        "source": "test2.jpg",
        "amount": {"whole": "9999", "cents": "99"},
        "sender": "Patron Galactico",
        "account": "9876543210",
        "user_id": 999901,
    },
]


def main() -> None:
    examples_dir = OUTPUT_DIR / "fun_examples"
    examples_dir.mkdir(exist_ok=True)

    for case in FUN_CASES:
        result_path = process_screenshot(
            screenshot_path=Path(case["source"]),
            amount_data=case["amount"],
            nombre_origen=case["sender"],
            cuenta_origen=case["account"],
            user_id=case["user_id"],
        )
        target_path = examples_dir / result_path.name
        target_path.write_bytes(result_path.read_bytes())
        debug_path = result_path.with_suffix(".txt")
        if debug_path.exists():
            target_debug_path = examples_dir / debug_path.name
            target_debug_path.write_bytes(debug_path.read_bytes())
        print(target_path)


if __name__ == "__main__":
    main()
