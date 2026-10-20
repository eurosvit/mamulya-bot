import os; os.environ.setdefault("DB", ":memory:")
from bot import is_cod

# порожній спосіб оплати → наложка (баг #12538: payment_method=None пропускав завдаток)
assert is_cod(None, "") is True
assert is_cod("", None) is True
# явна наложка за ключовим словом
assert is_cod(5, "Накладений платіж") is True
assert is_cod(7, "Оплата при отриманні") is True
# онлайн-передоплата (поле заповнене, не наложка) → без завдатку
assert is_cod(3, "Передоплата на картку") is False
assert is_cod(9, "LiqPay онлайн") is False
print("is_cod OK")
